import os
from datetime import datetime, time
from uuid import UUID

import psycopg2
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

from app.models import (
    FIELDS,
    EventConflictError,
    EventNotAssignedError,
    EventNotFoundError,
    EventNotSubmittedError,
    RejectionReasonError,
    approve_event,
    get_event,
    list_events,
    list_submitted,
    reject_event,
    submit_event,
    update_event_coordinator,
    update_event_information,
)
from app.validation import validate


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE_URL=os.getenv("DATABASE_URL"),
        FRONTEND_ORIGIN=os.getenv("FRONTEND_ORIGIN", "http://localhost:5173"),
        MAX_CONTENT_LENGTH=65536,
        ARRANGEMENT_CONFLICT_CHECKER=lambda event_id, current, proposed: [],
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
        return jsonify(submit_event(app.config["DATABASE_URL"], details)), 201

    @app.get("/events/submitted")
    def submitted():
        coordinator_id = request.args.get("coordinatorId")
        if coordinator_id not in (None, ""):
            try:
                coordinator_id = str(UUID(coordinator_id))
            except (ValueError, TypeError, AttributeError):
                return jsonify(
                    message="A valid current coordinator ID is required."
                ), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Event Service."
            ), 503
        return jsonify(
            events=list_submitted(app.config["DATABASE_URL"], coordinator_id)
        )

    @app.get("/events")
    def list_events_route():
        try:
            coordinator_id = str(UUID(request.args.get("coordinatorId", "")))
        except (ValueError, TypeError, AttributeError):
            return jsonify(message="A valid current coordinator ID is required."), 400

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
            )
        )

    @app.get("/events/<uuid:event_id>")
    def get_event_details(event_id):
        try:
            coordinator_id = str(UUID(request.args.get("coordinatorId", "")))
        except (ValueError, TypeError, AttributeError):
            return jsonify(message="A valid current coordinator ID is required."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Event Service."
            ), 503
        try:
            event = get_event(app.config["DATABASE_URL"], str(event_id), coordinator_id)
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
        coordinator_id = (
            data.get("assignedCoordinatorId", "") if isinstance(data, dict) else ""
        )
        try:
            coordinator_id = str(UUID(coordinator_id))
        except (ValueError, TypeError, AttributeError):
            return jsonify(message="A valid coordinator ID is required."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Event Service."
            ), 503
        try:
            assigned = update_event_coordinator(
                app.config["DATABASE_URL"], str(event_id), coordinator_id
            )
        except EventNotFoundError:
            return jsonify(message="Event request not found."), 404
        return jsonify(assigned), 200

    @app.patch("/events/<uuid:event_id>/update")
    def update_information(event_id):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(message="Send a JSON object."), 400
        coordinator_id = data.pop("coordinatorId", "")
        try:
            coordinator_id = str(UUID(coordinator_id))
        except (ValueError, TypeError, AttributeError):
            return jsonify(message="A valid current coordinator ID is required."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Event Service."
            ), 503
        try:
            updated = update_event_information(
                app.config["DATABASE_URL"],
                str(event_id),
                coordinator_id,
                data,
                app.config["ARRANGEMENT_CONFLICT_CHECKER"],
            )
        except EventNotFoundError:
            return jsonify(message="Event request not found."), 404
        except EventNotAssignedError:
            return jsonify(
                message="This event request is not assigned to the current coordinator."
            ), 403
        except EventConflictError as error:
            return jsonify(
                message="The change conflicts with an existing event arrangement.",
                conflicts=error.conflicts,
            ), 409
        except ValueError as error:
            details = error.args[0]
            if isinstance(details, dict):
                return jsonify(
                    message="Please correct the event details.", **details
                ), 400
            return jsonify(message=str(details)), 400
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
                message="Only submitted event requests can be approved."
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
                message="Only submitted event requests can be rejected."
            ), 409
        except RejectionReasonError:
            return jsonify(
                message="A reason is required when rejecting an event request."
            ), 400
        return jsonify(rejected), 200

    return app
