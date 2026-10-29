from uuid import UUID

from flask import Blueprint, jsonify, request

from app.clients import (
    RegistrationConflictError,
    get_attendee_registrations,
    get_confirmed_event,
    get_confirmed_events,
    get_event_registrations,
    get_historical_events,
    get_user,
    save_registration,
    withdraw_saved_registration,
)
from app.validation import event_has_started, validate_registration, withdrawal_deadline_has_passed

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
        missing_ids = {row["event_id"] for row in registrations if row.get("event_id") and row["event_id"] not in events}
        if missing_ids:
            events.update({event["id"]: event for event in get_historical_events(missing_ids)})
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
        registration = save_registration({**cleaned, "capacity": capacity, "notificationContext": dict(
            eventName=event["eventName"], startDateTime=event["preferredStartDate"], endDateTime=event["preferredEndDate"])})
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


@bp.patch("/registrations/<uuid:registration_id>/withdraw")
def withdraw_from_event(registration_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(message="Send a JSON object."), 400
    try:
        attendee_id = str(UUID(data.get("attendeeId", "")))
    except (ValueError, TypeError, AttributeError):
        return jsonify(message="A valid attendeeId is required."), 400

    try:
        registration = next(
            (
                item
                for item in get_attendee_registrations(attendee_id)
                if item.get("registration_id") == str(registration_id)
            ),
            None,
        )
    except Exception:
        return jsonify(message="Unable to check this registration right now."), 502
    if registration is None:
        return jsonify(
            code="REGISTRATION_NOT_FOUND",
            message="Registration not found.",
        ), 404
    if registration.get("status") == "Withdrawn":
        return jsonify(
            code="REGISTRATION_ALREADY_WITHDRAWN",
            message="This registration has already been withdrawn.",
        ), 409

    try:
        event = get_confirmed_event(registration.get("event_id"))
    except Exception:
        return jsonify(message="Unable to check the withdrawal deadline right now."), 502
    if event is None:
        return jsonify(
            code="WITHDRAWAL_UNAVAILABLE",
            message="This registration cannot be withdrawn online. Please contact the event organisers.",
        ), 409
    try:
        if withdrawal_deadline_has_passed(event):
            return jsonify(
                code="WITHDRAWAL_DEADLINE_PASSED",
                message="The withdrawal deadline has passed. Please contact the event organisers.",
            ), 409
    except (ValueError, TypeError):
        return jsonify(message="The withdrawal deadline is unavailable."), 502

    try:
        withdrawn = withdraw_saved_registration(str(registration_id), attendee_id, event["eventName"])
    except RegistrationConflictError as error:
        return jsonify(code=error.code, message=error.message), 409
    except Exception:
        return jsonify(message="Unable to withdraw this registration right now."), 502
    return jsonify(
        message=f"Registration withdrawn for {event['eventName']}.",
        registration=withdrawn,
    ), 200
