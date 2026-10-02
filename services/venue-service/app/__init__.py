import os

import psycopg2
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

from app.models import (
    ACCESSIBILITY_KEYWORDS,
    VenueNotFoundError,
    get_venue,
    list_venues,
    matches,
)


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
        return jsonify(message="Unable to load venue data."), 503

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/venues")
    def venues():
        try:
            criteria = read_criteria(request.args)
        except InvalidCriteriaError as error:
            return jsonify(message=str(error)), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Venue Service."), 503
        catalogue = list_venues(app.config["DATABASE_URL"])
        return jsonify(venues=[v for v in catalogue if matches(v, criteria)])

    @app.get("/venues/<uuid:venue_id>")
    def venue_details(venue_id):
        # The `uuid` converter answers a malformed id with a 404 before we get here.
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Venue Service."), 503
        try:
            venue = get_venue(app.config["DATABASE_URL"], str(venue_id))
        except VenueNotFoundError:
            return jsonify(message="Venue not found."), 404
        return jsonify(venue=venue)

    return app
