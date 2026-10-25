import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import UUID

import httpx
from flask import Blueprint, jsonify, request

from app.clients import (
    BookingConflictError,
    BookingNotFoundError,
    BookingStateError,
    EventNotAssignedError,
    EventNotFoundError,
    SafetyApprovalError,
    cancel_booking,
    create_booking,
    decide_booking,
    get_bookings_between,
    get_booking,
    get_event_bookings,
    get_event,
    get_event_for_internal_viewer,
    get_staff_events,
    get_safety_records,
    get_venue,
    get_venues,
    reconcile_legacy_conflicts,
    restore_safety_after_venue_change,
    search_venues,
    update_booking,
    update_venue_profile,
    withdraw_safety_for_venue_change,
)
from app.search import SearchError, shortlist, validate_search

bp = Blueprint("venue_booking_service", __name__)
logger = logging.getLogger(__name__)

# Event statuses in which Venue Staff can act on a venue request (unchanged
# behaviour of the staff review route, now named once).
REVIEWABLE_EVENT_STATUSES = ("Under Review", "Approved", "Safety Changes Requested")
# Event statuses in which a coordinator may submit a new venue request
# (SCRUM-28 AC2, Clarice 25 Oct): before and during review, and while fixing
# safety feedback. Never once the safety check has started or passed
# (SCRUM-149/152), nor for a closed event.
SUBMITTABLE_EVENT_STATUSES = ("Submitted", *REVIEWABLE_EVENT_STATUSES)
# SCRUM-28 Part B (Clarice, 25 Oct): an existing booking may also be edited or
# cancelled once the event is Confirmed, but that withdraws the event's safety
# approval first (the arrangement it approved is changing). Never while the
# safety check is pending, nor for a closed event.
CHANGEABLE_EVENT_STATUSES = (*SUBMITTABLE_EVENT_STATUSES, "Confirmed")
# Booking statuses that still need a Venue Staff decision. `Pending` is the
# legacy seed spelling; new requests are stored as `Pending Review`.
AWAITING_REVIEW_STATUSES = ("Pending", "Pending Review")


def _queue_order(booking):
    """SCRUM-28 AC4: awaiting requests first, oldest submission first, legacy rows last."""
    requested_at = booking.get("requestedAt")
    return (
        not booking["awaitingReview"],
        requested_at is None,
        requested_at or "",
        booking.get("requestedStartTime") or "",
    )


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


def _venue_staff():
    try:
        viewer_id = str(UUID(request.headers.get("X-Dev-User-Id", "")))
    except ValueError:
        return None, (jsonify(message="A valid DEV user UUID is required."), 401)
    if request.headers.get("X-Dev-Role") != "Venue Staff":
        return None, (jsonify(message="Only Venue Staff can review venue requests."), 403)
    return viewer_id, None


@bp.get("/booking-requests")
def staff_booking_requests():
    viewer_id, failure = _venue_staff()
    if failure:
        return failure
    status = request.args.get("status")
    if status not in (None, "Pending", "Approved", "Rejected"):
        return jsonify(message="Invalid booking status filter."), 400
    try:
        events = get_staff_events(viewer_id)
        venues = {venue["id"]: venue["name"] for venue in get_venues()}
        result = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            booking_lists = list(pool.map(get_event_bookings, [event["id"] for event in events]))
        for event, bookings in zip(events, booking_lists):
            selected = [booking for booking in bookings if status is None or
                (booking["status"] in AWAITING_REVIEW_STATUSES if status == "Pending" else booking["status"] == status)]
            if not selected:
                continue
            latest = None
            if event["status"] == "Safety Changes Requested":
                latest = max(get_safety_records(event["id"]), key=lambda review: review["roundNumber"], default=None)
            for booking in selected:
                booking["venueName"] = venues.get(booking["venueId"], "Unknown venue")
                changes = [flag["changeRequired"] for flag in (latest or {}).get("flags", [])
                    if flag["area"] == "venue arrangement" and flag.get("bookingId") in (None, booking["id"])]
                booking["safetyFeedback"] = {"reason": latest.get("remarks"), "requestedChanges": changes} if changes and latest["status"] == "Changes Requested" else None
                # SCRUM-28 AC2/AC4: when it was submitted, and whether it still needs a decision.
                booking["requestedAt"] = booking.get("requestedAt")
                booking["awaitingReview"] = booking["status"] in AWAITING_REVIEW_STATUSES
            selected.sort(key=_queue_order)
            # SCRUM-28 AC3: the event's own timing, so each booking is assessed in
            # context. Event Service sends "" for a date that isn't set.
            result.append({"eventId": event["id"], "eventName": event["eventName"], "eventStatus": event["status"],
                "coordinatorId": event.get("coordinatorId"), "eventStart": event.get("preferredStartDate") or None,
                "eventEnd": event.get("preferredEndDate") or None,
                "awaitingReviewCount": sum(booking["awaitingReview"] for booking in selected),
                "bookings": selected})
    except httpx.TimeoutException:
        return jsonify(message="Loading venue requests took too long."), 504
    except Exception:
        return jsonify(message="Unable to load venue requests right now."), 502
    return jsonify(events=result)


@bp.patch("/booking-requests/<booking_id>/review")
def staff_review_booking(booking_id):
    viewer_id, failure = _venue_staff()
    if failure:
        return failure
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or data.get("status") not in ("Approved", "Rejected") or data.get("reviewedBy") != viewer_id:
        return jsonify(message="A valid decision and matching reviewedBy are required."), 400
    try:
        booking = get_booking(booking_id)
        event = get_event_for_internal_viewer(booking["eventId"], viewer_id, "Venue Staff")
        if event["status"] not in REVIEWABLE_EVENT_STATUSES or booking["status"] not in AWAITING_REVIEW_STATUSES:
            return jsonify(message="This venue request is not awaiting staff review."), 409
    except BookingNotFoundError:
        return jsonify(message="Venue booking not found."), 404
    except Exception:
        return jsonify(message="Unable to check the venue request."), 502
    return _decide(booking_id, data["status"])


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
        event = get_event(event_id, coordinator_id)
    except EventNotFoundError:
        return jsonify(message="Event request not found."), 404
    except EventNotAssignedError:
        return jsonify(
            message="This event request is not assigned to the given coordinator."
        ), 403
    except Exception as e:
        return jsonify(message=f"Failed to look up the event: {e}"), 502

    # SCRUM-28 AC2: only record a request Venue Staff can go on to review. Runs
    # before the catalogue call, so a refused request costs no further calls.
    if event.get("status") not in SUBMITTABLE_EVENT_STATUSES:
        return jsonify(
            message=(
                "Venue requests can only be submitted while the event is Submitted, "
                "Under Review, Approved or Safety Changes Requested."
            ),
            code="EVENT_NOT_ACCEPTING_VENUE_REQUESTS",
            eventStatus=event.get("status"),
        ), 409

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
        event = get_event(event_id, coordinator_id)
    except EventNotFoundError:
        return jsonify(message="Event request not found."), 404
    except EventNotAssignedError:
        return jsonify(
            message="This event request is not assigned to the given coordinator."
        ), 403
    except Exception as error:
        return jsonify(message=f"Failed to look up the event: {error}"), 502
    closed = _changes_closed(event)
    if closed:
        return closed

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

    withdrawn_id, failure = _withdraw_safety_approval(
        event, event_id, coordinator_id, booking_id,
        f"A venue booking ({venue['name']}) was edited after safety approval.",
    )
    if failure:
        return failure
    result = _save_booking_update(
        booking_id, event_id, venue_id, start, end, required_capacity,
        venue_requirements.strip(), venue,
    )
    return _restore_if_failed(result, event_id, coordinator_id, withdrawn_id)


def _save_booking_update(
    booking_id, event_id, venue_id, start, end, required_capacity, venue_requirements, venue
):
    try:
        args = (
            booking_id,
            event_id,
            venue_id,
            start,
            end,
            required_capacity,
            venue_requirements,
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
        return (
            jsonify(
                message="Cancelled or Rejected venue bookings cannot be modified.",
                code="BOOKING_IMMUTABLE",
            ),
            409,
        )
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
        event = get_event(event_id, coordinator_id)
    except EventNotFoundError:
        return jsonify(message="Event request not found."), 404
    except EventNotAssignedError:
        return jsonify(
            message="This event request is not assigned to the given coordinator."
        ), 403
    except Exception as error:
        return jsonify(message=f"Failed to look up the event: {error}"), 502
    closed = _changes_closed(event)
    if closed:
        return closed
    withdrawn_id, failure = _withdraw_safety_approval(
        event, event_id, coordinator_id, booking_id,
        "A venue booking was cancelled after safety approval.",
    )
    if failure:
        return failure
    result = _save_booking_cancellation(booking_id, event_id)
    return _restore_if_failed(result, event_id, coordinator_id, withdrawn_id)


def _save_booking_cancellation(booking_id, event_id):
    try:
        booking = cancel_booking(booking_id, event_id)
    except BookingStateError:
        return (
            jsonify(
                message="Rejected venue bookings cannot be cancelled.",
                code="BOOKING_IMMUTABLE",
            ),
            409,
        )
    except BookingNotFoundError:
        return jsonify(message="Venue booking not found for this event."), 404
    except Exception as error:
        return jsonify(message=f"Failed to cancel the booking request: {error}"), 502
    return jsonify(booking), 200


def _changes_closed(event):
    """SCRUM-28 Part B: refuse an edit or cancel the event's status doesn't allow."""
    if event.get("status") in CHANGEABLE_EVENT_STATUSES:
        return None
    return jsonify(
        message=(
            "Venue bookings can only be changed while the event is Submitted, Under "
            "Review, Approved, Safety Changes Requested or Confirmed."
        ),
        code="EVENT_NOT_ACCEPTING_VENUE_CHANGES",
        eventStatus=event.get("status"),
    ), 409


def _withdraw_safety_approval(event, event_id, coordinator_id, booking_id, reason):
    """For a Confirmed event, withdraw its safety approval before the booking changes.

    Returns `(withdrawn_safety_check_id, failure)`. Any other status needs no
    withdrawal and returns `(None, None)`. If Safety Check Service refuses or
    fails, the booking is never touched and its answer is passed on.
    """
    if event.get("status") != "Confirmed":
        return None, None
    try:
        result = withdraw_safety_for_venue_change(event_id, coordinator_id, booking_id, reason)
    except SafetyApprovalError as error:
        status = error.status if error.status in (403, 404, 409) else 502
        body = error.body or {"message": "Unable to withdraw the event's safety approval."}
        return None, (jsonify(body), status)
    except Exception:
        return None, (
            jsonify(message="Unable to withdraw the event's safety approval right now."),
            502,
        )
    return result["withdrawnSafetyCheck"]["id"], None


def _restore_if_failed(result, event_id, coordinator_id, withdrawn_id):
    """Undo the withdrawal when the booking change it was made for didn't happen.

    The original booking error is what the caller gets either way. If the
    restore also fails there is nothing left to try, so it is logged for a
    manual repair: the event is left Approved, its booking unchanged.
    """
    if withdrawn_id and result[1] >= 400:
        try:
            restore_safety_after_venue_change(event_id, coordinator_id, withdrawn_id)
        except Exception:
            logger.error(
                "Could not restore safety approval %s for event %s after its venue "
                "booking change failed; the event is left Approved with its booking "
                "unchanged and needs manual repair.",
                withdrawn_id,
                event_id,
            )
    return result


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
        return (
            jsonify(
                message="Cancelled or Rejected venue bookings cannot be reviewed.",
                code="BOOKING_IMMUTABLE",
            ),
            409,
        )
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
