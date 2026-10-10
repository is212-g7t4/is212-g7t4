"""Execute the read predicate against an in-memory SQL engine, not mock results.

SQLite exercises NULL/AND/OR/comparison semantics, not Postgres driver/types.
Only placeholders and schema qualification are adapted; live smoke covers PG.
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
        self.db.execute(
            'CREATE TABLE "VenueBooking" ('
            + ",".join(f"{c.strip()} TEXT" for c in COLUMNS.split(","))
            + ")"
        )
        for row in rows:
            self.db.execute(
                'INSERT INTO "VenueBooking" VALUES ('
                + ",".join("?" for _ in COLUMNS.split(","))
                + ")",
                [v.isoformat() if isinstance(v, datetime) else v for v in row.values()],
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
)
def test_actual_sql_statuses(monkeypatch, status, count):
    assert len(read(monkeypatch, [booking_row(status=status)])) == count


@pytest.mark.parametrize(
    "start,end,count",
    [
        (datetime(2026, 9, 30, 23), datetime(2026, 10, 1), 0),
        (datetime(2026, 10, 2), datetime(2026, 10, 2, 1), 0),
        (datetime(2026, 9, 30), datetime(2026, 10, 3), 1),
        (datetime(2026, 10, 1, 23), datetime(2026, 10, 2, 1), 1),
    ],
)
def test_actual_sql_half_open(monkeypatch, start, end, count):
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
)
def test_actual_sql_invalid_candidates_survive_filter(monkeypatch, change):
    with pytest.raises(CalendarDataError):
        read(monkeypatch, [booking_row(**change)])


def test_actual_sql_other_venue_is_isolated(monkeypatch):
    assert (
        read(
            monkeypatch,
            [booking_row(venue_id="00000000-0000-0000-0000-000000000002", status=None)],
        )
        == []
    )


def test_actual_sql_excluded_malformed_row_is_ignored(monkeypatch):
    assert (
        read(monkeypatch, [booking_row(status="Cancelled", requested_start_time=None)])
        == []
    )
