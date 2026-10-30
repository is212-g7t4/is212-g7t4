"""
SCRUM-174: View Dated Closures in Venue Search & Calendar

User Story
----------
As an Event Coordinator, I want venue search and the availability calendar to
reflect dated closures, so that I can identify usable venues and understand
when a closed venue becomes eligible again and do not attempt to book
unavailable venues for my event duration.

Acceptance Criteria
-------------------
AC1: Given an internal user views the availability calendar, any periods marked
     as closed must be visually indicated and clearly distinguished from
     regular event bookings or open slots.
AC2: Given a user views the details of a closed period on the calendar, the
     system must display the specific start/end dates, times, and the
     operational reason for the closure.
AC3: Given an Event Coordinator searches for available venues, if their
     specified date and time overlap (even partially) with a venue's recorded
     closure, that venue must be automatically excluded from the search
     results.
AC4: Given an Event Coordinator searches for venues outside of a recorded
     closure period, the venue must be shown with its standard operating
     conditions, capacity, and existing bookings.

Real
----
- The calendar and window reads with closures: each closure projected once with
  its period and reason, malformed or duplicate closures failing the whole
  read, holds by expiry, and the half-open SQL over the full interval (run on
  in-memory sqlite3 in the SQL tests).
- Assertions are on the slots returned and the status.

Doubled
-------
- psycopg2.connect: Stub (`setup`/`client` fixtures) - fresh MagicMock
  connection; the cursor returns canned VenueBooking / VenueClosure rows (or
  raises); executed SQL, parameters and locks are inspected.
- PostgreSQL (SQL tests): Fake - in-memory sqlite3 runs the real predicate.

Not proven
----------
- That the SQL, locks and constraints behave the same on real PostgreSQL (->
  tests/integration/, throwaway postgres:17.6).
- That closed periods are visually distinct and searched venues excluded (AC1,
  AC3 UI and search) (-> frontend InspectionCalendar and ClosureDetails tests,
  venue-booking-service search tests).
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock
import pytest
from app import create_app
from tests.unit.factories import bearer, signed_in

VENUE = "00000000-0000-0000-0000-000000000001"
CLOSURE = "00000000-0000-0000-0000-000000000002"
START = datetime(2026, 10, 1)
END = datetime(2026, 10, 2)


def row(**changes):
    value = dict(
        closure_id=CLOSURE,
        venue_id=VENUE,
        start_date_time=datetime(2026, 9, 30, 1, 0, 0, 123456, tzinfo=timezone.utc),
        end_date_time=datetime(2026, 10, 3, 2, tzinfo=timezone.utc),
        reason="Repair roof",
    )
    return value | changes


@pytest.mark.parametrize("path", ["/venue-bookings", "/venue-bookings/window"], ids=["calendar", "window"])
def test_reads_return_each_closure_once_with_period_and_reason(path, monkeypatch):
    """
    Summary: Each closure appears once, with its own period and reason.
    AC1: Given an internal user views the availability calendar, any periods
        marked as closed must be visually indicated and clearly distinguished
        from regular event bookings or open slots.
    AC2: Given a user views the details of a closed period on the calendar, the
        system must display the specific start/end dates, times, and the
        operational reason for the closure.
    Double: Stub (cursor returns closures)
    """
    # Arrange (Given)
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [[], [row()]]
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: connection)
    client = signed_in(create_app(
        {"TESTING": True, "DATABASE_URL": "unused"}
    ).test_client())

    # Act (When)
    response = client.get(
        path,
        query_string=dict(
            venueId=VENUE, dateFrom=START.isoformat(), dateTo=END.isoformat()
        ),
        headers=bearer(VENUE, "Event Coordinator"),
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json == {
        "bookings": [],
        "closures": [
            {
                "closureId": CLOSURE,
                "venueId": VENUE,
                "startDateTime": "2026-09-30T09:00:00.123456+08:00",
                "endDateTime": "2026-10-03T10:00:00+08:00",
                "reason": "Repair roof",
            }
        ],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"closure_id": None},
        {"closure_id": "bad"},
        {"venue_id": None},
        {"venue_id": "bad"},
        {"start_date_time": None},
        {"end_date_time": None},
        {"start_date_time": "bad"},
        {"end_date_time": datetime(2020, 1, 1)},
        {"reason": None},
        {"reason": " "},
        {"reason": "bad\x00"},
    ],
    ids=["closure_id_none", "closure_id_bad", "venue_id_none", "venue_id_bad", "start_date_time_none", "end_date_time_none", "start_date_time_bad", "end_date_time_datetime_2020_1_1", "reason_none", "reason", "reason_bad_x00"],
)
def test_reads_with_malformed_closure_return_503(change, monkeypatch):
    """
    Summary: A malformed closure fails the read rather than showing the venue as open.
    AC1: Given an internal user views the availability calendar, any periods
        marked as closed must be visually indicated and clearly distinguished
        from regular event bookings or open slots.
    Double: Stub (cursor returns a malformed closure)
    """
    # Arrange (Given)
    from app.models import list_window_closures, CalendarDataError

    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value.fetchall.return_value = [
        row(**change)
    ]
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: connection)

    # Act + Assert (When / Then)
    with pytest.raises(CalendarDataError):
        list_window_closures("unused", START, END)


def test_reads_with_duplicate_closure_ids_return_503(monkeypatch):
    """
    Summary: Duplicate closure records fail the read.
    AC1: Given an internal user views the availability calendar, any periods
        marked as closed must be visually indicated and clearly distinguished
        from regular event bookings or open slots.
    Double: Stub (cursor returns the same closure twice)
    """
    # Arrange (Given)
    from app.models import list_window_closures, CalendarDataError

    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value.fetchall.return_value = [
        row(),
        row(),
    ]
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: connection)

    # Act + Assert (When / Then)
    with pytest.raises(CalendarDataError):
        list_window_closures("unused", START, END)


@pytest.mark.parametrize("calendar", [True, False], ids=["calendar", "window"])
@pytest.mark.parametrize("expiry_delta,count", [(-1, 0), (0, 0), (1, 1)], ids=["expired", "expires_now", "active"])
def test_reads_with_expired_hold_show_slot_as_free(monkeypatch, calendar, expiry_delta, count):
    """
    Summary: A hold blocks the slot until its expiry, and not after.
    AC4: (boundary: expiry before, at and after now)
    Double: Stub (cursor returns a hold)
    """
    from datetime import timedelta
    from app.models import list_bookings, list_window_bookings
    from tests.unit.availability_db import AvailabilityDB, NOW
    from tests.unit.factories import booking_row, VENUE_ID

    hold = booking_row(
        status="On Hold",
        event_id=None,
        requested_start_time=NOW - timedelta(hours=1),
        requested_end_time=NOW + timedelta(hours=1),
    )
    hold["hold_expires_at"] = NOW + timedelta(microseconds=expiry_delta)
    db = AvailabilityDB(bookings=[hold])
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: db)
    try:
        start, end = (
            NOW.replace(tzinfo=None),
            (NOW + timedelta(hours=1)).replace(tzinfo=None),
        )
        result = (
            list_bookings("unused", VENUE_ID, start, end)
            if calendar
            else list_window_bookings("unused", start, end)
        )
        assert len(result) == count
        assert (
            db.db.execute('SELECT status FROM "VenueBooking"').fetchone()[0]
            == "On Hold"
        )
    finally:
        db.db.close()


@pytest.mark.parametrize("calendar", [True, False], ids=["calendar", "window"])
def test_reads_with_hold_missing_expiry_return_503(monkeypatch, calendar):
    """
    Summary: A hold with no expiry fails the read.
    AC4: Given an Event Coordinator searches for venues outside of a recorded
        closure period, the venue must be shown with its standard operating
        conditions, capacity, and existing bookings.
    Double: Stub (cursor returns a hold without expiry)
    """
    from app.models import list_bookings, list_window_bookings, CalendarDataError
    from tests.unit.availability_db import AvailabilityDB
    from tests.unit.factories import booking_row, VENUE_ID

    hold = booking_row(status="On Hold", event_id=None)
    db = AvailabilityDB(bookings=[hold])
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: db)
    try:
        with pytest.raises(CalendarDataError):
            if calendar:
                list_bookings("unused", VENUE_ID, START, END)
            else:
                list_window_bookings("unused", START, END)
    finally:
        db.db.close()


def test_calendar_with_active_hold_marks_slot_blocked():
    """
    Summary: An active hold is marked as blocking on the calendar.
    AC1: Given an internal user views the availability calendar, any periods
        marked as closed must be visually indicated and clearly distinguished
        from regular event bookings or open slots.
    Double: Stub (cursor returns an active hold)
    """
    # Arrange (Given)
    from app.models import serialize_calendar

    # Act (When)
    from tests.unit.factories import booking_row

    # Assert (Then)
    assert (
        serialize_calendar(booking_row(status="On Hold", event_id=None))[
            "blocksSelection"
        ]
        is True
    )


@pytest.mark.parametrize("calendar", [True, False], ids=["calendar", "window"])
@pytest.mark.parametrize(
    "start,end,count",
    [
        ("2026-10-01T00:00:00+08:00", "2026-10-02T00:00:00+08:00", 1),
        ("2026-10-01T09:00:00+08:00", "2026-10-01T10:00:00+08:00", 1),
        ("2026-09-30T23:00:00+08:00", "2026-10-01T01:00:00+08:00", 1),
        ("2026-10-01T23:00:00+08:00", "2026-10-02T01:00:00+08:00", 1),
        ("2026-09-29T00:00:00+08:00", "2026-10-03T00:00:00+08:00", 1),
        ("2026-09-30T00:00:00+08:00", "2026-10-01T00:00:00+08:00", 0),
        ("2026-10-02T00:00:00+08:00", "2026-10-03T00:00:00+08:00", 0),
        ("2026-10-01T15:59:59.999999Z", "2026-10-02T00:00:00Z", 1),
        ("2026-10-01T16:00:00Z", "2026-10-02T00:00:00Z", 0),
    ],
    ids=["2026_10_01t00_00_00_08_00_2026_10_02t00_00_00_08", "2026_10_01t09_00_00_08_00_2026_10_01t10_00_00_08", "2026_09_30t23_00_00_08_00_2026_10_01t01_00_00_08", "2026_10_01t23_00_00_08_00_2026_10_02t01_00_00_08", "2026_09_29t00_00_00_08_00_2026_10_03t00_00_00_08", "2026_09_30t00_00_00_08_00_2026_10_01t00_00_00_08", "2026_10_02t00_00_00_08_00_2026_10_03t00_00_00_08", "2026_10_01t15_59_59_999999z_2026_10_02t00_00_00z", "2026_10_01t16_00_00z_2026_10_02t00_00_00z_0"],
)
def test_closure_sql_uses_half_open_overlap_over_whole_closure(
    monkeypatch, calendar, start, end, count
):
    """
    Summary: A closure overlapping the range even partly is returned; one only touching it is not.
    AC3: (boundary: partial overlap, touching edges)
    Double: Fake (in-memory sqlite3 database)
    """
    from tests.unit.closure_read_db import ClosureReadDB
    from app.models import list_window_closures

    db = ClosureReadDB(
        [
            row(
                start_date_time=datetime.fromisoformat(start),
                end_date_time=datetime.fromisoformat(end),
            )
        ]
    )
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: db)
    try:
        result = list_window_closures("unused", START, END, VENUE if calendar else None)
        assert len(result) == count
        if result:
            assert datetime.fromisoformat(
                result[0]["startDateTime"]
            ) == datetime.fromisoformat(start)
            assert datetime.fromisoformat(
                result[0]["endDateTime"]
            ) == datetime.fromisoformat(end)
        assert all(sql.lstrip().startswith("SELECT") for sql in db.statements)
    finally:
        db.db.close()


@pytest.mark.parametrize("calendar", [True, False], ids=["calendar", "window"])
@pytest.mark.parametrize(
    "change",
    [
        {"venue_id": None},
        {"closure_id": None},
        {"reason": None},
        {"start_date_time": None},
        {"end_date_time": None},
        {
            "start_date_time": datetime(2020, 1, 2),
            "end_date_time": datetime(2020, 1, 1),
        },
    ],
    ids=["venue_id_none", "closure_id_none", "reason_none", "start_date_time_none", "end_date_time_none", "start_date_time_datetime_2020_1_2_end_date_time"],
)
def test_closure_sql_keeps_malformed_candidates_so_read_fails(monkeypatch, calendar, change):
    """
    Summary: Malformed closure rows are kept by the query so the read fails closed.
    AC1: Given an internal user views the availability calendar, any periods
        marked as closed must be visually indicated and clearly distinguished
        from regular event bookings or open slots.
    Double: Fake (in-memory sqlite3 database)
    """
    from tests.unit.closure_read_db import ClosureReadDB
    from app.models import list_window_closures, CalendarDataError

    db = ClosureReadDB([row(**change)])
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: db)
    try:
        with pytest.raises(CalendarDataError):
            list_window_closures("unused", START, END, VENUE if calendar else None)
    finally:
        db.db.close()


def test_closure_sql_isolates_venue_and_returns_whole_window(monkeypatch):
    """
    Summary: Calendar reads see only their venue's closures; the window read sees all, unpaginated.
    AC4: Given an Event Coordinator searches for venues outside of a recorded
        closure period, the venue must be shown with its standard operating
        conditions, capacity, and existing bookings.
    Double: Fake (in-memory sqlite3 database)
    """
    from tests.unit.closure_read_db import ClosureReadDB
    from app.models import list_window_closures
    from uuid import UUID

    other = "00000000-0000-0000-0000-000000000003"
    db = ClosureReadDB(
        [row(venue_id=other, closure_id=str(UUID(int=100 + i))) for i in range(105)]
    )
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: db)
    try:
        assert list_window_closures("unused", START, END, VENUE) == []
        assert len(list_window_closures("unused", START, END)) == 105
    finally:
        db.db.close()


@pytest.mark.parametrize(
    "role,code",
    [
        ("Event Coordinator", 200),
        ("Venue Staff", 200),
        ("Technical Support", 200),
        ("Technical Support Staff", 200),
        ("Event Organiser", 403),
        ("Attendee", 403),
        ("Administrator", 403),
    ],
    ids=["event_coordinator_200", "venue_staff_200", "technical_support_200", "technical_support_staff_200", "event_organiser_403", "attendee_403", "administrator_403"],
)
def test_calendar_with_closures_keeps_the_internal_role_rule(monkeypatch, role, code):
    """
    Summary: Closures do not change who can open the calendar.
    AC1: Given an internal user views the availability calendar, any periods
        marked as closed must be visually indicated and clearly distinguished
        from regular event bookings or open slots.
    Double: Stub (cursor returns closures)
    """
    from tests.unit.closure_read_db import ClosureReadDB

    db = ClosureReadDB([row()])
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: db)
    client = signed_in(create_app(
        {"TESTING": True, "DATABASE_URL": "unused"}
    ).test_client())
    try:
        response = client.get(
            "/venue-bookings",
            query_string=dict(
                venueId=VENUE, dateFrom=START.isoformat(), dateTo=END.isoformat()
            ),
            headers=bearer(VENUE, role),
        )
        assert response.status_code == code
        if code == 200:
            assert response.json["closures"][0]["closureId"] == CLOSURE
        else:
            assert db.statements == []
    finally:
        db.db.close()


@pytest.mark.parametrize("path", ["/venue-bookings", "/venue-bookings/window"], ids=["calendar", "window"])
def test_reads_with_malformed_closure_return_no_partial_data(monkeypatch, path):
    """
    Summary: A malformed closure aborts the whole read; no partial data is sent.
    AC1: Given an internal user views the availability calendar, any periods
        marked as closed must be visually indicated and clearly distinguished
        from regular event bookings or open slots.
    Double: Stub (cursor returns a malformed closure)
    """
    from tests.unit.closure_read_db import ClosureReadDB

    db = ClosureReadDB([row(reason=None)])
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: db)
    client = signed_in(create_app(
        {"TESTING": True, "DATABASE_URL": "unused"}
    ).test_client())
    try:
        response = client.get(
            path,
            query_string=dict(
                venueId=VENUE, dateFrom=START.isoformat(), dateTo=END.isoformat()
            ),
            headers=bearer(VENUE, "Event Coordinator"),
        )
        assert response.status_code == 503
        assert "bookings" not in response.json and "closures" not in response.json
    finally:
        db.db.close()


@pytest.mark.parametrize("path", ["/venue-bookings", "/venue-bookings/window"], ids=["calendar", "window"])
def test_reads_with_closures_keep_booking_fields_unchanged(monkeypatch, path):
    """
    Summary: Adding closures does not change how bookings are returned.
    AC4: Given an Event Coordinator searches for venues outside of a recorded
        closure period, the venue must be shown with its standard operating
        conditions, capacity, and existing bookings.
    Double: Stub (cursor returns bookings and closures)
    """
    from tests.unit.closure_read_db import ClosureReadDB
    from tests.unit.factories import booking_row

    db = ClosureReadDB([row()], [booking_row(venue_id=VENUE, status="Approved")])
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: db)
    client = signed_in(create_app(
        {"TESTING": True, "DATABASE_URL": "unused"}
    ).test_client())
    try:
        response = client.get(
            path,
            query_string=dict(
                venueId=VENUE, dateFrom=START.isoformat(), dateTo=END.isoformat()
            ),
            headers=bearer(VENUE, "Event Coordinator"),
        )
        assert response.status_code == 200
        assert len(response.json["bookings"]) == len(response.json["closures"]) == 1
        assert response.json["bookings"][0]["eventId"] is not None
        assert "eventId" not in response.json["closures"][0]
        assert response.json["bookings"][0]["status"] == "Approved"
        assert all(sql.lstrip().startswith("SELECT") for sql in db.statements)
    finally:
        db.db.close()
