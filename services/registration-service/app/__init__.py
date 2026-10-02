import os
from uuid import UUID

import psycopg2
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

from app.models import count_registrations, list_registrations


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
            response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
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

    return app
