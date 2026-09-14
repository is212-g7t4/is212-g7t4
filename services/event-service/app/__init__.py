import os

import psycopg2
from flask import Flask, jsonify, request

from app.models import FIELDS, list_submitted, submit_event
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
        if request.headers.get("Origin") == app.config["FRONTEND_ORIGIN"]:
            response.headers["Access-Control-Allow-Origin"] = app.config["FRONTEND_ORIGIN"]
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    @app.errorhandler(psycopg2.Error)
    def database_failure(error):
        # Do not expose credentials, SQL or database internals in the response/log.
        return jsonify(message="Unable to save or load event requests. Please check the Event Service database connection and schema."), 503

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
            return jsonify(message="Please correct the event details.", missingFields=missing, errors=errors), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        details = {key: data.get(key, "").strip() for key in (*FIELDS, "purpose")}
        return jsonify(submit_event(app.config["DATABASE_URL"], details)), 201

    @app.get("/events/submitted")
    def submitted():
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Event Service."), 503
        return jsonify(events=list_submitted(app.config["DATABASE_URL"]))

    return app

