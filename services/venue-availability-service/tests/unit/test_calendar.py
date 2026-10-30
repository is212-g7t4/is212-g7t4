"""
SCRUM-25: Venue Availability Calendar

User Story
----------
As an Event Coordinator, I want to view a calendar showing venue availability
across different dates and times, so that I can easily identify open slots to
request for my clients.

Acceptance Criteria
-------------------
AC1: Given an internal user (Event Coordinator, Venue Staff, or Technical
     Support Staff) accesses the calendar, then the system must display a
     schedule showing dates, times, and current venue statuses.
AC2: The system must allow internal users (Event Coordinator, Venue Staff, or
     Technical Support Staff) to toggle the calendar interface between day,
     week, and month views.
AC3: Given a venue is unavailable, then the calendar must visually block out
     that specific time slot and disable it from being selected.
AC4: Given an external user (Event Organiser or Attendee) attempts to access
     the calendar, then the system must deny access and display a permission
     error.

SCRUM-8: User Authentication and Authorization

User Story
----------
As a system user, I want to securely access the system, so that I can use the
information and functionality available to me.

Acceptance Criteria
-------------------
AC1: Given a system user has not been successfully authenticated, when they
     attempt to access protected information or functionality, then access is
     denied.
AC2: Given a system user successfully authenticates, when they access protected
     information or functionality, then their access is evaluated according to
     their role and relationship to the relevant event.
AC3: Given a system user's authentication attempt is unsuccessful, when the
     authentication attempt is completed, then they remain unable to access
     protected information or functionality.

Real
----
- GET /venue-bookings (the calendar read): identity and the internal-role
  check, range validation (at most 42 days), Singapore-time binding, the
  half-open overlap, which statuses block, malformed rows failing closed, and
  CORS on the read.
- Assertions are on the status, the slots returned and the SQL parameters.

Doubled
-------
- psycopg2.connect: Stub (`setup`/`client` fixtures) - fresh MagicMock
  connection; the cursor returns canned VenueBooking / VenueClosure rows (or
  raises); executed SQL, parameters and locks are inspected.

Not proven
----------
- That the overlap SQL, locks and constraints behave the same on real
  PostgreSQL (-> tests/integration/, throwaway postgres:17.6, and the opt-in
  tests/live/test_calendar.py).
- Day/week/month views and the visual blocking (AC2, AC3 UI half) (-> frontend
  InspectionCalendar.test.tsx and e2e venues-calendar.spec.ts).
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import psycopg2
import pytest
from tests.unit.factories import USER_ID, VENUE_ID, booking_row, bearer

from app import create_app
from app.calendar import SINGAPORE, parse_boundary
from app.models import CalendarDataError, validate_calendar_row

QUERY = dict(venueId=VENUE_ID, dateFrom="2026-10-01T00:00", dateTo="2026-10-02T00:00")
HEADERS = bearer(USER_ID, "Event Coordinator")


@pytest.fixture
def calendar(monkeypatch):
    monkeypatch.setattr("app.list_window_closures", lambda *args: [])
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: connection)
    app = create_app(dict(TESTING=True, DATABASE_URL="test"))
    return app, app.test_client(), cursor


@pytest.mark.parametrize(
    "headers,code",
    [
        ({}, 401),
        ({"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Venue Staff"}, 401),
        ({"Authorization": "Bearer not-a-jwt"}, 401),
        (bearer(USER_ID, "Attendee"), 403),
        (bearer(USER_ID, "Event Organiser"), 403),
        (bearer(USER_ID, "Administrator"), 403),
    ],
    ids=["no_token", "dev_headers", "bad_token", "attendee", "event_organiser", "administrator"],
)
def test_calendar_without_internal_identity_is_refused(calendar, headers, code):
    """
    Summary: Anonymous callers, retired developer headers, bad tokens and external roles cannot open the calendar.
    AC4: Given an external user (Event Organiser or Attendee) attempts to
        access the calendar, then the system must deny access and display a
        permission error.
    SCRUM-8 AC1: Given a system user has not been successfully authenticated,
        when they attempt to access protected information or functionality,
        then access is denied.
    Double: Mock (cursor not executed)
    """
    # Arrange (Given)
    _, client, cursor = calendar

    # Act + Assert (When / Then)
    assert (
        client.get("/venue-bookings", query_string=QUERY, headers=headers).status_code
        == code
    )
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    "role",
    [
        "Event Coordinator",
        "Event Coordinator Lead",
        "Venue Staff",
        "Technical Support",
        "Technical Support Staff",
    ],
    ids=["event_coordinator", "event_coordinator_lead", "venue_staff", "technical_support", "technical_support_staff"],
)
def test_calendar_when_internal_role_returns_200(calendar, role):
    """
    Summary: Coordinators, the Lead, Venue Staff and Technical Support can open the calendar.
    AC1: Given an internal user (Event Coordinator, Venue Staff, or Technical
        Support Staff) accesses the calendar, then the system must display a
        schedule showing dates, times, and current venue statuses.
    Double: Stub (cursor returns no rows)
    """
    # Arrange (Given)
    _, client, _ = calendar

    # Act + Assert (When / Then)
    assert (
        client.get(
            "/venue-bookings",
            query_string=QUERY,
            headers=bearer(USER_ID, role),
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "change",
    [
        {"venueId": None},
        {"venueId": "bad"},
        {"dateFrom": None},
        {"dateTo": None},
        {"dateFrom": ""},
        {"dateFrom": "invalid"},
        {"dateFrom": "2026-10-01"},
        {"dateFrom": "2026-10-01 00:00"},
        {"dateTo": "2026-10-01T00:00"},
        {"dateTo": "2026-09-30T00:00"},
        {"dateTo": "2026-11-13T00:00"},
    ],
    ids=["venueid_none", "venueid_bad", "datefrom_none", "dateto_none", "datefrom", "datefrom_invalid", "datefrom_2026_10_01", "datefrom_2026_10_01_00_00", "dateto_2026_10_01t00_00", "dateto_2026_09_30t00_00", "dateto_2026_11_13t00_00"],
)
def test_calendar_with_invalid_venue_or_range_returns_400(calendar, change):
    """
    Summary: A calendar read needs a valid venue and a valid date range of at most 42 days.
    AC1: Given an internal user (Event Coordinator, Venue Staff, or Technical
        Support Staff) accesses the calendar, then the system must display a
        schedule showing dates, times, and current venue statuses.
    Double: Mock (cursor not executed)
    """
    # Arrange (Given)
    _, client, cursor = calendar
    query = {k: v for k, v in (QUERY | change).items() if v is not None}

    # Act + Assert (When / Then)
    assert (
        client.get("/venue-bookings", query_string=query, headers=HEADERS).status_code
        == 400
    )
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-09-30T16:00Z", "2026-10-01T16:00Z"),
        ("2026-10-01T00:00+08:00", "2026-10-02T00:00+08:00"),
        ("2026-09-30T12:00-04:00", "2026-10-01T12:00-04:00"),
    ],
    ids=["utc", "singapore", "new_york"],
)
def test_calendar_with_offset_range_binds_singapore_time(calendar, start, end):
    """
    Summary: A range given in any time zone is read in Singapore time.
    AC1: Given an internal user (Event Coordinator, Venue Staff, or Technical
        Support Staff) accesses the calendar, then the system must display a
        schedule showing dates, times, and current venue statuses.
    Double: Stub (cursor; parameters inspected)
    """
    # Arrange (Given)
    _, client, cursor = calendar

    # Act (When)
    response = client.get(
        "/venue-bookings",
        query_string=QUERY | dict(dateFrom=start, dateTo=end),
        headers=HEADERS,
    )

    # Assert (Then)
    assert response.status_code == 200
    assert cursor.execute.call_args.args[1] == [
        VENUE_ID,
        datetime(2026, 10, 2, tzinfo=SINGAPORE),
        datetime(2026, 10, 1, tzinfo=SINGAPORE),
    ]


@pytest.mark.parametrize("days", [1, 7, 31, 42], ids=["one_day", "one_week", "one_month", "six_weeks"])
def test_calendar_accepts_day_week_month_and_six_week_ranges(calendar, days):
    """
    Summary: Day, week, month and six-week ranges can be read.
    AC2: The system must allow internal users (Event Coordinator, Venue Staff,
        or Technical Support Staff) to toggle the calendar interface between
        day, week, and month views.
    Double: Stub (cursor returns no rows)
    """
    _, client, _ = calendar
    end = (datetime(2026, 10, 1) + timedelta(days=days)).isoformat()
    assert (
        client.get(
            "/venue-bookings", query_string=QUERY | dict(dateTo=end), headers=HEADERS
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "status,blocks", [("Approved", True), ("Pending", False), ("Pending Review", False)],
    ids=["approved", "pending", "pending_review"],
)
def test_calendar_marks_only_approved_bookings_as_blocking(calendar, status, blocks):
    """
    Summary: Only approved bookings block a slot; pending ones are shown but not blocking.
    AC3: Given a venue is unavailable, then the calendar must visually block
        out that specific time slot and disable it from being selected.
    Double: Stub (cursor returns a booking with the status)
    """
    # Arrange (Given)
    _, client, cursor = calendar
    cursor.fetchall.return_value = [booking_row(status=status)]

    # Act (When)
    response = client.get("/venue-bookings", query_string=QUERY, headers=HEADERS)

    # Assert (Then)
    assert response.status_code == 200
    booking = response.json["bookings"][0]
    assert booking["blocksSelection"] is blocks
    assert booking["requestedStartTime"] == "2026-10-01T09:00:00+08:00"
    assert booking["requestedEndTime"] == "2026-10-01T12:00:00+08:00"


@pytest.mark.parametrize("status", ["Rejected", "Cancelled"], ids=["rejected", "cancelled"])
def test_calendar_hides_rejected_and_cancelled_bookings(calendar, status):
    """
    Summary: Rejected and cancelled bookings are not shown.
    AC3: Given a venue is unavailable, then the calendar must visually block
        out that specific time slot and disable it from being selected.
    Double: Stub (cursor returns the row)
    """
    # Arrange (Given)
    _, client, cursor = calendar
    cursor.fetchall.return_value = [booking_row(status=status)]

    # Act + Assert (When / Then)
    assert client.get("/venue-bookings", query_string=QUERY, headers=HEADERS).json == {
        "bookings": [], "closures": []
    }


@pytest.mark.parametrize(
    "start,end,included",
    [
        ("2026-09-30T23:00", "2026-10-01T00:00", False),
        ("2026-10-02T00:00", "2026-10-02T01:00", False),
        ("2026-09-30T23:00", "2026-10-01T00:01", True),
        ("2026-10-01T23:59", "2026-10-02T01:00", True),
        ("2026-09-30T00:00", "2026-10-03T00:00", True),
    ],
    ids=["2026_09_30t23_00_2026_10_01t00_00_false", "2026_10_02t00_00_2026_10_02t01_00_false", "2026_09_30t23_00_2026_10_01t00_01_true", "2026_10_01t23_59_2026_10_02t01_00_true", "2026_09_30t00_00_2026_10_03t00_00_true"],
)
def test_calendar_includes_bookings_by_half_open_overlap(calendar, start, end, included):
    """
    Summary: A booking appears only if it really overlaps the range; touching edges do not count.
    AC1: (boundary: touching and overlapping intervals)
    Double: Stub (cursor returns the booking)
    """
    # Arrange (Given)
    _, client, cursor = calendar
    cursor.fetchall.return_value = [
        booking_row(
            requested_start_time=datetime.fromisoformat(start),
            requested_end_time=datetime.fromisoformat(end),
        )
    ]

    # Act (When)
    response = client.get("/venue-bookings", query_string=QUERY, headers=HEADERS)

    # Assert (Then)
    assert response.status_code == 200
    assert bool(response.json["bookings"]) is included


@pytest.mark.parametrize(
    "change",
    [
        {"status": None},
        {"status": "Unknown"},
        {"status": "approved"},
        {"requested_start_time": None},
        {"requested_end_time": None},
        {"requested_start_time": "bad"},
        {"requested_end_time": datetime(2026, 10, 1, 9)},
        {"requested_end_time": datetime(2026, 9, 1)},
        {"event_id": None},
        {"booking_id": "bad"},
        {"venue_id": None},
    ],
    ids=["status_none", "status_unknown", "status_approved", "requested_start_time_none", "requested_end_time_none", "requested_start_time_bad", "requested_end_time_datetime_2026_10_1_9", "requested_end_time_datetime_2026_9_1", "event_id_none", "booking_id_bad", "venue_id_none"],
)
def test_calendar_with_malformed_row_returns_503(calendar, change):
    """
    Summary: A malformed booking row fails the read instead of showing the slot as free.
    AC3: Given a venue is unavailable, then the calendar must visually block
        out that specific time slot and disable it from being selected.
    Double: Stub (cursor returns a malformed row)
    """
    # Arrange (Given)
    _, client, cursor = calendar
    cursor.fetchall.return_value = [booking_row(), booking_row(**change)]

    # Act (When)
    response = client.get("/venue-bookings", query_string=QUERY, headers=HEADERS)

    # Assert (Then)
    assert response.status_code == 503
    assert "bookings" not in response.json


def test_calendar_query_keeps_invalid_rows_for_checking(calendar):
    """
    Summary: The query keeps malformed rows so they cannot be silently dropped.
    AC3: Given a venue is unavailable, then the calendar must visually block
        out that specific time slot and disable it from being selected.
    Double: Stub (cursor; SQL inspected)
    """
    # Arrange (Given)
    _, client, cursor = calendar
    client.get("/venue-bookings", query_string=QUERY, headers=HEADERS)
    sql, params = cursor.execute.call_args.args

    # Act (When)
    normalized = " ".join(sql.split())

    # Assert (Then)
    assert "venue_id = %s" in normalized
    assert "requested_start_time < %s AND requested_end_time > %s" in normalized
    for condition in [
        "requested_start_time IS NULL",
        "requested_end_time IS NULL",
        "requested_end_time <= requested_start_time",
        "status IS NULL",
        "venue_id IS NULL",
    ]:
        assert condition in normalized
    assert params == [
        VENUE_ID,
        datetime(2026, 10, 2, tzinfo=SINGAPORE),
        datetime(2026, 10, 1, tzinfo=SINGAPORE),
    ]


@pytest.mark.parametrize("key", ["venueId", "dateFrom", "dateTo"], ids=["venue_id", "date_from", "date_to"])
def test_calendar_with_repeated_parameter_returns_400(calendar, key):
    """
    Summary: A parameter given twice is refused.
    AC1: Given an internal user (Event Coordinator, Venue Staff, or Technical
        Support Staff) accesses the calendar, then the system must display a
        schedule showing dates, times, and current venue statuses.
    Double: None
    """
    # Arrange (Given)
    _, client, cursor = calendar
    query = list(QUERY.items()) + [(key, QUERY[key])]

    # Act + Assert (When / Then)
    assert (
        client.get("/venue-bookings", query_string=query, headers=HEADERS).status_code
        == 400
    )
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("value", [None, "badTdate", "9999-12-31T23:59:59-12:00"], ids=["missing", "malformed", "overflowing"])
def test_calendar_boundary_parser_rejects_bad_values(value):
    """
    Summary: Missing, malformed or overflowing range boundaries are refused.
    AC1: Given an internal user (Event Coordinator, Venue Staff, or Technical
        Support Staff) accesses the calendar, then the system must display a
        schedule showing dates, times, and current venue statuses.
    Double: None
    """
    # Arrange (Given): value, from fixtures

    # Act + Assert (When / Then)
    assert parse_boundary(value) is None


@pytest.mark.parametrize(
    "change",
    [
        {"requested_end_time": datetime.max},
        {"requested_start_time": datetime.min},
    ],
    ids=["end", "start"],
)
def test_calendar_with_unusable_stored_time_returns_503(calendar, change):
    """
    Summary: A stored time that cannot be read in Singapore time fails the read.
    AC3: Given a venue is unavailable, then the calendar must visually block
        out that specific time slot and disable it from being selected.
    Double: Stub (cursor returns a bad time)
    """
    # Arrange (Given)
    _, client, cursor = calendar
    cursor.fetchall.return_value = [booking_row(**change)]

    # Act + Assert (When / Then)
    assert (
        client.get("/venue-bookings", query_string=QUERY, headers=HEADERS).status_code
        == 503
    )


def test_calendar_converts_stored_times_to_singapore(calendar):
    """
    Summary: Stored times with a zone are returned in Singapore time.
    AC1: Given an internal user (Event Coordinator, Venue Staff, or Technical
        Support Staff) accesses the calendar, then the system must display a
        schedule showing dates, times, and current venue statuses.
    Double: Stub (cursor returns aware times)
    """
    # Arrange (Given)
    _, client, cursor = calendar
    cursor.fetchall.return_value = [
        booking_row(
            requested_start_time=datetime(2026, 10, 1, 1, tzinfo=timezone.utc),
            requested_end_time=datetime(2026, 10, 1, 4, tzinfo=timezone.utc),
        )
    ]

    # Act (When)
    response = client.get("/venue-bookings", query_string=QUERY, headers=HEADERS)

    # Assert (Then)
    assert response.status_code == 200
    booking = response.json["bookings"][0]
    assert booking["requestedStartTime"] == "2026-10-01T09:00:00+08:00"
    assert booking["requestedEndTime"] == "2026-10-01T12:00:00+08:00"


def test_calendar_with_row_missing_fields_returns_503():
    """
    Summary: A row missing fields fails the read.
    AC3: Given a venue is unavailable, then the calendar must visually block
        out that specific time slot and disable it from being selected.
    Double: Stub (cursor returns an incomplete row)
    """
    # Act + Assert (When / Then)
    with pytest.raises(CalendarDataError):
        validate_calendar_row({})


@pytest.mark.parametrize(
    "role", ["event coordinator", " Venue Staff", "Venue Staff,Attendee"],
    ids=["lowercase", "leading_space", "two_roles"],
)
def test_calendar_role_check_needs_exact_role_name(calendar, role):
    """
    Summary: Role names must match exactly; look-alike roles are refused.
    AC4: Given an external user (Event Organiser or Attendee) attempts to
        access the calendar, then the system must deny access and display a
        permission error.
    Double: None
    """
    # Arrange (Given)
    _, client, cursor = calendar

    # Act + Assert (When / Then)
    assert (
        client.get(
            "/venue-bookings",
            query_string=QUERY,
            headers=bearer(USER_ID, role),
        ).status_code
        == 403
    )
    cursor.execute.assert_not_called()


def test_calendar_denial_still_carries_cors_headers(calendar):
    """
    Summary: A refused read still carries CORS headers so the browser shows the error.
    AC4: Given an external user (Event Organiser or Attendee) attempts to
        access the calendar, then the system must deny access and display a
        permission error.
    Double: None
    """
    # Arrange (Given)
    _, client, _ = calendar

    # Act (When)
    response = client.get(
        "/venue-bookings",
        query_string=QUERY,
        headers={"Origin": "http://localhost:5174"},
    )

    # Assert (Then)
    assert response.status_code == 401
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert response.headers["Vary"] == "Origin"


def test_calendar_with_empty_date_to_returns_400(calendar):
    """
    Summary: An empty end date is refused.
    AC1: Given an internal user (Event Coordinator, Venue Staff, or Technical
        Support Staff) accesses the calendar, then the system must display a
        schedule showing dates, times, and current venue statuses.
    Double: None
    """
    # Arrange (Given)
    _, client, _ = calendar

    # Act + Assert (When / Then)
    assert (
        client.get(
            "/venue-bookings", query_string=QUERY | {"dateTo": ""}, headers=HEADERS
        ).status_code
        == 400
    )


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_calendar_preflight_from_frontend_is_allowed(calendar):
    """
    Summary: The calendar can be read from the frontend in a browser.
    Supporting design check: CORS for the configured frontend origin
    Double: None
    """
    _, client, cursor = calendar
    response = client.options(
        "/venue-bookings",
        headers={
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert "GET" in response.headers["Access-Control-Allow-Methods"]
    assert "Authorization" in response.headers["Access-Control-Allow-Headers"]
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("origin", ["http://evil.example", "null"], ids=["other_site", "null_origin"])
def test_calendar_preflight_from_untrusted_origin_gets_no_grant(calendar, origin):
    """
    Summary: Other websites get no browser access.
    Supporting design check: CORS for the configured frontend origin
    Double: None
    """
    _, client, _ = calendar
    response = client.options("/venue-bookings", headers={"Origin": origin})
    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_allows_authorization_header_on_every_read(calendar):
    """
    Summary: Browser reads may send the sign-in token.
    Supporting design check: CORS for the configured frontend origin
    Double: None
    """
    _, client, _ = calendar
    response = client.options(
        f"/events/{VENUE_ID}/venue-bookings",
        headers={"Origin": "http://localhost:5174", "Access-Control-Request-Headers": "Authorization"},
    )
    assert response.status_code == 200
    assert "Authorization" in response.headers["Access-Control-Allow-Headers"]


def test_calendar_when_database_url_missing_returns_503(calendar):
    """
    Summary: The calendar reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured service answers 503
    Double: None
    """
    app, client, cursor = calendar
    app.config["DATABASE_URL"] = None
    assert (
        client.get("/venue-bookings", query_string=QUERY, headers=HEADERS).status_code
        == 503
    )
    cursor.execute.assert_not_called()


def test_calendar_when_database_fails_returns_503_without_details(calendar):
    """
    Summary: A database outage gives a 503 without internals.
    Supporting design check: database errors answer 503 with a safe message
    Double: Stub (cursor raises)
    """
    _, client, cursor = calendar
    cursor.execute.side_effect = psycopg2.OperationalError("secret detail")
    response = client.get("/venue-bookings", query_string=QUERY, headers=HEADERS)
    assert response.status_code == 503
    assert "secret" not in response.get_data(as_text=True)
