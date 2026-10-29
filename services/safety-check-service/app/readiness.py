"""SCRUM-149 AC1/AC2: are this event's arrangements ready for a safety check?

Ready means at least one approved venue booking and nothing still pending.
Rejected venue bookings (SCRUM-171) and rejected equipment requests (29 Oct
2026 dead-end fix) are final decisions the event no longer relies on, so they
are ignored rather than blocking for good.

A pure function over the two downstream responses, so the rule can be read and
tested without HTTP. Shared by `POST /safety-checks` and
`GET /safety-checks/readiness` so the UI's list and the submit check can never
disagree.

It **fails closed**: a status we don't recognise counts as outstanding. The
cost of being wrong the other way is an event reaching the Safety Officer with
an unapproved venue.
"""
from datetime import datetime

# A venue booking the event no longer relies on: withdrawn, lapsed, or
# retained rejected history. A separate live replacement still needs approval.
# ('On Hold' rows are never returned for an event, so they can't appear here.)
IGNORED_BOOKING_STATUSES = frozenset({"Cancelled", "Expired", "Rejected"})
APPROVED_BOOKING_STATUSES = frozenset({"Approved"})

# A request the event no longer relies on. 'Rejected' is a final decision
# (SCRUM-33) with no withdraw path, so blocking on it was a dead end; it is
# ignored, mirroring rejected venue bookings above.
IGNORED_REQUEST_STATUSES = frozenset({"Cancelled", "Rejected"})
# 'Reserved' is the Jira/db-structure.md wording for an allocated request; no
# endpoint sets it today, so this is harmless either way.
APPROVED_REQUEST_STATUSES = frozenset({"Approved", "Reserved"})

NO_VENUE_BOOKING = {
    "type": "venue",
    "id": None,
    "status": None,
    "label": "No venue booking",
    "reason": "No venue booking has been made for this event.",
}

VENUE_REASONS = {
    "Pending Review": "Waiting for Venue Staff approval.",
    "Pending": "Waiting for Venue Staff approval.",
}
EQUIPMENT_REASONS = {
    "Pending": "Waiting for Technical Support approval.",
}


def _unknown_reason(status):
    return f"Status '{status}' isn't recognised, so it can't be treated as approved."


def outstanding_arrangements(bookings, requests):
    """Arrangements standing between this event and its safety check (AC2).

    Empty means ready (AC1): at least one approved venue booking, and no venue
    booking or equipment request still pending. Rejected, cancelled or expired
    bookings and rejected or cancelled requests are skipped. Venue items come first, then equipment, each in
    the order its service returned them, so the UI's list is stable.
    """
    return [
        *_venue_items(bookings or []),
        *_equipment_items(requests or []),
    ]


def _venue_items(bookings):
    relevant = [
        booking
        for booking in bookings
        if booking.get("status") not in IGNORED_BOOKING_STATUSES
    ]
    if not relevant:
        # AC1 allows "no equipment requested" but says nothing about no venue;
        # an event with nowhere to happen isn't ready for a safety check.
        return [dict(NO_VENUE_BOOKING)]
    items = []
    for booking in relevant:
        status = booking.get("status")
        if status in APPROVED_BOOKING_STATUSES:
            continue
        items.append(
            {
                "type": "venue",
                "id": booking.get("id"),
                "status": status,
                "label": booking_label(booking),
                "reason": VENUE_REASONS.get(status) or _unknown_reason(status),
            }
        )
    return items


def _equipment_items(requests):
    items = []
    for item in requests:
        status = item.get("status")
        if status in APPROVED_REQUEST_STATUSES or status in IGNORED_REQUEST_STATUSES:
            continue
        items.append(
            {
                "type": "equipment",
                "id": item.get("id"),
                "status": status,
                "label": equipment_label(item),
                "reason": EQUIPMENT_REASONS.get(status) or _unknown_reason(status),
            }
        )
    return items


def booking_label(booking):
    """A booking named by what its own response carries.

    Deliberately no venue name: fetching one would mean calling Venue Service
    for a label. The UI already has venue names from `VenueBookingsPanel` and
    can enrich this client-side by `id`.
    """
    window = _window(
        booking.get("requestedStartTime"), booking.get("requestedEndTime")
    )
    capacity = booking.get("requiredCapacity")
    parts = ["Booking"]
    if window:
        parts.append(window)
    if isinstance(capacity, int):
        parts.append(f"({capacity} people)")
    return " ".join(parts)


def equipment_label(item):
    quantity = item.get("quantityRequested")
    if isinstance(quantity, int):
        return f"Equipment request × {quantity}"
    return "Equipment request"


def _window(start, end):
    """"12 Nov 2026 09:00–17:00", or the raw strings if they aren't parseable."""
    try:
        opens, closes = datetime.fromisoformat(start), datetime.fromisoformat(end)
    except (TypeError, ValueError):
        return " ".join(part for part in (start, end) if isinstance(part, str))
    if opens.date() == closes.date():
        return f"{opens.strftime('%-d %b %Y %H:%M')}–{closes.strftime('%H:%M')}"
    return (
        f"{opens.strftime('%-d %b %Y %H:%M')}–"
        f"{closes.strftime('%-d %b %Y %H:%M')}"
    )
