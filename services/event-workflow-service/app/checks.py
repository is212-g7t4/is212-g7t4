"""SCRUM-20 AC3: does a high-impact change contradict the event's other arrangements?

Pure logic over what the atomics return, in the shape of
`safety-check-service/app/readiness.py`: the rules can be read and tested
without HTTP. Only the checks the rubric names exist:

* new dates   -> the event's venue bookings, and its equipment requests
                 against stock in the new window;
* more people -> the capacity of every venue the event has booked.

Venue requirements, accessibility needs and the free-text equipment
requirements have no contradiction rule, so changing them is never blocked.
"""
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from app import clients

# Event Service's API works in naive Singapore local time.
SINGAPORE = ZoneInfo("Asia/Singapore")

DATE_FIELDS = ("preferredStartDate", "preferredEndDate")

# A booking the event no longer relies on (same set as safety-check-service).
IGNORED_BOOKING_STATUSES = frozenset({"Cancelled", "Expired", "Rejected"})
HELD_REQUEST_STATUSES = frozenset({"Pending", "Approved"})

# Event statuses whose Approved equipment lines hold stock; mirrors
# equipment-reservation-service/app/availability.py.
RESERVING_EVENT_STATUSES = (
    "Approved",
    "Confirmed",
    "Under Review",
    "Clarification Requested",
    "Amendment Requested",  # SCRUM-16: approved stock stays held while the organiser amends
    "Pending Safety Check",
    "Safety Changes Requested",
)


def _naive(value):
    """An ISO date-time as naive Singapore time, or None when blank or invalid."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo:
        parsed = parsed.astimezone(SINGAPORE).replace(tzinfo=None)
    return parsed


def _format(moment):
    return moment.strftime("%d %b %Y %H:%M")


def _conflict(field, area, message):
    return {"field": field, "area": area, "message": message}


def live_bookings(bookings):
    return [
        booking
        for booking in bookings
        if booking.get("status") not in IGNORED_BOOKING_STATUSES
    ]


def attendance_increased(event, changes):
    """True when the new attendance is above the current one."""
    try:
        new = int(str(changes["expectedAttendance"]).strip())
    except (KeyError, ValueError):
        return False
    try:
        old = int(str(event.get("expectedAttendance") or 0).strip())
    except ValueError:
        old = 0
    return new > old


def venue_date_conflicts(bookings, start, end):
    """Live bookings exist, but none of them overlaps the event's new dates."""
    live = live_bookings(bookings)
    if not live:
        return []
    windows = []
    for booking in live:
        booked_start = _naive(booking.get("requestedStartTime"))
        booked_end = _naive(booking.get("requestedEndTime"))
        if booked_start < end and booked_end > start:
            return []
        windows.append(f"{_format(booked_start)} to {_format(booked_end)}")
    windows = ", ".join(windows)
    return [
        _conflict(
            "preferredStartDate",
            "venue",
            f"The new dates ({_format(start)} to {_format(end)}) don't overlap "
            f"this event's venue booking ({windows}). Move or cancel the booking "
            "first.",
        )
    ]


def capacity_conflicts(bookings, venues, attendance):
    """Live bookings at a venue whose catalogue capacity is below the new attendance."""
    catalogue = {venue["id"]: venue for venue in venues}
    conflicts = []
    for booking in live_bookings(bookings):
        venue = catalogue.get(booking.get("venueId"))
        capacity = venue.get("capacity") if venue else None
        if isinstance(capacity, int) and attendance > capacity:
            conflicts.append(
                _conflict(
                    "expectedAttendance",
                    "venue",
                    f"{venue.get('name') or 'The booked venue'} holds up to "
                    f"{capacity} people, fewer than the new attendance of "
                    f"{attendance}.",
                )
            )
    return conflicts


def equipment_conflicts(own_requests, equipment, reserved, start, end):
    """Pending/Approved lines of this event that the new window's stock can't cover."""
    catalogue = {item["id"]: item for item in equipment}
    conflicts = []
    for line in own_requests:
        item = catalogue.get(line["equipmentId"])
        available = (
            max(0, item["totalQuantity"] - reserved.get(line["equipmentId"], 0))
            if item and item.get("status") == "Available"
            else 0
        )
        if line["quantityRequested"] > available:
            name = (item or {}).get("description") or "Requested equipment"
            conflicts.append(
                _conflict(
                    "preferredStartDate",
                    "equipment",
                    f"{name}: {line['quantityRequested']} requested but only "
                    f"{available} available between {_format(start)} and "
                    f"{_format(end)}.",
                )
            )
    return conflicts


def find_conflicts(event, changes, high_fields):
    """Every contradiction between a high-impact change and the event's arrangements.

    Empty means the change may go ahead. A downstream failure propagates as
    `DownstreamError`/`DownstreamTimeout` rather than passing the change: if
    the arrangements can't be read, the change isn't known to be safe.
    """
    merged = {**event, **changes}
    start, end = _naive(merged.get("preferredStartDate")), _naive(
        merged.get("preferredEndDate")
    )
    dates_changed = any(field in high_fields for field in DATE_FIELDS) and start and end
    more_people = "expectedAttendance" in high_fields and attendance_increased(
        event, changes
    )
    if not dates_changed and not more_people:
        return []

    bookings = clients.get_event_venue_bookings(event["id"])
    conflicts = []
    if dates_changed:
        conflicts += venue_date_conflicts(bookings, start, end)
        conflicts += _equipment_window_conflicts(event["id"], start, end)
    if more_people:
        attendance = int(str(merged["expectedAttendance"]).strip())
        if live_bookings(bookings):
            conflicts += capacity_conflicts(bookings, clients.list_venues(), attendance)
    return conflicts


def _equipment_window_conflicts(event_id, start, end):
    own = [
        line
        for line in clients.list_event_equipment_requests(event_id)
        if line.get("status") in HELD_REQUEST_STATUSES
    ]
    if not own:
        return []
    others = clients.list_overlapping_events(
        start.isoformat(), end.isoformat(), RESERVING_EVENT_STATUSES, event_id
    )
    reserved = defaultdict(int)
    if others:
        for line in clients.list_approved_equipment_requests(
            [other["id"] for other in others]
        ):
            reserved[line["equipmentId"]] += line["quantityRequested"]
    return equipment_conflicts(own, clients.list_equipment(), reserved, start, end)
