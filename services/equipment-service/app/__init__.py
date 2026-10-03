import os
import uuid

import psycopg2
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

from app.equipment import EQUIPMENT_TYPES, STATUSES
from app.models import create_equipment, list_equipment

MAX_TYPE_LENGTH = 100  # equipment_type is varchar(100)
ALLOWED_ROLES = {"Technical Support", "Technical Support Staff"}


def _is_uuid(value):
    try:
        uuid.UUID(value or "")
    except ValueError:
        return False
    return True


def _validate(payload):
    """Return (clean values, error message) for a POST /equipment body."""
    if not isinstance(payload, dict):
        return None, "A JSON object is required."
    equipment_type = payload.get("equipmentType")
    if not isinstance(equipment_type, str) or not equipment_type.strip():
        return None, "equipmentType is required."
    equipment_type = equipment_type.strip()
    if len(equipment_type) > MAX_TYPE_LENGTH:
        return None, f"equipmentType must be {MAX_TYPE_LENGTH} characters or fewer."
    # A known type in any casing is stored under its canonical name so it keeps its subclass.
    equipment_type = next((t for t in EQUIPMENT_TYPES if t.lower() == equipment_type.lower()), equipment_type)
    description = payload.get("description")
    if not isinstance(description, str) or not description.strip():
        return None, "description is required."
    quantity = payload.get("totalQuantity")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
        return None, "totalQuantity must be a whole number of 0 or more."
    location = payload.get("location")
    if not isinstance(location, str) or not location.strip():
        return None, "location is required."
    status = payload.get("status", "Available")
    if status not in STATUSES:
        return None, f"status must be one of: {', '.join(STATUSES)}."
    return (equipment_type, description.strip(), quantity, location.strip(), status), None


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
            response.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, Accept, X-Dev-User-Id, X-Dev-Role"
            )
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        if request.method == "OPTIONS":
            response.status_code = 200
        return response

    @app.errorhandler(psycopg2.Error)
    def database_failure(error):
        # Do not expose credentials, SQL or database internals in the response/log.
        return jsonify(message="Unable to load or save equipment data."), 503

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/equipment")
    def equipment_list():
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Equipment Service."), 503
        status = request.args.get("status")
        if status is not None and status not in STATUSES:
            return jsonify(message=f"status must be one of: {', '.join(STATUSES)}."), 400
        return jsonify(equipment=list_equipment(app.config["DATABASE_URL"], status))

    @app.post("/equipment")
    def equipment_create():
        # DEV-only role check, same headers as Venue Availability Service.
        # Replace with Supabase JWT verification when real auth lands.
        role = request.headers.get("X-Dev-Role")
        if not _is_uuid(request.headers.get("X-Dev-User-Id")) or not role:
            return jsonify(message="DEV user UUID and role headers are required."), 401
        if role not in ALLOWED_ROLES:
            return jsonify(message="Only Technical Support can add equipment."), 403
        values, error = _validate(request.get_json(silent=True))
        if error:
            return jsonify(message=error), 400
        if not app.config["DATABASE_URL"]:
            return jsonify(message="DATABASE_URL is not configured for Equipment Service."), 503
        return jsonify(equipment=create_equipment(app.config["DATABASE_URL"], *values)), 201

    return app
