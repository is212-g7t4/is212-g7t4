from uuid import UUID

from flask import Blueprint, jsonify, request

from app.clients import (
    RegistrationConflictError,
    get_attendee_registrations,
    get_confirmed_event,
    get_confirmed_events,
    get_event_registrations,
    get_user,
    save_registration,
)
from app.validation import event_has_started, validate_registration

bp = Blueprint("attendee_registration_service", __name__)


@bp.get("/health")
def health():
    return jsonify(status="ok")


def with_attendee_details(registrations):
    """Add the attendee's name, email and organisation from User Service.

    Registration stores only attendee_id; these fields keep the names the
    frontend already reads. Each attendee is looked up once.
    """
    users = {
        attendee_id: get_user(attendee_id)
        for attendee_id in {r.get("attendee_id") for r in registrations}
        if attendee_id
    }
    enriched = []
    for registration in registrations:
        user = users.get(registration.get("attendee_id")) or {}
        enriched.append({
            **registration,
            "attendee_name": user.get("username", ""),
            "attendee_email": user.get("email", ""),
            "attendee_organization": user.get("organization", ""),
        })
    return enriched


@bp.get("/events/<uuid:event_id>/registrations")
def event_registrations(event_id):
    """Coordinator registration list for one event, with attendee details."""
    try:
        registrations = with_attendee_details(get_event_registrations(str(event_id)))
    except Exception:
        return jsonify(message="Unable to load registrations right now."), 502
    return jsonify(registrations=registrations)


@bp.get("/registrations")
def attendee_registrations():
    try:
        attendee_id = str(UUID(request.args.get("attendeeId", "")))
    except (ValueError, TypeError, AttributeError):
        return jsonify(message="A valid attendeeId is required."), 400
    try:
        registrations = with_attendee_details(get_attendee_registrations(attendee_id))
        events = {event["id"]: event for event in get_confirmed_events()}
    except Exception:
        return jsonify(message="Unable to load your registrations right now."), 502

    items = [
        {"registration": registration, "event": events[registration["event_id"]]}
        for registration in registrations
        if registration.get("event_id") in events
    ]
    return jsonify(registrations=items)


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
        },
    ), 201
