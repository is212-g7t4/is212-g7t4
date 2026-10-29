import uuid

from flask import Blueprint, g, jsonify, request

from app import clients, reservations
from app.clients import DownstreamError

bp = Blueprint("equipment_reservation_service", __name__)

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


def _authorise(allowed_roles, denied_message):
    if not g.user_id:
        return jsonify(message="Sign in to continue."), 401
    if g.role not in allowed_roles:
        return jsonify(message=denied_message), 403
    return None


def _decision():
    payload = request.get_json(silent=True)
    status = payload.get("status") if isinstance(payload, dict) else None
    return status if status in DECISIONS else None


def _rejection_reason(status):
    if status != "Rejected":
        return None, None
    reason = request.get_json().get("rejectionReason")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
        return None, "A rejection reason between 1 and 500 characters is required."
    return reason.strip(), None


@bp.errorhandler(DownstreamError)
def downstream_failure(error):
    return jsonify(message=error.message), error.status


@bp.errorhandler(reservations.InsufficientStockError)
def insufficient_stock(error):
    return jsonify(message=str(error)), 409


@bp.errorhandler(reservations.RequestNotAllowedError)
def request_not_allowed(error):
    return jsonify(message=error.message), error.status


@bp.get("/health")
def health():
    return jsonify(status="ok")


@bp.get("/equipment-reservations")
def reservations_list():
    """Equipment requests grouped by event, with the availability of each Pending line."""
    failure = _authorise(READ_ROLES, "Only Technical Support or Event Coordinators can view equipment requests.")
    if failure:
        return failure
    status = request.args.get("status")
    if status is not None and status not in STATUSES:
        return jsonify(message=f"status must be one of: {', '.join(STATUSES)}."), 400
    event_ids = None
    if g.role == "Event Coordinator":
        event_ids = clients.list_assigned_event_ids()
    requests = clients.list_requests(status, event_ids)
    return jsonify(events=reservations.build_event_views(requests))


@bp.patch("/equipment-reservations/requests/<request_id>")
def request_review(request_id):
    failure = _authorise(REVIEW_ROLES, "Only Technical Support can review equipment requests.")
    if failure:
        return failure
    request_id = _uuid_or_none(request_id)
    if not request_id:
        return jsonify(message="The equipment request ID must be a valid UUID."), 400
    status = _decision()
    if not status:
        return jsonify(message=f"status must be one of: {', '.join(DECISIONS)}."), 400
    reason, error = _rejection_reason(status)
    if error:
        return jsonify(message=error), 400
    return jsonify(request=reservations.review_request(request_id, status, reason))


@bp.patch("/equipment-reservations/events/<event_id>")
def event_review(event_id):
    failure = _authorise(REVIEW_ROLES, "Only Technical Support can review equipment requests.")
    if failure:
        return failure
    event_id = _uuid_or_none(event_id)
    if not event_id:
        return jsonify(message="The event ID must be a valid UUID."), 400
    status = _decision()
    if not status:
        return jsonify(message=f"status must be one of: {', '.join(DECISIONS)}."), 400
    reason, error = _rejection_reason(status)
    if error:
        return jsonify(message=error), 400
    return jsonify(requests=reservations.review_event(event_id, status, reason))


@bp.post("/equipment-reservations/events/<event_id>/requests")
def event_requests_create(event_id):
    failure = _authorise(CREATE_ROLES, "Only Event Coordinators can request equipment.")
    if failure:
        return failure
    event_id = _uuid_or_none(event_id)
    if not event_id:
        return jsonify(message="The event ID must be a valid UUID."), 400
    items, error = _validate_items(request.get_json(silent=True))
    if error:
        return jsonify(message=error), 400
    created = reservations.create_requests(event_id, items)
    return jsonify(requests=created), 201
