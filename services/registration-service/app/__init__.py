import os
from uuid import UUID

import psycopg2
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

from app.models import (
    CapacityReachedError,
    DuplicateRegistrationError,
    count_registrations,
    create_registration,
    list_registrations,
)


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE_URL=os.getenv("DATABASE_URL"),
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
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Accept"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        if request.method == "OPTIONS":
            response.status_code = 200
        return response

    @app.errorhandler(psycopg2.Error)
    def database_failure(error):
        # Do not expose credentials, SQL or database internals in the response/log.
        return jsonify(
            message="Unable to load registrations. Please check the Registration Service database connection and schema."
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
        try:
            event_id = str(UUID(request.args.get("eventId", "")))
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

        try:
            event_id = str(UUID(data.get("eventId", "")))
            attendee_id = str(UUID(data.get("attendeeId", "")))
            capacity = int(data.get("capacity"))
        except (ValueError, TypeError, AttributeError):
            return jsonify(message="Valid eventId, attendeeId and capacity are required."), 400
        name = str(data.get("fullName") or "").strip()
        email = str(data.get("email") or "").strip().lower()
        organization = str(data.get("organization") or "").strip()
        if capacity < 1 or not name or not email:
            return jsonify(message="Valid eventId, attendeeId, capacity, fullName and email are required."), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Registration Service."), 503

        try:
            registration = create_registration(
                app.config["DATABASE_URL"], event_id, attendee_id, capacity,
                name, email, organization,
            )
        except DuplicateRegistrationError:
            return jsonify(code="DUPLICATE_REGISTRATION", message="This email is already registered for the event."), 409
        except CapacityReachedError:
            return jsonify(code="EVENT_FULL", message="This event has reached maximum capacity."), 409
        return jsonify(registration=registration), 201

    return app
