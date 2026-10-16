"""SCRUM-26 Venue Search and Filtering — the composite's own search logic.

Kept free of Flask and httpx so every rule here is unit-testable on plain
dicts. The route in `routes.py` does the HTTP work; this module decides what
is a valid search and what each venue's availability is.
"""
from datetime import datetime, timedelta, timezone

SINGAPORE = timezone(timedelta(hours=8))

# AC1's required criteria, in the order the message lists them back.
REQUIRED_FIELDS = [
    ("start", "Date and start time"),
    ("end", "End time"),
    ("expectedAttendance", "Expected attendance"),
]

# Optional filters forwarded to Venue Service untouched. The repeatable ones
# can appear more than once in the query string.
SINGLE_FILTERS = ["location", "layout"]
REPEATABLE_FILTERS = ["facility", "accessibility"]

AVAILABLE = "Available"
PENDING = "Pending request"
BOOKED = "Booked"
NOT_OPERATIONAL = "Not operational"

# Only these appear in results: a Booked or Not operational venue cannot host
# the event at the requested time, so AC3's "matching all active criteria"
# leaves it out.
SHOWN = [AVAILABLE, PENDING]


class SearchError(Exception):
    """The search as submitted cannot be run. `missing` lists empty required fields."""

    def __init__(self, message, missing=None):
        super().__init__(message)
        self.message = message
        self.missing = missing or []


def _parse_datetime(value):
    """Naive local (Singapore) time only — VenueBooking has no time zone.

    Matches Venue Availability's own `_parse_datetime`, including its rule
    that the date and time are joined by "T": Python would also accept a
    space, but the atomic rejects it, so accepting it here would only turn a
    bad request into a downstream failure.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo or "T" not in value:
        return None
    return parsed


def validate_search(args, now=None):
    """Return parsed criteria, or raise SearchError describing what is wrong.

    `args` is anything with `.get(name)` and `.getlist(name)` (a Flask
    MultiDict in the route, a plain helper in tests).
    """
    missing = [label for name, label in REQUIRED_FIELDS if not (args.get(name) or "").strip()]
    if missing:
        return _raise_missing(missing)

    start = _parse_datetime(args.get("start").strip())
    end = _parse_datetime(args.get("end").strip())
    if not start or not end:
        raise SearchError("Enter a valid date, start time and end time.")
    if end <= start:
        raise SearchError("The end time must be after the start time.")
    if end - start > timedelta(days=42):
        raise SearchError("Search windows must not exceed 42 days.")
    if start < (now or datetime.now(SINGAPORE).replace(tzinfo=None)):
        raise SearchError("Choose a date and time in the future.")

    attendance = _positive_int(args.get("expectedAttendance"))
    if attendance is None:
        raise SearchError("Expected attendance must be a whole number of at least 1.")

    min_capacity_raw = (args.get("minCapacity") or "").strip()
    min_capacity = attendance
    if min_capacity_raw:
        parsed = _positive_int(min_capacity_raw)
        if parsed is None:
            raise SearchError("Minimum capacity must be a whole number of at least 1.")
        # Both are floors on the same column, so the stricter one wins.
        min_capacity = max(attendance, parsed)

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "filters": _venue_filters(args, min_capacity),
    }


def _raise_missing(missing):
    raise SearchError(
        f"Please fill in the required fields: {', '.join(missing)}.", missing=missing
    )


def _positive_int(value):
    try:
        number = int(str(value).strip())
    except (ValueError, TypeError, AttributeError):
        return None
    return number if number >= 1 else None


def _venue_filters(args, min_capacity):
    """The query Venue Service answers, as (name, value) pairs."""
    filters = [("minCapacity", str(min_capacity))]
    for name in SINGLE_FILTERS:
        value = (args.get(name) or "").strip()
        if value:
            filters.append((name, value))
    for name in REPEATABLE_FILTERS:
        filters.extend(
            (name, value.strip()) for value in args.getlist(name) if value.strip()
        )
    return filters


def _effective_window(venue, start, end):
    return (
        _shift(start, -int(venue.get("setupTimeMinutes", 0))),
        _shift(end, int(venue.get("turnaroundTimeMinutes", 0))),
    )


def _shift(value, minutes):
    try:
        return value + timedelta(minutes=minutes)
    except OverflowError:
        boundary = datetime.max if minutes > 0 else datetime.min
        return boundary.replace(tzinfo=value.tzinfo)


def _overlaps(first_start, first_end, second_start, second_end):
    return first_start < second_end and first_end > second_start


def _local_datetime(value):
    parsed = datetime.fromisoformat(value)
    return (
        parsed.astimezone(SINGAPORE).replace(tzinfo=None)
        if parsed.tzinfo
        else parsed
    )


def availability_for(venue, bookings, requested_start=None, requested_end=None):
    """How free is this venue in the requested window?

    Venue Availability Service has already narrowed `bookings` to the ones
    overlapping the window and dropped Rejected ones, so only status matters
    here. Statuses disagree across the system ("Pending" in the live data,
    "Pending Review" from the service), so anything that is not Approved is
    treated as a pending request.
    """
    if venue.get("status") != "Available":
        return NOT_OPERATIONAL
    candidates = [b for b in bookings if b.get("venueId") == venue.get("id")]
    if requested_start is not None and requested_end is not None:
        event_start = _local_datetime(requested_start)
        event_end = _local_datetime(requested_end)
        wanted_start, wanted_end = _effective_window(venue, event_start, event_end)
        overlapping = []
        for booking in candidates:
            if not booking.get("requestedStartTime") or not booking.get(
                "requestedEndTime"
            ):
                # Compatibility with an already-windowed availability result.
                overlapping.append(booking)
                continue
            booking_start = _local_datetime(booking["requestedStartTime"])
            booking_end = _local_datetime(booking["requestedEndTime"])
            if booking.get("status") != "On Hold":
                booking_start, booking_end = _effective_window(
                    venue, booking_start, booking_end
                )
            if _overlaps(wanted_start, wanted_end, booking_start, booking_end):
                overlapping.append(booking)
    else:
        # Compatibility for callers that already supplied a narrowed window.
        overlapping = candidates
    if any(booking.get("status") == "On Hold" for booking in overlapping):
        return BOOKED
    if any(booking.get("status") == "Approved" for booking in overlapping):
        return BOOKED
    return PENDING if overlapping else AVAILABLE


def shortlist(venues, bookings, closures, requested_start=None, requested_end=None):
    """Venues a coordinator can still request, Available ones first."""
    event_start = _local_datetime(requested_start) if requested_start else None
    event_end = _local_datetime(requested_end) if requested_end else None

    def is_closed(venue):
        venue_closures = [
            closure for closure in closures if closure["venueId"] == venue.get("id")
        ]
        if event_start is None or event_end is None:
            return bool(venue_closures)
        wanted_start, wanted_end = _effective_window(venue, event_start, event_end)
        return any(
            _overlaps(
                wanted_start,
                wanted_end,
                _local_datetime(closure["startDateTime"]),
                _local_datetime(closure["endDateTime"]),
            )
            for closure in venue_closures
        )

    results = [
        {
            **venue,
            "availability": availability_for(
                venue, bookings, requested_start, requested_end
            ),
        }
        for venue in venues
        if not is_closed(venue)
    ]
    bookable = [venue for venue in results if venue["availability"] in SHOWN]
    return sorted(
        bookable, key=lambda v: (SHOWN.index(v["availability"]), v.get("name") or "")
    )


def validate_window(payload, start, end, padding_minutes=0):
    """Validate the full response, then retain half-open overlapping closures."""
    from app.closure_contract import timestamp, uuid_value

    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("bookings"), list)
        or not isinstance(payload.get("closures"), list)
    ):
        raise ValueError("Invalid availability window")
    window_start = _shift(
        datetime.fromisoformat(start).replace(tzinfo=SINGAPORE), -padding_minutes
    )
    window_end = _shift(
        datetime.fromisoformat(end).replace(tzinfo=SINGAPORE), padding_minutes
    )
    closures, seen = [], set()
    for closure in payload["closures"]:
        if not isinstance(closure, dict):
            raise ValueError("Invalid closure")
        closure_id = uuid_value(closure["closureId"])
        venue_id = uuid_value(closure["venueId"])
        closure_start = timestamp(closure["startDateTime"])
        closure_end = timestamp(closure["endDateTime"])
        reason = closure["reason"]
        if (
            closure_id in seen
            or closure_end <= closure_start
            or not isinstance(reason, str)
            or not reason.strip()
            or "\x00" in reason
        ):
            raise ValueError("Invalid closure")
        reason.encode("utf-8")
        seen.add(closure_id)
        if closure_start < window_end and closure_end > window_start:
            closures.append({**closure, "venueId": venue_id})
    return {"bookings": payload["bookings"], "closures": closures}
