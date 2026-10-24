from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4

import psycopg2
import psycopg2.errors
from psycopg2.extras import RealDictCursor

# Only columns owned by Registration Service. The attendee's name, email and
# organisation live on User; the Attendee Registration composite adds them.
COLUMNS = "registration_id, event_id, attendee_id, registration_date, status, withdrawn_at"


class DuplicateRegistrationError(Exception):
    pass


class CapacityReachedError(Exception):
    pass


class RegistrationNotFoundError(Exception):
    pass


class RegistrationOwnershipError(Exception):
    pass


class RegistrationAlreadyWithdrawnError(Exception):
    pass


def serialize(row):
    return {
        "registration_id": str(row["registration_id"]),
        "event_id": str(row["event_id"]) if row.get("event_id") else None,
        "attendee_id": str(row["attendee_id"]) if row.get("attendee_id") else None,
        # TIMESTAMPTZ comes back aware, so the string carries its offset.
        "registration_date": row["registration_date"].isoformat() if row["registration_date"] else None,
        "status": row["status"] or "",
        "withdrawn_at": row["withdrawn_at"].isoformat() if row.get("withdrawn_at") else None,
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


def list_attendee_registrations(database_url, attendee_id):
    """Return every registration belonging to one attendee, newest first."""
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {COLUMNS} FROM public."Registration" WHERE attendee_id = %s
                    ORDER BY registration_date DESC NULLS LAST, registration_id ASC""",
                [attendee_id],
            )
            return [serialize(row) for row in cursor.fetchall()]


def create_registration(database_url, event_id, attendee_id, capacity):
    """Confirm one attendee for one event while serializing capacity checks.

    One row per (event, attendee), enforced by a UNIQUE constraint. Registering
    again after withdrawing reuses the withdrawn row.
    """
    registered_at = datetime.now(timezone.utc)
    try:
        with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
            with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
                # Concurrent registrations for one event must check and claim the
                # last place in sequence. The transaction-scoped lock is released
                # on commit.
                cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [event_id])
                cursor.execute(
                    """SELECT registration_id, status FROM public."Registration"
                       WHERE event_id = %s AND attendee_id = %s""",
                    [event_id, attendee_id],
                )
                existing = cursor.fetchone()
                if existing and existing["status"] != "Withdrawn":
                    raise DuplicateRegistrationError

                cursor.execute(
                    """SELECT COUNT(*) AS confirmed FROM public."Registration"
                       WHERE event_id = %s AND status = 'Confirmed'""",
                    [event_id],
                )
                if int(cursor.fetchone()["confirmed"]) >= capacity:
                    raise CapacityReachedError

                if existing:
                    cursor.execute(
                        f"""UPDATE public."Registration"
                            SET status = 'Confirmed', registration_date = %s, withdrawn_at = NULL
                            WHERE registration_id = %s
                            RETURNING {COLUMNS}""",
                        [registered_at, existing["registration_id"]],
                    )
                else:
                    cursor.execute(
                        f"""INSERT INTO public."Registration" ({COLUMNS})
                            VALUES (%s, %s, %s, %s, 'Confirmed', NULL)
                            RETURNING {COLUMNS}""",
                        [str(uuid4()), event_id, attendee_id, registered_at],
                    )
                return serialize(cursor.fetchone())
    except psycopg2.errors.UniqueViolation as error:
        # Safety net: the advisory lock should already prevent this.
        raise DuplicateRegistrationError from error


def withdraw_registration(database_url, registration_id, attendee_id):
    """Withdraw an attendee's own confirmed registration and timestamp it."""
    withdrawn_at = datetime.now(timezone.utc)
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f'''SELECT {COLUMNS} FROM public."Registration"
                    WHERE registration_id = %s FOR UPDATE''',
                [registration_id],
            )
            registration = cursor.fetchone()
            if not registration:
                raise RegistrationNotFoundError
            if str(registration["attendee_id"]) != attendee_id:
                raise RegistrationOwnershipError
            if registration["status"] == "Withdrawn":
                raise RegistrationAlreadyWithdrawnError
            cursor.execute(
                f'''UPDATE public."Registration"
                    SET status = 'Withdrawn', withdrawn_at = %s
                    WHERE registration_id = %s
                    RETURNING {COLUMNS}''',
                [withdrawn_at, registration_id],
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
