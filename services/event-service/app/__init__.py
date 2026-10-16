import hmac
import os
from datetime import datetime, time
from uuid import UUID

import psycopg2
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

from app.models import (
    ALL_STATUSES,
    FIELDS,
    SAFETY_FLAG_AREAS,
    SAFETY_STATUSES,
    EventClosedError,
    EventNotAssignedError,
    EventNotFoundError,
    EventNotOwnedError,
    EventNotSubmittedError,
    InvalidStatusTransitionError,
    NoCoordinatorChangeError,
    RejectionReasonError,
    SafetyApprovalRequiredError,
    SafetyCheckAlreadyPendingError,
    StaleSafetyCheckError,
    approve_event,
    get_event,
    get_organiser_event,
    list_event_summaries,
    list_events,
    list_confirmed_events,
    list_organiser_events,
    list_overlapping_events,
    list_submitted,
    list_unassigned,
    reject_event,
    submit_event,
    update_event_coordinator,
    update_event_progress,
    update_event_safety_status,
)
from app.validation import validate

# Roles that see every event rather than only the ones assigned to them,
# passed as ?viewerRole=. Until services verify a JWT (AGENTS.md) the role is
# whatever the caller sends, like coordinatorId.
LEAD_ROLE = "Event Coordinator Lead"
ALL_EVENTS_ROLES = (LEAD_ROLE, "Venue Staff", "Technical Support", "Safety Officer")


def create_app(config=None):
    app = Flask(__name__)
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
            "is not locked to Safety Check Service (SCRUM-150/152)."
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
                "GET, POST, PATCH, OPTIONS"
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

    @app.post("/events")
    def submit():
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
        organiser_id = data.get("organiserId")
        if organiser_id not in (None, ""):
            try:
                details["organiserId"] = str(UUID(organiser_id))
            except (ValueError, TypeError, AttributeError):
                return jsonify(message="A valid organiser ID is required."), 400
        return jsonify(submit_event(app.config["DATABASE_URL"], details)), 201

    @app.get("/events/submitted")
    def submitted():
        try:
            coordinator_id = str(UUID(request.args.get("coordinatorId", "")))
        except (ValueError, TypeError, AttributeError):
            return jsonify(message="A valid current coordinator ID is required."), 400
        viewer_role = request.args.get("viewerRole") or None
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
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Event Service."
            ), 503
        return jsonify(events=list_unassigned(app.config["DATABASE_URL"]))

    @app.get("/events")
    def list_events_route():
        if request.args.get("organiserId") and not request.args.get("coordinatorId"):
            try:
                organiser_id = str(UUID(request.args["organiserId"]))
            except (ValueError, TypeError, AttributeError):
                return jsonify(message="A valid current organiser ID is required."), 400
            if not app.config["DATABASE_URL"]:
                return jsonify(
                    message="DATABASE_URL is not configured for Event Service."
                ), 503
            return jsonify(
                events=list_organiser_events(app.config["DATABASE_URL"], organiser_id)
            )
        try:
            coordinator_id = str(UUID(request.args.get("coordinatorId", "")))
        except (ValueError, TypeError, AttributeError):
            return jsonify(message="A valid current coordinator ID is required."), 400

        viewer_role = request.args.get("viewerRole") or None
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
        return jsonify(
            events=list_events(
                app.config["DATABASE_URL"],
                coordinator_id,
                status,
                venue,
                date_from,
                date_to,
                view_all=bool(viewer_role),
            )
        )

    @app.get("/events/registration")
    def registration_events():
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        return jsonify(events=list_confirmed_events(app.config["DATABASE_URL"]))

    @app.get("/events/summaries")
    def event_summaries():
        # Name/status lookup for other screens (e.g. equipment review); no event body or ownership check.
        raw_ids = [part for part in request.args.get("ids", "").split(",") if part]
        if not raw_ids or len(raw_ids) > 100:
            return jsonify(message="Provide between 1 and 100 comma-separated event IDs."), 400
        try:
            ids = [str(UUID(part)) for part in raw_ids]
        except ValueError:
            return jsonify(message="Every event ID must be a valid UUID."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        return jsonify(events=list_event_summaries(app.config["DATABASE_URL"], ids))

    @app.get("/events/overlapping")
    def overlapping_events():
        # Time-window lookup for Equipment Reservation Service; summaries only, no event body.
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
        if request.args.get("organiserId") and not request.args.get("coordinatorId"):
            try:
                organiser_id = str(UUID(request.args["organiserId"]))
            except (ValueError, TypeError, AttributeError):
                return jsonify(message="A valid current organiser ID is required."), 400
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
        try:
            coordinator_id = str(UUID(request.args.get("coordinatorId", "")))
        except (ValueError, TypeError, AttributeError):
            return jsonify(message="A valid current coordinator ID is required."), 400
        viewer_role = request.args.get("viewerRole") or None
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
        return jsonify(event), 200

    @app.patch("/events/<uuid:event_id>")
    def assign_coordinator(event_id):
        data = request.get_json(silent=True)
        coordinator_id = data.get("assignedCoordinatorId", "") if isinstance(data, dict) else ""
        assigned_by = data.get("assignedBy", "") if isinstance(data, dict) else ""
        try:
            coordinator_id = str(UUID(coordinator_id))
        except (ValueError, TypeError, AttributeError):
            return jsonify(message="A valid coordinator ID is required."), 400
        # Who made the assignment is shown on the event's detail page, so it
        # is required rather than left blank.
        try:
            assigned_by = str(UUID(assigned_by))
        except (ValueError, TypeError, AttributeError):
            return jsonify(message="A valid assigning user ID is required."), 400
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
        data = request.get_json(silent=True)
        coordinator_id = data.get("coordinatorId", "") if isinstance(data, dict) else ""
        status = data.get("status", "") if isinstance(data, dict) else ""
        action_details = data.get("actionDetails", "") if isinstance(data, dict) else ""
        try:
            coordinator_id = str(UUID(coordinator_id))
        except (ValueError, TypeError, AttributeError):
            return jsonify(message="A valid current coordinator ID is required."), 400
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

    @app.patch("/events/<uuid:event_id>/safety-status")
    def update_safety_status(event_id):
        """Move an event along the safety-check workflow (SCRUM-149 AC1, SCRUM-150 AC1).

        For Safety Check Service only: it is the service that has checked the
        caller's role and the event's arrangements first. Deliberately
        separate from PATCH /progress, which still cannot reach any safety
        status (SCRUM-152), so there is exactly one way into this part of the
        lifecycle.

        The internal token below (SCRUM-150, moved forward from SCRUM-152 v2)
        is an opt-in lock: if `INTERNAL_SERVICE_TOKEN` isn't configured on
        this service, the check is skipped entirely rather than failing
        closed — local/dev setups that don't set it behave exactly as before
        SCRUM-150. Configuring it (on both this service and Safety Check
        Service) turns the lock on.
        """
        configured_token = app.config["INTERNAL_SERVICE_TOKEN"]
        if configured_token:
            presented_token = request.headers.get("X-Internal-Service-Token", "")
            if not hmac.compare_digest(presented_token, configured_token):
                return jsonify(
                    code="INTERNAL_ONLY",
                    message="Only the Safety Check workflow can change an event's safety status.",
                ), 403

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(message="Send a JSON object."), 400
        status = data.get("status", "")
        if status not in SAFETY_STATUSES:
            return jsonify(
                message=f"Status must be one of: {', '.join(SAFETY_STATUSES)}."
            ), 400
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

        # Each move needs its own identity fields validated.
        coordinator_id = None
        decided_by = None
        remarks = None
        areas = None
        if status == "Pending Safety Check":
            try:
                coordinator_id = str(UUID(data.get("coordinatorId", "")))
            except (ValueError, TypeError, AttributeError):
                return jsonify(message="A valid coordinator ID is required."), 400
        elif status in ("Confirmed", "Safety Changes Requested", "Cancelled"):
            try:
                decided_by = str(UUID(data.get("decidedBy", "")))
            except (ValueError, TypeError, AttributeError):
                return jsonify(message="A valid decidedBy ID is required."), 400
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
        return jsonify(updated), 200

    @app.patch("/events/<uuid:event_id>/approve")
    def approve(event_id):
        data = request.get_json(silent=True)
        coordinator_id = data.get("coordinatorId", "") if isinstance(data, dict) else ""
        try:
            coordinator_id = str(UUID(coordinator_id))
        except (ValueError, TypeError, AttributeError):
            return jsonify(message="A valid current coordinator ID is required."), 400
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

    @app.patch("/events/<uuid:event_id>/reject")
    def reject(event_id):
        data = request.get_json(silent=True)
        coordinator_id = data.get("coordinatorId", "") if isinstance(data, dict) else ""
        reason = data.get("reason") if isinstance(data, dict) else None
        try:
            coordinator_id = str(UUID(coordinator_id))
        except (ValueError, TypeError, AttributeError):
            return jsonify(message="A valid current coordinator ID is required."), 400
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
        except RejectionReasonError:
            return jsonify(
                message="A reason is required when rejecting an event request."
            ), 400
        return jsonify(rejected), 200

    return app
