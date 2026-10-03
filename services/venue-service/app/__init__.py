import os

import psycopg2
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

from app.models import (
    ACCESSIBILITY_KEYWORDS,
    DuplicateVenueNameError,
    VenueNotFoundError,
    create_venue,
    get_venue,
    list_venues,
    matches,
    update_venue,
)
from app.validation import validate


class InvalidCriteriaError(Exception):
    """A filter parameter on GET /venues was present but unusable."""


def _nonblank(values):
    return [value.strip() for value in values if value.strip()]


def read_criteria(args):
    """SCRUM-26: turn GET /venues query parameters into `matches` criteria.

    Blank values count as not set, so an untouched form field is the same as
    an absent one and the catalogue page's unfiltered request is unchanged.
    """
    raw_capacity = (args.get("minCapacity") or "").strip()
    min_capacity = None
    if raw_capacity:
        try:
            min_capacity = int(raw_capacity)
        except ValueError:
            raise InvalidCriteriaError(
                "minCapacity must be a whole number of at least 1."
            ) from None
        if min_capacity < 1:
            raise InvalidCriteriaError("minCapacity must be a whole number of at least 1.")

    accessibility = _nonblank(args.getlist("accessibility"))
    unknown = [key for key in accessibility if key not in ACCESSIBILITY_KEYWORDS]
    if unknown:
        raise InvalidCriteriaError(
            f"accessibility must be one of: {', '.join(sorted(ACCESSIBILITY_KEYWORDS))}."
        )

    return {
        "min_capacity": min_capacity,
        "location": (args.get("location") or "").strip(),
        "layout": (args.get("layout") or "").strip(),
        "facilities": _nonblank(args.getlist("facility")),
        "accessibility": accessibility,
    }


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
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Accept"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, OPTIONS"
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
        try:
            criteria = read_criteria(request.args)
        except InvalidCriteriaError as error:
            return jsonify(message=str(error)), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Venue Service."), 503
        catalogue = list_venues(app.config["DATABASE_URL"])
        return jsonify(venues=[v for v in catalogue if matches(v, criteria)])

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

    @app.route("/venues/<uuid:venue_id>", methods=["PUT"])
    def edit_venue(venue_id):
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
        details = {
            "name": data["name"].strip(),
            "location": data["location"].strip(),
            "capacity": int(str(data["capacity"]).strip()),
            "facilities": [item.strip() for item in data["facilities"]],
            "accessibility": (data.get("accessibility") or "").strip(),
            "supportedLayouts": [item.strip() for item in data["supportedLayouts"]],
            "status": data["status"].strip(),
        }
        try:
            venue = update_venue(app.config["DATABASE_URL"], str(venue_id), details)
        except DuplicateVenueNameError:
            return jsonify(
                message="Please correct the venue details.",
                missingFields=[],
                errors=["A venue with this name already exists."],
            ), 409
        except VenueNotFoundError:
            return jsonify(message="Venue not found."), 404
        return jsonify(venue=venue), 200

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
