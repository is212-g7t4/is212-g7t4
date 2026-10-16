import httpx
from flask import Blueprint, jsonify, request

from app.clients import (
    get_active_events,
    get_available_coordinators,
    get_unassigned_events,
    get_user,
    assign_event_coordinator,
)

bp = Blueprint("coordinator_assignment_service", __name__)

# The Lead assigns coordinators; it is its own role (docs/db-structure.md).
LEAD_ROLE = "Event Coordinator Lead"


@bp.get("/health")
def health():
    """Health check endpoint."""
    return jsonify(status="ok")


@bp.get("/coordinators")
def get_coordinators():
    """
    Get list of available Event Coordinators.
    
    Query parameters:
    - role: "EventCoordinator" (optional filter, applied by User Service)
    - available: "true" (optional filter, applied by User Service)
    
    Response:
    List of available coordinators with their details.
    """
    try:
        coordinators = get_available_coordinators()
        return jsonify(coordinators=coordinators), 200
    except Exception as e:
        return jsonify(error=f"Failed to fetch coordinators: {str(e)}"), 500


@bp.get("/queue")
def get_queue():
    """
    The Event Coordinator Lead's queue of submitted requests with no
    coordinator assigned yet, oldest submission first.

    Query parameters:
    - actingUserId: the id of the user asking. Only the Event Coordinator
      Lead may see the queue.

    Response (200):
    {"events": [...]}
    """
    acting_user_id = request.args.get("actingUserId")
    if not acting_user_id:
        return jsonify(error="actingUserId is required"), 400

    try:
        acting_user = get_user(acting_user_id)
    except Exception as e:
        return jsonify(error=f"Failed to validate acting user: {str(e)}"), 500

    if not acting_user or acting_user.get("role") != LEAD_ROLE:
        return jsonify(
            error="Only the Event Coordinator Lead can view the unassigned queue"
        ), 403

    try:
        return jsonify(events=get_unassigned_events()), 200
    except Exception as e:
        return jsonify(error=f"Failed to fetch unassigned events: {str(e)}"), 500


@bp.get("/workload")
def get_workload():
    """
    The Event Coordinator Lead's read-only workload view: every coordinator
    (the Lead included) with the active events assigned to them, plus the
    active events nobody has been assigned yet.

    Query parameters:
    - actingUserId: the id of the user asking. Only the Event Coordinator
      Lead may see the workload.

    Response (200):
    {
        "coordinators": [{...coordinator, "events": [...]}],
        "unassigned": [...],
        "otherAssigned": [...]
    }
    otherAssigned holds events whose coordinator is no longer an Event
    Coordinator, so they still show up rather than silently disappear.
    """
    acting_user_id = request.args.get("actingUserId")
    if not acting_user_id:
        return jsonify(error="actingUserId is required"), 400

    try:
        acting_user = get_user(acting_user_id)
    except Exception as e:
        return jsonify(error=f"Failed to validate acting user: {str(e)}"), 500

    if not acting_user or acting_user.get("role") != LEAD_ROLE:
        return jsonify(
            error="Only the Event Coordinator Lead can view coordinator workload"
        ), 403

    try:
        coordinators = get_available_coordinators()
        events = get_active_events()
    except Exception as e:
        return jsonify(error=f"Failed to fetch coordinator workload: {str(e)}"), 500

    by_coordinator = {c.get("user_id"): {**c, "events": []} for c in coordinators}
    unassigned, other_assigned = [], []
    for event in events:
        coordinator_id = event.get("coordinatorId")
        if not coordinator_id:
            unassigned.append(event)
        elif coordinator_id in by_coordinator:
            by_coordinator[coordinator_id]["events"].append(event)
        else:
            other_assigned.append(event)

    return jsonify(
        coordinators=list(by_coordinator.values()),
        unassigned=unassigned,
        otherAssigned=other_assigned,
    ), 200


@bp.post("/events/<event_id>/assign-coordinator/<coordinator_id>")
def assign_coordinator(event_id, coordinator_id):
    """
    Assign an Event Coordinator to an event.

    Path parameters:
    - event_id: The event ID (format: EVT-XXX)
    - coordinator_id: The user ID of the coordinator to assign

    Body:
    - actingUserId: the id of the user making the assignment. Only the
      Event Coordinator Lead (role "Event Coordinator Lead") may assign or
      reassign.

    Response (200):
    {
        "eventId": "EVT-001",
        "assignedCoordinatorId": "user-123"
    }
    """
    try:
        if not event_id or not coordinator_id:
            return jsonify(error="event_id and coordinator_id are required"), 400

        data = request.get_json(silent=True)
        acting_user_id = data.get("actingUserId") if isinstance(data, dict) else None
        if not acting_user_id:
            return jsonify(error="actingUserId is required"), 400

        try:
            acting_user = get_user(acting_user_id)
        except Exception as e:
            return jsonify(error=f"Failed to validate acting user: {str(e)}"), 500

        if not acting_user or acting_user.get("role") != LEAD_ROLE:
            return jsonify(
                error="Only the Event Coordinator Lead can assign or reassign coordinators"
            ), 403

        # Fetch available coordinators to validate the provided coordinator exists
        # and is available
        try:
            available_coordinators = get_available_coordinators()
            coordinator_ids = [c.get("user_id", c.get("id")) for c in available_coordinators]
            
            if coordinator_id not in coordinator_ids:
                return jsonify(
                    error=f"Coordinator {coordinator_id} is not available or does not exist"
                ), 404
        except Exception as e:
            return jsonify(
                error=f"Failed to validate coordinator: {str(e)}"
            ), 500
        
        # Assign the coordinator to the event via Event Service
        try:
            result = assign_event_coordinator(event_id, coordinator_id, acting_user_id)
            return jsonify(result), 200
        except httpx.HTTPStatusError as e:
            # Event Service's own refusals (unknown event, closed event, no
            # change) reach the Lead as they are; anything else is a failure.
            if 400 <= e.response.status_code < 500:
                try:
                    message = e.response.json().get("message")
                except ValueError:
                    message = None
                return jsonify(
                    error=message or "Event Service refused the assignment."
                ), e.response.status_code
            return jsonify(
                error=f"Failed to assign coordinator to event: {str(e)}"
            ), 500
        except Exception as e:
            return jsonify(
                error=f"Failed to assign coordinator to event: {str(e)}"
            ), 500
    
    except Exception as e:
        return jsonify(error=f"Internal server error: {str(e)}"), 500
