import uuid

from flask import Blueprint, jsonify, request

from app import clients, reservations
from app.clients import DownstreamError

bp = Blueprint("equipment_reservation_service", __name__)

STATUSES = ("Pending", "Approved", "Rejected")
DECISIONS = ("Approved", "Rejected")
REVIEW_ROLES = {"Technical Support", "Technical Support Staff"}
READ_ROLES = REVIEW_ROLES | {"Event Coordinator"}


def _uuid_or_none(value):
    try:
        return str(uuid.UUID(value or ""))
    except (ValueError, AttributeError, TypeError):
        return None


def _authorise(allowed_roles, denied_message):
    # DEV-only identity headers, same as the atomics; replace with Supabase JWT verification.
    role = request.headers.get("X-Dev-Role")
    if not _uuid_or_none(request.headers.get("X-Dev-User-Id")) or not role:
        return jsonify(message="DEV user UUID and role headers are required."), 401
    if role not in allowed_roles:
        return jsonify(message=denied_message), 403
    return None


def _decision():
    payload = request.get_json(silent=True)
    status = payload.get("status") if isinstance(payload, dict) else None
    return status if status in DECISIONS else None


@bp.errorhandler(DownstreamError)
def downstream_failure(error):
    return jsonify(message=error.message), error.status


@bp.errorhandler(reservations.InsufficientStockError)
def insufficient_stock(error):
    return jsonify(message=str(error)), 409


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
    requests = clients.list_requests(request.headers, status)
    return jsonify(events=reservations.build_event_views(requests, request.headers))


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
    return jsonify(request=reservations.review_request(request.headers, request_id, status))


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
    return jsonify(requests=reservations.review_event(request.headers, event_id, status))
