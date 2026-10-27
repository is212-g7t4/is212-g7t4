from contextlib import closing
import os
from datetime import datetime, timedelta
from uuid import uuid4

import psycopg2
from psycopg2.extras import RealDictCursor, register_uuid, Json

from app.calendar import SINGAPORE

# Flask routes validate identifiers as ``uuid.UUID`` values before they reach
# this database boundary. Register Psycopg's standard adapter once so those
# validated values can be used consistently by every booking query.
register_uuid()

# Only columns owned by Venue Availability Service; no queries to other
# services' tables. This atomic owns both the booking records and the
# overlap/conflict computation over them (merged design — see AGENTS.md).
BASE_COLUMNS = (
    "booking_id, event_id, venue_id, requested_start_time, requested_end_time, "
    "required_capacity, venue_requirements, status, requested_by, reviewed_by, "
    "requested_at, reviewed_at, rejection_reason, "
)
COLUMNS = BASE_COLUMNS + "rejection_closure_id, rejection_closure_start, rejection_closure_end, rejection_closure_reason, rejected_at"
LEGACY_COLUMNS = BASE_COLUMNS + (
    "(to_jsonb(\"VenueBooking\")->>'rejection_closure_id')::uuid AS rejection_closure_id, "
    "(to_jsonb(\"VenueBooking\")->>'rejection_closure_start')::timestamptz AS rejection_closure_start, "
    "(to_jsonb(\"VenueBooking\")->>'rejection_closure_end')::timestamptz AS rejection_closure_end, "
    "to_jsonb(\"VenueBooking\")->>'rejection_closure_reason' AS rejection_closure_reason, "
    "(to_jsonb(\"VenueBooking\")->>'rejected_at')::timestamptz AS rejected_at"
)
FLAG_COLUMNS = f"{COLUMNS}, conflict_reason"


def booking_columns():
    return LEGACY_COLUMNS if os.getenv("VENUE_BOOKING_LEGACY_SCHEMA") == "true" else COLUMNS

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


def _shift(value, minutes):
    """Shift a datetime without letting a valid database integer overflow Python."""
    try:
        return value + timedelta(minutes=minutes)
    except OverflowError:
        boundary = datetime.max if minutes > 0 else datetime.min
        return boundary.replace(tzinfo=value.tzinfo)


class BookingNotFoundError(Exception):
    pass


class BookingConflictError(Exception):
    def __init__(self, conflict_types=()):
        super().__init__("Venue unavailable for the requested time.")
        self.conflict_types = list(conflict_types)


class BookingStateError(Exception):
    pass


class BookingAlreadyDecidedError(Exception):
    """SCRUM-29 AC5: only an undecided booking can be approved or rejected."""


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
        # SCRUM-28 AC2: when the request was recorded. Legacy rows, and hold
        # rows that never carry the column, serialise as None.
        "requestedAt": (
            _aware(row["requested_at"]).astimezone(SINGAPORE).isoformat()
            if row.get("requested_at")
            else None
        ),
        # SCRUM-29 AC2/AC6: when Venue Staff decided, and why they rejected.
        # Undecided, legacy and hold rows serialise both as None.
        "reviewedAt": (
            _aware(row["reviewed_at"]).astimezone(SINGAPORE).isoformat()
            if row.get("reviewed_at")
            else None
        ),
        "rejectionReason": row.get("rejection_reason"),
        "conflictReason": row.get("conflict_reason"),
        "closureRejection": (
            dict(
                closureId=str(row["rejection_closure_id"]),
                startDateTime=_aware(row["rejection_closure_start"])
                .astimezone(SINGAPORE)
                .isoformat(),
                endDateTime=_aware(row["rejection_closure_end"])
                .astimezone(SINGAPORE)
                .isoformat(),
                reason=row["rejection_closure_reason"],
                rejectedAt=_aware(row["rejected_at"]).astimezone(SINGAPORE).isoformat(),
            )
            if row.get("rejection_closure_id")
            else None
        ),
    }


def _effective_window(row, setup_time_minutes=0, turnaround_time_minutes=0):
    """Return the venue occupancy interval for one stored booking.

    Event bookings use the venue's buffers. A temporary hold already stores
    the exact interval it blocks, so applying event preparation time to it a
    second time would artificially extend the hold.
    """
    start = row["requested_start_time"]
    end = row["requested_end_time"]
    if row.get("status") == "On Hold":
        return start, end
    return (
        _shift(start, -setup_time_minutes),
        _shift(end, turnaround_time_minutes),
    )


def serialize_calendar(row, setup_time_minutes=0, turnaround_time_minutes=0):
    result = serialize(row)
    result["requestedStartTime"] = (
        row["requested_start_time"].replace(tzinfo=SINGAPORE).isoformat()
    )
    result["requestedEndTime"] = (
        row["requested_end_time"].replace(tzinfo=SINGAPORE).isoformat()
    )
    result["blocksSelection"] = row["status"] in {"Approved", "On Hold"}
    effective_start, effective_end = _effective_window(
        row, setup_time_minutes, turnaround_time_minutes
    )
    result["effectiveStartTime"] = effective_start.replace(
        tzinfo=SINGAPORE
    ).isoformat()
    result["effectiveEndTime"] = effective_end.replace(tzinfo=SINGAPORE).isoformat()
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


def list_bookings(
    database_url,
    venue_id,
    date_from,
    date_to,
    setup_time_minutes=0,
    turnaround_time_minutes=0,
):
    """Bounded calendar read, including invalid candidates so they fail closed.

    Null venue IDs cannot safely be assigned to any venue. Invalid intervals
    for this venue (or an unknown venue) fail the entire read even outside the
    window; otherwise malformed times could disappear in SQL comparisons.
    """
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            if setup_time_minutes == 0 and turnaround_time_minutes == 0:
                cursor.execute(
                    f"""SELECT {booking_columns()}, hold_expires_at FROM public."VenueBooking"
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
            else:
                cursor.execute(
                    f"""SELECT {booking_columns()}, hold_expires_at FROM public."VenueBooking"
                        WHERE (venue_id = %s OR venue_id IS NULL)
                          AND (status IS NULL OR status NOT IN ('Rejected', 'Cancelled', 'Expired'))
                          AND (status IS NULL OR status <> 'On Hold' OR hold_expires_at IS NULL OR hold_expires_at > now())
                          AND (((status = 'On Hold' AND requested_start_time < %s
                                 AND requested_end_time > %s)
                            OR (status <> 'On Hold' AND requested_start_time < %s
                                 AND requested_end_time > %s))
                            OR requested_start_time IS NULL
                            OR requested_end_time IS NULL
                            OR requested_end_time <= requested_start_time)
                        ORDER BY requested_start_time ASC, booking_id ASC""",
                    [
                        venue_id,
                        _aware(date_to),
                        _aware(date_from),
                        _aware(_shift(date_to, setup_time_minutes)),
                        _aware(_shift(date_from, -turnaround_time_minutes)),
                    ],
                )
            bookings = []
            for row in map(_localize, cursor.fetchall()):
                if row.get("status") in {"Rejected", "Cancelled", "Expired"}:
                    continue
                validate_calendar_row(row)
                effective_start, effective_end = _effective_window(
                    row, setup_time_minutes, turnaround_time_minutes
                )
                if effective_start < date_to and effective_end > date_from:
                    bookings.append(
                        serialize_calendar(
                            row, setup_time_minutes, turnaround_time_minutes
                        )
                    )
            return bookings


def _conflict_types(
    cursor,
    venue_id,
    start,
    end,
    exclude_booking_id=None,
    setup_time_minutes=0,
    turnaround_time_minutes=0,
):
    """Return blockers for a candidate event's buffered half-open interval."""
    if setup_time_minutes == 0 and turnaround_time_minutes == 0:
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

    effective_start = _shift(start, -setup_time_minutes)
    effective_end = _shift(end, turnaround_time_minutes)
    # Approved event bookings have the same venue-specific padding. Holds and
    # closures already store their exact blocked intervals.
    query = """SELECT DISTINCT CASE WHEN status = 'Approved' THEN 'APPROVED_BOOKING'
                        ELSE 'TENTATIVE_HOLD' END AS conflict_type
               FROM public."VenueBooking"
               WHERE venue_id = %s AND status IN ('Approved', 'On Hold')
                 AND ((status = 'Approved' AND requested_start_time < %s
                       AND requested_end_time > %s)
                   OR (status = 'On Hold' AND hold_expires_at > now()
                       AND requested_start_time < %s AND requested_end_time > %s))"""
    params = [
        venue_id,
        _aware(_shift(effective_end, setup_time_minutes)),
        _aware(_shift(effective_start, -turnaround_time_minutes)),
        _aware(effective_end),
        _aware(effective_start),
    ]
    if exclude_booking_id:
        query += " AND booking_id <> %s"
        params.append(exclude_booking_id)
    query += """ UNION SELECT 'VENUE_CLOSURE' AS conflict_type
                 FROM public."VenueClosure"
                 WHERE venue_id = %s
                   AND start_date_time < %s AND end_date_time > %s"""
    params.extend([venue_id, _aware(effective_end), _aware(effective_start)])
    cursor.execute(query, params)
    return sorted(row["conflict_type"] for row in cursor.fetchall())


def _has_conflict(
    cursor,
    venue_id,
    start,
    end,
    exclude_booking_id=None,
    setup_time_minutes=0,
    turnaround_time_minutes=0,
):
    return bool(
        _conflict_types(
            cursor,
            venue_id,
            start,
            end,
            exclude_booking_id,
            setup_time_minutes,
            turnaround_time_minutes,
        )
    )


def lock_booking_writes(cursor):
    # All application writers take this transaction gate BEFORE any row lock.
    # Existing edit/approve lock booking then venue; closure locks venue then
    # bookings. Serializing this small write domain avoids that lock inversion
    # (including edits moving between venues), while reads remain concurrent.
    # Any future booking/closure writer must join this protocol.
    cursor.execute("SELECT pg_advisory_xact_lock(171, 1)")


def create_booking(
    database_url,
    event_id,
    venue_id,
    start,
    end,
    required_capacity,
    venue_requirements,
    requested_by,
    setup_time_minutes=0,
    turnaround_time_minutes=0,
):
    booking_id = str(uuid4())
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            lock_booking_writes(cursor)
            # A venue-row lock serializes bookings and holds, even when no
            # booking row exists yet.
            cursor.execute(
                'SELECT venue_id FROM public."Venue" WHERE venue_id = %s FOR UPDATE',
                [venue_id],
            )
            conflicts = _conflict_types(
                cursor,
                venue_id,
                start,
                end,
                setup_time_minutes=setup_time_minutes,
                turnaround_time_minutes=turnaround_time_minutes,
            )
            if conflicts:
                raise BookingConflictError(conflicts)
            cursor.execute(
                f"""INSERT INTO public."VenueBooking"
                    (booking_id, event_id, venue_id, requested_start_time,
                     requested_end_time, required_capacity, venue_requirements,
                     status, requested_by, requested_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'Pending Review', %s, now())
                    RETURNING {booking_columns()}""",
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
            enqueue_booking_notification(cursor, saved, "venue.booking-submission-fanout")
    return serialize(saved)


def enqueue_booking_notification(cursor, booking, kind):
    """Capture owner facts atomically; the composite enriches names over HTTP."""
    source = dict(
        bookingId=str(booking["booking_id"]), eventId=str(booking["event_id"]),
        venueId=str(booking["venue_id"]), requestedBy=str(booking["requested_by"]),
        startDateTime=_aware(booking["requested_start_time"]).isoformat(),
        endDateTime=_aware(booking["requested_end_time"]).isoformat(),
    )
    repeat_decision = ""
    if kind == "venue.booking-decision":
        source["decision"] = booking["status"]
        # Preserve existing edit/resubmission decisions without adding another alert.
        repeat_decision = " ON CONFLICT (booking_id) WHERE type = 'venue.booking-decision' DO NOTHING"
    cursor.execute(
        'INSERT INTO public."VenueNotificationOutbox" (type,booking_id,source) VALUES (%s,%s,%s)' + repeat_decision,
        (kind, booking["booking_id"], Json(source)),
    )


def update_booking(
    database_url,
    booking_id,
    event_id,
    venue_id,
    start,
    end,
    required_capacity,
    venue_requirements,
    setup_time_minutes=0,
    turnaround_time_minutes=0,
):
    """Update one booking and resubmit only that row for review."""
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            lock_booking_writes(cursor)
            cursor.execute(
                f"""SELECT {booking_columns()} FROM public."VenueBooking"
                    WHERE booking_id = %s AND event_id = %s FOR UPDATE""",
                [booking_id, event_id],
            )
            booking = cursor.fetchone()
            if not booking:
                raise BookingNotFoundError
            if booking["status"] in {"Cancelled", "Rejected"}:
                raise BookingStateError

            cursor.execute(
                'SELECT venue_id FROM public."Venue" WHERE venue_id = %s FOR UPDATE',
                [venue_id],
            )
            conflicts = _conflict_types(
                cursor,
                venue_id,
                start,
                end,
                exclude_booking_id=booking_id,
                setup_time_minutes=setup_time_minutes,
                turnaround_time_minutes=turnaround_time_minutes,
            )
            if conflicts:
                raise BookingConflictError(conflicts)

            cursor.execute(
                f"""UPDATE public."VenueBooking"
                    SET venue_id = %s, requested_start_time = %s,
                        requested_end_time = %s, required_capacity = %s,
                        venue_requirements = %s, status = 'Pending Review',
                        reviewed_by = NULL, conflict_reason = NULL,
                        -- SCRUM-29 AC5: the old decision no longer applies.
                        reviewed_at = NULL, rejection_reason = NULL,
                        -- SCRUM-28 Part B: a changed request rejoins the
                        -- Venue Staff queue as a new submission.
                        requested_at = now()
                    WHERE booking_id = %s AND event_id = %s
                    RETURNING {booking_columns()}""",
                [
                    venue_id,
                    # Naive Singapore local time, as in create_booking: without
                    # _aware() Postgres reads it in the session time zone (UTC).
                    _aware(start),
                    _aware(end),
                    required_capacity,
                    venue_requirements,
                    booking_id,
                    event_id,
                ],
            )
            saved = _localize(cursor.fetchone())
    return serialize(saved)


def cancel_booking(database_url, booking_id, event_id):
    """Retain one booking as Cancelled without touching sibling bookings."""
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            lock_booking_writes(cursor)
            cursor.execute(
                f"""SELECT {booking_columns()} FROM public."VenueBooking"
                    WHERE booking_id = %s AND event_id = %s FOR UPDATE""",
                [booking_id, event_id],
            )
            booking = cursor.fetchone()
            if not booking:
                raise BookingNotFoundError
            if booking["status"] == "Rejected":
                raise BookingStateError
            if booking["status"] == "Cancelled":
                return serialize(booking)

            cursor.execute(
                f"""UPDATE public."VenueBooking"
                    SET status = 'Cancelled', conflict_reason = NULL
                    WHERE booking_id = %s AND event_id = %s
                    RETURNING {booking_columns()}""",
                [booking_id, event_id],
            )
            cancelled = cursor.fetchone()
    return serialize(cancelled)


def reset_safety_bookings(database_url, event_id, booking_ids):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            lock_booking_writes(cursor)
            cursor.execute(
                f'''SELECT {booking_columns()} FROM public."VenueBooking"
                    WHERE event_id = %s AND booking_id = ANY(%s::uuid[]) FOR UPDATE''',
                [event_id, booking_ids],
            )
            if len(cursor.fetchall()) != len(booking_ids):
                raise BookingNotFoundError
            cursor.execute(
                f'''UPDATE public."VenueBooking" SET status = 'Pending Review', reviewed_by = NULL,
                    reviewed_at = NULL, rejection_reason = NULL
                    WHERE event_id = %s AND booking_id = ANY(%s::uuid[])
                    AND status IN ('Approved', 'Pending', 'Pending Review')
                    RETURNING {booking_columns()}''',
                [event_id, booking_ids],
            )
            return [serialize(row) for row in cursor.fetchall()]


def list_event_bookings(database_url, event_id):
    """Return each independently managed booking linked to one event."""
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {booking_columns()} FROM public."VenueBooking"
                    WHERE event_id = %s
                    ORDER BY requested_start_time ASC, booking_id ASC""",
                [event_id],
            )
            return [serialize(_localize(row)) for row in cursor.fetchall()]


def get_booking(database_url, booking_id):
    """Return one booking so a composite can obtain its owning venue."""
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""SELECT {booking_columns()} FROM public."VenueBooking"
                    WHERE booking_id = %s""",
                [booking_id],
            )
            booking = cursor.fetchone()
    if not booking:
        raise BookingNotFoundError
    return serialize(_localize(booking))


def create_hold(
    database_url,
    venue_id,
    expires_at,
    held_by,
    held_for=None,
    setup_time_minutes=0,
    turnaround_time_minutes=0,
):
    hold_now = datetime.now(SINGAPORE)
    expires_at = _aware(expires_at)
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            lock_booking_writes(cursor)
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
                      AND ((status = 'On Hold' AND requested_start_time < %s
                            AND requested_end_time > %s)
                        OR (status <> 'On Hold' AND requested_start_time < %s
                            AND requested_end_time > %s))
                    LIMIT 1""",
                [
                    venue_id,
                    expires_at,
                    hold_now,
                    _shift(expires_at, setup_time_minutes),
                    _shift(hold_now, -turnaround_time_minutes),
                ],
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
    """Return this coordinator's active holds that expire within three days."""
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


def decide_booking(
    database_url,
    booking_id,
    reviewed_by,
    status,
    setup_time_minutes=0,
    turnaround_time_minutes=0,
    rejection_reason=None,
):
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            lock_booking_writes(cursor)
            cursor.execute(
                f"""SELECT {booking_columns()} FROM public."VenueBooking"
                    WHERE booking_id = %s FOR UPDATE""",
                [booking_id],
            )
            booking = cursor.fetchone()
            booking = _localize(booking) if booking else booking
            if not booking:
                raise BookingNotFoundError
            if booking["status"] in {"Cancelled", "Rejected"}:
                raise BookingStateError
            # SCRUM-29 AC5: decisions are final; an approved (or held/expired)
            # row is never decided again.
            if booking["status"] not in {"Pending", "Pending Review"}:
                raise BookingAlreadyDecidedError
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
                    setup_time_minutes=setup_time_minutes,
                    turnaround_time_minutes=turnaround_time_minutes,
                )
                if conflicts:
                    raise BookingConflictError(conflicts)
            cursor.execute(
                f"""UPDATE public."VenueBooking"
                    SET status = %s, reviewed_by = %s, reviewed_at = now(),
                        rejection_reason = %s, conflict_reason = NULL
                    WHERE booking_id = %s
                    RETURNING {booking_columns()}""",
                [
                    status,
                    reviewed_by,
                    rejection_reason if status == "Rejected" else None,
                    booking_id,
                ],
            )
            decided = _localize(cursor.fetchone())
            enqueue_booking_notification(cursor, decided, "venue.booking-decision")
    return serialize(decided)


def list_window_bookings(database_url, date_from, date_to, padding_minutes=0):
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
                f"""SELECT {booking_columns()}, hold_expires_at FROM public."VenueBooking"
                    WHERE (status IS NULL OR status NOT IN ('Rejected', 'Cancelled', 'Expired'))
                      AND (status IS NULL OR status <> 'On Hold' OR hold_expires_at IS NULL OR hold_expires_at > now())
                      AND ((requested_start_time < %s AND requested_end_time > %s)
                        OR requested_start_time IS NULL
                        OR requested_end_time IS NULL
                        OR requested_end_time <= requested_start_time)
                    ORDER BY requested_start_time ASC, booking_id ASC""",
                [
                    _aware(_shift(date_to, padding_minutes)),
                    _aware(_shift(date_from, -padding_minutes)),
                ],
            )
            bookings = []
            for row in map(_localize, cursor.fetchall()):
                validate_calendar_row(row)
                if (
                    row["requested_start_time"]
                    < _shift(date_to, padding_minutes)
                    and row["requested_end_time"]
                    > _shift(date_from, -padding_minutes)
                ):
                    bookings.append(serialize(row))
            return bookings


def _legacy_conflict_pairs(rows, setup_time_minutes, turnaround_time_minutes):
    """Find conflicts introduced by padding while retaining original rows."""
    pairs = []
    for index, first in enumerate(rows):
        first_effective = _effective_window(
            first, setup_time_minutes, turnaround_time_minutes
        )
        for second in rows[index + 1 :]:
            # A raw overlap is not a conflict introduced by the buffer rule.
            raw_overlap = (
                first["requested_start_time"] < second["requested_end_time"]
                and first["requested_end_time"] > second["requested_start_time"]
            )
            second_effective = _effective_window(
                second, setup_time_minutes, turnaround_time_minutes
            )
            padded_overlap = (
                first_effective[0] < second_effective[1]
                and first_effective[1] > second_effective[0]
            )
            if padded_overlap and not raw_overlap:
                pairs.append((first, first_effective, second, second_effective))
    return pairs


def _serialize_conflict_member(row, effective):
    return {
        **serialize(row),
        "effectiveStartTime": effective[0].isoformat(),
        "effectiveEndTime": effective[1].isoformat(),
        "conflictReason": "BUFFER_OVERLAP",
    }


def reconcile_legacy_conflicts(
    database_url, venue_id, setup_time_minutes, turnaround_time_minutes
):
    """Persist and return buffer-only conflicts without changing bookings.

    The existing single `conflict_reason` field is updated only when empty or
    already owned by this rule, so another reason is never overwritten.
    """
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            # Buffer reconciliation is also a multi-row booking writer.
            lock_booking_writes(cursor)
            cursor.execute(
                f"""SELECT {booking_columns()}, conflict_reason, hold_expires_at
                    FROM public."VenueBooking"
                    WHERE venue_id = %s
                      AND (status = 'Approved'
                        OR (status = 'On Hold' AND hold_expires_at > now()))
                    ORDER BY requested_start_time ASC, booking_id ASC
                    FOR UPDATE""",
                [venue_id],
            )
            rows = [_localize(row) for row in cursor.fetchall()]
            pairs = _legacy_conflict_pairs(
                rows, setup_time_minutes, turnaround_time_minutes
            )
            flagged_ids = sorted(
                {
                    str(row["booking_id"])
                    for first, _, second, _ in pairs
                    for row in (first, second)
                }
            )
            cursor.execute(
                """UPDATE public."VenueBooking"
                   SET conflict_reason = NULL
                   WHERE venue_id = %s AND conflict_reason = 'BUFFER_OVERLAP'""",
                [venue_id],
            )
            if flagged_ids:
                placeholders = ", ".join("%s" for _ in flagged_ids)
                cursor.execute(
                    f"""UPDATE public."VenueBooking"
                        SET conflict_reason = 'BUFFER_OVERLAP'
                        WHERE booking_id IN ({placeholders})
                          AND (conflict_reason IS NULL
                            OR conflict_reason = 'BUFFER_OVERLAP')""",
                    flagged_ids,
                )
    return {
        "venueId": str(venue_id),
        "conflictCount": len(pairs),
        "conflicts": [
            {
                "reason": "BUFFER_OVERLAP",
                "firstBooking": _serialize_conflict_member(first, first_effective),
                "secondBooking": _serialize_conflict_member(second, second_effective),
            }
            for first, first_effective, second, second_effective in pairs
        ],
    }


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
