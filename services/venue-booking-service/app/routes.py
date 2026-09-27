from flask import Blueprint, jsonify, request

from app.clients import (
    EventNotAssignedError,
    EventNotFoundError,
    get_event,
    get_venues,
)

bp = Blueprint("venue_booking_service", __name__)


@bp.get("/health")
def health():
    return jsonify(status="ok")


@bp.post("/booking-requests")
def create_booking_request():
    """
    Validate a venue booking request against the Event and Venue catalogues.

    Body:
    - eventId: the event this booking is for
    - venueId: the venue being requested — must exist in Venue Service's
      catalogue, be Operational, and have enough capacity
    - coordinatorId: the Event Coordinator making the request; must be the
      coordinator assigned to the event

    This only validates suitability end to end (event exists, venue is a
    real catalogue entry, is operational, has enough capacity) — it does not
    check for double-booking or persist the request. Those belong to
    Booking Conflict Service and Venue Availabilities Service, neither of
    which is built yet (see INDEX.md).
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(message="Send a JSON object."), 400

    event_id = data.get("eventId")
    venue_id = data.get("venueId")
    coordinator_id = data.get("coordinatorId")
    if not event_id or not venue_id or not coordinator_id:
        return jsonify(message="eventId, venueId and coordinatorId are required."), 400

    try:
        event = get_event(event_id, coordinator_id)
    except EventNotFoundError:
        return jsonify(message="Event request not found."), 404
    except EventNotAssignedError:
        return jsonify(
            message="This event request is not assigned to the given coordinator."
        ), 403
    except Exception as e:
        return jsonify(message=f"Failed to look up the event: {e}"), 502

    try:
        venues = get_venues()
    except Exception as e:
        return jsonify(message=f"Failed to load the venue catalogue: {e}"), 502

    venue = next((v for v in venues if v.get("id") == venue_id), None)
    if venue is None:
        return jsonify(message="Venue must be selected from the venue catalogue."), 404
    if venue.get("status") != "Operational":
        return jsonify(message=f"{venue['name']} is not currently operational."), 409

    expected_attendance = event.get("expectedAttendance")
    capacity = venue.get("capacity")
    if (
        expected_attendance
        and capacity is not None
        and int(expected_attendance) > int(capacity)
    ):
        return jsonify(
            message=(
                f"{venue['name']} capacity ({capacity}) is below the expected "
                f"attendance ({expected_attendance})."
            )
        ), 422

    return jsonify(
        eventId=event_id,
        venueId=venue_id,
        venueName=venue["name"],
        status="validated",
    ), 201
