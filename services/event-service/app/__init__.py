import hmac
import os
from datetime import datetime, time
from uuid import UUID

import psycopg2
from dotenv import load_dotenv
from flask import Flask, g, jsonify, request

load_dotenv()

from app.models import (
    ALL_STATUSES,
    AMENDABLE_FIELDS,
    EDITABLE_FIELDS,
    FIELDS,
    RECHECK_ONLY_MOVES,
    VENUE_CHANGE_RESTORE,
    VENUE_CHANGE_WITHDRAW,
    SAFETY_FLAG_AREAS,
    SAFETY_STATUSES,
    UNDER_SAFETY_REVIEW_MESSAGE,
    AmendmentFieldLockedError,
    AmendmentNotAllowedError,
    AmendmentNotOpenError,
    ChangeRequestAlreadyPendingError,
    ChangeRequestAlreadyDecidedError,
    ChangeRequestNotFoundError,
    ChangeRequestNotAllowedError,
    ClarificationNotAllowedError,
    ClarificationNotOpenError,
    EventClosedError,
    EventNotDraftError,
    EventNotAssignedError,
    EventNotEditableError,
    EventNotFoundError,
    EventNotOwnedError,
    EventNotSubmittedError,
    EventUnderSafetyReviewError,
    InvalidStatusTransitionError,
    InvalidProposedChangesError,
    NoAmendmentChangesError,
    NoProposedChangesError,
    NoCoordinatorChangeError,
    SafetyApprovalRequiredError,
    SafetyCheckAlreadyPendingError,
    SafetyRecheckRequiredError,
    StaleSafetyCheckError,
    approve_event,
    create_change_request,
    decide_change_request,
    delete_draft,
    get_event,
    get_change_request,
    get_organiser_event,
    list_active_events,
    list_attendee_event_summaries,
    list_event_summaries,
    list_events,
    list_organiser_drafts,
    list_confirmed_events,
    list_pending_change_requests,
    list_organiser_events,
    list_overlapping_events,
    list_submitted,
    list_unassigned,
    reject_event,
    request_event_amendment,
    request_event_clarification,
    respond_to_event_amendment,
    respond_to_event_clarification,
    save_draft,
    submit_draft,
    submit_event,
    update_event_coordinator,
    update_event_details,
    update_event_progress,
    update_event_safety_status,
    update_draft,
)
from app.validation import validate, validate_draft
from app.auth import authenticate

# Roles that see every event rather than only the ones assigned to them,
# asked for with ?viewerRole=. The role itself is the signed-in caller's (SCRUM-8).
LEAD_ROLE = "Event Coordinator Lead"
ALL_EVENTS_ROLES = (LEAD_ROLE, "Venue Staff", "Technical Support", "Safety Officer")
# SCRUM-9: operational staff see every event, but not who organised it or the
# internal decision/action history (which carries rejection reasons).
STAFF_ROLES = ("Venue Staff", "Technical Support", "Safety Officer")
STAFF_HIDDEN_FIELDS = ("organiserId", "actionHistory", "decision", "decisionHistory")
# Roles that may look events up by id or time window (summaries only).
LOOKUP_ROLES = ALL_EVENTS_ROLES + ("Event Coordinator",)
# SCRUM-10: who may change what. The role is the token's; the caller's
# relationship to the event (owner, assigned coordinator) is still checked
# afterwards by the model layer.
ORGANISER_ROLE = "Event Organiser"
ORGANISER_ONLY = (ORGANISER_ROLE,)
COORDINATOR_ROLES = ("Event Coordinator", LEAD_ROLE)
LEAD_ONLY = (LEAD_ROLE,)
SAFETY_OFFICER_ONLY = ("Safety Officer",)
# PATCH /safety-status is called by Safety Check Service with the caller's own token: a coordinator
# submits or withdraws, a Safety Officer decides.
SAFETY_STATUS_ROLES = COORDINATOR_ROLES + SAFETY_OFFICER_ONLY


def _role_allowed(roles):
    """True for a signed-in caller whose token role is in `roles`, and for an
    internal background caller (no user, authenticated by X-Internal-Token)."""
    return g.user_id is None or g.role in roles


def _forbidden():
    return jsonify(message="Your role cannot view this information."), 403


def _cannot_modify(roles):
    """SCRUM-10: the 403 for a signed-in caller whose role may not change this
    information, else None. Runs before the body is read or the database is
    touched, so a refused change leaves the event as it was."""
    if _role_allowed(roles):
        return None
    return jsonify(message="Your role cannot change this information."), 403


def _for_viewer(event):
    """The event as the caller may see it: staff roles get the trimmed view."""
    if g.role in STAFF_ROLES:
        return {k: v for k, v in event.items() if k not in STAFF_HIDDEN_FIELDS}
    return event


def _venue_change(data, status, safety_check_id):
    """Validate SCRUM-28 Part B's markers on PATCH /safety-status.

    Returns `(venue_change, failure)`. `withdrawnSafetyCheckId` (with a
    `reason`) is the only way to reach 'Approved' here, and
    `restoredSafetyCheckId` the only way back to 'Confirmed' from it; both
    must name the round given as `safetyCheckId`.
    """
    withdrawn = data.get("withdrawnSafetyCheckId")
    restored = data.get("restoredSafetyCheckId")
    if withdrawn is None and restored is None:
        return None, None
    if withdrawn is not None and restored is not None:
        return None, (jsonify(message="Send withdrawnSafetyCheckId or restoredSafetyCheckId, not both."), 400)
    marker, value, target = (
        ("withdrawnSafetyCheckId", withdrawn, "Approved")
        if withdrawn is not None
        else ("restoredSafetyCheckId", restored, "Confirmed")
    )
    if status != target:
        return None, (jsonify(message=f"{marker} is only valid with status '{target}'."), 400)
    try:
        value = str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        return None, (jsonify(message=f"{marker} must be a valid UUID."), 400)
    if value != safety_check_id:
        return None, (jsonify(message=f"{marker} must match safetyCheckId."), 400)
    if target == "Confirmed":
        return {"move": VENUE_CHANGE_RESTORE}, None
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return None, (jsonify(message="reason is required."), 400)
    if len(reason) > 2000:
        return None, (jsonify(message="reason must be 2000 characters or fewer."), 400)
    return {"move": VENUE_CHANGE_WITHDRAW, "reason": reason.strip(), **({"venueBefore": data["venueBefore"]} if data.get("venueBefore") else {})}, None


def _safety_recheck(data):
    """Validate the optional `safetyRecheck` block on PATCH /details (SCRUM-153).

    Present only when Safety Check Service has already withdrawn the approval
    and opened round N+1, and it names both rounds so this service can check
    the withdrawn one really is the approval the event holds.
    """
    raw = data.get("safetyRecheck")
    if raw is None:
        return None, None
    if not isinstance(raw, dict):
        return None, (jsonify(message="safetyRecheck must be an object."), 400)
    cleaned = {}
    for key in ("withdrawnSafetyCheckId", "safetyCheckId"):
        try:
            cleaned[key] = str(UUID(raw.get(key, "")))
        except (ValueError, TypeError, AttributeError):
            return None, (
                jsonify(message=f"safetyRecheck.{key} must be a valid UUID."),
                400,
            )
    round_number = raw.get("roundNumber")
    if (
        isinstance(round_number, bool)
        or not isinstance(round_number, int)
        or round_number < 1
    ):
        return None, (
            jsonify(
                message="safetyRecheck.roundNumber must be a positive whole number."
            ),
            400,
        )
    if raw.get("venueBefore"):
        cleaned["venueBefore"] = raw["venueBefore"]
    cleaned["roundNumber"] = round_number
    return cleaned, None


def _current_user():
    """The signed-in caller (SCRUM-8); never an id from the request body or query."""
    if g.user_id:
        return g.user_id, None
    return None, (jsonify(message="Sign in to continue."), 401)


def _draft_details(data, validator):
    """The organiser and event details from a draft request body, or the 400 to send."""
    if not isinstance(data, dict):
        return None, None, (jsonify(message="Send a JSON object."), 400)
    organiser_id, failure = _current_user()
    if failure:
        return None, None, failure
    missing, errors = validator(data)
    if missing or errors:
        return None, None, (
            jsonify(
                message="Please correct the event details.",
                missingFields=missing,
                errors=errors,
            ),
            400,
        )
    return organiser_id, {key: data.get(key) or "" for key in (*FIELDS, "purpose")}, None


def _draft_not_writable(error):
    """The response for a draft another organiser owns or that is already submitted (AC4)."""
    if isinstance(error, EventNotFoundError):
        return jsonify(message="Draft not found."), 404
    if isinstance(error, EventNotOwnedError):
        return jsonify(message="You can only change drafts you created."), 403
    return jsonify(
        code="EVENT_NOT_DRAFT",
        message=f"This request is '{error.current_status}', not a draft.",
        currentStatus=error.current_status,
    ), 409


def create_app(config=None):
    app = Flask(__name__)
    app.before_request(authenticate)
    app.config.from_mapping(
        DATABASE_URL=os.getenv("DATABASE_URL"),
        # The Vite dev server is pinned to 5174 (strictPort in
        # vite.config.ts), so that is the origin the browser sends.
        FRONTEND_ORIGIN=os.getenv("FRONTEND_ORIGIN", "http://localhost:5174"),
        MAX_CONTENT_LENGTH=65536,
        INTERNAL_SERVICE_TOKEN=os.getenv("INTERNAL_SERVICE_TOKEN"),
    )
    app.config.update(config or {})

    if not app.config["INTERNAL_SERVICE_TOKEN"]:
        app.logger.warning(
            "INTERNAL_SERVICE_TOKEN is not set: PATCH /events/<id>/safety-status "
            "and the safety re-check on PATCH /events/<id>/details are not "
            "locked to Safety Check Service (SCRUM-150/152/153)."
        )

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
            # Deliberately not listing X-Internal-Service-Token here: a
            # browser can't send it, so only a server-to-server caller can.
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
            message="Unable to save or load event requests. Please check the Event Service database connection and schema."
        ), 503

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/internal/events/<uuid:event_id>/notification-context")
    def notification_context(event_id):
        token = app.config.get("INTERNAL_SERVICE_TOKEN")
        if not token or not hmac.compare_digest(token.encode(), request.headers.get("X-Internal-Token", "").encode()):
            return jsonify(message="Internal token required."), 401
        if not app.config["DATABASE_URL"]:
            return jsonify(message="Event database unavailable."), 503
        try:
            event = get_event(app.config["DATABASE_URL"], str(event_id), None, view_all=True)
        except EventNotFoundError:
            return jsonify(message="Event not found."), 404
        context = dict(id=event["id"], eventName=event["eventName"], coordinatorId=event["coordinatorId"])
        if request.args.get("includeSchedule") == "true":
            context.update(startDateTime=event["preferredStartDate"], endDateTime=event["preferredEndDate"])
        if request.args.get("includeOrganiser") == "true":
            context["organiserId"] = event["organiserId"]
        return jsonify(context)

    @app.post("/events")
    def submit():
        if (forbidden := _cannot_modify(ORGANISER_ONLY)):
            return forbidden
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(message="Send a JSON object."), 400
        missing, errors = validate(data)
        if missing or errors:
            return jsonify(
                message="Please correct the event details.",
                missingFields=missing,
                errors=errors,
            ), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Event Service."
            ), 503
        details = {key: data.get(key, "").strip() for key in (*FIELDS, "purpose")}
        if g.user_id:
            details["organiserId"] = g.user_id
        return jsonify(submit_event(app.config["DATABASE_URL"], details)), 201

    @app.post("/events/drafts")
    def create_draft():
        if (forbidden := _cannot_modify(ORGANISER_ONLY)):
            return forbidden
        organiser_id, details, failure = _draft_details(
            request.get_json(silent=True), validate_draft
        )
        if failure:
            return failure
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        return jsonify(save_draft(app.config["DATABASE_URL"], organiser_id, details)), 201

    @app.get("/events/drafts")
    def drafts():
        organiser_id, failure = _current_user()
        if failure:
            return failure
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        return jsonify(events=list_organiser_drafts(app.config["DATABASE_URL"], organiser_id))

    @app.patch("/events/drafts/<uuid:event_id>")
    def edit_draft(event_id):
        if (forbidden := _cannot_modify(ORGANISER_ONLY)):
            return forbidden
        organiser_id, details, failure = _draft_details(
            request.get_json(silent=True), validate_draft
        )
        if failure:
            return failure
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        try:
            saved = update_draft(
                app.config["DATABASE_URL"], str(event_id), organiser_id, details
            )
        except (EventNotFoundError, EventNotOwnedError, EventNotDraftError) as error:
            return _draft_not_writable(error)
        return jsonify(saved), 200

    @app.post("/events/drafts/<uuid:event_id>/submit")
    def submit_existing_draft(event_id):
        if (forbidden := _cannot_modify(ORGANISER_ONLY)):
            return forbidden
        # The full submission rules, the same as POST /events (AC5).
        organiser_id, details, failure = _draft_details(
            request.get_json(silent=True), validate
        )
        if failure:
            return failure
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        try:
            submitted_event = submit_draft(
                app.config["DATABASE_URL"], str(event_id), organiser_id, details
            )
        except (EventNotFoundError, EventNotOwnedError, EventNotDraftError) as error:
            return _draft_not_writable(error)
        return jsonify(submitted_event), 200

    @app.delete("/events/drafts/<uuid:event_id>")
    def remove_draft(event_id):
        if (forbidden := _cannot_modify(ORGANISER_ONLY)):
            return forbidden
        organiser_id, failure = _current_user()
        if failure:
            return failure
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        try:
            delete_draft(app.config["DATABASE_URL"], str(event_id), organiser_id)
        except (EventNotFoundError, EventNotOwnedError, EventNotDraftError) as error:
            return _draft_not_writable(error)
        return "", 204

    @app.get("/events/submitted")
    def submitted():
        coordinator_id, failure = _current_user()
        if failure:
            return failure
        viewer_role = g.role if request.args.get("viewerRole") else None
        if viewer_role and viewer_role != LEAD_ROLE:
            return jsonify(
                message="Only the Event Coordinator Lead can view every submitted request."
            ), 403
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Event Service."
            ), 503
        return jsonify(
            events=list_submitted(
                app.config["DATABASE_URL"], coordinator_id, view_all=bool(viewer_role)
            )
        )

    @app.get("/events/unassigned")
    def unassigned():
        if not _role_allowed((LEAD_ROLE,)):
            return _forbidden()
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Event Service."
            ), 503
        return jsonify(events=list_unassigned(app.config["DATABASE_URL"]))

    @app.get("/events/active")
    def active():
        if not _role_allowed(ALL_EVENTS_ROLES):
            return _forbidden()
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Event Service."
            ), 503
        return jsonify(events=list_active_events(app.config["DATABASE_URL"]))

    @app.get("/events")
    def list_events_route():
        # ?organiserId= asks for the organiser's own view; who they are comes from the token.
        if request.args.get("organiserId") and not request.args.get("coordinatorId"):
            organiser_id, failure = _current_user()
            if failure:
                return failure
            if not app.config["DATABASE_URL"]:
                return jsonify(
                    message="DATABASE_URL is not configured for Event Service."
                ), 503
            return jsonify(
                events=list_organiser_events(app.config["DATABASE_URL"], organiser_id)
            )
        coordinator_id, failure = _current_user()
        if failure:
            return failure

        viewer_role = g.role if request.args.get("viewerRole") else None
        if viewer_role and viewer_role not in ALL_EVENTS_ROLES:
            return jsonify(message="This role cannot view all internal events."), 403
        status = request.args.get("status") or None
        venue = request.args.get("venue") or None

        date_from = date_to = None
        try:
            if request.args.get("dateFrom"):
                if "T" in request.args["dateFrom"]:
                    raise ValueError
                date_from = datetime.fromisoformat(request.args["dateFrom"])
            if request.args.get("dateTo"):
                if "T" in request.args["dateTo"]:
                    raise ValueError
                date_to = datetime.combine(
                    datetime.fromisoformat(request.args["dateTo"]).date(), time.max
                )
        except ValueError:
            return jsonify(
                message="dateFrom and dateTo must be valid dates (YYYY-MM-DD)."
            ), 400
        if date_from and date_to and date_to < date_from:
            return jsonify(message="dateTo must be on or after dateFrom."), 400

        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Event Service."
            ), 503
        events = list_events(
            app.config["DATABASE_URL"],
            coordinator_id,
            status,
            venue,
            date_from,
            date_to,
            view_all=bool(viewer_role),
        )
        return jsonify(events=[_for_viewer(event) for event in events])

    @app.get("/events/registration")
    def registration_events():
        if not _role_allowed(("Attendee",) + ALL_EVENTS_ROLES):
            return _forbidden()
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        return jsonify(events=list_confirmed_events(app.config["DATABASE_URL"]))

    def _summaries(lookup):
        raw_ids = [part for part in request.args.get("ids", "").split(",") if part]
        if not raw_ids or len(raw_ids) > 100:
            return jsonify(message="Provide between 1 and 100 comma-separated event IDs."), 400
        try:
            ids = [str(UUID(part)) for part in raw_ids]
        except ValueError:
            return jsonify(message="Every event ID must be a valid UUID."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        return jsonify(events=lookup(app.config["DATABASE_URL"], ids))

    @app.get("/events/summaries")
    def event_summaries():
        # Name/status lookup for other screens (e.g. equipment review); no event body.
        if not _role_allowed(LOOKUP_ROLES):
            return _forbidden()
        return _summaries(list_event_summaries)

    @app.get("/events/attendee-summaries")
    def attendee_event_summaries():
        # The same lookup for registered Attendees: while a safety re-check is
        # open they see the last approved times and venue (SCRUM-153 AC4/AC5).
        # Which ids an Attendee may ask for (their own registrations) is
        # enforced by Attendee Registration Service, which supplies them.
        if not _role_allowed(("Attendee",) + LOOKUP_ROLES):
            return _forbidden()
        return _summaries(list_attendee_event_summaries)

    @app.get("/events/overlapping")
    def overlapping_events():
        # Time-window lookup for Equipment Reservation Service; summaries only, no event body.
        if not _role_allowed(LOOKUP_ROLES):
            return _forbidden()
        statuses = [part for part in request.args.get("statuses", "").split(",") if part]
        if not statuses or any(s not in ALL_STATUSES for s in statuses):
            return jsonify(message=f"statuses must list values from: {', '.join(ALL_STATUSES)}."), 400
        try:
            start, end = (datetime.fromisoformat(request.args.get(key, "")) for key in ("start", "end"))
            exclude = request.args.get("excludeEventId")
            exclude = str(UUID(exclude)) if exclude else None
        except ValueError:
            return jsonify(message="start and end must be ISO date-times and excludeEventId a UUID."), 400
        if end <= start:
            return jsonify(message="end must be after start."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        return jsonify(events=list_overlapping_events(app.config["DATABASE_URL"], start, end, statuses, exclude))

    @app.get("/events/<uuid:event_id>")
    def get_event_details(event_id):
        # ?organiserId= asks for the organiser's own view; who they are comes from the token.
        if request.args.get("organiserId") and not request.args.get("coordinatorId"):
            organiser_id, failure = _current_user()
            if failure:
                return failure
            if not app.config["DATABASE_URL"]:
                return jsonify(
                    message="DATABASE_URL is not configured for Event Service."
                ), 503
            try:
                event = get_organiser_event(
                    app.config["DATABASE_URL"], str(event_id), organiser_id
                )
            except EventNotFoundError:
                return jsonify(message="Event not found."), 404
            except EventNotOwnedError:
                return jsonify(
                    message="You can only view registrations for events you created."
                ), 403
            return jsonify(event), 200
        coordinator_id, failure = _current_user()
        if failure:
            return failure
        viewer_role = g.role if request.args.get("viewerRole") else None
        if viewer_role and viewer_role not in ALL_EVENTS_ROLES:
            return jsonify(message="This role cannot view all internal events."), 403
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Event Service."
            ), 503
        try:
            event = get_event(
                app.config["DATABASE_URL"],
                str(event_id),
                coordinator_id,
                view_all=bool(viewer_role),
            )
        except EventNotFoundError:
            return jsonify(message="Event request not found."), 404
        except EventNotAssignedError:
            return jsonify(
                message="This event request is not assigned to the current coordinator."
            ), 403
        return jsonify(_for_viewer(event)), 200

    @app.post("/events/<uuid:event_id>/change-requests")
    def request_changes(event_id):
        if (forbidden := _cannot_modify(ORGANISER_ONLY)):
            return forbidden
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(message="Send a JSON object."), 400
        organiser_id, failure = _current_user()
        if failure:
            return failure
        changes = data.get("changes")
        if not isinstance(changes, dict) or not changes:
            return jsonify(message="Propose at least one event detail change."), 400
        unknown = sorted(set(changes) - set(EDITABLE_FIELDS))
        if unknown:
            return jsonify(
                message="One or more proposed fields cannot be changed.",
                invalidFields=unknown,
            ), 400
        if any(not isinstance(value, str) for value in changes.values()):
            return jsonify(message="Every proposed value must be text."), 400
        reason = data.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            return jsonify(message="A reason or justification is required."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        try:
            saved = create_change_request(
                app.config["DATABASE_URL"],
                str(event_id),
                organiser_id,
                changes,
                reason.strip(),
            )
        except EventNotFoundError:
            return jsonify(message="Event not found."), 404
        except EventNotOwnedError:
            return jsonify(message="You can only request changes to events you submitted."), 403
        except ChangeRequestNotAllowedError as error:
            return jsonify(
                code="CHANGE_REQUEST_NOT_ALLOWED",
                message=f"Changes cannot be requested while this event is '{error.current_status}'.",
                currentStatus=error.current_status,
            ), 409
        except ChangeRequestAlreadyPendingError:
            return jsonify(
                code="CHANGE_REQUEST_ALREADY_PENDING",
                message="This event already has a change request pending review.",
            ), 409
        except NoProposedChangesError:
            return jsonify(message="At least one proposed value must differ from the event's current details."), 400
        except InvalidProposedChangesError as error:
            return jsonify(
                message="Please correct the proposed event details.",
                missingFields=error.missing,
                errors=error.errors,
            ), 400
        return jsonify(saved), 201

    def _internal_lock_failure(code, message):
        """The refusal for a route only another service may call, else None.

        SCRUM-10: fails closed. An unconfigured token used to switch the lock off; the role checks
        say who the person is, this says the call came through the workflow.
        """
        configured_token = app.config["INTERNAL_SERVICE_TOKEN"]
        if not configured_token:
            return jsonify(
                code="INTERNAL_AUTH_NOT_CONFIGURED",
                message="Internal service authentication is not configured.",
            ), 503
        presented_token = request.headers.get("X-Internal-Service-Token", "")
        if not hmac.compare_digest(presented_token, configured_token):
            return jsonify(code=code, message=message), 403
        return None

    def _change_workflow_failure():
        return _internal_lock_failure("INTERNAL_ONLY", "Internal workflow access required.")

    @app.get("/change-requests")
    def pending_change_requests():
        """Atomic read used by Event Workflow Service (SCRUM-43 AC1/AC2)."""
        if (locked := _change_workflow_failure()):
            return locked
        coordinator_id, failure = _current_user()
        if failure:
            return failure
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        return jsonify(
            changeRequests=list_pending_change_requests(
                app.config["DATABASE_URL"], coordinator_id
            )
        )

    @app.get("/change-requests/<uuid:change_request_id>")
    def change_request_details(change_request_id):
        if (locked := _change_workflow_failure()):
            return locked
        coordinator_id, failure = _current_user()
        if failure:
            return failure
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        try:
            change = get_change_request(
                app.config["DATABASE_URL"], str(change_request_id), coordinator_id
            )
        except ChangeRequestNotFoundError:
            return jsonify(message="Change request not found."), 404
        except EventNotAssignedError:
            return jsonify(message="This event is not assigned to the current coordinator."), 403
        return jsonify(change), 200

    @app.patch("/change-requests/<uuid:change_request_id>/decision")
    def process_change_request(change_request_id):
        """Commit a workflow-approved decision and its event update atomically."""
        if (forbidden := _cannot_modify(COORDINATOR_ROLES)):
            return forbidden
        if (locked := _change_workflow_failure()):
            return locked
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(message="Send a JSON object."), 400
        coordinator_id, failure = _current_user()
        if failure:
            return failure
        decision = data.get("decision")
        if decision not in ("Approved", "Rejected"):
            return jsonify(message="decision must be Approved or Rejected."), 400
        rejection_reason = data.get("reason")
        if decision == "Rejected":
            if not isinstance(rejection_reason, str) or not rejection_reason.strip():
                return jsonify(message="A rejection reason is required."), 400
            rejection_reason = rejection_reason.strip()
            if len(rejection_reason) > 2000:
                return jsonify(message="A rejection reason must be 2000 characters or fewer."), 400
        else:
            rejection_reason = None
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        try:
            decided = decide_change_request(
                app.config["DATABASE_URL"],
                str(change_request_id),
                coordinator_id,
                decision,
                rejection_reason,
            )
        except ChangeRequestNotFoundError:
            return jsonify(message="Change request not found."), 404
        except EventNotAssignedError:
            return jsonify(message="This event is not assigned to the current coordinator."), 403
        except ChangeRequestAlreadyDecidedError as error:
            return jsonify(
                code="CHANGE_REQUEST_ALREADY_DECIDED",
                message=f"This change request is already '{error.current_status}'.",
                currentStatus=error.current_status,
            ), 409
        except ChangeRequestNotAllowedError as error:
            return jsonify(
                code="CHANGE_REQUEST_NOT_APPLICABLE",
                message=f"This request cannot be approved while the event is '{error.current_status}'.",
                currentStatus=error.current_status,
            ), 409
        except InvalidProposedChangesError as error:
            return jsonify(
                code="INVALID_STORED_PROPOSAL",
                message="The proposed event details are no longer valid.",
                missingFields=error.missing,
                errors=error.errors,
            ), 409
        return jsonify(decided), 200

    @app.patch("/events/<uuid:event_id>")
    def assign_coordinator(event_id):
        if (forbidden := _cannot_modify(LEAD_ONLY)):
            return forbidden
        data = request.get_json(silent=True)
        coordinator_id = data.get("assignedCoordinatorId", "") if isinstance(data, dict) else ""
        try:
            coordinator_id = str(UUID(coordinator_id))
        except (ValueError, TypeError, AttributeError):
            return jsonify(message="A valid coordinator ID is required."), 400
        # Who made the assignment is shown on the event's detail page, so it
        # is required rather than left blank.
        assigned_by, failure = _current_user()
        if failure:
            return failure
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        try:
            assigned = update_event_coordinator(
                app.config["DATABASE_URL"], str(event_id), coordinator_id, assigned_by
            )
        except EventNotFoundError:
            return jsonify(message="Event request not found."), 404
        except EventClosedError as closed:
            return jsonify(
                message=f"A {closed.current_status} event can't be reassigned."
            ), 409
        except NoCoordinatorChangeError:
            return jsonify(
                message="That coordinator is already assigned to this event. No change was made."
            ), 409
        return jsonify(assigned), 200

    @app.patch("/events/<uuid:event_id>/progress")
    def update_progress(event_id):
        if (forbidden := _cannot_modify(COORDINATOR_ROLES)):
            return forbidden
        data = request.get_json(silent=True)
        status = data.get("status", "") if isinstance(data, dict) else ""
        action_details = data.get("actionDetails", "") if isinstance(data, dict) else ""
        coordinator_id, failure = _current_user()
        if failure:
            return failure
        if status not in ALL_STATUSES:
            return jsonify(
                message=f"Status must be one of: {', '.join(ALL_STATUSES)}."
            ), 400
        if not isinstance(action_details, str) or not action_details.strip():
            return jsonify(message="Action details are required."), 400
        action_details = action_details.strip()
        if len(action_details) > 1000:
            return jsonify(message="Action details must be 1000 characters or fewer."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        try:
            updated = update_event_progress(
                app.config["DATABASE_URL"],
                str(event_id),
                coordinator_id,
                status,
                action_details,
            )
        except EventNotFoundError:
            return jsonify(message="Event request not found."), 404
        except EventNotAssignedError:
            return jsonify(
                message="This event request is not assigned to the current coordinator."
            ), 403
        # SCRUM-152 AC1: more specific than InvalidStatusTransitionError, so it
        # must be caught first.
        except SafetyApprovalRequiredError as blocked:
            return jsonify(
                code="SAFETY_APPROVAL_REQUIRED",
                message=blocked.message,
                currentStatus=blocked.current_status,
                requiredStatus="Confirmed",
            ), 409
        except InvalidStatusTransitionError:
            return jsonify(
                message="This status change is not allowed for the event's current stage."
            ), 409
        return jsonify(updated), 200

    @app.patch("/events/<uuid:event_id>/details")
    def update_details(event_id):
        """Edit an event's details (SCRUM-153 AC1, AC2; the write SCRUM-20 reuses).

        Body: `{changes: {<EDITABLE_FIELDS>: text}, actorRole?, dryRun?,
        safetyRecheck?: {withdrawnSafetyCheckId, safetyCheckId, roundNumber}}`.

        This is the only endpoint that classifies a change as low- or
        high-impact, which is why the UI calls it first: the low-impact path
        (AC2) needs no safety call at all, and the `409` it answers a
        high-impact change with carries everything the confirm step has to
        show. `safetyRecheck` is accepted only from Safety Check Service, with
        the internal token — that is the gate, so a client that skips the UI
        still can't change a `Confirmed` event's high-impact fields without
        the approval being withdrawn.
        """
        if (forbidden := _cannot_modify(COORDINATOR_ROLES)):
            return forbidden
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(message="Send a JSON object."), 400
        coordinator_id, failure = _current_user()
        if failure:
            return failure

        changes = data.get("changes")
        if not isinstance(changes, dict) or not changes:
            return jsonify(
                message="changes must be a non-empty object of fields to update."
            ), 400
        unknown = sorted(set(changes) - set(EDITABLE_FIELDS))
        if unknown:
            return jsonify(
                message=(
                    f"These fields can't be edited: {', '.join(unknown)}. "
                    f"Editable fields are: {', '.join(EDITABLE_FIELDS)}."
                )
            ), 400
        if any(not isinstance(value, str) for value in changes.values()):
            return jsonify(message="Every value in changes must be text."), 400
        # Asking to act in one's role (the Lead, SCRUM-20); the role itself comes from the token.
        actor_role = g.role if data.get("actorRole") is not None else None
        dry_run = data.get("dryRun", False)
        if not isinstance(dry_run, bool):
            return jsonify(message="dryRun must be true or false."), 400
        safety_recheck, failure = _safety_recheck(data)
        if failure:
            return failure
        # The same lock as /safety-status, and it fails closed (SCRUM-10): without INTERNAL_SERVICE_TOKEN
        # the re-check and the Lead's edit of an unassigned event are refused. Only those two need it; a
        # plain coordinator edit never does, so it works whether or not the token is configured.
        configured_token = app.config["INTERNAL_SERVICE_TOKEN"]
        if (safety_recheck is not None or actor_role is not None) and not configured_token:
            return jsonify(
                code="INTERNAL_AUTH_NOT_CONFIGURED",
                message="Internal service authentication is not configured.",
            ), 503
        internal = bool(configured_token) and hmac.compare_digest(
            request.headers.get("X-Internal-Service-Token", ""), configured_token
        )

        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        try:
            updated = update_event_details(
                app.config["DATABASE_URL"],
                str(event_id),
                coordinator_id,
                changes,
                safety_recheck=safety_recheck,
                internal=internal,
                actor_role=actor_role,
                dry_run=dry_run,
            )
        except EventNotFoundError:
            return jsonify(message="Event request not found."), 404
        except EventNotAssignedError:
            return jsonify(
                message="This event request is not assigned to the current coordinator."
            ), 403
        except EventNotEditableError as blocked:
            return jsonify(
                code="EVENT_NOT_EDITABLE",
                message=(
                    f"An event that is '{blocked.current_status}' can no longer "
                    "be edited."
                ),
                currentStatus=blocked.current_status,
            ), 409
        except SafetyRecheckRequiredError as recheck:
            # AC1, before anything is written: the coordinator is told what
            # this change costs and confirms it, and the workflow (not this
            # endpoint) is what actually withdraws the approval.
            return jsonify(
                code="SAFETY_RECHECK_REQUIRED",
                message=recheck.message,
                changedFields=recheck.changed_fields,
                highImpactFields=recheck.high_impact_fields,
                labels=recheck.labels,
            ), 409
        except EventUnderSafetyReviewError:
            return jsonify(
                code="EVENT_UNDER_SAFETY_REVIEW",
                message=UNDER_SAFETY_REVIEW_MESSAGE,
                currentStatus="Pending Safety Check",
            ), 409
        except StaleSafetyCheckError:
            return jsonify(
                code="STALE_SAFETY_CHECK",
                message="This safety check round is not the approval this event holds.",
            ), 409
        except ValueError as invalid:
            details = invalid.args[0]
            return jsonify(
                message="Please correct the event details.",
                missingFields=details["missingFields"],
                errors=details["errors"],
            ), 400
        return jsonify(updated), 200

    @app.patch("/events/<uuid:event_id>/safety-status")
    def update_safety_status(event_id):
        """Move an event along the safety-check workflow (SCRUM-149 AC1, SCRUM-150 AC1).

        For Safety Check Service only: it is the service that has checked the
        caller's role and the event's arrangements first. Deliberately
        separate from PATCH /progress, which still cannot reach any safety
        status (SCRUM-152), so there is exactly one way into this part of the
        lifecycle.

        Two checks, in this order. The caller's role (SCRUM-10): a coordinator
        submits, withdraws or restores; only a Safety Officer decides. Then the
        internal token (SCRUM-150, moved forward from SCRUM-152 v2), which
        proves the call came through Safety Check Service. The token fails
        closed (SCRUM-10): without `INTERNAL_SERVICE_TOKEN` configured on this
        service the route answers 503 rather than skipping the lock.
        """
        if (forbidden := _cannot_modify(SAFETY_STATUS_ROLES)):
            return forbidden
        if (locked := _internal_lock_failure(
            "INTERNAL_ONLY", "Only the Safety Check workflow can change an event's safety status."
        )):
            return locked
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(message="Send a JSON object."), 400
        status = data.get("status", "")
        # SCRUM-28 Part B: 'Approved' is a target only for a venue-change
        # withdrawal, which names the round (checked below). Without that
        # marker it is a pre-safety status, refused like the others.
        if status not in SAFETY_STATUSES and not (
            status == "Approved" and data.get("withdrawnSafetyCheckId") is not None
        ):
            return jsonify(
                message=f"Status must be one of: {', '.join(SAFETY_STATUSES)}."
            ), 400
        # SCRUM-153: 'Confirmed -> Pending Safety Check' can't be refused here,
        # before the database is read — `Pending Safety Check` is also the
        # target of SCRUM-149's legitimate submit move, so only the event's
        # current status tells the two apart. `update_event_safety_status`
        # refuses every pair in RECHECK_ONLY_MOVES under its row lock, which
        # is where that status is known and can't be stale.
        try:
            safety_check_id = str(UUID(data.get("safetyCheckId", "")))
        except (ValueError, TypeError, AttributeError):
            return jsonify(message="A valid safety check ID is required."), 400
        round_number = data.get("roundNumber")
        if (
            isinstance(round_number, bool)
            or not isinstance(round_number, int)
            or round_number < 1
        ):
            return jsonify(message="roundNumber must be a positive whole number."), 400

        # SCRUM-28 Part B: a venue booking change withdraws a Confirmed
        # event's approval (-> Approved), or undoes that (-> Confirmed). The
        # marker must name the same round as safetyCheckId.
        venue_change, failure = _venue_change(data, status, safety_check_id)
        if failure:
            return failure

        # SCRUM-10: who may make this move depends on the move. A coordinator submits, withdraws or
        # restores; only a Safety Officer decides. Still before anything is read or written.
        decides = not venue_change and status != "Pending Safety Check"
        if (forbidden := _cannot_modify(SAFETY_OFFICER_ONLY if decides else COORDINATOR_ROLES)):
            return forbidden

        # Each move needs its own identity fields validated.
        coordinator_id = None
        decided_by = None
        remarks = None
        areas = None
        if status == "Pending Safety Check" or venue_change:
            coordinator_id, failure = _current_user()
            if failure:
                return failure
        if venue_change:
            pass
        elif status in ("Confirmed", "Safety Changes Requested", "Cancelled"):
            decided_by, failure = _current_user()
            if failure:
                return failure
            remarks = data.get("remarks")
            if remarks is not None and not isinstance(remarks, str):
                return jsonify(message="remarks must be text."), 400
            if isinstance(remarks, str):
                remarks = remarks.strip() or None
                if remarks and len(remarks) > 2000:
                    return jsonify(
                        message="remarks must be 2000 characters or fewer."
                    ), 400
            # 'Confirmed' keeps remarks optional (SCRUM-150); the other two
            # require it, non-blank (SCRUM-151 AC1, AC3, AC6).
            if status != "Confirmed" and not remarks:
                return jsonify(message="remarks is required."), 400
            if status == "Safety Changes Requested":
                raw_areas = data.get("areas")
                if not isinstance(raw_areas, list) or not raw_areas:
                    return jsonify(
                        message="areas must be a non-empty list."
                    ), 400
                if len(raw_areas) != len(set(raw_areas)) or any(
                    area not in SAFETY_FLAG_AREAS for area in raw_areas
                ):
                    return jsonify(
                        message=(
                            f"areas must be distinct values from: "
                            f"{', '.join(SAFETY_FLAG_AREAS)}."
                        )
                    ), 400
                areas = raw_areas

        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        try:
            updated = update_event_safety_status(
                app.config["DATABASE_URL"],
                str(event_id),
                status,
                safety_check_id,
                round_number,
                coordinator_id=coordinator_id,
                decided_by=decided_by,
                remarks=remarks,
                areas=areas,
                venue_change=venue_change,
                attendee_venue=data.get("attendeeVenue"),
            )
        except EventNotFoundError:
            return jsonify(message="Event request not found."), 404
        except EventNotAssignedError:
            return jsonify(
                message="This event request is not assigned to the current coordinator."
            ), 403
        # More specific than InvalidStatusTransitionError, so it comes first.
        except SafetyCheckAlreadyPendingError:
            return jsonify(
                code="SAFETY_CHECK_ALREADY_PENDING",
                message="This event is already waiting for its safety check.",
            ), 409
        except StaleSafetyCheckError:
            return jsonify(
                code="STALE_SAFETY_CHECK",
                message="This safety check round is no longer the one awaiting a decision.",
            ), 409
        except InvalidStatusTransitionError as blocked:
            return jsonify(
                code="INVALID_SAFETY_TRANSITION",
                message=(
                    f"This event can't move to '{status}' from "
                    f"'{blocked.current_status}'."
                ),
                currentStatus=blocked.current_status,
            ), 409
        except ValueError:
            return jsonify(message="A complete approved attendee schedule is required."), 400
        return jsonify(updated), 200

    @app.patch("/events/<uuid:event_id>/approve")
    def approve(event_id):
        if (forbidden := _cannot_modify(COORDINATOR_ROLES)):
            return forbidden
        coordinator_id, failure = _current_user()
        if failure:
            return failure
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Event Service."
            ), 503
        try:
            approved = approve_event(
                app.config["DATABASE_URL"], str(event_id), coordinator_id
            )
        except EventNotFoundError:
            return jsonify(message="Event request not found."), 404
        except EventNotAssignedError:
            return jsonify(
                message="This event request is not assigned to the current coordinator."
            ), 403
        except EventNotSubmittedError:
            return jsonify(
                message="Only submitted or under-review event requests can be approved."
            ), 409
        return jsonify(approved), 200

    @app.patch("/events/<uuid:event_id>/clarification-request")
    def request_clarification(event_id):
        if (forbidden := _cannot_modify(COORDINATOR_ROLES)):
            return forbidden
        data = request.get_json(silent=True)
        message = data.get("message") if isinstance(data, dict) else None
        coordinator_id, failure = _current_user()
        if failure:
            return failure
        if not isinstance(message, str) or not message.strip():
            return jsonify(message="A clarification question is required."), 400
        message = message.strip()
        if len(message) > 1000:
            return jsonify(message="A clarification question must be 1000 characters or fewer."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        try:
            updated = request_event_clarification(
                app.config["DATABASE_URL"], str(event_id), coordinator_id, message
            )
        except EventNotFoundError:
            return jsonify(message="Event request not found."), 404
        except EventNotAssignedError:
            return jsonify(
                message="This event request is not assigned to the current coordinator."
            ), 403
        except ClarificationNotAllowedError as blocked:
            return jsonify(
                code="CLARIFICATION_NOT_ALLOWED",
                message=(
                    "Clarification can only be requested for a submitted or "
                    "under-review event request."
                ),
                currentStatus=blocked.current_status,
            ), 409
        return jsonify(updated), 200

    @app.patch("/events/<uuid:event_id>/clarification-response")
    def respond_to_clarification(event_id):
        if (forbidden := _cannot_modify(ORGANISER_ONLY)):
            return forbidden
        data = request.get_json(silent=True)
        response = data.get("response") if isinstance(data, dict) else None
        organiser_id, failure = _current_user()
        if failure:
            return failure
        if not isinstance(response, str) or not response.strip():
            return jsonify(message="A clarification response is required."), 400
        response = response.strip()
        if len(response) > 1000:
            return jsonify(message="A clarification response must be 1000 characters or fewer."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        try:
            updated = respond_to_event_clarification(
                app.config["DATABASE_URL"], str(event_id), organiser_id, response
            )
        except EventNotFoundError:
            return jsonify(message="Event request not found."), 404
        except EventNotOwnedError:
            return jsonify(
                message="You can only respond to clarification requests for events you created."
            ), 403
        except ClarificationNotOpenError:
            return jsonify(
                code="CLARIFICATION_NOT_OPEN",
                message="This event does not have an open clarification request.",
            ), 409
        return jsonify(updated), 200

    @app.patch("/events/<uuid:event_id>/amendment-request")
    def request_amendment(event_id):
        """SCRUM-16 AC1/AC2/AC5: the assigned coordinator flags fields for the organiser to amend."""
        if (forbidden := _cannot_modify(COORDINATOR_ROLES)):
            return forbidden
        data = request.get_json(silent=True)
        fields = data.get("fields") if isinstance(data, dict) else None
        reason = data.get("reason") if isinstance(data, dict) else None
        coordinator_id, failure = _current_user()
        if failure:
            return failure
        if (
            not isinstance(fields, list)
            or not fields
            or any(not isinstance(field, str) for field in fields)
        ):
            return jsonify(message="Flag at least one field that needs amending."), 400
        invalid = sorted(set(fields) - set(AMENDABLE_FIELDS))
        if invalid:
            return jsonify(
                message="One or more flagged fields cannot be amended.",
                invalidFields=invalid,
            ), 400
        if not isinstance(reason, str) or not reason.strip():
            return jsonify(message="A reason for the amendment is required."), 400
        reason = reason.strip()
        if len(reason) > 1000:
            return jsonify(message="An amendment reason must be 1000 characters or fewer."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        try:
            updated = request_event_amendment(
                app.config["DATABASE_URL"], str(event_id), coordinator_id, fields, reason
            )
        except EventNotFoundError:
            return jsonify(message="Event request not found."), 404
        except EventNotAssignedError:
            return jsonify(
                message="This event request is not assigned to the current coordinator."
            ), 403
        except AmendmentNotAllowedError as blocked:
            return jsonify(
                code="AMENDMENT_NOT_ALLOWED",
                message=(
                    "Amendment can only be requested for a submitted or "
                    "under-review event request."
                ),
                currentStatus=blocked.current_status,
            ), 409
        return jsonify(updated), 200

    @app.patch("/events/<uuid:event_id>/amendment-response")
    def respond_to_amendment(event_id):
        """SCRUM-16 AC3/AC4: the organiser amends only the flagged fields and resubmits."""
        if (forbidden := _cannot_modify(ORGANISER_ONLY)):
            return forbidden
        data = request.get_json(silent=True)
        changes = data.get("changes") if isinstance(data, dict) else None
        note = data.get("note") if isinstance(data, dict) else None
        organiser_id, failure = _current_user()
        if failure:
            return failure
        if not isinstance(changes, dict) or not changes:
            return jsonify(message="Send the amended values for the flagged fields."), 400
        if any(not isinstance(value, str) for value in changes.values()):
            return jsonify(message="Every amended value must be text."), 400
        if note is not None and (not isinstance(note, str) or len(note.strip()) > 1000):
            return jsonify(message="A resubmission note must be 1000 characters or fewer."), 400
        note = (note or "").strip() or None
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        try:
            updated = respond_to_event_amendment(
                app.config["DATABASE_URL"], str(event_id), organiser_id, changes, note
            )
        except EventNotFoundError:
            return jsonify(message="Event request not found."), 404
        except EventNotOwnedError:
            return jsonify(message="You can only amend event requests you created."), 403
        except AmendmentNotOpenError:
            return jsonify(
                code="AMENDMENT_NOT_OPEN",
                message="This event does not have an open amendment request.",
            ), 409
        except AmendmentFieldLockedError as locked:
            return jsonify(
                code="AMENDMENT_FIELD_LOCKED",
                message="Only the fields the Event Coordinator flagged can be changed.",
                lockedFields=locked.locked_fields,
            ), 400
        except NoAmendmentChangesError:
            return jsonify(
                code="NO_AMENDMENT_CHANGES",
                message="Change at least one flagged field before resubmitting.",
            ), 400
        except InvalidProposedChangesError as error:
            return jsonify(
                message="Please correct the event details.",
                missingFields=error.missing,
                errors=error.errors,
            ), 400
        return jsonify(updated), 200

    @app.patch("/events/<uuid:event_id>/reject")
    def reject(event_id):
        if (forbidden := _cannot_modify(COORDINATOR_ROLES)):
            return forbidden
        data = request.get_json(silent=True)
        reason = data.get("reason") if isinstance(data, dict) else None
        coordinator_id, failure = _current_user()
        if failure:
            return failure
        if not isinstance(reason, str) or not reason.strip():
            return jsonify(
                message="A reason is required when rejecting an event request."
            ), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Event Service."
            ), 503
        try:
            rejected = reject_event(
                app.config["DATABASE_URL"], str(event_id), coordinator_id, reason
            )
        except EventNotFoundError:
            return jsonify(message="Event request not found."), 404
        except EventNotAssignedError:
            return jsonify(
                message="This event request is not assigned to the current coordinator."
            ), 403
        except EventNotSubmittedError:
            return jsonify(
                message="Only submitted or under-review event requests can be rejected."
            ), 409
        return jsonify(rejected), 200

    from app.outbox import bp as outbox_bp
    app.register_blueprint(outbox_bp)
    return app
