from contextlib import closing
from uuid import uuid4

import psycopg2
from psycopg2.extras import RealDictCursor

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


def list_bookings(database_url, venue_id=None, date_from=None, date_to=None):
    """Calendar read. Rejected bookings are excluded; Pending Review and
    Approved are both returned — only Approved should be treated as blocking
    by the caller (see docs/supabase-setup.md)."""
    conditions = ["status <> 'Rejected'"]
    params = []
    if venue_id:
        conditions.append("venue_id = %s")
        params.append(venue_id)
    if date_to:
        conditions.append("requested_start_time < %s")
        params.append(date_to)
    if date_from:
        conditions.append("requested_end_time > %s")
        params.append(date_from)
    where_clause = f"WHERE {' AND '.join(conditions)}"
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {COLUMNS} FROM public."VenueBooking"
                    {where_clause}
                    ORDER BY requested_start_time ASC, booking_id ASC""",
                params,
            )
            return [serialize(row) for row in cursor.fetchall()]


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
