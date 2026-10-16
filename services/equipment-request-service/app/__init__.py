import os
import uuid

import psycopg2
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

from app.models import (
    RequestAlreadyReviewedError,
    RequestNotFoundError,
    UnknownReferenceError,
    create_requests,
    get_request,
    list_requests,
    review_event_requests,
    review_request,
)

STATUSES = ("Pending", "Approved", "Rejected")
DECISIONS = ("Approved", "Rejected")
REVIEW_ROLES = {"Technical Support", "Technical Support Staff"}
READ_ROLES = REVIEW_ROLES | {"Event Coordinator"}
CREATE_ROLES = {"Event Coordinator"}
MAX_ITEMS = 50
MAX_REQUIREMENTS_LENGTH = 1000


def _uuid_or_none(value):
    try:
        return str(uuid.UUID(value or ""))
    except (ValueError, AttributeError, TypeError):
        return None


def _validate_items(payload):
    """Return (items, error) for a {items: [{equipmentId, quantityRequested, technicalRequirements?}]} body."""
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        return None, "Add at least one equipment item."
    if len(items) > MAX_ITEMS:
        return None, f"A request can include at most {MAX_ITEMS} equipment items."
    cleaned = []
    for item in items:
        if not isinstance(item, dict):
            return None, "Each equipment item must be an object."
        equipment_id = _uuid_or_none(item.get("equipmentId"))
        if not equipment_id:
            return None, "Each equipment item needs a valid equipmentId."
        quantity = item.get("quantityRequested")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            return None, "Quantity must be a whole number of at least 1."
        requirements = item.get("technicalRequirements") or ""
        if not isinstance(requirements, str) or len(requirements.strip()) > MAX_REQUIREMENTS_LENGTH:
            return None, f"Technical requirements must be text of {MAX_REQUIREMENTS_LENGTH} characters or fewer."
        cleaned.append({"equipmentId": equipment_id, "quantityRequested": quantity, "technicalRequirements": requirements.strip()})
    if len({item["equipmentId"] for item in cleaned}) != len(cleaned):
        return None, "Each equipment item can appear only once in a request."
    return cleaned, None


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE_URL=os.getenv("DATABASE_URL"),
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
            response.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, Accept, X-Dev-User-Id, X-Dev-Role"
            )
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
        if request.method == "OPTIONS":
            response.status_code = 200
        return response

    @app.errorhandler(psycopg2.Error)
    def database_failure(error):
        # Do not expose credentials, SQL or database internals in the response.
        return jsonify(message="Unable to load or save equipment requests."), 503

    def authorise(allowed_roles, denied_message):
        # DEV-only identity headers, same as Equipment Service; replace with Supabase JWT verification.
        role = request.headers.get("X-Dev-Role")
        user_id = _uuid_or_none(request.headers.get("X-Dev-User-Id"))
        if not user_id or not role:
            return None, (jsonify(message="DEV user UUID and role headers are required."), 401)
        if role not in allowed_roles:
            return None, (jsonify(message=denied_message), 403)
        if not app.config["DATABASE_URL"]:
            return None, (
                jsonify(message="DATABASE_URL is not configured for Equipment Request Service."),
                503,
            )
        return user_id, None

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/equipment-requests")
    def requests_list():
        _, failure = authorise(READ_ROLES, "Only Technical Support or Event Coordinators can view equipment requests.")
        if failure:
            return failure
        status = request.args.get("status")
        if status is not None and status not in STATUSES:
            return jsonify(message=f"status must be one of: {', '.join(STATUSES)}."), 400
        event_id = request.args.get("eventId")
        if event_id is not None:
            event_id = _uuid_or_none(event_id)
            if not event_id:
                return jsonify(message="eventId must be a valid UUID."), 400
        event_ids = None
        if request.args.get("eventIds") is not None:
            raw_ids = [part for part in request.args["eventIds"].split(",") if part]
            event_ids = [_uuid_or_none(part) for part in raw_ids]
            if len(raw_ids) > 500 or None in event_ids:
                return jsonify(message="eventIds must be up to 500 comma-separated UUIDs."), 400
        return jsonify(requests=list_requests(app.config["DATABASE_URL"], status, event_id, event_ids))

    @app.get("/equipment-requests/<request_id>")
    def request_get(request_id):
        _, failure = authorise(READ_ROLES, "Only Technical Support or Event Coordinators can view equipment requests.")
        if failure:
            return failure
        request_id = _uuid_or_none(request_id)
        if not request_id:
            return jsonify(message="The equipment request ID must be a valid UUID."), 400
        try:
            return jsonify(request=get_request(app.config["DATABASE_URL"], request_id))
        except RequestNotFoundError:
            return jsonify(message="Equipment request not found."), 404

    @app.post("/events/<event_id>/equipment-requests")
    def event_requests_create(event_id):
        # Assignment, event status and equipment availability are checked by Equipment Reservation Service.
        requester_id, failure = authorise(CREATE_ROLES, "Only Event Coordinators can request equipment.")
        if failure:
            return failure
        event_id = _uuid_or_none(event_id)
        if not event_id:
            return jsonify(message="The event ID must be a valid UUID."), 400
        items, error = _validate_items(request.get_json(silent=True))
        if error:
            return jsonify(message=error), 400
        try:
            created = create_requests(app.config["DATABASE_URL"], event_id, items, requester_id)
        except UnknownReferenceError:
            return jsonify(message="The event, requester or an equipment item no longer exists."), 404
        return jsonify(requests=created), 201

    @app.patch("/events/<event_id>/equipment-requests")
    def event_requests_review(event_id):
        reviewer_id, failure = authorise(REVIEW_ROLES, "Only Technical Support can review equipment requests.")
        if failure:
            return failure
        event_id = _uuid_or_none(event_id)
        if not event_id:
            return jsonify(message="The event ID must be a valid UUID."), 400
        payload = request.get_json(silent=True)
        status = payload.get("status") if isinstance(payload, dict) else None
        if status not in DECISIONS:
            return jsonify(message=f"status must be one of: {', '.join(DECISIONS)}."), 400
        try:
            updated = review_event_requests(app.config["DATABASE_URL"], event_id, status, reviewer_id)
        except RequestNotFoundError:
            return jsonify(message="No equipment requests found for this event."), 404
        except RequestAlreadyReviewedError:
            return jsonify(message="This event has no Pending equipment requests."), 409
        return jsonify(requests=updated)

    @app.patch("/equipment-requests/<request_id>")
    def request_review(request_id):
        reviewer_id, failure = authorise(REVIEW_ROLES, "Only Technical Support can review equipment requests.")
        if failure:
            return failure
        request_id = _uuid_or_none(request_id)
        if not request_id:
            return jsonify(message="The equipment request ID must be a valid UUID."), 400
        payload = request.get_json(silent=True)
        status = payload.get("status") if isinstance(payload, dict) else None
        if status not in DECISIONS:
            return jsonify(message=f"status must be one of: {', '.join(DECISIONS)}."), 400
        try:
            updated = review_request(app.config["DATABASE_URL"], request_id, status, reviewer_id)
        except RequestNotFoundError:
            return jsonify(message="Equipment request not found."), 404
        except RequestAlreadyReviewedError:
            return jsonify(message="Only Pending equipment requests can be reviewed."), 409
        return jsonify(request=updated)

    return app
