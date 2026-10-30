import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from flask import Blueprint, g, jsonify, request

from app.clients import (
    BookingAlreadyDecidedError,
    BookingConflictError,
    BookingNotFoundError,
    BookingStateError,
    EventNotAssignedError,
    EventNotFoundError,
    RejectionReasonRequiredError,
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


class _RequestPool(ThreadPoolExecutor):
    """Worker threads run in this request's context, so they forward the caller's token (SCRUM-8)."""

    def submit(self, fn, /, *args, **kwargs):
        return super().submit(contextvars.copy_context().run, fn, *args, **kwargs)

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
# SCRUM-29 AC4: the longest rejection reason, matching the frontend's
# RejectionDialog and Venue Availability Service.
MAX_REJECTION_REASON = 500
# SCRUM-29 AC1: the event fields Venue Staff need to assess a request. Only
# these are forwarded, never the event's history or metadata.
REVIEW_EVENT_FIELDS = (
    "id",
    "eventName",
    "status",
    "coordinatorId",
    "preferredStartDate",
    "preferredEndDate",
    "expectedAttendance",
    "venueRequirements",
    "accessibilityNeeds",
)
REVIEW_VENUE_FIELDS = (
    "id",
    "name",
    "capacity",
    "status",
    "setupTimeMinutes",
    "turnaroundTimeMinutes",
)



# Booking times are naive Singapore local time, like the event's own dates.
SINGAPORE = ZoneInfo("Asia/Singapore")


def _booking_window_invalid(event, start, end, now=None):
    """
    SCRUM-28: a venue request must be for a future slot that falls on the
    event's own dates. Days, not exact times, so a booking can still cover
    setup on the morning of the event. Returns a 422 response, or None.
    """
    current = now or datetime.now(SINGAPORE).replace(tzinfo=None)
    if start <= current:
        return jsonify(
            message="The requested start time must be in the future.",
            code="BOOKING_IN_PAST",
        ), 422
    try:
        event_start = datetime.fromisoformat(event.get("preferredStartDate") or "")
        event_end = datetime.fromisoformat(event.get("preferredEndDate") or "")
    except (TypeError, ValueError):
        # No event dates to compare against; Venue Staff still review it.
        return None
    if start.date() < event_start.date() or end.date() > event_end.date():
        return jsonify(
            message=(
                "The requested time must fall within the event's dates "
                f"({event_start.date().isoformat()} to {event_end.date().isoformat()})."
            ),
            code="BOOKING_OUTSIDE_EVENT_DATES",
        ), 422
    return None


def _queue_order(booking):
    """SCRUM-28 AC4: awaiting requests first, oldest submission first, legacy rows last."""
    requested_at = booking.get("requestedAt")
    return (
        not booking["awaitingReview"],
        requested_at is None,
        requested_at or "",
        booking.get("requestedStartTime") or "",
    )


def _add_event_names(result, viewer_role):
    """Best-effort display enrichment; conflict identification must still work if Event Service is down."""
    if viewer_role != "Venue Staff":
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
                    event = get_event_for_internal_viewer(event_id, viewer_role)
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
    if not g.user_id:
        return jsonify(message="Sign in to continue."), 401
    if g.role != "Venue Staff":
        return jsonify(message="Only Venue Staff can review venue requests."), 403
    return None


@bp.get("/booking-requests")
def staff_booking_requests():
    failure = _venue_staff()
    if failure:
        return failure
    status = request.args.get("status")
    if status not in (None, "Pending", "Approved", "Rejected"):
        return jsonify(message="Invalid booking status filter."), 400
    try:
        events = get_staff_events()
        venues = {venue["id"]: venue["name"] for venue in get_venues()}
        result = []
        with _RequestPool(max_workers=8) as pool:
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


def _rejection_reason(value):
    """Return the stripped reason, or None when it is missing or invalid."""
    if not isinstance(value, str):
        return None
    reason = value.strip()
    return reason if 0 < len(reason) <= MAX_REJECTION_REASON else None


def _decision_blocked_reason(event_status, booking_status):
    """SCRUM-29 AC1/AC5: why Venue Staff can't decide, in the page's own wording."""
    if booking_status not in AWAITING_REVIEW_STATUSES:
        return "Already decided"
    if event_status == "Submitted":
        return "Opens for review when the event is Under Review"
    if event_status not in REVIEWABLE_EVENT_STATUSES:
        return f"Not open for review while the event is {event_status}"
    return None


def _occupied(value, minutes):
    """Shift a naive local booking time by a venue buffer, keeping its format."""
    try:
        return (datetime.fromisoformat(value) + timedelta(minutes=int(minutes or 0))).isoformat()
    except (TypeError, ValueError):
        return None


@bp.get("/booking-requests/<booking_id>")
def staff_booking_request(booking_id):
    """SCRUM-29 AC1: open one venue request with what Venue Staff need to assess it.

    Combines the booking (Venue Availability), the event's timing and
    requirements (Event Service) and the venue's capacity and buffers (Venue
    Service), so the occupied window shows what an approval would block.
    """
    failure = _venue_staff()
    if failure:
        return failure
    try:
        booking = get_booking(booking_id)
        with _RequestPool(max_workers=2) as pool:
            event_call = pool.submit(get_event_for_internal_viewer, booking["eventId"], "Venue Staff")
            venue_call = pool.submit(get_venue, booking["venueId"])
            event = event_call.result()
            venue = venue_call.result()
    except BookingNotFoundError:
        return jsonify(message="Venue booking not found."), 404
    except httpx.TimeoutException:
        return jsonify(message="Loading the venue request took too long."), 504
    except Exception:
        return jsonify(message="Unable to load the venue request right now."), 502

    # Event Service sends "" for unset dates and requirements.
    event_view = {field: event.get(field) or None for field in REVIEW_EVENT_FIELDS}
    venue_view = {field: venue.get(field) for field in REVIEW_VENUE_FIELDS}
    blocked = _decision_blocked_reason(event.get("status"), booking.get("status"))
    return jsonify(
        booking={
            **booking,
            "venueName": venue.get("name") or "Unknown venue",
            "awaitingReview": booking.get("status") in AWAITING_REVIEW_STATUSES,
            "occupiedFrom": _occupied(
                booking.get("requestedStartTime"), -int(venue.get("setupTimeMinutes") or 0)
            ),
            "occupiedTo": _occupied(
                booking.get("requestedEndTime"), venue.get("turnaroundTimeMinutes")
            ),
        },
        event=event_view,
        venue=venue_view,
        canDecide=blocked is None,
        decisionBlockedReason=blocked,
    )


@bp.patch("/booking-requests/<booking_id>/review")
def staff_review_booking(booking_id):
    return _review_decision(booking_id)


def _review_decision(booking_id, status=None):
    """SCRUM-29 AC2-AC5: the one path by which Venue Staff record a decision.

    `/review` reads the decision from the body; the legacy `/approve` and
    `/reject` routes pass it in, but run every same check.
    """
    failure = _venue_staff()
    if failure:
        return failure
    data = request.get_json(silent=True)
    decision = status or (data.get("status") if isinstance(data, dict) else None)
    if not isinstance(data, dict) or decision not in ("Approved", "Rejected"):
        return jsonify(message="A valid decision is required."), 400
    rejection_reason = None
    if decision == "Rejected":
        # Checked before any downstream call so a bad request costs nothing.
        rejection_reason = _rejection_reason(data.get("rejectionReason"))
        if rejection_reason is None:
            return _rejection_reason_required()
    try:
        booking = get_booking(booking_id)
        event = get_event_for_internal_viewer(booking["eventId"], "Venue Staff")
    except BookingNotFoundError:
        return jsonify(message="Venue booking not found."), 404
    except Exception:
        return jsonify(message="Unable to check the venue request."), 502
    # .get: a malformed downstream answer is refused, never a 500.
    if event.get("status") not in REVIEWABLE_EVENT_STATUSES:
        return jsonify(
            message="This venue request is not awaiting staff review.",
            code="EVENT_NOT_REVIEWABLE",
            eventStatus=event.get("status"),
        ), 409
    if booking.get("status") not in AWAITING_REVIEW_STATUSES:
        return _already_decided()
    return _decide(booking_id, booking, decision, rejection_reason)


def _rejection_reason_required():
    return jsonify(
        message="A reason is required to reject a venue request.",
        code="REJECTION_REASON_REQUIRED",
    ), 400


def _already_decided():
    return jsonify(
        message="This venue request is not awaiting staff review.",
        code="BOOKING_ALREADY_DECIDED",
    ), 409


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
        with _RequestPool(max_workers=2) as pool:
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
    The requester is the signed-in Event Coordinator (SCRUM-8); they must be
    the coordinator assigned to the event.
    - requestedStartTime/requestedEndTime: this booking's own window
    - requiredCapacity: this booking's expected attendance, independent from
      the event's total expected attendance
    - venueRequirements: this booking's own free-text requirements
    """
    if not g.user_id:
        return jsonify(message="Sign in to continue."), 401
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(message="Send a JSON object."), 400

    event_id = data.get("eventId")
    venue_id = data.get("venueId")
    start = data.get("requestedStartTime")
    end = data.get("requestedEndTime")
    required_capacity = data.get("requiredCapacity")
    venue_requirements = data.get("venueRequirements")
    if not event_id or not venue_id or not start or not end:
        return jsonify(
            message="eventId, venueId, requestedStartTime and requestedEndTime are required."
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
        event = get_event(event_id)
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
    invalid_window = _booking_window_invalid(event, parsed_start, parsed_end)
    if invalid_window:
        return invalid_window

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
    if not g.user_id:
        return jsonify(message="Sign in to continue."), 401
    try:
        get_event(event_id)
    except EventNotFoundError:
        return jsonify(message="Event request not found."), 404
    except EventNotAssignedError:
        return jsonify(
            message="This event request is not assigned to the given coordinator."
        ), 403
    except Exception as error:
        return jsonify(message=f"Failed to look up the event: {error}"), 502

    with _RequestPool(max_workers=2) as pool:
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
    if not g.user_id:
        return jsonify(message="Sign in to continue."), 401
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(message="Send a JSON object."), 400

    event_id = data.get("eventId")
    venue_id = data.get("venueId")
    start = data.get("requestedStartTime")
    end = data.get("requestedEndTime")
    required_capacity = data.get("requiredCapacity")
    venue_requirements = data.get("venueRequirements")
    if not event_id or not venue_id or not start or not end:
        return jsonify(
            message="eventId, venueId, requestedStartTime and requestedEndTime are required."
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
        event = get_event(event_id)
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
    invalid_window = _booking_window_invalid(event, parsed_start, parsed_end)
    if invalid_window:
        return invalid_window

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
        event, event_id, booking_id,
        f"A venue booking ({venue['name']}) was edited after safety approval.",
    )
    if failure:
        return failure
    result = _save_booking_update(
        booking_id, event_id, venue_id, start, end, required_capacity,
        venue_requirements.strip(), venue,
    )
    return _restore_if_failed(result, event_id, withdrawn_id)


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
    if not g.user_id:
        return jsonify(message="Sign in to continue."), 401
    data = request.get_json(silent=True)
    event_id = data.get("eventId") if isinstance(data, dict) else None
    if not event_id:
        return jsonify(message="eventId is required."), 400
    try:
        event = get_event(event_id)
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
        event, event_id, booking_id,
        "A venue booking was cancelled after safety approval.",
    )
    if failure:
        return failure
    result = _save_booking_cancellation(booking_id, event_id)
    return _restore_if_failed(result, event_id, withdrawn_id)


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


def _withdraw_safety_approval(event, event_id, booking_id, reason):
    """For a Confirmed event, withdraw its safety approval before the booking changes.

    Returns `(withdrawn_safety_check_id, failure)`. Any other status needs no
    withdrawal and returns `(None, None)`. If Safety Check Service refuses or
    fails, the booking is never touched and its answer is passed on.
    """
    if event.get("status") != "Confirmed":
        return None, None
    try:
        result = withdraw_safety_for_venue_change(event_id, booking_id, reason)
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


def _restore_if_failed(result, event_id, withdrawn_id):
    """Undo the withdrawal when the booking change it was made for didn't happen.

    The original booking error is what the caller gets either way. If the
    restore also fails there is nothing left to try, so it is logged for a
    manual repair: the event is left Approved, its booking unchanged.
    """
    if withdrawn_id and result[1] >= 400:
        try:
            restore_safety_after_venue_change(event_id, withdrawn_id)
        except Exception:
            logger.error(
                "Could not restore safety approval %s for event %s after its venue "
                "booking change failed; the event is left Approved with its booking "
                "unchanged and needs manual repair.",
                withdrawn_id,
                event_id,
            )
    return result


# SCRUM-29 D7 (Clarice, 25 Oct): the legacy decision URLs stay, but run the
# same Venue Staff, event-status, awaiting and reason checks as /review.
@bp.patch("/booking-requests/<booking_id>/approve")
def approve_booking_request(booking_id):
    return _review_decision(booking_id, "Approved")


@bp.patch("/booking-requests/<booking_id>/reject")
def reject_booking_request(booking_id):
    return _review_decision(booking_id, "Rejected")


def _decide(booking_id, booking, status, rejection_reason=None):
    try:
        if status == "Approved":
            venue = get_venue(booking["venueId"])
            decided = decide_booking(
                booking_id,
                status,
                int(venue.get("setupTimeMinutes", 0)),
                int(venue.get("turnaroundTimeMinutes", 0)),
            )
        else:
            # Rejection cannot create a scheduling conflict, so it needs no
            # venue buffers.
            decided = decide_booking(
                booking_id, status, rejection_reason=rejection_reason
            )
    except BookingNotFoundError:
        return jsonify(message="Venue booking not found."), 404
    except RejectionReasonRequiredError:
        return _rejection_reason_required()
    except BookingAlreadyDecidedError:
        # Another staff member decided between our check and the write.
        return _already_decided()
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
    return jsonify(decided), 200


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
            _add_event_names(conflicts, g.role)
        )
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            return jsonify(message="Venue not found."), 404
        return jsonify(message="Unable to identify scheduling conflicts."), 502
    except Exception:
        return jsonify(message="Unable to identify scheduling conflicts."), 502
