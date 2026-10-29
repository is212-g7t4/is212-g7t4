import os

import httpx
from flask import has_request_context, request

# Composites are the only services allowed to call other services (see
# AGENTS.md). Each downstream service gets its own base-URL env var and a
# thin wrapper function here — copy this pattern per atomic this composite
# calls, don't build a generic client.

EVENT_SERVICE_URL = os.environ.get("EVENT_SERVICE_URL") or "http://localhost:5003"
VENUE_SERVICE_URL = os.environ.get("VENUE_SERVICE_URL") or "http://localhost:5006"
VENUE_AVAILABILITY_SERVICE_URL = (
    os.environ.get("VENUE_AVAILABILITY_SERVICE_URL") or "http://localhost:5008"
)
# SCRUM-28 Part B: a composite-to-composite call. Changing a booking of a
# Confirmed event withdraws its safety approval, and that lifecycle logic
# (record and event, with compensation) already lives in Safety Check Service.
SAFETY_CHECK_SERVICE_URL = (
    os.environ.get("SAFETY_CHECK_SERVICE_URL") or "http://localhost:5012"
)


# SCRUM-26 AC3 gives the whole search a 3-second budget. The two downstream
# calls run in parallel, so each gets most of it rather than half.
SEARCH_TIMEOUT = 2.5


def _forwarded_auth():
    """The caller's Supabase token, so downstream services see the same signed-in user (SCRUM-8)."""
    if has_request_context() and request.headers.get("Authorization"):
        return {"Authorization": request.headers["Authorization"]}
    return {}


class EventNotFoundError(Exception):
    pass


class EventNotAssignedError(Exception):
    pass


class BookingConflictError(Exception):
    def __init__(self, conflict_types=()):
        super().__init__("Venue unavailable for the requested time.")
        self.conflict_types = list(conflict_types)


def _conflict_types(response):
    # Legacy 409s have only a message; retain their generic conflict behavior.
    types = response.json().get("conflictTypes", [])
    if not isinstance(types, list) or any(
        kind not in ("APPROVED_BOOKING", "TENTATIVE_HOLD", "VENUE_CLOSURE")
        for kind in types
    ):
        raise ValueError("Invalid availability conflict response.")
    return types


class BookingNotFoundError(Exception):
    pass


class SafetyApprovalError(Exception):
    """Safety Check Service refused or failed to change the approval; carries its answer."""

    def __init__(self, status, body):
        super().__init__(status)
        self.status = status
        self.body = body


class BookingStateError(Exception):
    pass


class BookingAlreadyDecidedError(Exception):
    """SCRUM-29 AC5: Venue Availability found the booking already decided."""


class RejectionReasonRequiredError(Exception):
    """SCRUM-29 AC4: Venue Availability refused a reject with no usable reason."""


def get_event(event_id: str) -> dict:
    """Fetch an event from Event Service, scoped to the signed-in coordinator."""
    response = httpx.get(f"{EVENT_SERVICE_URL}/events/{event_id}", headers=_forwarded_auth())
    if response.status_code == 404:
        raise EventNotFoundError
    if response.status_code == 403:
        raise EventNotAssignedError
    response.raise_for_status()
    return response.json()


def get_event_for_internal_viewer(event_id: str, viewer_role: str) -> dict:
    """Resolve event display details for an authorised internal venue workflow."""
    response = httpx.get(
        f"{EVENT_SERVICE_URL}/events/{event_id}",
        params={"viewerRole": viewer_role},
        headers=_forwarded_auth(),
    )
    response.raise_for_status()
    return response.json()


def get_venues() -> list:
    """Return the venue catalogue from Venue Service."""
    response = httpx.get(f"{VENUE_SERVICE_URL}/venues", headers=_forwarded_auth())
    response.raise_for_status()
    return response.json()["venues"]


def get_staff_events():
    response = httpx.get(f"{EVENT_SERVICE_URL}/events", params={"viewerRole": "Venue Staff"}, headers=_forwarded_auth())
    response.raise_for_status()
    return response.json()["events"]


def get_safety_records(event_id):
    base = os.environ.get("SAFETY_CHECK_RECORD_SERVICE_URL") or "http://localhost:5013"
    response = httpx.get(f"{base}/safety-check-records", params={"eventId": event_id}, headers=_forwarded_auth())
    response.raise_for_status()
    return response.json()["safetyChecks"]


def get_venue(venue_id: str) -> dict:
    response = httpx.get(f"{VENUE_SERVICE_URL}/venues/{venue_id}", headers=_forwarded_auth())
    response.raise_for_status()
    return response.json()["venue"]


def update_venue_profile(venue_id: str, details: dict) -> dict:
    response = httpx.put(f"{VENUE_SERVICE_URL}/venues/{venue_id}", json=details, headers=_forwarded_auth())
    response.raise_for_status()
    return response.json()["venue"]


def reconcile_legacy_conflicts(venue: dict) -> dict:
    response = httpx.post(
        f"{VENUE_AVAILABILITY_SERVICE_URL}/venues/{venue['id']}/legacy-conflicts/reconcile",
        json={
            "setupTimeMinutes": venue.get("setupTimeMinutes", 0),
            "turnaroundTimeMinutes": venue.get("turnaroundTimeMinutes", 0),
        },
        headers=_forwarded_auth(),
    )
    response.raise_for_status()
    return response.json()


def search_venues(filters: list) -> list:
    """Venues from Venue Service that meet the event's requirements.

    `filters` is a list of (name, value) pairs so repeatable parameters
    (facility, accessibility) survive the trip.
    """
    response = httpx.get(
        f"{VENUE_SERVICE_URL}/venues", params=filters, timeout=SEARCH_TIMEOUT,
        headers=_forwarded_auth(),
    )
    response.raise_for_status()
    return response.json()["venues"]


def get_bookings_between(start: str, end: str, padding_minutes: int = 0) -> dict:
    """Bookings and distinct closures overlapping [start, end) for every venue.

    Uses the window read, not `GET /venue-bookings`: that one answers for a
    single venue (what SCRUM-25's calendar grid needs) and is role-gated
    for the calendar's viewers.
    """
    response = httpx.get(
        f"{VENUE_AVAILABILITY_SERVICE_URL}/venue-bookings/window",
        params={"dateFrom": start, "dateTo": end}
        | ({"paddingMinutes": padding_minutes} if padding_minutes else {}),
        timeout=SEARCH_TIMEOUT,
        headers=_forwarded_auth(),
    )
    response.raise_for_status()
    payload = response.json()
    from app.search import validate_window

    return validate_window(payload, start, end, padding_minutes)


def create_booking(
    event_id: str,
    venue_id: str,
    start: str,
    end: str,
    required_capacity: int,
    venue_requirements: str,
    setup_time_minutes: int | None = None,
    turnaround_time_minutes: int | None = None,
) -> dict:
    """Persist a booking request in Venue Availability Service (conflict-checked there)."""
    response = httpx.post(
        f"{VENUE_AVAILABILITY_SERVICE_URL}/venue-bookings",
        json={
            "eventId": event_id,
            "venueId": venue_id,
            "requestedStartTime": start,
            "requestedEndTime": end,
            "requiredCapacity": required_capacity,
            "venueRequirements": venue_requirements,
        }
        | (
            {
                "setupTimeMinutes": setup_time_minutes,
                "turnaroundTimeMinutes": turnaround_time_minutes,
            }
            if setup_time_minutes is not None and turnaround_time_minutes is not None
            else {}
        ),
        headers=_forwarded_auth(),
    )
    if response.status_code == 409:
        raise BookingConflictError(_conflict_types(response))
    response.raise_for_status()
    return response.json()


def get_event_bookings(event_id: str) -> list:
    """Load all independently managed venue bookings linked to an event."""
    response = httpx.get(
        f"{VENUE_AVAILABILITY_SERVICE_URL}/events/{event_id}/venue-bookings",
        headers=_forwarded_auth(),
    )
    response.raise_for_status()
    return response.json()["bookings"]


def get_booking(booking_id: str) -> dict:
    response = httpx.get(
        f"{VENUE_AVAILABILITY_SERVICE_URL}/venue-bookings/{booking_id}",
        headers=_forwarded_auth(),
    )
    if response.status_code == 404:
        raise BookingNotFoundError
    response.raise_for_status()
    return response.json()


def update_booking(
    booking_id: str,
    event_id: str,
    venue_id: str,
    start: str,
    end: str,
    required_capacity: int,
    venue_requirements: str,
    setup_time_minutes: int | None = None,
    turnaround_time_minutes: int | None = None,
) -> dict:
    """Update and revalidate one booking without changing its siblings."""
    response = httpx.patch(
        f"{VENUE_AVAILABILITY_SERVICE_URL}/venue-bookings/{booking_id}",
        json={
            "eventId": event_id,
            "venueId": venue_id,
            "requestedStartTime": start,
            "requestedEndTime": end,
            "requiredCapacity": required_capacity,
            "venueRequirements": venue_requirements,
        }
        | (
            {
                "setupTimeMinutes": setup_time_minutes,
                "turnaroundTimeMinutes": turnaround_time_minutes,
            }
            if setup_time_minutes is not None and turnaround_time_minutes is not None
            else {}
        ),
        headers=_forwarded_auth(),
    )
    if response.status_code == 404:
        raise BookingNotFoundError
    if response.status_code == 409:
        if response.json().get("code") == "BOOKING_IMMUTABLE" or response.json().get(
            "message", ""
        ).startswith("Cancelled"):
            raise BookingStateError
        raise BookingConflictError(_conflict_types(response))
    response.raise_for_status()
    return response.json()


def cancel_booking(booking_id: str, event_id: str) -> dict:
    """Cancel one retained booking record."""
    response = httpx.patch(
        f"{VENUE_AVAILABILITY_SERVICE_URL}/venue-bookings/{booking_id}/cancel",
        json={"eventId": event_id},
        headers=_forwarded_auth(),
    )
    if response.status_code == 404:
        raise BookingNotFoundError
    if (
        response.status_code == 409
        and response.json().get("code") == "BOOKING_IMMUTABLE"
    ):
        raise BookingStateError
    response.raise_for_status()
    return response.json()


def decide_booking(
    booking_id: str,
    status: str,
    setup_time_minutes: int = 0,
    turnaround_time_minutes: int = 0,
    rejection_reason: str | None = None,
) -> dict:
    """Approve or reject a booking via Venue Availability Service."""
    action = "approve" if status == "Approved" else "reject"
    body = {
        "setupTimeMinutes": setup_time_minutes,
        "turnaroundTimeMinutes": turnaround_time_minutes,
    }
    # SCRUM-29 AC4: only a rejection carries a reason.
    if status == "Rejected":
        body["rejectionReason"] = rejection_reason
    response = httpx.patch(
        f"{VENUE_AVAILABILITY_SERVICE_URL}/venue-bookings/{booking_id}/{action}",
        json=body,
        headers=_forwarded_auth(),
    )
    if response.status_code == 404:
        raise BookingNotFoundError
    if (
        response.status_code == 400
        and response.json().get("code") == "REJECTION_REASON_REQUIRED"
    ):
        raise RejectionReasonRequiredError
    if response.status_code == 409:
        if response.json().get("code") == "BOOKING_ALREADY_DECIDED":
            raise BookingAlreadyDecidedError
        if response.json().get("code") == "BOOKING_IMMUTABLE" or response.json().get(
            "message", ""
        ).startswith("Cancelled"):
            raise BookingStateError
        raise BookingConflictError(_conflict_types(response))
    response.raise_for_status()
    return response.json()


def withdraw_safety_for_venue_change(event_id: str, booking_id: str, reason: str) -> dict:
    """SCRUM-28 Part B: withdraw a Confirmed event's approval before its booking changes."""
    response = httpx.post(
        f"{SAFETY_CHECK_SERVICE_URL}/safety-checks/withdraw-for-venue-change",
        json={
            "eventId": event_id,
            "bookingId": booking_id,
            "reason": reason,
        },
        headers=_forwarded_auth(),
    )
    if not response.is_success:
        try:
            body = response.json()
        except ValueError:
            body = {}
        raise SafetyApprovalError(response.status_code, body)
    return response.json()


def restore_safety_after_venue_change(event_id: str, withdrawn_safety_check_id: str) -> dict:
    """Undo `withdraw_safety_for_venue_change` when the booking change then failed."""
    response = httpx.post(
        f"{SAFETY_CHECK_SERVICE_URL}/safety-checks/restore-after-venue-change",
        json={
            "eventId": event_id,
            "withdrawnSafetyCheckId": withdrawn_safety_check_id,
        },
        headers=_forwarded_auth(),
    )
    response.raise_for_status()
    return response.json()
