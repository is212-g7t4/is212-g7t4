import os

import httpx

# Composites are the only services allowed to call other services (see
# AGENTS.md). Each downstream service gets its own base-URL env var and a
# thin wrapper function here — copy this pattern per atomic this composite
# calls, don't build a generic client.

EVENT_SERVICE_URL = os.environ.get("EVENT_SERVICE_URL") or "http://localhost:5003"
VENUE_SERVICE_URL = os.environ.get("VENUE_SERVICE_URL") or "http://localhost:5006"
VENUE_AVAILABILITY_SERVICE_URL = (
    os.environ.get("VENUE_AVAILABILITY_SERVICE_URL") or "http://localhost:5008"
)


# SCRUM-26 AC3 gives the whole search a 3-second budget. The two downstream
# calls run in parallel, so each gets most of it rather than half.
SEARCH_TIMEOUT = 2.5


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


class BookingStateError(Exception):
    pass


def get_event(event_id: str, coordinator_id: str) -> dict:
    """Fetch an event from Event Service, scoped to the requesting coordinator."""
    response = httpx.get(
        f"{EVENT_SERVICE_URL}/events/{event_id}",
        params={"coordinatorId": coordinator_id},
    )
    if response.status_code == 404:
        raise EventNotFoundError
    if response.status_code == 403:
        raise EventNotAssignedError
    response.raise_for_status()
    return response.json()


def get_event_for_internal_viewer(event_id: str, viewer_id: str, viewer_role: str) -> dict:
    """Resolve event display details for an authorised internal venue workflow."""
    response = httpx.get(
        f"{EVENT_SERVICE_URL}/events/{event_id}",
        params={"coordinatorId": viewer_id, "viewerRole": viewer_role},
    )
    response.raise_for_status()
    return response.json()


def get_venues() -> list:
    """Return the venue catalogue from Venue Service."""
    response = httpx.get(f"{VENUE_SERVICE_URL}/venues")
    response.raise_for_status()
    return response.json()["venues"]


def get_venue(venue_id: str) -> dict:
    response = httpx.get(f"{VENUE_SERVICE_URL}/venues/{venue_id}")
    response.raise_for_status()
    return response.json()["venue"]


def update_venue_profile(venue_id: str, details: dict) -> dict:
    response = httpx.put(f"{VENUE_SERVICE_URL}/venues/{venue_id}", json=details)
    response.raise_for_status()
    return response.json()["venue"]


def reconcile_legacy_conflicts(venue: dict) -> dict:
    response = httpx.post(
        f"{VENUE_AVAILABILITY_SERVICE_URL}/venues/{venue['id']}/legacy-conflicts/reconcile",
        json={
            "setupTimeMinutes": venue.get("setupTimeMinutes", 0),
            "turnaroundTimeMinutes": venue.get("turnaroundTimeMinutes", 0),
        },
    )
    response.raise_for_status()
    return response.json()


def search_venues(filters: list) -> list:
    """Venues from Venue Service that meet the event's requirements.

    `filters` is a list of (name, value) pairs so repeatable parameters
    (facility, accessibility) survive the trip.
    """
    response = httpx.get(
        f"{VENUE_SERVICE_URL}/venues", params=filters, timeout=SEARCH_TIMEOUT
    )
    response.raise_for_status()
    return response.json()["venues"]


def get_bookings_between(start: str, end: str, padding_minutes: int = 0) -> dict:
    """Bookings and distinct closures overlapping [start, end) for every venue.

    Uses the window read, not `GET /venue-bookings`: that one answers for a
    single venue (what SCRUM-25's calendar grid needs) and is behind the
    calendar's DEV-mode/user-switcher simulation, which a composite has no
    business impersonating.
    """
    response = httpx.get(
        f"{VENUE_AVAILABILITY_SERVICE_URL}/venue-bookings/window",
        params={"dateFrom": start, "dateTo": end}
        | ({"paddingMinutes": padding_minutes} if padding_minutes else {}),
        timeout=SEARCH_TIMEOUT,
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
    requested_by: str,
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
            "requestedBy": requested_by,
        }
        | (
            {
                "setupTimeMinutes": setup_time_minutes,
                "turnaroundTimeMinutes": turnaround_time_minutes,
            }
            if setup_time_minutes is not None and turnaround_time_minutes is not None
            else {}
        ),
    )
    if response.status_code == 409:
        raise BookingConflictError(_conflict_types(response))
    response.raise_for_status()
    return response.json()


def get_event_bookings(event_id: str) -> list:
    """Load all independently managed venue bookings linked to an event."""
    response = httpx.get(
        f"{VENUE_AVAILABILITY_SERVICE_URL}/events/{event_id}/venue-bookings"
    )
    response.raise_for_status()
    return response.json()["bookings"]


def get_booking(booking_id: str) -> dict:
    response = httpx.get(
        f"{VENUE_AVAILABILITY_SERVICE_URL}/venue-bookings/{booking_id}"
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
    )
    if response.status_code == 404:
        raise BookingNotFoundError
    if response.status_code == 409:
        if response.json().get("message", "").startswith("Cancelled"):
            raise BookingStateError
        raise BookingConflictError(_conflict_types(response))
    response.raise_for_status()
    return response.json()


def cancel_booking(booking_id: str, event_id: str) -> dict:
    """Cancel one retained booking record."""
    response = httpx.patch(
        f"{VENUE_AVAILABILITY_SERVICE_URL}/venue-bookings/{booking_id}/cancel",
        json={"eventId": event_id},
    )
    if response.status_code == 404:
        raise BookingNotFoundError
    response.raise_for_status()
    return response.json()


def decide_booking(
    booking_id: str,
    reviewed_by: str,
    status: str,
    setup_time_minutes: int = 0,
    turnaround_time_minutes: int = 0,
) -> dict:
    """Approve or reject a booking via Venue Availability Service."""
    action = "approve" if status == "Approved" else "reject"
    response = httpx.patch(
        f"{VENUE_AVAILABILITY_SERVICE_URL}/venue-bookings/{booking_id}/{action}",
        json={
            "reviewedBy": reviewed_by,
            "setupTimeMinutes": setup_time_minutes,
            "turnaroundTimeMinutes": turnaround_time_minutes,
        },
    )
    if response.status_code == 404:
        raise BookingNotFoundError
    if response.status_code == 409:
        if response.json().get("message", "").startswith("Cancelled"):
            raise BookingStateError
        raise BookingConflictError(_conflict_types(response))
    response.raise_for_status()
    return response.json()
