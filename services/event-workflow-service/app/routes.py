"""SCRUM-20: edit an event's details, checked against its other arrangements first.

A composite because the check needs facts from Event, Venue Availability,
Venue, Equipment Request and Equipment Services and ends in a write to Event
Service (AGENTS.md). The event's fields and the low/high-impact split belong
to Event Service; this service only orchestrates.
"""
from uuid import UUID

from flask import Blueprint, g, jsonify, request

from app import checks, clients

bp = Blueprint("event_workflow_service", __name__)

LEAD_ROLE = "Event Coordinator Lead"
COORDINATOR_ROLES = {"Event Coordinator", LEAD_ROLE}

UNREADABLE = (
    "Unable to check this change against the event's venue and equipment "
    "arrangements right now. Nothing was changed."
)
NOT_ASSIGNED = (
    "Only the event's assigned coordinator can edit its details, or the Event "
    "Coordinator Lead while it has no assigned coordinator."
)


@bp.get("/health")
def health():
    return jsonify(status="ok")


def _cannot_modify(roles):
    """SCRUM-10: the 403 for a signed-in caller whose role may not change event details, else None.

    Checked on the token's role before any downstream call, so a refused edit asks Event Service,
    User Service and the booking services nothing. A caller with no user passes and meets the
    handler's own sign-in check.
    """
    if g.user_id is None or g.role in roles:
        return None
    return jsonify(
        code="NOT_ASSIGNED_COORDINATOR", message="Your role cannot change this information."
    ), 403


def _uuid_or_none(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        return None


@bp.patch("/events/<event_id>/details")
def update_event_details(event_id):
    """Validate an edit, then save it (SCRUM-20 AC2, AC3, AC4).

    Body: `{changes: {<field>: text}}`; the editor is the signed-in user (SCRUM-8).

    1. The caller must be the assigned coordinator, or the Lead when no
       coordinator is assigned; the role is
       looked up in User Service rather than taken from the request.
    2. Event Service classifies the change with nothing written.
    3. A high-impact change is checked against the venue and equipment
       arrangements; any contradiction refuses it with `409
       CHANGE_CONTRADICTS_ARRANGEMENTS` and the reasons, and nothing is saved.
    4. Otherwise Event Service saves it. A high-impact edit of a `Confirmed`
       event comes back `409 SAFETY_RECHECK_REQUIRED` as before: the safety
       re-check is only offered once this validation has passed.
    """
    if (forbidden := _cannot_modify(COORDINATOR_ROLES)):
        return forbidden
    event_id = _uuid_or_none(event_id)
    data = request.get_json(silent=True)
    if not event_id:
        return jsonify(message="A valid event ID is required."), 400
    if not isinstance(data, dict):
        return jsonify(message="Send a JSON object."), 400
    coordinator_id = g.user_id
    changes = data.get("changes")
    if (
        not isinstance(changes, dict)
        or not changes
        or any(not isinstance(value, str) for value in changes.values())
    ):
        return jsonify(
            message="changes must be a non-empty object of text values."
        ), 400

    try:
        actor_role = _lead_role(coordinator_id)
        preview = clients.preview_event_details(event_id, changes, actor_role)
        high = preview["highImpactFields"]
        if high:
            conflicts = checks.find_conflicts(preview["event"], changes, high)
            if conflicts:
                return jsonify(
                    code="CHANGE_CONTRADICTS_ARRANGEMENTS",
                    message=(
                        "This change can't be saved because it contradicts "
                        "arrangements already made for the event."
                    ),
                    changedFields=preview["changedFields"],
                    highImpactFields=high,
                    conflicts=conflicts,
                ), 409
        saved = clients.save_event_details(event_id, changes, actor_role)
    except clients.UserNotFoundError:
        return jsonify(code="NOT_ASSIGNED_COORDINATOR", message=NOT_ASSIGNED), 403
    except clients.EventRejectedError as refused:
        return jsonify(refused.body), refused.status
    except clients.DownstreamTimeout:
        return jsonify(message=UNREADABLE), 504
    except clients.DownstreamError:
        return jsonify(message=UNREADABLE), 502
    return jsonify(saved), 200


def _lead_role(coordinator_id):
    """The Lead role if the caller holds it, else None (Event Service then checks assignment)."""
    role = clients.get_user(coordinator_id).get("role")
    return LEAD_ROLE if role == LEAD_ROLE else None


def _coordinator_role(coordinator_id):
    role = clients.get_user(coordinator_id).get("role")
    if role not in COORDINATOR_ROLES:
        raise clients.UserNotFoundError
    return role


def _workflow_failure(error):
    if isinstance(error, clients.UserNotFoundError):
        return jsonify(
            code="COORDINATOR_REQUIRED",
            message="Only an Event Coordinator can review change requests.",
        ), 403
    if isinstance(error, clients.EventRejectedError):
        return jsonify(error.body), error.status
    if isinstance(error, clients.DownstreamTimeout):
        return jsonify(message=UNREADABLE), 504
    return jsonify(message=UNREADABLE), 502


@bp.get("/change-requests")
def pending_change_requests():
    coordinator_id = g.user_id
    try:
        _coordinator_role(coordinator_id)
        changes = clients.list_pending_change_requests()
    except (
        clients.UserNotFoundError,
        clients.EventRejectedError,
        clients.DownstreamTimeout,
        clients.DownstreamError,
    ) as error:
        return _workflow_failure(error)
    return jsonify(changeRequests=changes), 200


@bp.patch("/change-requests/<change_request_id>")
def process_change_request(change_request_id):
    change_request_id = _uuid_or_none(change_request_id)
    data = request.get_json(silent=True)
    if not change_request_id:
        return jsonify(message="A valid change request ID is required."), 400
    if not isinstance(data, dict):
        return jsonify(message="Send a JSON object."), 400
    coordinator_id = g.user_id
    decision = data.get("decision")
    if decision not in ("Approved", "Rejected"):
        return jsonify(message="decision must be Approved or Rejected."), 400
    reason = data.get("reason")
    if decision == "Rejected":
        if not isinstance(reason, str) or not reason.strip():
            return jsonify(message="A rejection reason is required."), 400
        reason = reason.strip()
        if len(reason) > 2000:
            return jsonify(message="A rejection reason must be 2000 characters or fewer."), 400
    else:
        reason = None

    try:
        role = _coordinator_role(coordinator_id)
        change = clients.get_change_request(change_request_id)
        if decision == "Approved":
            actor_role = LEAD_ROLE if role == LEAD_ROLE else None
            preview = clients.preview_event_details(
                change["eventId"],
                change["proposedChanges"],
                actor_role,
            )
            high = preview["highImpactFields"]
            if high:
                conflicts = checks.find_conflicts(
                    preview["event"],
                    change["proposedChanges"],
                    high,
                )
                if conflicts:
                    return jsonify(
                        code="CHANGE_CONTRADICTS_ARRANGEMENTS",
                        message=(
                            "This request can't be approved because it contradicts "
                            "arrangements already made for the event."
                        ),
                        changedFields=preview["changedFields"],
                        highImpactFields=high,
                        conflicts=conflicts,
                    ), 409
        decided = clients.decide_change_request(change_request_id, decision, reason)
    except (
        clients.UserNotFoundError,
        clients.EventRejectedError,
        clients.DownstreamTimeout,
        clients.DownstreamError,
    ) as error:
        return _workflow_failure(error)
    return jsonify(decided), 200
