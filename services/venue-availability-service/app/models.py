from contextlib import closing
from uuid import uuid4

import psycopg2
from psycopg2.extras import RealDictCursor

from app.calendar import SINGAPORE

# Only columns owned by Venue Availability Service; no queries to other
# services' tables. This atomic owns both the booking records and the
# overlap/conflict computation over them (merged design — see AGENTS.md).
COLUMNS = (
    "booking_id, event_id, venue_id, requested_start_time, requested_end_time, "
    "required_capacity, venue_requirements, status, requested_by, reviewed_by"
)
HOLD_COLUMNS = "hold_id, venue_id, created_at, expires_at, held_by"


class BookingNotFoundError(Exception):
    pass


class BookingConflictError(Exception):
    pass


class BookingStateError(Exception):
    pass


class HoldConflictError(Exception):
    pass


class HoldVenueNotFoundError(Exception):
    pass


def serialize(row):
    return {
        "id": str(row["booking_id"]),
        "eventId": str(row["event_id"]) if row["event_id"] else None,
        "venueId": str(row["venue_id"]),
        "requestedStartTime": row["requested_start_time"].isoformat(),
        "requestedEndTime": row["requested_end_time"].isoformat(),
        "requiredCapacity": row["required_capacity"],
        "venueRequirements": row["venue_requirements"] or "",
        "status": row["status"],
        "requestedBy": str(row["requested_by"]) if row["requested_by"] else None,
        "reviewedBy": str(row["reviewed_by"]) if row["reviewed_by"] else None,
    }


def serialize_calendar(row):
    result = serialize(row)
    result["requestedStartTime"] = (
        row["requested_start_time"].replace(tzinfo=SINGAPORE).isoformat()
    )
    result["requestedEndTime"] = (
        row["requested_end_time"].replace(tzinfo=SINGAPORE).isoformat()
    )
    result["blocksSelection"] = row["status"] == "Approved"
    return result


def serialize_hold(row):
    return {
        "id": str(row["hold_id"]),
        "venueId": str(row["venue_id"]),
        "createdAt": row["created_at"].isoformat(),
        "expiresAt": row["expires_at"].isoformat(),
        "heldBy": str(row["held_by"]) if row["held_by"] else None,
    }


class CalendarDataError(Exception):
    """Cannot safely infer availability from the stored records."""


def validate_calendar_row(row):
    from datetime import datetime
    from uuid import UUID

    try:
        fields = ("booking_id", "venue_id")
        if row.get("status") != "On Hold":
            fields += ("event_id",)
        for field in fields:
            UUID(str(row[field]))
        start, end = row["requested_start_time"], row["requested_end_time"]
        if (
            not isinstance(start, datetime)
            or not isinstance(end, datetime)
            or start.tzinfo is not None
            or end.tzinfo is not None
            or end <= start
            or start in (datetime.min, datetime.max)
            or end in (datetime.min, datetime.max)
        ):
            raise ValueError("Invalid local interval")
        if row["status"] not in {"Approved", "Pending", "Pending Review", "On Hold"}:
            raise ValueError("Unknown status")
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise CalendarDataError from error


def list_bookings(database_url, venue_id, date_from, date_to):
    """Bounded calendar read, including invalid candidates so they fail closed.

    Null venue IDs cannot safely be assigned to any venue. Invalid intervals
    for this venue (or an unknown venue) fail the entire read even outside the
    window; otherwise malformed times could disappear in SQL comparisons.
    """
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {COLUMNS} FROM public."VenueBooking"
                    WHERE (venue_id = %s OR venue_id IS NULL)
                      AND (status IS NULL OR status NOT IN ('Rejected', 'Cancelled'))
                      AND ((requested_start_time < %s AND requested_end_time > %s)
                        OR requested_start_time IS NULL
                        OR requested_end_time IS NULL
                        OR requested_end_time <= requested_start_time)
                    ORDER BY requested_start_time ASC, booking_id ASC""",
                [venue_id, date_to, date_from],
            )
            bookings = []
            for row in cursor.fetchall():
                if row.get("status") in {"Rejected", "Cancelled"}:
                    continue
                validate_calendar_row(row)
                if (
                    row["requested_start_time"] < date_to
                    and row["requested_end_time"] > date_from
                ):
                    bookings.append(serialize_calendar(row))
            return bookings


def _has_conflict(cursor, venue_id, start, end, exclude_booking_id=None):
    # Start-inclusive, end-exclusive overlap check. Active holds are hard conflicts.
    query = """SELECT 1 FROM public."VenueBooking"
               WHERE venue_id = %s AND status = 'Approved'
                 AND requested_start_time < %s AND requested_end_time > %s"""
    params = [venue_id, end, start]
    if exclude_booking_id:
        query += " AND booking_id <> %s"
        params.append(exclude_booking_id)
    query = f"""{query}
        UNION ALL
        SELECT 1 FROM public."VenueHold"
        WHERE venue_id = %s AND created_at < %s AND expires_at > %s
        LIMIT 1"""
    params.extend([venue_id, end, start])
    cursor.execute(query, params)
    return cursor.fetchone() is not None


def create_booking(database_url, event_id, venue_id, start, end, required_capacity, venue_requirements, requested_by):
    booking_id = str(uuid4())
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            # A venue-row lock serializes bookings and holds, even when no
            # booking row exists yet.
            cursor.execute(
                'SELECT venue_id FROM public."Venue" WHERE venue_id = %s FOR UPDATE',
                [venue_id],
            )
            if _has_conflict(cursor, venue_id, start, end):
                raise BookingConflictError
            cursor.execute(
                f"""INSERT INTO public."VenueBooking"
                    (booking_id, event_id, venue_id, requested_start_time,
                     requested_end_time, required_capacity, venue_requirements,
                     status, requested_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'Pending Review', %s)
                    RETURNING {COLUMNS}""",
                [
                    booking_id,
                    event_id,
                    venue_id,
                    start,
                    end,
                    required_capacity,
                    venue_requirements,
                    requested_by,
                ],
            )
            saved = cursor.fetchone()
    return serialize(saved)


def update_booking(
    database_url,
    booking_id,
    event_id,
    venue_id,
    start,
    end,
    required_capacity,
    venue_requirements,
):
    """Update one booking and resubmit only that row for review."""
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {COLUMNS} FROM public."VenueBooking"
                    WHERE booking_id = %s AND event_id = %s FOR UPDATE""",
                [booking_id, event_id],
            )
            booking = cursor.fetchone()
            if not booking:
                raise BookingNotFoundError
            if booking["status"] == "Cancelled":
                raise BookingStateError

            cursor.execute(
                'SELECT venue_id FROM public."Venue" WHERE venue_id = %s FOR UPDATE',
                [venue_id],
            )
            if _has_conflict(
                cursor, venue_id, start, end, exclude_booking_id=booking_id
            ):
                raise BookingConflictError

            cursor.execute(
                f"""UPDATE public."VenueBooking"
                    SET venue_id = %s, requested_start_time = %s,
                        requested_end_time = %s, required_capacity = %s,
                        venue_requirements = %s, status = 'Pending Review',
                        reviewed_by = NULL
                    WHERE booking_id = %s AND event_id = %s
                    RETURNING {COLUMNS}""",
                [
                    venue_id,
                    start,
                    end,
                    required_capacity,
                    venue_requirements,
                    booking_id,
                    event_id,
                ],
            )
            saved = cursor.fetchone()
    return serialize(saved)


def cancel_booking(database_url, booking_id, event_id):
    """Retain one booking as Cancelled without touching sibling bookings."""
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {COLUMNS} FROM public."VenueBooking"
                    WHERE booking_id = %s AND event_id = %s FOR UPDATE""",
                [booking_id, event_id],
            )
            booking = cursor.fetchone()
            if not booking:
                raise BookingNotFoundError
            if booking["status"] == "Cancelled":
                return serialize(booking)

            cursor.execute(
                f"""UPDATE public."VenueBooking"
                    SET status = 'Cancelled'
                    WHERE booking_id = %s AND event_id = %s
                    RETURNING {COLUMNS}""",
                [booking_id, event_id],
            )
            cancelled = cursor.fetchone()
    return serialize(cancelled)


def list_event_bookings(database_url, event_id):
    """Return each independently managed booking linked to one event."""
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {COLUMNS} FROM public."VenueBooking"
                    WHERE event_id = %s
                    ORDER BY requested_start_time ASC, booking_id ASC""",
                [event_id],
            )
            return [serialize(row) for row in cursor.fetchall()]


def create_hold(database_url, venue_id, expires_at, held_by):
    from datetime import datetime

    hold_now = datetime.now(SINGAPORE).replace(tzinfo=None)
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                'SELECT venue_id FROM public."Venue" WHERE venue_id = %s FOR UPDATE',
                [venue_id],
            )
            if not cursor.fetchone():
                raise HoldVenueNotFoundError
            cursor.execute(
                """SELECT 1 FROM public."VenueBooking"
                   WHERE venue_id = %s AND status NOT IN ('Rejected', 'Cancelled')
                     AND requested_start_time < %s AND requested_end_time > %s
                   LIMIT 1""",
                [venue_id, expires_at, hold_now],
            )
            if cursor.fetchone():
                raise HoldConflictError
            cursor.execute(
                """SELECT 1 FROM public."VenueHold"
                   WHERE venue_id = %s AND created_at < %s AND expires_at > %s
                   LIMIT 1""",
                [venue_id, expires_at, hold_now],
            )
            if cursor.fetchone():
                raise HoldConflictError
            cursor.execute(
                f"""INSERT INTO public."VenueHold" (venue_id, expires_at, held_by)
                    VALUES (%s, %s, %s) RETURNING {HOLD_COLUMNS}""",
                [venue_id, expires_at, held_by],
            )
            saved = cursor.fetchone()
    return serialize_hold(saved)


def list_active_holds(database_url):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {HOLD_COLUMNS} FROM public."VenueHold"
                    WHERE expires_at > (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Singapore')
                    ORDER BY expires_at ASC, hold_id ASC"""
            )
            return [serialize_hold(row) for row in cursor.fetchall()]


def decide_booking(database_url, booking_id, reviewed_by, status):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {COLUMNS} FROM public."VenueBooking"
                    WHERE booking_id = %s FOR UPDATE""",
                [booking_id],
            )
            booking = cursor.fetchone()
            if not booking:
                raise BookingNotFoundError
            if booking["status"] == "Cancelled":
                raise BookingStateError
            if status == "Approved":
                # Re-check — another booking may have been approved since this one was requested.
                cursor.execute(
                    'SELECT venue_id FROM public."Venue" WHERE venue_id = %s FOR UPDATE',
                    [booking["venue_id"]],
                )
                if _has_conflict(
                    cursor,
                    booking["venue_id"],
                    booking["requested_start_time"],
                    booking["requested_end_time"],
                    exclude_booking_id=booking_id,
                ):
                    raise BookingConflictError
            cursor.execute(
                f"""UPDATE public."VenueBooking"
                    SET status = %s, reviewed_by = %s
                    WHERE booking_id = %s
                    RETURNING {COLUMNS}""",
                [status, reviewed_by, booking_id],
            )
            decided = cursor.fetchone()
    return serialize(decided)


def list_window_bookings(database_url, date_from, date_to):
    """SCRUM-26: every venue's bookings overlapping [date_from, date_to).

    The calendar read above answers for one venue at a time, which is what a
    calendar grid needs. Venue search asks the opposite question — "across the
    whole catalogue, what is taken in this window?" — and doing that as one
    call per venue would be N round trips inside a 3-second budget.

    Same conservative stance as the calendar: a row this service cannot read
    raises CalendarDataError rather than being dropped, because a dropped
    booking would show a taken venue as free. Active holds are unioned into
    this read so the caller needs no additional downstream call.
    """
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {COLUMNS} FROM public."VenueBooking"
                    WHERE (status IS NULL OR status NOT IN ('Rejected', 'Cancelled'))
                      AND ((requested_start_time < %s AND requested_end_time > %s)
                        OR requested_start_time IS NULL
                        OR requested_end_time IS NULL
                        OR requested_end_time <= requested_start_time)
                    UNION ALL
                    SELECT hold_id AS booking_id, NULL::uuid AS event_id,
                        venue_id, created_at AS requested_start_time,
                        expires_at AS requested_end_time,
                        NULL::integer AS required_capacity,
                        ''::text AS venue_requirements, 'On Hold' AS status,
                        held_by AS requested_by, NULL::uuid AS reviewed_by
                    FROM public."VenueHold"
                    WHERE created_at < %s AND expires_at > %s
                    ORDER BY requested_start_time ASC, booking_id ASC""",
                [date_to, date_from, date_to, date_from],
            )
            bookings = []
            for row in cursor.fetchall():
                validate_calendar_row(row)
                if (
                    row["requested_start_time"] < date_to
                    and row["requested_end_time"] > date_from
                ):
                    bookings.append(serialize(row))
            return bookings
