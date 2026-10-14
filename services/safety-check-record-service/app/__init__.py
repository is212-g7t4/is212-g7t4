import os
from uuid import UUID

import psycopg2
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

from app.models import (
    CHANGES_REQUESTED,
    DECISION_STATUSES,
    FLAG_AREAS,
    NOTES_LIMIT,
    RECORD_STATUSES,
    SAFETY_REJECTED,
    RecordNotDeletableError,
    RecordNotFoundError,
    RoundAlreadyDecidedError,
    RoundAlreadyOpenError,
    RoundNotLatestError,
    RoundNotReopenableError,
    clean_notes,
    create_round,
    decide_round,
    delete_open_round,
    list_rounds,
    reopen_round,
)

NO_DATABASE = (
    "DATABASE_URL is not configured for Safety Check Record Service."
)


def _uuid_or_none(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        return None


def create_app(config=None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE_URL=os.getenv("DATABASE_URL"),
        # The Vite dev server is pinned to 5174 (strictPort in
        # vite.config.ts), so that is the origin the browser sends.
        FRONTEND_ORIGIN=os.getenv("FRONTEND_ORIGIN", "http://localhost:5174"),
        MAX_CONTENT_LENGTH=65536,
    )
    app.config.update(config or {})

    @app.after_request
    def cors(response):
        origin = request.headers.get("Origin")
        configured_origin = app.config["FRONTEND_ORIGIN"]
        allowed_origins = {configured_origin}
        if configured_origin:
            allowed_origins.add(configured_origin.replace("localhost", "127.0.0.1"))
            allowed_origins.add(configured_origin.replace("127.0.0.1", "localhost"))
        if origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, Authorization, Accept"
            )
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, POST, PATCH, DELETE, OPTIONS"
            )
        if request.method == "OPTIONS":
            response.status_code = 200
        return response

    @app.errorhandler(psycopg2.Error)
    def database_failure(error):
        # Do not expose credentials, SQL or database internals in the response/log.
        return jsonify(
            message=(
                "Unable to save or load safety checks. Please check the Safety "
                "Check Record Service database connection and schema."
            )
        ), 503

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.post("/safety-check-records")
    def create_record():
        """Open the next review round for an event (SCRUM-149 AC1, AC3, AC4).

        Called by Safety Check Service, which has already checked the caller
        and the event's arrangements. Everything is re-validated here anyway:
        an atomic never trusts its caller's homework.
        """
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(message="Send a JSON object."), 400
        event_id = _uuid_or_none(data.get("eventId"))
        submitted_by = _uuid_or_none(data.get("submittedBy"))
        if not event_id or not submitted_by:
            return jsonify(
                message="eventId and submittedBy must be valid UUIDs."
            ), 400
        notes, failure = _notes(data)
        if failure:
            return failure
        if not app.config["DATABASE_URL"]:
            return jsonify(message=NO_DATABASE), 503
        try:
            created = create_round(
                app.config["DATABASE_URL"], event_id, submitted_by, *notes
            )
        except RoundAlreadyOpenError as open_round:
            return jsonify(
                code="SAFETY_CHECK_ALREADY_PENDING",
                message="This event already has a safety check awaiting a decision.",
                safetyCheck=open_round.existing,
            ), 409
        return jsonify(created), 201

    @app.get("/safety-check-records")
    def list_records():
        event_id = _uuid_or_none(request.args.get("eventId"))
        if not event_id:
            return jsonify(message="eventId must be a valid UUID."), 400
        status = request.args.get("status") or None
        if status is not None and status not in RECORD_STATUSES:
            return jsonify(
                message=f"status must be one of: {', '.join(RECORD_STATUSES)}."
            ), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message=NO_DATABASE), 503
        return jsonify(
            safetyChecks=list_rounds(app.config["DATABASE_URL"], event_id, status)
        )

    @app.delete("/safety-check-records/<safety_check_id>")
    def delete_record(safety_check_id):
        """Remove an undecided round.

        Compensation only — Safety Check Service calls this when it opened a
        round but could not then move the event to 'Pending Safety Check'.
        Not a general "withdraw a safety check" endpoint, and it refuses any
        round that has been decided.
        """
        safety_check_id = _uuid_or_none(safety_check_id)
        if not safety_check_id:
            return jsonify(message="The safety check ID must be a valid UUID."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message=NO_DATABASE), 503
        try:
            delete_open_round(app.config["DATABASE_URL"], safety_check_id)
        except RecordNotFoundError:
            return jsonify(message="Safety check not found."), 404
        except RecordNotDeletableError:
            return jsonify(
                message="A safety check that has been decided can't be removed."
            ), 409
        return "", 204

    @app.patch("/safety-check-records/<safety_check_id>/decision")
    def decide_record(safety_check_id):
        """Decide the open round (SCRUM-150 AC2): status, who decided, when, remarks.

        Called by Safety Check Service after it has checked the caller's role
        and the event's status. Re-validated here anyway, and the row is
        locked `FOR UPDATE` so a simultaneous decide loses the race here, not
        in the event (AC3 / the race guard).
        """
        safety_check_id = _uuid_or_none(safety_check_id)
        if not safety_check_id:
            return jsonify(message="The safety check ID must be a valid UUID."), 400
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(message="Send a JSON object."), 400
        status = data.get("status")
        if status not in DECISION_STATUSES:
            return jsonify(
                message=f"status must be one of: {', '.join(DECISION_STATUSES)}."
            ), 400
        decided_by = _uuid_or_none(data.get("decidedBy"))
        if not decided_by:
            return jsonify(message="decidedBy must be a valid UUID."), 400
        remarks_required = status in (CHANGES_REQUESTED, SAFETY_REJECTED)
        remarks, failure = _remarks(data, required=remarks_required)
        if failure:
            return failure
        flags, failure = _flags(data, status)
        if failure:
            return failure
        if not app.config["DATABASE_URL"]:
            return jsonify(message=NO_DATABASE), 503
        try:
            decided = decide_round(
                app.config["DATABASE_URL"],
                safety_check_id,
                status,
                decided_by,
                remarks,
                flags,
            )
        except RecordNotFoundError:
            return jsonify(message="Safety check not found."), 404
        except RoundAlreadyDecidedError as already:
            return jsonify(
                code="SAFETY_CHECK_ALREADY_DECIDED",
                message="This safety check has already been decided.",
                safetyCheck=already.existing,
            ), 409
        except RoundNotLatestError:
            return jsonify(
                code="NOT_LATEST_ROUND",
                message="A later round exists for this event; this round can no longer be decided.",
            ), 409
        return jsonify(decided), 200

    @app.post("/safety-check-records/<safety_check_id>/reopen")
    def reopen_record(safety_check_id):
        """Compensation only: undo the decision the caller's own request just made.

        Not a general "withdraw a decision" endpoint. `decidedAt` must match
        what `decide_round` returned, so this can only undo the write the
        same request just made, never an older decision (SCRUM-153 handles
        a deliberate later withdrawal).
        """
        safety_check_id = _uuid_or_none(safety_check_id)
        if not safety_check_id:
            return jsonify(message="The safety check ID must be a valid UUID."), 400
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(message="Send a JSON object."), 400
        decided_at = data.get("decidedAt")
        if not isinstance(decided_at, str) or not decided_at:
            return jsonify(message="decidedAt is required."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message=NO_DATABASE), 503
        try:
            reopened = reopen_round(app.config["DATABASE_URL"], safety_check_id, decided_at)
        except RecordNotFoundError:
            return jsonify(message="Safety check not found."), 404
        except RoundNotReopenableError:
            return jsonify(
                message="This safety check is not the decided round being undone."
            ), 409
        return jsonify(reopened), 200

    return app


def _notes(data):
    """The two optional note fields, trimmed to NULL when blank (SCRUM-149 AC3)."""
    cleaned = []
    for key, label in (
        ("equipmentPlacementNotes", "Equipment placement notes"),
        ("crowdMovementNotes", "Expected crowd movement notes"),
    ):
        value = data.get(key)
        if value is not None and not isinstance(value, str):
            return None, (jsonify(message=f"{label} must be text."), 400)
        if isinstance(value, str) and len(value) > NOTES_LIMIT:
            return None, (
                jsonify(message=f"{label} must be {NOTES_LIMIT} characters or fewer."),
                400,
            )
        cleaned.append(clean_notes(value))
    return cleaned, None


def _remarks(data, required=False):
    """The Safety Officer's remarks, trimmed to NULL when blank.

    Optional for an approval (SCRUM-150 AC2); required, non-blank for a
    change request or a rejection (SCRUM-151 AC1, AC3, AC6).
    """
    value = data.get("remarks")
    if value is not None and not isinstance(value, str):
        return None, (jsonify(message="remarks must be text."), 400)
    if isinstance(value, str) and len(value) > NOTES_LIMIT:
        return None, (
            jsonify(message=f"remarks must be {NOTES_LIMIT} characters or fewer."),
            400,
        )
    cleaned = clean_notes(value)
    if required and not cleaned:
        return None, (jsonify(message="remarks is required."), 400)
    return cleaned, None


def _flags(data, status):
    """Validate the per-area flags for a decision (SCRUM-151 AC1).

    A change request needs 1 to 3 flags, each a known area (no area twice)
    with non-blank `changeRequired` text; approval and rejection must send
    none.
    """
    raw = data.get("flags", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        return None, (jsonify(message="flags must be a list."), 400)

    if status != CHANGES_REQUESTED:
        if raw:
            return None, (
                jsonify(message=f"flags are only accepted for {CHANGES_REQUESTED}."),
                400,
            )
        return [], None

    if not raw:
        return None, (
            jsonify(message="At least one area must be selected."),
            400,
        )
    if len(raw) > len(FLAG_AREAS):
        return None, (jsonify(message="Each area may be flagged at most once."), 400)

    seen = set()
    cleaned = []
    for item in raw:
        if not isinstance(item, dict):
            return None, (jsonify(message="Each flag must be an object."), 400)
        area = item.get("area")
        if area not in FLAG_AREAS:
            return None, (
                jsonify(message=f"area must be one of: {', '.join(FLAG_AREAS)}."),
                400,
            )
        if area in seen:
            return None, (jsonify(message="Each area may be flagged at most once."), 400)
        seen.add(area)
        change_required = item.get("changeRequired")
        if not isinstance(change_required, str) or not change_required.strip():
            return None, (
                jsonify(message="changeRequired is required for each selected area."),
                400,
            )
        if len(change_required) > NOTES_LIMIT:
            return None, (
                jsonify(message=f"changeRequired must be {NOTES_LIMIT} characters or fewer."),
                400,
            )
        cleaned.append({"area": area, "changeRequired": change_required.strip()})
    return cleaned, None
