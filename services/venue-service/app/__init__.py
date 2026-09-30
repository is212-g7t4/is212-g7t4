import os

import psycopg2
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

from app.models import VenueNotFoundError, get_venue, list_venues


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE_URL=os.getenv("DATABASE_URL"),
        FRONTEND_ORIGIN=os.getenv("FRONTEND_ORIGIN", "http://localhost:5173"),
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
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Venue Service."), 503
        return jsonify(venues=list_venues(app.config["DATABASE_URL"]))

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
