"""Hermetic read harness; SQLite tests predicates, not PostgreSQL behavior."""

from datetime import datetime
from tests.unit.availability_db import AvailabilityDB, sql_value


class ClosureReadDB(AvailabilityDB):
    def __init__(self, rows=(), bookings=()):
        super().__init__(bookings=bookings)
        for column in ("closure_id", "reason"):
            self.db.execute(f'ALTER TABLE "VenueClosure" ADD COLUMN {column} TEXT')
        for row in rows:
            self.db.execute(
                'INSERT INTO "VenueClosure" ('
                + ",".join(row)
                + ") VALUES ("
                + ",".join("?" for _ in row)
                + ")",
                [sql_value(value) for value in row.values()],
            )
        self.db.commit()

    @staticmethod
    def decode(row):
        result = AvailabilityDB.decode(row)
        if result is not None:
            for key in ("start_date_time", "end_date_time"):
                if result.get(key) is not None:
                    result[key] = datetime.fromisoformat(result[key])
        return result
