import os
from uuid import UUID

import psycopg2
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

from app.models import (
    NOTES_LIMIT,
    RECORD_STATUSES,
    RecordNotDeletableError,
    RecordNotFoundError,
    RoundAlreadyOpenError,
    clean_notes,
    create_round,
    delete_open_round,
    list_rounds,
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
                "GET, POST, DELETE, OPTIONS"
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
