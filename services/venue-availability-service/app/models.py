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
    "status, requested_by, reviewed_by"
)


class BookingNotFoundError(Exception):
    pass


class BookingConflictError(Exception):
    pass


def serialize(row):
    return {
        "id": str(row["booking_id"]),
        "eventId": str(row["event_id"]),
        "venueId": str(row["venue_id"]),
        "requestedStartTime": row["requested_start_time"].isoformat(),
        "requestedEndTime": row["requested_end_time"].isoformat(),
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


class CalendarDataError(Exception):
    """Cannot safely infer availability from the stored records."""


def validate_calendar_row(row):
    from datetime import datetime
    from uuid import UUID

    try:
        for field in ("booking_id", "event_id", "venue_id"):
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
        if row["status"] not in {"Approved", "Pending", "Pending Review"}:
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
    # Start-inclusive, end-exclusive overlap check; only Approved bookings block.
    query = """SELECT 1 FROM public."VenueBooking"
               WHERE venue_id = %s AND status = 'Approved'
                 AND requested_start_time < %s AND requested_end_time > %s"""
    params = [venue_id, end, start]
    if exclude_booking_id:
        query += " AND booking_id <> %s"
        params.append(exclude_booking_id)
    cursor.execute(query + " LIMIT 1", params)
    return cursor.fetchone() is not None


def create_booking(database_url, event_id, venue_id, start, end, requested_by):
    booking_id = str(uuid4())
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            # Lock this venue's existing rows so a concurrent request can't
            # also pass the conflict check before either commits.
            cursor.execute(
                """SELECT booking_id FROM public."VenueBooking"
                   WHERE venue_id = %s FOR UPDATE""",
                [venue_id],
            )
            if _has_conflict(cursor, venue_id, start, end):
                raise BookingConflictError
            cursor.execute(
                f"""INSERT INTO public."VenueBooking"
                    (booking_id, event_id, venue_id, requested_start_time,
                     requested_end_time, status, requested_by)
                    VALUES (%s, %s, %s, %s, %s, 'Pending Review', %s)
                    RETURNING {COLUMNS}""",
                [booking_id, event_id, venue_id, start, end, requested_by],
            )
            saved = cursor.fetchone()
    return serialize(saved)


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
            if status == "Approved":
                # Re-check — another booking may have been approved since this one was requested.
                cursor.execute(
                    """SELECT booking_id FROM public."VenueBooking"
                       WHERE venue_id = %s FOR UPDATE""",
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
    booking would show a taken venue as free. Rejected and Cancelled bookings
    never block, so they are excluded; the caller decides what the remaining
    statuses mean.
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
                    ORDER BY requested_start_time ASC, booking_id ASC""",
                [date_to, date_from],
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
