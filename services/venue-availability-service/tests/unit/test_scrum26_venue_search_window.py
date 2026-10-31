"""
SCRUM-26: Venue Search and Filtering

User Story
----------
As an Event Coordinator, I want to search and filter potential venues by event
requirements, so that I can shortlist venues that meet my specific event
requirements.

Acceptance Criteria
-------------------
AC1: Event Coordinator must be able to input the following criteria: Date and
     time (required), Expected attendance (required), Location (optional),
     Minimum capacity (optional), Accessibility requirements (optional),
     Supported layout (optional), and Required facilities (optional).
AC2: Given the Event Coordinator submits a search without the mandatory fields,
     when they click the search button, the system displays a message informing
     the user to input the required fields.
AC3: Given the Event Coordinator provides all required fields, when they click
     search, then the system must return a list of venues matching all active
     criteria within 3 seconds.
AC4: The search results must display the following for each matching venue:
     name, location, capacity, accessibility, supported layouts, available
     facilities, and availability status for the requested date/time.
AC5: Given no venues match the selected criteria, when the search completes,
     then the system must display a message informing the user that no venues
     are available.
AC6: The Event Coordinator must be able to clear all search and filter criteria
     with a single button click, resetting the form to its initial empty state.

Real
----
- GET /venue-bookings/window: every venue's bookings and active holds in a time
  window (at most 42 days), naive Singapore times, the status filter, the
  Python overlap re-check and failing closed on unreadable rows.
- Assertions are on the bookings returned and the status.

Doubled
-------
- psycopg2.connect: Stub (`setup`/`client` fixtures) - fresh MagicMock
  connection; the cursor returns canned VenueBooking / VenueClosure rows (or
  raises); executed SQL, parameters and locks are inspected.

Not proven
----------
- That the SQL, locks and constraints behave the same on real PostgreSQL (->
  tests/integration/, throwaway postgres:17.6).
- AC1's catalogue criteria are covered by Venue Service; AC5's empty-state
  message and AC6's clear-all action are frontend responsibilities.
"""
from datetime import datetime

from app.calendar import SINGAPORE

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


def test_ac3_window_returns_every_venues_bookings_in_one_call(setup):
    """
    Summary: The search gets every venue's bookings for the requested time in one call.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (cursor returns bookings of two venues)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = [
        booking_row(),
        booking_row(
            booking_id="00000000-0000-0000-0000-00000000000d",
            venue_id=OTHER_VENUE_ID,
            status="Pending Review",
        ),
    ]

    # Act (When)
    response = client.get(f"/venue-bookings/window?{WINDOW}")

    # Assert (Then)
    assert response.status_code == 200
    assert [(b["venueId"], b["status"]) for b in response.json["bookings"]] == [
        (VENUE_ID, "Approved"),
        (OTHER_VENUE_ID, "Pending Review"),
    ]
    query, params = cursor.execute.call_args.args
    assert "venue_id = %s" not in query
    assert params == [
        datetime(2026, 11, 10, 12, 0, tzinfo=SINGAPORE),
        datetime(2026, 11, 10, 9, 0, tzinfo=SINGAPORE),
    ]


def test_ac3_window_answers_composite_without_identity_headers(setup):
    """
    Summary: The search composite can read the window without browser identity headers.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (cursor returns no rows)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = []

    # Act (When)
    response = client.get(f"/venue-bookings/window?{WINDOW}")

    # Assert (Then)
    assert response.status_code == 200


def test_ac4_window_returns_naive_singapore_times(setup):
    """
    Summary: Times are returned as Singapore local times, matching the stored bookings.
    AC4: The search results must display the following for each matching venue:
        name, location, capacity, accessibility, supported layouts, available
        facilities, and availability status for the requested date/time.
    Double: Stub (cursor returns bookings)
    """
    client, cursor = setup
    cursor.fetchall.return_value = [booking_row()]

    booking = client.get(f"/venue-bookings/window?{WINDOW}").json["bookings"][0]

    assert booking["requestedStartTime"] == "2026-11-10T09:00:00"
    assert "+08:00" not in booking["requestedEndTime"]


def test_ac4_window_returns_active_hold_as_on_hold(setup):
    """
    Summary: An active hold is returned as an On Hold interval.
    AC4: The search results must display the following for each matching venue:
        name, location, capacity, accessibility, supported layouts, available
        facilities, and availability status for the requested date/time.
    Double: Stub (cursor returns a hold)
    """
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
            "hold_expires_at": datetime(2090, 1, 1),
            "requested_by": "00000000-0000-0000-0000-00000000000c",
            "reviewed_by": None,
        }
    ]

    hold = client.get(f"/venue-bookings/window?{WINDOW}").json["bookings"][0]

    assert hold["status"] == "On Hold"
    assert hold["eventId"] is None
    assert hold["venueId"] == VENUE_ID


def test_ac4_window_never_returns_rejected_cancelled_or_expired(setup):
    """
    Summary: Rejected, cancelled and expired bookings never make a venue look taken.
    AC4: The search results must display the following for each matching venue:
        name, location, capacity, accessibility, supported layouts, available
        facilities, and availability status for the requested date/time.
    Double: Stub (cursor; SQL inspected)
    """
    client, cursor = setup
    cursor.fetchall.return_value = []

    client.get(f"/venue-bookings/window?{WINDOW}")

    query, _ = cursor.execute.call_args.args
    assert "NOT IN ('Rejected', 'Cancelled', 'Expired')" in query


def test_ac3_window_with_offset_input_reads_singapore_time(setup):
    """
    Summary: A window given with a time zone is read in Singapore time.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (cursor; parameters inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = []

    # Act (When)
    response = client.get(
        "/venue-bookings/window"
        "?dateFrom=2026-11-10T09:00:00%2B08:00&dateTo=2026-11-10T12:00:00%2B08:00"
    )

    # Assert (Then)
    assert response.status_code == 200
    _, params = cursor.execute.call_args.args
    assert params == [
        datetime(2026, 11, 10, 12, 0, tzinfo=SINGAPORE),
        datetime(2026, 11, 10, 9, 0, tzinfo=SINGAPORE),
    ]


def test_ac3_window_filters_out_booking_outside_the_window(setup):
    """
    Summary: A booking outside the window is filtered out.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (cursor returns an outside row)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = [
        booking_row(
            requested_start_time=datetime(2026, 11, 10, 12, 0),
            requested_end_time=datetime(2026, 11, 10, 14, 0),
        )
    ]

    # Act + Assert (When / Then)
    # End-exclusive: a booking starting exactly when the window ends is free.
    assert client.get(f"/venue-bookings/window?{WINDOW}").json["bookings"] == []


def test_ac4_window_with_unreadable_row_returns_503(setup):
    """
    Summary: An unreadable booking fails the read rather than showing a taken venue as free.
    AC4: The search results must display the following for each matching venue:
        name, location, capacity, accessibility, supported layouts, available
        facilities, and availability status for the requested date/time.
    Double: Stub (cursor returns a malformed row)
    """
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
    ids=["empty", "datefrom_2026_11_10t09_00_00", "dateto_2026_11_10t12_00_00", "datefrom_not_a_date_dateto_2026_11_10t12_00_00", "datefrom_2026_11_10_dateto_2026_11_11", "datefrom_2026_11_10t12_00_00_dateto_2026_11_10t0", "datefrom_2026_11_10t09_00_00_dateto_2026_11_10t0", "datefrom_2026_01_01t00_00_00_dateto_2026_03_01t0", "datefrom_2026_11_10t09_00_00_datefrom_2026_11_11"],
)
def test_ac2_window_with_unusable_range_returns_400(setup, query):
    """
    Summary: A window the service cannot read is refused before any query.
    AC2: Given the Event Coordinator submits a search without the mandatory
        fields, when they click the search button, the system displays a
        message informing the user to input the required fields.
    Double: Mock (cursor not executed)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act + Assert (When / Then)
    assert client.get(f"/venue-bookings/window?{query}").status_code == 400
    cursor.execute.assert_not_called()


def test_ac3_window_of_exactly_42_days_is_allowed(setup):
    """
    Summary: A window of exactly 42 days is accepted.
    AC3: (boundary: window = 42 days)
    Double: Stub (cursor returns no rows)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = []

    # Act (When)
    response = client.get(
        "/venue-bookings/window?dateFrom=2026-01-01T00:00:00&dateTo=2026-02-12T00:00:00"
    )

    # Assert (Then)
    assert response.status_code == 200


def test_ac3_window_offers_no_write_method(setup):
    """
    Summary: The window is read-only.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: None
    """
    client, _ = setup

    for method in (client.post, client.patch, client.put, client.delete):
        assert method("/venue-bookings/window").status_code == 405


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_support_window_when_database_url_missing_returns_503(setup):
    """
    Summary: The window read reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured service answers 503
    Double: None
    """
    client, cursor = setup
    client.application.config["DATABASE_URL"] = None

    response = client.get(f"/venue-bookings/window?{WINDOW}")

    assert response.status_code == 503
    cursor.execute.assert_not_called()
