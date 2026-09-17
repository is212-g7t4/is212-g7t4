import os
from uuid import UUID

import psycopg2
from flask import Flask, jsonify, request

from app.models import (
    FIELDS,
    EventNotAssignedError,
    EventNotFoundError,
    EventNotSubmittedError,
    RejectionReasonError,
    approve_event,
    list_submitted,
    reject_event,
    submit_event,
)
from app.validation import validate


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE_URL=os.getenv("DATABASE_URL"),
        FRONTEND_ORIGIN=os.getenv("FRONTEND_ORIGIN", "http://localhost:5173"),
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
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, POST, PATCH, OPTIONS"
            )
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
        if not app.config["DATABASE_URL"]:
            return jsonify(
                message="DATABASE_URL is not configured for Event Service."
            ), 503
        return jsonify(events=list_submitted(app.config["DATABASE_URL"]))

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
