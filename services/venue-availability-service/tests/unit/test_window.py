"""SCRUM-26 — GET /venue-bookings/window, the venue search's bookings read.

The calendar read (GET /venue-bookings, SCRUM-25) answers for one venue at a
time. Venue search needs the opposite: every venue's bookings in one window,
in a single call, inside a 3-second budget. This endpoint is that read.

It is deliberately not behind CALENDAR_DEV_MODE or the X-Dev-* headers —
those simulate the browser's user switcher, and this caller is Venue Booking
Service, a composite. Database calls are mocked.
"""
from datetime import datetime

import pytest

VENUE_ID = "00000000-0000-0000-0000-0000000000f1"
OTHER_VENUE_ID = "00000000-0000-0000-0000-0000000000f2"
WINDOW = "dateFrom=2026-11-10T09:00:00&dateTo=2026-11-10T12:00:00"


def booking_row(**overrides):
    row = {
        "booking_id": "00000000-0000-0000-0000-00000000000a",
        "event_id": "00000000-0000-0000-0000-00000000000b",
        "venue_id": VENUE_ID,
        "requested_start_time": datetime(2026, 11, 10, 9, 0),
        "requested_end_time": datetime(2026, 11, 10, 12, 0),
        "required_capacity": 80,
        "venue_requirements": "Projector",
        "status": "Approved",
        "requested_by": "00000000-0000-0000-0000-00000000000c",
        "reviewed_by": None,
    }
    row.update(overrides)
    return row


def test_returns_every_venues_bookings_in_one_call(setup):
    """The point of the endpoint: no venueId, so the whole catalogue."""
    client, cursor = setup
    cursor.fetchall.return_value = [
        booking_row(),
        booking_row(
            booking_id="00000000-0000-0000-0000-00000000000d",
            venue_id=OTHER_VENUE_ID,
            status="Pending Review",
        ),
    ]

    response = client.get(f"/venue-bookings/window?{WINDOW}")

    assert response.status_code == 200
    assert [(b["venueId"], b["status"]) for b in response.json["bookings"]] == [
        (VENUE_ID, "Approved"),
        (OTHER_VENUE_ID, "Pending Review"),
    ]
    query, params = cursor.execute.call_args.args
    assert "venue_id = %s" not in query
    assert params == [
        datetime(2026, 11, 10, 12, 0),
        datetime(2026, 11, 10, 9, 0),
        datetime(2026, 11, 10, 12, 0),
        datetime(2026, 11, 10, 9, 0),
    ]


def test_needs_no_dev_mode_or_identity_headers(setup):
    """A composite is not a browser, so the user-switcher simulation is skipped."""
    client, cursor = setup
    cursor.fetchall.return_value = []

    response = client.get(f"/venue-bookings/window?{WINDOW}")

    assert response.status_code == 200


def test_database_unconfigured_returns_503_before_read(setup):
    client, cursor = setup
    client.application.config["DATABASE_URL"] = None

    response = client.get(f"/venue-bookings/window?{WINDOW}")

    assert response.status_code == 503
    cursor.execute.assert_not_called()


def test_times_are_naive_local(setup):
    """The search compares against naive VenueBooking timestamps."""
    client, cursor = setup
    cursor.fetchall.return_value = [booking_row()]

    booking = client.get(f"/venue-bookings/window?{WINDOW}").json["bookings"][0]

    assert booking["requestedStartTime"] == "2026-11-10T09:00:00"
    assert "+08:00" not in booking["requestedEndTime"]


def test_active_hold_is_returned_as_an_on_hold_interval(setup):
    client, cursor = setup
    cursor.fetchall.return_value = [
        {
            "booking_id": "00000000-0000-0000-0000-000000000010",
            "event_id": None,
            "venue_id": VENUE_ID,
            "requested_start_time": datetime(2026, 11, 10, 9, 0),
            "requested_end_time": datetime(2026, 11, 10, 12, 0),
            "required_capacity": None,
            "venue_requirements": "",
            "status": "On Hold",
            "requested_by": "00000000-0000-0000-0000-00000000000c",
            "reviewed_by": None,
        }
    ]

    hold = client.get(f"/venue-bookings/window?{WINDOW}").json["bookings"][0]

    assert hold["status"] == "On Hold"
    assert hold["eventId"] is None
    assert hold["venueId"] == VENUE_ID


def test_rejected_and_cancelled_never_block(setup):
    """Only statuses that can still take the venue are returned."""
    client, cursor = setup
    cursor.fetchall.return_value = []

    client.get(f"/venue-bookings/window?{WINDOW}")

    query, _ = cursor.execute.call_args.args
    assert "NOT IN ('Rejected', 'Cancelled')" in query


def test_offset_input_is_converted_to_singapore_local(setup):
    """Same time convention as the calendar read."""
    client, cursor = setup
    cursor.fetchall.return_value = []

    response = client.get(
        "/venue-bookings/window"
        "?dateFrom=2026-11-10T09:00:00%2B08:00&dateTo=2026-11-10T12:00:00%2B08:00"
    )

    assert response.status_code == 200
    _, params = cursor.execute.call_args.args
    assert params == [
        datetime(2026, 11, 10, 12, 0),
        datetime(2026, 11, 10, 9, 0),
        datetime(2026, 11, 10, 12, 0),
        datetime(2026, 11, 10, 9, 0),
    ]


def test_booking_outside_the_window_is_filtered_out(setup):
    """SQL keeps null/inverted candidates, so Python re-checks the overlap."""
    client, cursor = setup
    cursor.fetchall.return_value = [
        booking_row(
            requested_start_time=datetime(2026, 11, 10, 12, 0),
            requested_end_time=datetime(2026, 11, 10, 14, 0),
        )
    ]

    # End-exclusive: a booking starting exactly when the window ends is free.
    assert client.get(f"/venue-bookings/window?{WINDOW}").json["bookings"] == []


def test_unreadable_row_fails_the_read_rather_than_hiding_it(setup):
    """A dropped booking would show a taken venue as free — 503 instead."""
    client, cursor = setup
    cursor.fetchall.return_value = [booking_row(status="Nonsense")]

    response = client.get(f"/venue-bookings/window?{WINDOW}")

    assert response.status_code == 503
    assert response.json["message"] == "Unable to save or load venue bookings."


@pytest.mark.parametrize(
    "query",
    [
        "",
        "dateFrom=2026-11-10T09:00:00",
        "dateTo=2026-11-10T12:00:00",
        "dateFrom=not-a-date&dateTo=2026-11-10T12:00:00",
        "dateFrom=2026-11-10&dateTo=2026-11-11",  # date-only, no T
        "dateFrom=2026-11-10T12:00:00&dateTo=2026-11-10T09:00:00",  # reversed
        "dateFrom=2026-11-10T09:00:00&dateTo=2026-11-10T09:00:00",  # empty window
        "dateFrom=2026-01-01T00:00:00&dateTo=2026-03-01T00:00:00",  # over 42 days
        "dateFrom=2026-11-10T09:00:00&dateFrom=2026-11-11T09:00:00&dateTo=2026-11-10T12:00:00",
    ],
)
def test_unusable_window_returns_400_before_any_query(setup, query):
    """Failure: never answer a window the service cannot read."""
    client, cursor = setup

    assert client.get(f"/venue-bookings/window?{query}").status_code == 400
    cursor.execute.assert_not_called()


def test_exactly_42_days_is_allowed(setup):
    """Boundary: the cap is inclusive, matching the calendar's bound."""
    client, cursor = setup
    cursor.fetchall.return_value = []

    response = client.get(
        "/venue-bookings/window?dateFrom=2026-01-01T00:00:00&dateTo=2026-02-12T00:00:00"
    )

    assert response.status_code == 200


def test_window_read_is_read_only(setup):
    """It is a read: no write verb is offered."""
    client, _ = setup

    for method in (client.post, client.patch, client.put, client.delete):
        assert method("/venue-bookings/window").status_code == 405
