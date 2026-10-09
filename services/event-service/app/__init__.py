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
    EventNotAssignedError,
    EventNotFoundError,
    EventNotOwnedError,
    EventNotSubmittedError,
    InvalidStatusTransitionError,
    RejectionReasonError,
    SafetyApprovalRequiredError,
    approve_event,
    get_event,
    get_organiser_event,
    list_event_summaries,
    list_events,
    list_confirmed_events,
    list_organiser_events,
    list_overlapping_events,
    list_submitted,
    reject_event,
    submit_event,
    update_event_coordinator,
    update_event_progress,
)
from app.validation import validate

EVENT_STATUSES = ("Submitted", "Under Review", "Approved", "Confirmed", "Rejected")


def create_app(config=None):
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
        coordinator_id = request.args.get("coordinatorId")
        if coordinator_id not in (None, ""):
            try:
                coordinator_id = str(UUID(coordinator_id))
            except (ValueError, TypeError, AttributeError):
                return jsonify(message="A valid current coordinator ID is required."), 400
        is_manager = request.args.get("isManager") in ("true", "1")
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Event Service."
            ), 503
        return jsonify(
            events=list_submitted(app.config["DATABASE_URL"], coordinator_id, is_manager)
        )

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
        if viewer_role and viewer_role not in ("Venue Staff", "Technical Support"):
            return jsonify(message="This role cannot view all internal events."), 403
        status = request.args.get("status") or None
        venue = request.args.get("venue") or None
        venue_id = request.args.get("venueId") or None
        if venue_id:
            try:
                venue_id = str(UUID(venue_id))
            except (ValueError, TypeError, AttributeError):
                return jsonify(message="venueId must be a valid venue ID."), 400
        is_manager = (
            request.args.get("isManager") in ("true", "1")
            or viewer_role in ("Venue Staff", "Technical Support")
        )

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
                is_manager,
                venue_id=venue_id,
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
        if not statuses or any(s not in EVENT_STATUSES for s in statuses):
            return jsonify(message=f"statuses must list values from: {', '.join(EVENT_STATUSES)}."), 400
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
        if viewer_role and viewer_role not in ("Venue Staff", "Technical Support"):
            return jsonify(message="This role cannot view all internal events."), 403
        is_manager = (
            request.args.get("isManager") in ("true", "1")
            or viewer_role in ("Venue Staff", "Technical Support")
        )
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Event Service."
            ), 503
        try:
            event = get_event(app.config["DATABASE_URL"], str(event_id), coordinator_id, is_manager)
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
        try:
            coordinator_id = str(UUID(coordinator_id))
        except (ValueError, TypeError, AttributeError):
            return jsonify(message="A valid coordinator ID is required."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        try:
            assigned = update_event_coordinator(
                app.config["DATABASE_URL"], str(event_id), coordinator_id
            )
        except EventNotFoundError:
            return jsonify(message="Event request not found."), 404
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
