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


class PreviewChangedError(Exception):
    """Refresh the preview and explicitly confirm again; nothing was saved."""


def sign_preview(data, staff, impact, key, expires=None):
    import hashlib
    import hmac
    import json
    import time

    expires = int(time.time()) + 900 if expires is None else expires
    payload = json.dumps(
        ["closure-preview-v1", expires, data, staff, impact],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()
    return f"{expires}.{signature}"


def verify_preview(token, data, staff, impact, key):
    import hmac
    import time

    try:
        expires = int(token.split(".")[0])
        if not int(time.time()) < expires <= int(time.time()) + 900:
            raise ValueError()
        if not hmac.compare_digest(
            token, sign_preview(data, staff, impact, key, expires)
        ):
            raise ValueError()
    except (ValueError, AttributeError, TypeError):
        raise PreviewChangedError from None


IMPACT_WHERE = """venue_id = %s
    AND status IN ('Pending', 'Pending Review', 'Approved')
    AND requested_start_time < %s AND requested_end_time > %s"""


def affected(cursor, data):
    from app.models import _aware

    cursor.execute(
        "SELECT booking_id, event_id, venue_id, requested_start_time, requested_end_time, status "
        'FROM public."VenueBooking" WHERE ' + IMPACT_WHERE + " ORDER BY booking_id",
        (data["venueId"], data["endDateTime"], data["startDateTime"]),
    )
    return [
        dict(
            id=str(row["booking_id"]),
            eventId=str(row["event_id"]) if row["event_id"] else None,
            venueId=str(row["venue_id"]),
            status=row["status"],
            requestedStartTime=_aware(row["requested_start_time"])
            .astimezone(SINGAPORE)
            .isoformat(),
            requestedEndTime=_aware(row["requested_end_time"])
            .astimezone(SINGAPORE)
            .isoformat(),
        )
        for row in cursor.fetchall()
    ]


def preview(dsn, data, staff, key):
    connection = psycopg2.connect(dsn)
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            impact = affected(cursor, data)
        return dict(
            closure=data,
            affectedCount=len(impact),
            affectedRequests=impact,
            confirmationToken=sign_preview(data, staff, impact, key),
        )
    finally:
        connection.close()


def create(dsn, data, staff, token, key):
    from app.models import lock_booking_writes

    connection = psycopg2.connect(dsn)
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            lock_booking_writes(cursor)
            cursor.execute(
                'SELECT venue_id FROM public."Venue" WHERE venue_id = %s FOR UPDATE',
                (data["venueId"],),
            )
            impact = affected(cursor, data)
            verify_preview(token, data, staff, impact, key)
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
            cursor.execute(
                "UPDATE public.\"VenueBooking\" SET status = 'Rejected', "
                "rejection_closure_id = %s, rejection_closure_start = %s, rejection_closure_end = %s, "
                "rejection_closure_reason = %s, rejected_at = %s WHERE " + IMPACT_WHERE,
                (
                    result["closureId"],
                    data["startDateTime"],
                    data["endDateTime"],
                    data["reason"],
                    datetime.now(timezone.utc),
                    data["venueId"],
                    data["endDateTime"],
                    data["startDateTime"],
                ),
            )
            count = cursor.rowcount
            # Intent and rejection are committed together. No broker/downstream I/O here.
            from psycopg2.extras import Json
            for booking in impact:
                source = dict(
                    closureId=result["closureId"], bookingId=booking["id"],
                    eventId=booking["eventId"], venueId=data["venueId"],
                    startDateTime=data["startDateTime"], endDateTime=data["endDateTime"],
                    reason=data["reason"],
                )
                cursor.execute(
                    'INSERT INTO public."VenueNotificationOutbox" (closure_id,booking_id,source) VALUES (%s,%s,%s)',
                    (result["closureId"], booking["id"], Json(source)),
                )
        connection.commit()
        return dict(closure=result, rejectedCount=count)
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
