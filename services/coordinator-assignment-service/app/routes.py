from flask import Blueprint, jsonify

from app.clients import (
    get_available_coordinators,
    assign_event_coordinator,
)

bp = Blueprint("coordinator_assignment_service", __name__)


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


@bp.post("/events/<event_id>/assign-coordinator/<coordinator_id>")
def assign_coordinator(event_id, coordinator_id):
    """
    Assign an Event Coordinator to an event.
    
    Path parameters:
    - event_id: The event ID (format: EVT-XXX)
    - coordinator_id: The user ID of the coordinator to assign
    
    Response (200):
    {
        "eventId": "EVT-001",
        "assignedCoordinatorId": "user-123"
    }
    """
    try:
        if not event_id or not coordinator_id:
            return jsonify(error="event_id and coordinator_id are required"), 400
        
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
            result = assign_event_coordinator(event_id, coordinator_id)
            return jsonify(result), 200
        except Exception as e:
            return jsonify(
                error=f"Failed to assign coordinator to event: {str(e)}"
            ), 500
    
    except Exception as e:
        return jsonify(error=f"Internal server error: {str(e)}"), 500
