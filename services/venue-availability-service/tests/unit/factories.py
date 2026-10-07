"""Shared ids and row builders for the Venue Availability unit tests.

These used to live in test_bookings.py and were imported from there by the
other test modules. A test module should never import another test module, so
they live here instead.
"""

from datetime import datetime

EVENT_ID = "00000000-0000-0000-0000-0000000000e1"
VENUE_ID = "00000000-0000-0000-0000-0000000000f1"
USER_ID = "00000000-0000-0000-0000-000000000001"
BOOKING_ID = "00000000-0000-0000-0000-00000000000b"


def booking_row(**overrides):
    row = {
        "booking_id": BOOKING_ID,
        "event_id": EVENT_ID,
        "venue_id": VENUE_ID,
        "requested_start_time": datetime(2026, 10, 1, 9),
        "requested_end_time": datetime(2026, 10, 1, 12),
        "status": "Pending Review",
        "requested_by": USER_ID,
        "reviewed_by": None,
    }
    row.update(overrides)
    return row
