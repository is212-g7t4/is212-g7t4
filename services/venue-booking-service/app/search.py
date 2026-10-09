"""SCRUM-26 Venue Search and Filtering — the composite's own search logic.

Kept free of Flask and httpx so every rule here is unit-testable on plain
dicts. The route in `routes.py` does the HTTP work; this module decides what
is a valid search and what each venue's availability is.
"""
from datetime import datetime

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
    if start < (now or datetime.now()):
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


def availability_for(venue, bookings):
    """How free is this venue in the requested window?

    Venue Availability Service has already narrowed `bookings` to the ones
    overlapping the window and dropped Rejected ones, so only status matters
    here. Statuses disagree across the system ("Pending" in the live data,
    "Pending Review" from the service), so anything that is not Approved is
    treated as a pending request.
    """
    if venue.get("status") != "Available":
        return NOT_OPERATIONAL
    overlapping = [b for b in bookings if b.get("venueId") == venue.get("id")]
    if any(booking.get("status") == "On Hold" for booking in overlapping):
        return BOOKED
    if any(booking.get("status") == "Approved" for booking in overlapping):
        return BOOKED
    return PENDING if overlapping else AVAILABLE


def shortlist(venues, bookings):
    """Venues a coordinator can still request, Available ones first."""
    results = [
        {**venue, "availability": availability_for(venue, bookings)} for venue in venues
    ]
    bookable = [venue for venue in results if venue["availability"] in SHOWN]
    return sorted(
        bookable, key=lambda v: (SHOWN.index(v["availability"]), v.get("name") or "")
    )
