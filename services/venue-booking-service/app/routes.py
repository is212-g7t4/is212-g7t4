from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import httpx
from flask import Blueprint, jsonify, request

from app.clients import (
    BookingConflictError,
    BookingNotFoundError,
    BookingStateError,
    EventNotAssignedError,
    EventNotFoundError,
    cancel_booking,
    create_booking,
    decide_booking,
    get_bookings_between,
    get_booking,
    get_event_bookings,
    get_event,
    get_event_for_internal_viewer,
    get_venue,
    get_venues,
    reconcile_legacy_conflicts,
    search_venues,
    update_booking,
    update_venue_profile,
)
from app.search import SearchError, shortlist, validate_search

bp = Blueprint("venue_booking_service", __name__)


def _add_event_names(result, viewer_id, viewer_role):
    """Best-effort display enrichment; conflict identification must still work if Event Service is down."""
    if not viewer_id or viewer_role != "Venue Staff":
        return result
    names = {}
    for conflict in result.get("conflicts", []):
        for key in ("firstBooking", "secondBooking"):
            booking = conflict.get(key, {})
            event_id = booking.get("eventId")
            if not event_id:
                continue
            if event_id not in names:
                try:
                    event = get_event_for_internal_viewer(event_id, viewer_id, viewer_role)
                    names[event_id] = event.get("eventName") or None
                except Exception:
                    names[event_id] = None
            if names[event_id]:
                booking["eventName"] = names[event_id]
    return result


@bp.get("/health")
def health():
    return jsonify(status="ok")


@bp.get("/venue-search")
def venue_search():
    """
    SCRUM-26: find the venues that fit an event's requirements and are free
    at the requested time.

    Required query parameters: `start`, `end` (naive local ISO date-times) and
    `expectedAttendance`. Optional: `minCapacity`, `location`, `layout`, and
    the repeatable `facility` and `accessibility`.

    Venue Service filters the catalogue and Venue Availability Service returns
    the bookings overlapping the window; neither can answer this alone, so the
    merge happens here. Read-only: no booking is created.
    """
    try:
        criteria = validate_search(request.args)
    except SearchError as error:
        return jsonify(message=error.message, missing=error.missing), 400

    try:
        # Preserve the existing parallel fast path. If any matching venue has
        # padding, issue one widened read after the catalogue reveals the safe
        # bound; zero-buffer catalogues still cost only the slower first call.
        with ThreadPoolExecutor(max_workers=2) as pool:
            venues_call = pool.submit(search_venues, criteria["filters"])
            window_call = pool.submit(
                get_bookings_between, criteria["start"], criteria["end"]
            )
            venues = venues_call.result()
            window = window_call.result()
        padding = max(
            (
                int(venue.get("setupTimeMinutes", 0))
                + int(venue.get("turnaroundTimeMinutes", 0))
                for venue in venues
            ),
            default=0,
        )
        if padding:
            window = get_bookings_between(
                criteria["start"], criteria["end"], padding
            )
    except httpx.TimeoutException:
        return jsonify(message="Venue search took too long. Please try again."), 504
    except Exception:
        # Don't leak the downstream URL or error text to the browser.
        return jsonify(message="Unable to search venues right now."), 502

    results = shortlist(
        venues,
        window["bookings"],
        window["closures"],
        criteria["start"],
        criteria["end"],
    )
    return jsonify(venues=results, count=len(results))


@bp.post("/booking-requests")
def create_booking_request():
    """
    Submit a venue booking request: validates it against the Event and Venue
    catalogues, then persists it (as Pending Review) in Venue Availability
    Service, which is also where the double-booking conflict check lives.

    Body:
    - eventId: the event this booking is for
    - venueId: the venue being requested — must exist in Venue Service's
      catalogue, be Available, and have enough capacity
    - coordinatorId: the Event Coordinator making the request; must be the
      coordinator assigned to the event
    - requestedStartTime/requestedEndTime: this booking's own window
    - requiredCapacity: this booking's expected attendance, independent from
      the event's total expected attendance
    - venueRequirements: this booking's own free-text requirements
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(message="Send a JSON object."), 400

    event_id = data.get("eventId")
    venue_id = data.get("venueId")
    coordinator_id = data.get("coordinatorId")
    start = data.get("requestedStartTime")
    end = data.get("requestedEndTime")
    required_capacity = data.get("requiredCapacity")
    venue_requirements = data.get("venueRequirements")
    if not event_id or not venue_id or not coordinator_id or not start or not end:
        return jsonify(
            message=(
                "eventId, venueId, coordinatorId, requestedStartTime and "
                "requestedEndTime are required."
            )
        ), 400
    if (
        isinstance(required_capacity, bool)
        or not isinstance(required_capacity, int)
        or not 1 <= required_capacity <= 2147483647
    ):
        return jsonify(
            message="requiredCapacity must be a positive whole number."
        ), 400
    if not isinstance(venue_requirements, str):
        return jsonify(message="venueRequirements must be text."), 400
    try:
        if (
            not isinstance(start, str)
            or not isinstance(end, str)
            or "T" not in start
            or "T" not in end
        ):
            raise ValueError
        parsed_start = datetime.fromisoformat(start)
        parsed_end = datetime.fromisoformat(end)
        if parsed_start.tzinfo or parsed_end.tzinfo or parsed_end <= parsed_start:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify(
            message=(
                "requestedStartTime and requestedEndTime must be local date-times, "
                "with the end after the start."
            )
        ), 400

    try:
        get_event(event_id, coordinator_id)
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

    capacity = venue.get("capacity")
    if capacity is None or required_capacity > int(capacity):
        return jsonify(
            message=(
                f"{venue['name']} capacity ({capacity}) is below the expected "
                f"attendance for this booking ({required_capacity})."
            )
        ), 422

    try:
        args = (
            event_id,
            venue_id,
            start,
            end,
            required_capacity,
            venue_requirements.strip(),
            coordinator_id,
        )
        if "setupTimeMinutes" in venue or "turnaroundTimeMinutes" in venue:
            booking = create_booking(
                *args,
                int(venue.get("setupTimeMinutes", 0)),
                int(venue.get("turnaroundTimeMinutes", 0)),
            )
        else:
            booking = create_booking(*args)
    except BookingConflictError as error:
        return jsonify(
            message=f"{venue['name']} is unavailable for that time.",
            code="VENUE_UNAVAILABLE",
            conflictTypes=error.conflict_types,
        ), 409
    except Exception as e:
        return jsonify(message=f"Failed to save the booking request: {e}"), 502

    return jsonify(booking), 201


@bp.get("/events/<event_id>/booking-requests")
def list_booking_requests(event_id):
    """Return each venue request for an event as a separate record."""
    coordinator_id = request.args.get("coordinatorId")
    if not coordinator_id:
        return jsonify(message="coordinatorId is required."), 400
    try:
        get_event(event_id, coordinator_id)
    except EventNotFoundError:
        return jsonify(message="Event request not found."), 404
    except EventNotAssignedError:
        return jsonify(
            message="This event request is not assigned to the given coordinator."
        ), 403
    except Exception as error:
        return jsonify(message=f"Failed to look up the event: {error}"), 502

    with ThreadPoolExecutor(max_workers=2) as pool:
        bookings_call = pool.submit(get_event_bookings, event_id)
        venues_call = pool.submit(get_venues)
        try:
            bookings = bookings_call.result()
            venues = venues_call.result()
        except Exception:
            return jsonify(message="Unable to load venue booking requests."), 502

    venue_names = {
        venue.get("id"): venue.get("name", "Unknown venue") for venue in venues
    }
    return jsonify(
        bookings=[
            {
                **booking,
                "venueName": venue_names.get(
                    booking.get("venueId"), "Unknown venue"
                ),
            }
            for booking in bookings
        ]
    )


@bp.patch("/booking-requests/<booking_id>")
def update_booking_request(booking_id):
    """Modify and resubmit only the selected booking."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(message="Send a JSON object."), 400

    event_id = data.get("eventId")
    venue_id = data.get("venueId")
    coordinator_id = data.get("coordinatorId")
    start = data.get("requestedStartTime")
    end = data.get("requestedEndTime")
    required_capacity = data.get("requiredCapacity")
    venue_requirements = data.get("venueRequirements")
    if not event_id or not venue_id or not coordinator_id or not start or not end:
        return jsonify(
            message=(
                "eventId, venueId, coordinatorId, requestedStartTime and "
                "requestedEndTime are required."
            )
        ), 400
    if (
        isinstance(required_capacity, bool)
        or not isinstance(required_capacity, int)
        or not 1 <= required_capacity <= 2147483647
    ):
        return jsonify(
            message="requiredCapacity must be a positive whole number."
        ), 400
    if not isinstance(venue_requirements, str):
        return jsonify(message="venueRequirements must be text."), 400
    try:
        if (
            not isinstance(start, str)
            or not isinstance(end, str)
            or "T" not in start
            or "T" not in end
        ):
            raise ValueError
        parsed_start = datetime.fromisoformat(start)
        parsed_end = datetime.fromisoformat(end)
        if parsed_start.tzinfo or parsed_end.tzinfo or parsed_end <= parsed_start:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify(
            message=(
                "requestedStartTime and requestedEndTime must be local date-times, "
                "with the end after the start."
            )
        ), 400

    try:
        get_event(event_id, coordinator_id)
    except EventNotFoundError:
        return jsonify(message="Event request not found."), 404
    except EventNotAssignedError:
        return jsonify(
            message="This event request is not assigned to the given coordinator."
        ), 403
    except Exception as error:
        return jsonify(message=f"Failed to look up the event: {error}"), 502

    try:
        venues = get_venues()
    except Exception as error:
        return jsonify(message=f"Failed to load the venue catalogue: {error}"), 502
    venue = next((item for item in venues if item.get("id") == venue_id), None)
    if venue is None:
        return jsonify(message="Venue must be selected from the venue catalogue."), 404
    if venue.get("status") != "Available":
        return jsonify(
            message=f"{venue['name']} is not currently available for booking."
        ), 409
    capacity = venue.get("capacity")
    if capacity is None or required_capacity > int(capacity):
        return jsonify(
            message=(
                f"{venue['name']} capacity ({capacity}) is below the expected "
                f"attendance for this booking ({required_capacity})."
            )
        ), 422

    try:
        args = (
            booking_id,
            event_id,
            venue_id,
            start,
            end,
            required_capacity,
            venue_requirements.strip(),
        )
        if "setupTimeMinutes" in venue or "turnaroundTimeMinutes" in venue:
            booking = update_booking(
                *args,
                int(venue.get("setupTimeMinutes", 0)),
                int(venue.get("turnaroundTimeMinutes", 0)),
            )
        else:
            booking = update_booking(*args)
    except BookingNotFoundError:
        return jsonify(message="Venue booking not found for this event."), 404
    except BookingStateError:
        return jsonify(message="Cancelled venue bookings cannot be modified."), 409
    except BookingConflictError as error:
        return jsonify(
            message=f"{venue['name']} is unavailable for that time.",
            code="VENUE_UNAVAILABLE",
            conflictTypes=error.conflict_types,
        ), 409
    except Exception as error:
        return jsonify(message=f"Failed to update the booking request: {error}"), 502
    return jsonify(booking), 200


@bp.patch("/booking-requests/<booking_id>/cancel")
def cancel_booking_request(booking_id):
    """Cancel only the selected booking and retain its event association."""
    data = request.get_json(silent=True)
    event_id = data.get("eventId") if isinstance(data, dict) else None
    coordinator_id = data.get("coordinatorId") if isinstance(data, dict) else None
    if not event_id or not coordinator_id:
        return jsonify(message="eventId and coordinatorId are required."), 400
    try:
        get_event(event_id, coordinator_id)
    except EventNotFoundError:
        return jsonify(message="Event request not found."), 404
    except EventNotAssignedError:
        return jsonify(
            message="This event request is not assigned to the given coordinator."
        ), 403
    except Exception as error:
        return jsonify(message=f"Failed to look up the event: {error}"), 502
    try:
        booking = cancel_booking(booking_id, event_id)
    except BookingNotFoundError:
        return jsonify(message="Venue booking not found for this event."), 404
    except Exception as error:
        return jsonify(message=f"Failed to cancel the booking request: {error}"), 502
    return jsonify(booking), 200


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
        if status == "Approved":
            current = get_booking(booking_id)
            venue = get_venue(current["venueId"])
            booking = decide_booking(
                booking_id,
                reviewed_by,
                status,
                int(venue.get("setupTimeMinutes", 0)),
                int(venue.get("turnaroundTimeMinutes", 0)),
            )
        else:
            # Rejection cannot create a scheduling conflict and retains the
            # existing one-call workflow.
            booking = decide_booking(booking_id, reviewed_by, status)
    except BookingNotFoundError:
        return jsonify(message="Venue booking not found."), 404
    except BookingStateError:
        return jsonify(message="Cancelled venue bookings cannot be reviewed."), 409
    except BookingConflictError as error:
        return jsonify(
            message="This venue is unavailable for the requested time.",
            code="VENUE_UNAVAILABLE",
            conflictTypes=error.conflict_types,
        ), 409
    except Exception as e:
        return jsonify(message=f"Failed to update the booking request: {e}"), 502
    return jsonify(booking), 200


@bp.put("/venues/<uuid:venue_id>")
def update_venue_and_reconcile(venue_id):
    """Save a venue profile, then identify conflicts introduced by buffers."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(message="Send a JSON object."), 400
    try:
        venue = update_venue_profile(str(venue_id), data)
    except httpx.HTTPStatusError as error:
        try:
            body = error.response.json()
        except ValueError:
            body = {"message": "Unable to save the venue."}
        return jsonify(body), error.response.status_code
    except Exception:
        return jsonify(message="Unable to save the venue."), 502

    try:
        conflicts = reconcile_legacy_conflicts(venue)
    except Exception:
        return jsonify(
            message=(
                "The venue was saved, but legacy scheduling conflicts could "
                "not be refreshed. Open the venue and retry."
            ),
            venueSaved=True,
            venue=venue,
        ), 502
    return jsonify(venue=venue, legacyConflicts=conflicts), 200


@bp.get("/venues/<uuid:venue_id>/legacy-conflicts")
def list_venue_legacy_conflicts(venue_id):
    """Reconcile on read so booking edits/cancellations cannot leave stale flags."""
    try:
        venue = get_venue(str(venue_id))
        conflicts = reconcile_legacy_conflicts(venue)
        return jsonify(
            _add_event_names(
                conflicts,
                request.headers.get("X-Dev-User-Id"),
                request.headers.get("X-Dev-Role"),
            )
        )
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            return jsonify(message="Venue not found."), 404
        return jsonify(message="Unable to identify scheduling conflicts."), 502
    except Exception:
        return jsonify(message="Unable to identify scheduling conflicts."), 502
