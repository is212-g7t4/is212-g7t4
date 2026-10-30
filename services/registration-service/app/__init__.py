import os
from uuid import UUID

import psycopg2
from dotenv import load_dotenv
from flask import Flask, g, jsonify, request

load_dotenv()

from app.models import (
    CapacityReachedError,
    DuplicateRegistrationError,
    RegistrationAlreadyWithdrawnError,
    RegistrationNotFoundError,
    RegistrationOwnershipError,
    count_registrations,
    create_registration,
    list_attendee_registrations,
    list_registrations,
    withdraw_registration,
)
from app.auth import authenticate

EVENT_TEAM_ROLES = ("Event Organiser", "Event Coordinator", "Event Coordinator Lead")


def create_app(config=None):
    app = Flask(__name__)
    app.before_request(authenticate)
    app.config.from_mapping(
        DATABASE_URL=os.getenv("DATABASE_URL"),
        INTERNAL_SERVICE_TOKEN=os.getenv("INTERNAL_SERVICE_TOKEN", ""),
        # The Vite dev server is pinned to 5174 (strictPort in
        # vite.config.ts), so that is the origin the browser sends.
        FRONTEND_ORIGIN=os.getenv("FRONTEND_ORIGIN", "http://localhost:5174"),
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
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Accept, Authorization"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
        if request.method == "OPTIONS":
            response.status_code = 200
        return response

    @app.errorhandler(psycopg2.Error)
    def database_failure(error):
        # Do not expose credentials, SQL or database internals in the response/log.
        return jsonify(
            message="Unable to save or load registrations. Please check the Registration Service database connection and schema."
        ), 503

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/registrations/counts")
    def registration_counts():
        raw = request.args.get("eventIds", "")
        try:
            event_ids = list(dict.fromkeys(str(UUID(part)) for part in raw.split(",")))
        except (ValueError, TypeError, AttributeError):
            return jsonify(message="eventIds must be a comma-separated list of valid event IDs."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Registration Service."), 503
        return jsonify(counts=count_registrations(app.config["DATABASE_URL"], event_ids))

    @app.get("/registrations")
    def registrations():
        event_id = request.args.get("eventId")
        # Without an event, the signed-in attendee's own registrations.
        if event_id is None and g.user_id:
            if not app.config["DATABASE_URL"]:
                return jsonify(message="DATABASE_URL is not configured for Registration Service."), 503
            return jsonify(
                registrations=list_attendee_registrations(app.config["DATABASE_URL"], g.user_id)
            )
        # An event's attendee list is for its team only (SCRUM-9); whether this caller
        # is that event's organiser/coordinator is checked by Attendee Registration Service.
        if g.user_id and g.role not in EVENT_TEAM_ROLES:
            return jsonify(message="Your role cannot view an event's registrations."), 403
        try:
            event_id = str(UUID(event_id or ""))
        except (ValueError, TypeError, AttributeError):
            return jsonify(message="A valid eventId is required."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Registration Service."), 503
        return jsonify(registrations=list_registrations(app.config["DATABASE_URL"], event_id))

    @app.post("/registrations")
    def add_registration():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(message="Send a JSON object."), 400

        attendee_id = g.user_id
        if not attendee_id:
            return jsonify(message="Sign in to continue."), 401
        try:
            event_id = str(UUID(data.get("eventId", "")))
            capacity = int(data.get("capacity"))
        except (ValueError, TypeError, AttributeError):
            return jsonify(message="Valid eventId and capacity are required."), 400
        if capacity < 1:
            return jsonify(message="Valid eventId and capacity are required."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Registration Service."), 503

        try:
            registration = create_registration(
                app.config["DATABASE_URL"], event_id, attendee_id, capacity,
                **({"notification_context": data["notificationContext"]} if "notificationContext" in data else {})
            )
        except ValueError:
            return jsonify(message="Complete notification snapshot required."), 400
        except DuplicateRegistrationError:
            return jsonify(code="DUPLICATE_REGISTRATION", message="You are already registered for this event."), 409
        except CapacityReachedError:
            return jsonify(code="EVENT_FULL", message="This event has reached maximum capacity."), 409
        return jsonify(registration=registration), 201

    @app.patch("/registrations/<uuid:registration_id>/withdraw")
    def withdraw(registration_id):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(message="Send a JSON object."), 400
        attendee_id = g.user_id
        if not attendee_id:
            return jsonify(message="Sign in to continue."), 401
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Registration Service."), 503
        try:
            registration = withdraw_registration(
                app.config["DATABASE_URL"], str(registration_id), attendee_id,
                **({"notification_context": data["notificationContext"]} if "notificationContext" in data else {})
            )
        except ValueError:
            return jsonify(message="Complete notification snapshot required."), 400
        except RegistrationNotFoundError:
            return jsonify(code="REGISTRATION_NOT_FOUND", message="Registration not found."), 404
        except RegistrationOwnershipError:
            return jsonify(
                code="REGISTRATION_NOT_OWNED",
                message="You can only withdraw your own registration.",
            ), 403
        except RegistrationAlreadyWithdrawnError:
            return jsonify(
                code="REGISTRATION_ALREADY_WITHDRAWN",
                message="This registration has already been withdrawn.",
            ), 409
        return jsonify(registration=registration), 200

    from app.outbox import bp
    app.register_blueprint(bp)
    return app
