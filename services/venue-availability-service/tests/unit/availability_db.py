"""# Test scope and acceptance mapping — SCRUM-171 integration

- **Test infrastructure (no direct acceptance case):** SQLite executes existing SCRUM-30 availability predicates and inserts with fixed time. New nullable closure snapshot columns and advisory-lock adaptation keep those tests compatible.
- **Limit:** SQLite does not establish PostgreSQL lock ordering, rollback or SCRUM-171 AC5; use the isolated PostgreSQL harness.

## Case/group traceability

The named test functions/cases below implement the groups above; their existing
names and assertions specify the scenario. No group is credited with all five ACs.

## Existing test contract and detailed cases

Hermetic SQL write harness: actual predicates/inserts, not PostgreSQL locking.

Adapt only schema qualifiers, placeholders, FOR UPDATE and timestamp transport.
All timestamps are normalized to UTC; now() is fixed for expiry boundaries.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from app.calendar import SINGAPORE
from app.models import COLUMNS
from tests.unit.factories import VENUE_ID

NOW = datetime(2026, 10, 1, 10, tzinfo=SINGAPORE)


def sql_value(value):
    if isinstance(value, datetime):
        value = value.replace(tzinfo=SINGAPORE) if value.tzinfo is None else value
        return value.astimezone(timezone.utc).isoformat()
    return value


class AvailabilityDB:
    def __init__(self, bookings=(), closures=()):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.create_function("now", 0, lambda: sql_value(NOW))
        self.statements = []
        self.db.execute('CREATE TABLE "Venue" (venue_id TEXT)')
        self.db.execute('INSERT INTO "Venue" VALUES (?)', [VENUE_ID])
        self.db.execute(
            'CREATE TABLE "VenueBooking" ('
            + ",".join(
                f"{c.strip()} {'INTEGER' if c.strip() == 'required_capacity' else 'TEXT'}"
                for c in (COLUMNS + ", hold_expires_at").split(",")
            )
            + ")"
        )
        self.db.execute(
            'CREATE TABLE "VenueClosure" '
            "(venue_id TEXT, start_date_time TEXT, end_date_time TEXT)"
        )
        for row in bookings:
            self.db.execute(
                'INSERT INTO "VenueBooking" ('
                + ",".join(row)
                + ") VALUES ("
                + ",".join("?" for _ in row)
                + ")",
                [sql_value(v) for v in row.values()],
            )
        for row in closures:
            self.db.execute(
                'INSERT INTO "VenueClosure" VALUES (?,?,?)', [sql_value(v) for v in row]
            )
        self.db.commit()

    def __enter__(self):
        self.db.__enter__()
        return self

    def __exit__(self, *args):
        return self.db.__exit__(*args)

    def close(self):
        # The fixture owns lifetime so persisted rows can be inspected afterward.
        pass

    @contextmanager
    def cursor(self, **kwargs):
        yield self

    def execute(self, sql, params=()):
        self.statements.append(sql)
        if "pg_advisory_xact_lock" in sql:
            return
        self.result = self.db.execute(
            sql.replace("public.", "").replace("%s", "?").replace(" FOR UPDATE", ""),
            [sql_value(v) for v in params],
        )

    @staticmethod
    def decode(row):
        if row is None:
            return None
        result = dict(row)
        for key in ("requested_start_time", "requested_end_time", "hold_expires_at"):
            if result.get(key) is not None:
                result[key] = datetime.fromisoformat(result[key])
        return result

    def fetchone(self):
        return self.decode(self.result.fetchone())

    def fetchall(self):
        return [self.decode(row) for row in self.result.fetchall()]

    def count(self):
        return self.db.execute('SELECT COUNT(*) FROM "VenueBooking"').fetchone()[0]
