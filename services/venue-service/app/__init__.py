import os

import psycopg2
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

from app.models import DuplicateVenueNameError, VenueNotFoundError, create_venue, get_venue, list_venues
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
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Accept"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        if request.method == "OPTIONS":
            response.status_code = 200
        return response

    @app.errorhandler(psycopg2.Error)
    def database_failure(error):
        # Do not expose credentials, SQL or database internals in the response/log.
        return jsonify(message="Unable to load venue data."), 503

    @app.before_request
    def log_request():
        app.logger.debug(f"Incoming request: {request.method} {request.path}")

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify(status="ok")

    @app.route("/venues", methods=["GET"])
    def venues():
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Venue Service."), 503
        return jsonify(venues=list_venues(app.config["DATABASE_URL"]))

    @app.route("/venues", methods=["OPTIONS"])
    def venues_options():
        # Explicitly respond to CORS preflight requests for the collection path.
        resp = jsonify({})
        resp.status_code = 200
        return resp

    @app.route("/venues", methods=["POST"])
    def add_venue():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(message="Send a JSON object."), 400
        missing, errors = validate(data)
        if missing or errors:
            return jsonify(
                message="Please correct the venue details.",
                missingFields=missing,
                errors=errors,
            ), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Venue Service."), 503
        # Be defensive: callers may send numbers for capacity instead of strings.
        raw_capacity = data.get("capacity", "")
        capacity_str = str(raw_capacity).strip()
        try:
            capacity_val = int(capacity_str)
        except Exception:
            return jsonify(message="Please correct the venue details.", missingFields=[], errors=["Capacity must be a positive whole number (maximum 2147483647)."]), 400

        details = {
            "name": data["name"].strip(),
            "location": data["location"].strip(),
            "capacity": capacity_val,
            "facilities": [item.strip() for item in (data.get("facilities") or [])],
            "accessibility": (data.get("accessibility") or "").strip(),
            "supportedLayouts": [item.strip() for item in data["supportedLayouts"]],
            "status": data["status"].strip(),
        }
        try:
            venue = create_venue(app.config["DATABASE_URL"], details)
        except DuplicateVenueNameError:
            return jsonify(
                message="Please correct the venue details.",
                missingFields=[],
                errors=["A venue with this name already exists."],
            ), 409
        return jsonify(venue=venue), 201

    @app.route("/venues/<uuid:venue_id>", methods=["GET"])
    def venue_details(venue_id):
        # The `uuid` converter answers a malformed id with a 404 before we get here.
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Venue Service."), 503
        try:
            venue = get_venue(app.config["DATABASE_URL"], str(venue_id))
        except VenueNotFoundError:
            return jsonify(message="Venue not found."), 404
        return jsonify(venue=venue)

    # Log the URL map at startup to help runtime debugging (visible in container logs).
    app.logger.info("Registered routes:\n%s", app.url_map)

    @app.route("/__routes", methods=["GET"])
    def dump_routes():
        # Diagnostic endpoint: returns registered URL rules.
        rules = []
        for rule in app.url_map.iter_rules():
            rules.append({
                "rule": str(rule),
                "methods": sorted(list(rule.methods)),
                "endpoint": rule.endpoint,
            })
        return jsonify(routes=rules)

    return app
