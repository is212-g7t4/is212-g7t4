import json
import os
from uuid import UUID

import psycopg2
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from psycopg2.extras import RealDictCursor

load_dotenv()


def _json_value(value):
    if isinstance(value, UUID):
        return str(value)
    return value


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
        if origin == app.config["FRONTEND_ORIGIN"]:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        return response

    @app.errorhandler(psycopg2.Error)
    def database_failure(error):
        return jsonify(message="Unable to load the venue catalogue."), 503

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/venues")
    def venues():
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Venue Service."), 503
        with psycopg2.connect(app.config["DATABASE_URL"], connect_timeout=10) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """SELECT venue_id, venue_name, location, max_capacity,
                              facilities, accessibility, supported_layouts,
                              operational_status
                       FROM public."Venue"
                       ORDER BY venue_name ASC, venue_id ASC"""
                )
                records = []
                for row in cursor.fetchall():
                    records.append({
                        "id": str(row["venue_id"]),
                        "name": row["venue_name"] or "",
                        "location": row["location"] or "",
                        "capacity": row["max_capacity"],
                        "facilities": row["facilities"] or [],
                        "accessibility": row["accessibility"] or "",
                        "supportedLayouts": row["supported_layouts"] or [],
                        "status": row["operational_status"] or "Unknown",
                    })
        return jsonify(venues=records)

    return app
