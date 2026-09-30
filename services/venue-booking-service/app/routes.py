from flask import Blueprint, jsonify, request

from app.clients import (
    BookingConflictError,
    BookingNotFoundError,
    EventNotAssignedError,
    EventNotFoundError,
    create_booking,
    decide_booking,
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
    Submit a venue booking request: validates it against the Event and Venue
    catalogues, then persists it (as Pending Review) in Venue Availability
    Service, which is also where the double-booking conflict check lives.

    Body:
    - eventId: the event this booking is for — its preferredStartDate/
      preferredEndDate are used as the requested booking window
    - venueId: the venue being requested — must exist in Venue Service's
      catalogue, be Available, and have enough capacity
    - coordinatorId: the Event Coordinator making the request; must be the
      coordinator assigned to the event
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
    if venue.get("status") != "Available":
        return jsonify(message=f"{venue['name']} is not currently available for booking."), 409

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

    start, end = event.get("preferredStartDate"), event.get("preferredEndDate")
    if not start or not end:
        return jsonify(message="Event is missing its preferred start/end dates."), 422

    try:
        booking = create_booking(event_id, venue_id, start, end, coordinator_id)
    except BookingConflictError:
        return jsonify(message=f"{venue['name']} is already booked for that time."), 409
    except Exception as e:
        return jsonify(message=f"Failed to save the booking request: {e}"), 502

    return jsonify(booking), 201


@bp.patch("/booking-requests/<booking_id>/approve")
def approve_booking_request(booking_id):
    return _decide(booking_id, "Approved")


@bp.patch("/booking-requests/<booking_id>/reject")
def reject_booking_request(booking_id):
    return _decide(booking_id, "Rejected")


def _decide(booking_id, status):
    data = request.get_json(silent=True)
    reviewed_by = data.get("reviewedBy") if isinstance(data, dict) else None
    if not reviewed_by:
        return jsonify(message="reviewedBy is required."), 400
    try:
        booking = decide_booking(booking_id, reviewed_by, status)
    except BookingNotFoundError:
        return jsonify(message="Venue booking not found."), 404
    except BookingConflictError:
        return jsonify(
            message="This venue is already booked for the requested time."
        ), 409
    except Exception as e:
        return jsonify(message=f"Failed to update the booking request: {e}"), 502
    return jsonify(booking), 200
