from contextlib import closing
from datetime import datetime
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
# A hold is an 'On Hold' VenueBooking row spanning held_at .. hold_expires_at.
# The aliases keep serialize_hold's shape (and the HTTP API) unchanged.
HOLD_COLUMNS = (
    "booking_id AS hold_id, venue_id, held_at AS created_at, "
    "hold_expires_at AS expires_at, held_by"
)
INACTIVE_STATUSES = "('Rejected', 'Cancelled', 'Expired')"


# The database stores TIMESTAMPTZ; the rest of this service works in naive
# Singapore local time. Convert at the boundary so neither side depends on the
# connection's session time zone.
def _aware(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=SINGAPORE)
    return value


def _local(value):
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(SINGAPORE).replace(tzinfo=None)
    return value


def _localize(row):
    return {key: _local(value) for key, value in row.items()}


class BookingNotFoundError(Exception):
    pass


class BookingConflictError(Exception):
    def __init__(self, conflict_types=()):
        super().__init__("Venue unavailable for the requested time.")
        self.conflict_types = list(conflict_types)


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
    result["blocksSelection"] = row["status"] in {"Approved", "On Hold"}
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
    from uuid import UUID

    try:
        fields = ("booking_id", "venue_id")
        if row.get("status") != "On Hold":
            fields += ("event_id",)
        elif not isinstance(row.get("hold_expires_at"), datetime):
            raise ValueError("Missing hold expiry")
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
                f"""SELECT {COLUMNS}, hold_expires_at FROM public."VenueBooking"
                    WHERE (venue_id = %s OR venue_id IS NULL)
                      AND (status IS NULL OR status NOT IN ('Rejected', 'Cancelled', 'Expired'))
                      AND (status IS NULL OR status <> 'On Hold' OR hold_expires_at IS NULL OR hold_expires_at > now())
                      AND ((requested_start_time < %s AND requested_end_time > %s)
                        OR requested_start_time IS NULL
                        OR requested_end_time IS NULL
                        OR requested_end_time <= requested_start_time)
                    ORDER BY requested_start_time ASC, booking_id ASC""",
                [venue_id, _aware(date_to), _aware(date_from)],
            )
            bookings = []
            for row in map(_localize, cursor.fetchall()):
                if row.get("status") in {"Rejected", "Cancelled", "Expired"}:
                    continue
                validate_calendar_row(row)
                if (
                    row["requested_start_time"] < date_to
                    and row["requested_end_time"] > date_from
                ):
                    bookings.append(serialize_calendar(row))
            return bookings


def _conflict_types(cursor, venue_id, start, end, exclude_booking_id=None):
    # Raw half-open intervals; no setup/turnaround buffer is applied.
    query = """SELECT DISTINCT CASE WHEN status = 'Approved' THEN 'APPROVED_BOOKING'
                        ELSE 'TENTATIVE_HOLD' END AS conflict_type
               FROM public."VenueBooking"
               WHERE venue_id = %s AND status IN ('Approved', 'On Hold')
                 AND (status = 'Approved' OR hold_expires_at > now())
                 AND requested_start_time < %s AND requested_end_time > %s"""
    params = [venue_id, _aware(end), _aware(start)]
    if exclude_booking_id:
        query += " AND booking_id <> %s"
        params.append(exclude_booking_id)
    query += """ UNION SELECT 'VENUE_CLOSURE' AS conflict_type
                 FROM public."VenueClosure"
                 WHERE venue_id = %s
                   AND start_date_time < %s AND end_date_time > %s"""
    params.extend([venue_id, _aware(end), _aware(start)])
    cursor.execute(query, params)
    return sorted(row["conflict_type"] for row in cursor.fetchall())


def _has_conflict(cursor, venue_id, start, end, exclude_booking_id=None):
    return bool(_conflict_types(cursor, venue_id, start, end, exclude_booking_id))


def create_booking(
    database_url,
    event_id,
    venue_id,
    start,
    end,
    required_capacity,
    venue_requirements,
    requested_by,
):
    booking_id = str(uuid4())
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            # A venue-row lock serializes bookings and holds, even when no
            # booking row exists yet.
            cursor.execute(
                'SELECT venue_id FROM public."Venue" WHERE venue_id = %s FOR UPDATE',
                [venue_id],
            )
            conflicts = _conflict_types(cursor, venue_id, start, end)
            if conflicts:
                raise BookingConflictError(conflicts)
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
                    _aware(start),
                    _aware(end),
                    required_capacity,
                    venue_requirements,
                    requested_by,
                ],
            )
            saved = _localize(cursor.fetchone())
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
            conflicts = _conflict_types(
                cursor, venue_id, start, end, exclude_booking_id=booking_id
            )
            if conflicts:
                raise BookingConflictError(conflicts)

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
            return [serialize(_localize(row)) for row in cursor.fetchall()]


def create_hold(database_url, venue_id, expires_at, held_by, held_for=None):
    hold_now = datetime.now(SINGAPORE)
    expires_at = _aware(expires_at)
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                'SELECT venue_id FROM public."Venue" WHERE venue_id = %s FOR UPDATE',
                [venue_id],
            )
            if not cursor.fetchone():
                raise HoldVenueNotFoundError
            # Bookings and other holds live in the same table, so one overlap
            # check covers both.
            cursor.execute(
                f"""SELECT 1 FROM public."VenueBooking"
                    WHERE venue_id = %s AND status NOT IN {INACTIVE_STATUSES}
                      AND requested_start_time < %s AND requested_end_time > %s
                    LIMIT 1""",
                [venue_id, expires_at, hold_now],
            )
            if cursor.fetchone():
                raise HoldConflictError
            # Not tied to an event yet; required_capacity is the minimum the
            # table allows, since a hold reserves the venue, not a headcount.
            cursor.execute(
                f"""INSERT INTO public."VenueBooking"
                    (venue_id, requested_start_time, requested_end_time,
                     required_capacity, status, held_by, held_at, hold_expires_at,
                     held_for)
                    VALUES (%s, %s, %s, 1, 'On Hold', %s, %s, %s, %s)
                    RETURNING {HOLD_COLUMNS}""",
                [
                    venue_id,
                    hold_now,
                    expires_at,
                    held_by,
                    hold_now,
                    expires_at,
                    held_for,
                ],
            )
            saved = _localize(cursor.fetchone())
    return serialize_hold(saved)


def list_active_holds(database_url):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {HOLD_COLUMNS} FROM public."VenueBooking"
                    WHERE status = 'On Hold' AND hold_expires_at > now()
                    ORDER BY hold_expires_at ASC, booking_id ASC"""
            )
            return [serialize_hold(_localize(row)) for row in cursor.fetchall()]


def list_hold_reminders(database_url, coordinator_id):
    """Active holds placed for this coordinator that expire within 3 days.

    Computed at read time from hold_expires_at: a hold that has expired, or
    whose status is no longer 'On Hold', is never returned.
    """
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {HOLD_COLUMNS} FROM public."VenueBooking"
                    WHERE status = 'On Hold' AND held_for = %s
                      AND hold_expires_at > now()
                      AND hold_expires_at <= now() + interval '3 days'
                    ORDER BY hold_expires_at ASC, booking_id ASC""",
                [coordinator_id],
            )
            return [serialize_hold(_localize(row)) for row in cursor.fetchall()]


def decide_booking(database_url, booking_id, reviewed_by, status):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {COLUMNS} FROM public."VenueBooking"
                    WHERE booking_id = %s FOR UPDATE""",
                [booking_id],
            )
            booking = cursor.fetchone()
            booking = _localize(booking) if booking else booking
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
                conflicts = _conflict_types(
                    cursor,
                    booking["venue_id"],
                    booking["requested_start_time"],
                    booking["requested_end_time"],
                    exclude_booking_id=booking_id,
                )
                if conflicts:
                    raise BookingConflictError(conflicts)
            cursor.execute(
                f"""UPDATE public."VenueBooking"
                    SET status = %s, reviewed_by = %s
                    WHERE booking_id = %s
                    RETURNING {COLUMNS}""",
                [status, reviewed_by, booking_id],
            )
            decided = _localize(cursor.fetchone())
    return serialize(decided)


def list_window_bookings(database_url, date_from, date_to):
    """SCRUM-26: every venue's bookings overlapping [date_from, date_to).

    The calendar read above answers for one venue at a time, which is what a
    calendar grid needs. Venue search asks the opposite question — "across the
    whole catalogue, what is taken in this window?" — and doing that as one
    call per venue would be N round trips inside a 3-second budget.

    Same conservative stance as the calendar: a row this service cannot read
    raises CalendarDataError rather than being dropped, because a dropped
    booking would show a taken venue as free. Active holds are 'On Hold' rows
    in the same table, so one read returns bookings and holds together.
    """
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {COLUMNS}, hold_expires_at FROM public."VenueBooking"
                    WHERE (status IS NULL OR status NOT IN ('Rejected', 'Cancelled', 'Expired'))
                      AND (status IS NULL OR status <> 'On Hold' OR hold_expires_at IS NULL OR hold_expires_at > now())
                      AND ((requested_start_time < %s AND requested_end_time > %s)
                        OR requested_start_time IS NULL
                        OR requested_end_time IS NULL
                        OR requested_end_time <= requested_start_time)
                    ORDER BY requested_start_time ASC, booking_id ASC""",
                [_aware(date_to), _aware(date_from)],
            )
            bookings = []
            for row in map(_localize, cursor.fetchall()):
                validate_calendar_row(row)
                if (
                    row["requested_start_time"] < date_to
                    and row["requested_end_time"] > date_from
                ):
                    bookings.append(serialize(row))
            return bookings


def list_window_closures(database_url, date_from, date_to, venue_id=None):
    """SCRUM-174: full original closure intervals, never paginated or clipped.

    Retain null/inverted candidates in SQL so malformed data fails the read
    instead of making a closed venue appear free. No booking/event is forged.
    """
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            scope = "(venue_id = %s OR venue_id IS NULL) AND " if venue_id else ""
            params = [venue_id] if venue_id else []
            params.extend([_aware(date_to), _aware(date_from)])
            cursor.execute(
                "SELECT closure_id, venue_id, start_date_time, end_date_time, reason "
                'FROM public."VenueClosure" WHERE '
                + scope
                + "((start_date_time < %s AND end_date_time > %s) "
                "OR start_date_time IS NULL OR end_date_time IS NULL "
                "OR end_date_time <= start_date_time) "
                "ORDER BY start_date_time, closure_id",
                params,
            )
            from uuid import UUID

            closures, seen = [], set()
            for row in cursor.fetchall():
                try:
                    closure_id = str(UUID(str(row["closure_id"])))
                    venue = str(UUID(str(row["venue_id"])))
                    start = _aware(row["start_date_time"]).astimezone(SINGAPORE)
                    end = _aware(row["end_date_time"]).astimezone(SINGAPORE)
                    reason = row["reason"]
                    if (
                        end <= start
                        or closure_id in seen
                        or not isinstance(reason, str)
                        or not reason.strip()
                        or "\x00" in reason
                    ):
                        raise ValueError("Invalid closure")
                    reason.encode("utf-8")
                except (
                    KeyError,
                    TypeError,
                    ValueError,
                    AttributeError,
                    OverflowError,
                ) as error:
                    raise CalendarDataError from error
                seen.add(closure_id)
                closures.append(
                    dict(
                        closureId=closure_id,
                        venueId=venue,
                        startDateTime=start.isoformat(),
                        endDateTime=end.isoformat(),
                        reason=reason,
                    )
                )
            return closures
