from uuid import UUID

from flask import Blueprint, jsonify, request

from app.clients import RegistrationConflictError, get_confirmed_event, save_registration
from app.validation import event_has_started, validate_registration

bp = Blueprint("attendee_registration_service", __name__)


@bp.get("/health")
def health():
    return jsonify(status="ok")


@bp.post("/registrations")
def register_for_event():
    cleaned, errors, missing = validate_registration(request.get_json(silent=True))
    if missing or errors:
        return jsonify(
            message="Complete the required registration fields.",
            missingFields=missing,
            errors=errors,
        ), 400
    try:
        cleaned["eventId"] = str(UUID(cleaned["eventId"]))
        cleaned["attendeeId"] = str(UUID(cleaned["attendeeId"]))
    except (ValueError, TypeError, AttributeError):
        return jsonify(message="A valid event and attendee are required."), 400

    try:
        event = get_confirmed_event(cleaned["eventId"])
    except Exception:
        return jsonify(message="Unable to check event registration right now."), 502
    if event is None:
        return jsonify(
            code="REGISTRATION_CLOSED",
            message="Registration is available only for confirmed events.",
        ), 409
    try:
        if event_has_started(event):
            return jsonify(
                code="REGISTRATION_CLOSED",
                message="Registration has closed because this event has started.",
            ), 409
        capacity = int(event.get("expectedAttendance"))
        if capacity < 1:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify(message="The event registration capacity is unavailable."), 422

    try:
        registration = save_registration({**cleaned, "capacity": capacity})
    except RegistrationConflictError as error:
        return jsonify(code=error.code, message=error.message), 409
    except Exception:
        return jsonify(message="Unable to save the registration right now."), 502

    return jsonify(
        message=f"Registration confirmed for {event['eventName']}.",
        registration=registration,
        event={
            "id": event["id"],
            "eventName": event["eventName"],
            "preferredStartDate": event.get("preferredStartDate"),
            "preferredEndDate": event.get("preferredEndDate"),
            "venueId": event.get("venueId"),
        },
    ), 201
