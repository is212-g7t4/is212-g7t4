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

Real
----
- The calendar read's SQL predicate itself, run against in-memory rows: which
  statuses are included, the half-open window and that invalid candidates
  survive for the Python check.
- Assertions are on the rows the SQL returns.

Doubled
-------
- PostgreSQL: Fake - an in-memory sqlite3 database runs the real read predicate
  (placeholders and schema qualification adapted), so NULL/AND/OR semantics are
  exercised but not Postgres types.

Not proven
----------
- That the overlap SQL, locks and constraints behave the same on real
  PostgreSQL (-> tests/integration/, throwaway postgres:17.6, and the opt-in
  tests/live/test_calendar.py).
- AC2 and AC4 presentation/access behaviour is covered by
  `test_scrum25_venue_availability_calendar.py`; this module isolates AC1/AC3
  SQL overlap semantics.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime

import pytest
from tests.unit.factories import VENUE_ID, booking_row

from app.models import COLUMNS, CalendarDataError, list_bookings


class ReadConnection:
    def __init__(self, rows):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.create_function("now", 0, lambda: "2026-10-01T00:00:00+08:00")
        self.db.execute(
            'CREATE TABLE "VenueBooking" ('
            + ",".join(f"{c.strip()} TEXT" for c in COLUMNS.split(","))
            + ", hold_expires_at TEXT)"
        )
        for row in rows:
            self.db.execute(
                'INSERT INTO "VenueBooking" ('
                + COLUMNS
                + ") VALUES ("
                + ",".join("?" for _ in COLUMNS.split(","))
                + ")",
                [
                    v.isoformat() if isinstance(v, datetime) else v
                    for v in (row.get(c.strip()) for c in COLUMNS.split(","))
                ],
            )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def close(self):
        self.db.close()

    @contextmanager
    def cursor(self, **kwargs):
        yield self

    def execute(self, sql, params):
        assert sql.lstrip().startswith("SELECT")
        self.result = self.db.execute(
            sql.replace("public.", "").replace("%s", "?"),
            [v.isoformat() if isinstance(v, datetime) else v for v in params],
        )

    def fetchall(self):
        rows = [dict(r) for r in self.result.fetchall()]
        for row in rows:
            for key in ("requested_start_time", "requested_end_time"):
                if row[key] is not None:
                    row[key] = datetime.fromisoformat(row[key])
        return rows


def read(monkeypatch, rows):
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *a, **k: ReadConnection(rows)
    )
    return list_bookings("test", VENUE_ID, datetime(2026, 10, 1), datetime(2026, 10, 2))


@pytest.mark.parametrize(
    "status,count",
    [
        ("Approved", 1),
        ("Pending", 1),
        ("Pending Review", 1),
        ("Rejected", 0),
        ("Cancelled", 0),
    ],
    ids=["approved", "pending", "pending_review", "rejected", "cancelled"],
)
def test_ac3_calendar_sql_includes_only_showable_statuses(monkeypatch, status, count):
    """
    Summary: The calendar query returns approved and pending bookings, not rejected or cancelled ones.
    AC3: Given a venue is unavailable, then the calendar must visually block
        out that specific time slot and disable it from being selected.
    Double: Fake (in-memory sqlite3 database)
    """
    # Arrange (Given): monkeypatch, status, count, from fixtures

    # Act + Assert (When / Then)
    assert len(read(monkeypatch, [booking_row(status=status)])) == count


@pytest.mark.parametrize(
    "start,end,count",
    [
        (datetime(2026, 9, 30, 23), datetime(2026, 10, 1), 0),
        (datetime(2026, 10, 2), datetime(2026, 10, 2, 1), 0),
        (datetime(2026, 9, 30), datetime(2026, 10, 3), 1),
        (datetime(2026, 10, 1, 23), datetime(2026, 10, 2, 1), 1),
    ],
    ids=["datetime_2026_9_30_23_datetime_2026_10_1_0", "datetime_2026_10_2_datetime_2026_10_2_1_0", "datetime_2026_9_30_datetime_2026_10_3_1", "datetime_2026_10_1_23_datetime_2026_10_2_1_1"],
)
def test_ac1_calendar_sql_uses_half_open_window(monkeypatch, start, end, count):
    """
    Summary: The query includes overlapping bookings and excludes ones only touching the range.
    AC1: (boundary: touching and overlapping intervals)
    Double: Fake (in-memory sqlite3 database)
    """
    # Arrange (Given): monkeypatch, start, end, count, from fixtures

    # Act + Assert (When / Then)
    assert (
        len(
            read(
                monkeypatch,
                [booking_row(requested_start_time=start, requested_end_time=end)],
            )
        )
        == count
    )


@pytest.mark.parametrize(
    "change",
    [
        {"requested_start_time": None},
        {"requested_end_time": None},
        {"status": None},
        {"status": "Surprise"},
        {"venue_id": None},
        {"event_id": None},
        {
            "requested_start_time": datetime(2025, 1, 2),
            "requested_end_time": datetime(2025, 1, 1),
        },
    ],
    ids=["requested_start_time_none", "requested_end_time_none", "status_none", "status_surprise", "venue_id_none", "event_id_none", "requested_start_time_datetime_2025_1_2_requested"],
)
def test_ac3_calendar_sql_keeps_invalid_candidates(monkeypatch, change):
    """
    Summary: Malformed rows are kept by the query so the read can fail closed.
    AC3: Given a venue is unavailable, then the calendar must visually block
        out that specific time slot and disable it from being selected.
    Double: Fake (in-memory sqlite3 database)
    """
    # Arrange (Given): monkeypatch, change, from fixtures

    # Act + Assert (When / Then)
    with pytest.raises(CalendarDataError):
        read(monkeypatch, [booking_row(**change)])


def test_ac1_calendar_sql_returns_only_the_venue_asked_for(monkeypatch):
    """
    Summary: Another venue's bookings are never returned.
    AC1: Given an internal user (Event Coordinator, Venue Staff, or Technical
        Support Staff) accesses the calendar, then the system must display a
        schedule showing dates, times, and current venue statuses.
    Double: Fake (in-memory sqlite3 database)
    """
    # Arrange (Given): monkeypatch, from fixtures

    # Act + Assert (When / Then)
    assert (
        read(
            monkeypatch,
            [booking_row(venue_id="00000000-0000-0000-0000-000000000002", status=None)],
        )
        == []
    )


def test_ac3_calendar_sql_ignores_malformed_row_of_excluded_status(monkeypatch):
    """
    Summary: A malformed row that is rejected or cancelled is ignored.
    AC3: Given a venue is unavailable, then the calendar must visually block
        out that specific time slot and disable it from being selected.
    Double: Fake (in-memory sqlite3 database)
    """
    # Arrange (Given): monkeypatch, from fixtures

    # Act + Assert (When / Then)
    assert (
        read(monkeypatch, [booking_row(status="Cancelled", requested_start_time=None)])
        == []
    )
