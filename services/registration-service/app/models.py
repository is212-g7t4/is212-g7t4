from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4

import psycopg2
from psycopg2.extras import RealDictCursor

COLUMNS = "registration_id, event_id, attendee_id, registration_date, status, attendee_name, attendee_email, attendee_organization"


class DuplicateRegistrationError(Exception):
    pass


class CapacityReachedError(Exception):
    pass


def serialize(row):
    return {
        "registration_id": str(row["registration_id"]),
        "event_id": str(row["event_id"]) if row.get("event_id") else None,
        "attendee_id": str(row["attendee_id"]) if row.get("attendee_id") else None,
        "registration_date": row["registration_date"].isoformat() if row["registration_date"] else None,
        "status": row["status"] or "",
        "attendee_name": row["attendee_name"] or "",
        "attendee_email": row["attendee_email"] or "",
        "attendee_organization": row["attendee_organization"] or "",
    }


def list_registrations(database_url, event_id):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {COLUMNS} FROM public."Registration" WHERE event_id = %s
                    ORDER BY registration_date ASC NULLS LAST, registration_id ASC""",
                [event_id],
            )
            return [serialize(row) for row in cursor.fetchall()]


def create_registration(database_url, event_id, attendee_id, capacity, name, email, organization):
    """Insert a confirmed registration while serializing capacity checks per event."""
    registration_id = str(uuid4())
    registered_at = datetime.now(timezone.utc)
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            # Concurrent registrations for one event must check and claim the last
            # place in sequence. The transaction-scoped lock is released on commit.
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [event_id])
            cursor.execute(
                """SELECT 1 FROM public."Registration"
                   WHERE event_id = %s AND LOWER(attendee_email) = LOWER(%s)
                     AND status <> 'Withdrawn'
                   LIMIT 1""",
                [event_id, email],
            )
            if cursor.fetchone():
                raise DuplicateRegistrationError

            cursor.execute(
                """SELECT COUNT(*) AS confirmed FROM public."Registration"
                   WHERE event_id = %s AND status = 'Confirmed'""",
                [event_id],
            )
            if int(cursor.fetchone()["confirmed"]) >= capacity:
                raise CapacityReachedError

            cursor.execute(
                f"""INSERT INTO public."Registration" ({COLUMNS})
                    VALUES (%s, %s, %s, %s, 'Confirmed', %s, %s, %s)
                    RETURNING {COLUMNS}""",
                [registration_id, event_id, attendee_id, registered_at, name, email, organization],
            )
            return serialize(cursor.fetchone())


def count_registrations(database_url, event_ids):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """SELECT event_id,
                          COUNT(*) AS total,
                          COUNT(*) FILTER (WHERE status = 'Confirmed') AS confirmed
                   FROM public."Registration" WHERE event_id = ANY(%s::uuid[])
                   GROUP BY event_id""",
                [event_ids],
            )
            found = {
                str(row["event_id"]): {
                    "total": row["total"],
                    "confirmed": row["confirmed"],
                }
                for row in cursor.fetchall()
            }
    # Events with no registrations have no rows; report zeros so callers needn't guess.
    return {
        event_id: found.get(event_id, {"total": 0, "confirmed": 0})
        for event_id in event_ids
    }
