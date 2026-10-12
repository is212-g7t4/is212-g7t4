"""SQL owned exclusively by Venue Availability; no downstream calls."""

from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import RealDictCursor
from app.calendar import SINGAPORE

COLUMNS = "closure_id, venue_id, start_date_time, end_date_time, reason, created_by, created_at"


def serialize(row):
    return dict(
        closureId=str(row["closure_id"]),
        venueId=str(row["venue_id"]) if row["venue_id"] is not None else None,
        startDateTime=row["start_date_time"].astimezone(SINGAPORE).isoformat(),
        endDateTime=row["end_date_time"].astimezone(SINGAPORE).isoformat(),
        reason=row["reason"],
        createdBy=str(row["created_by"]) if row["created_by"] is not None else None,
        createdAt=(
            row["created_at"].astimezone(SINGAPORE).isoformat()
            if row["created_at"] is not None
            else None
        ),
    )


def create(dsn, data, staff):
    connection = psycopg2.connect(dsn)
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                'INSERT INTO public."VenueClosure" '
                "(venue_id, start_date_time, end_date_time, reason, created_by, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING " + COLUMNS,
                (
                    data["venueId"],
                    data["startDateTime"],
                    data["endDateTime"],
                    data["reason"],
                    staff,
                    datetime.now(timezone.utc),
                ),
            )
            result = serialize(cursor.fetchone())
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def read(dsn, closure_id=None, venue=None, limit=50, after=None):
    from app.closure_contract import encode_cursor

    connection = psycopg2.connect(dsn)
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            if closure_id is not None:
                cursor.execute(
                    "SELECT "
                    + COLUMNS
                    + ' FROM public."VenueClosure" WHERE closure_id = %s',
                    (closure_id,),
                )
                row = cursor.fetchone()
                return serialize(row) if row else None
            sql = (
                "SELECT " + COLUMNS + ' FROM public."VenueClosure" WHERE venue_id = %s'
            )
            params = [venue]
            if after is not None:
                sql += " AND (start_date_time, closure_id) > (%s, %s)"
                params.extend(after)
            sql += " ORDER BY start_date_time, closure_id LIMIT %s"
            params.append(limit + 1)
            cursor.execute(sql, tuple(params))
            rows = [serialize(row) for row in cursor.fetchall()]
            page = rows[:limit]
            return dict(
                closures=page,
                nextCursor=encode_cursor(page[-1]) if len(rows) > limit else None,
            )
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
