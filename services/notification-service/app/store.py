"""Notification owns all inbox persistence. Legacy nullable rows are retained."""

import base64
import json
from datetime import datetime
from uuid import UUID
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from contextlib import contextmanager


@contextmanager
def transaction(dsn):
    connection = psycopg2.connect(
        dsn, connect_timeout=5, options="-c statement_timeout=5000 -c lock_timeout=2000"
    )
    try:
        with connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor
    finally:
        connection.close()


def serialize(row):
    return dict(
        id=str(row["notification_id"]),
        type=row["type"],
        eventId=str(row["event_id"]) if row["event_id"] else None,
        payload=row["payload"],
        createdAt=row["created_at"].isoformat() if row["created_at"] else None,
        readAt=row["read_at"].isoformat() if row["read_at"] else None,
    )


def decode_cursor(value):
    if value is None:
        return None
    try:
        stamp, identifier = json.loads(base64.urlsafe_b64decode(value.encode()))
        parsed = datetime.fromisoformat(stamp)
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed, str(UUID(identifier))
    except Exception as error:
        raise ValueError("Invalid cursor") from error


def list_inbox(dsn, user, limit=20, after=None, unread=False):
    sql = 'SELECT * FROM public."Notification" WHERE recipient_id=%s AND created_at IS NOT NULL'
    params = [user]
    if unread:
        sql += " AND read_at IS NULL"
    if after:
        sql += " AND (created_at,notification_id)<(%s,%s)"
        params.extend(after)
    sql += " ORDER BY created_at DESC,notification_id DESC LIMIT %s"
    params.append(limit + 1)
    with transaction(dsn) as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    page = [serialize(row) for row in rows[:limit]]
    following = (
        base64.urlsafe_b64encode(
            json.dumps([page[-1]["createdAt"], page[-1]["id"]]).encode()
        ).decode()
        if len(rows) > limit
        else None
    )
    return dict(notifications=page, nextCursor=following)


def unread_count(dsn, user):
    with transaction(dsn) as cursor:
        cursor.execute(
            'SELECT count(*) AS count FROM public."Notification" WHERE recipient_id=%s AND created_at IS NOT NULL AND read_at IS NULL',
            (user,),
        )
        return cursor.fetchone()["count"]


def set_read(dsn, user, identifier, read):
    with transaction(dsn) as cursor:
        cursor.execute(
            'UPDATE public."Notification" SET read_at=CASE WHEN %s THEN COALESCE(read_at,now()) ELSE NULL END WHERE recipient_id=%s AND notification_id=%s RETURNING *',
            (read, user, identifier),
        )
        row = cursor.fetchone()
        return serialize(row) if row else None


def deliver(dsn, envelope):
    with transaction(dsn) as cursor:
        cursor.execute(
            'INSERT INTO public."Notification" (source_id,notification_id,recipient_id,type,event_id,payload,dedupe_key,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (source_id) WHERE source_id IS NOT NULL DO NOTHING',
            (
                envelope["id"],
                envelope["id"],
                envelope["recipientId"],
                envelope["type"],
                (envelope["details"]["eventId"] if envelope["type"] == "event.coordinator-removed"
                 else envelope["destination"].get("eventId")),
                Json(envelope),
                envelope["id"],
                envelope["createdAt"],
            ),
        )


def safe_error(error):
    # Untrusted parser/UUID errors may themselves contain invalid database text.
    return str(error).encode("unicode_escape").decode("ascii")[:2000]


def quarantine(dsn, body, error):
    with transaction(dsn) as cursor:
        cursor.execute(
            'INSERT INTO public."NotificationFailure" (body,error) VALUES (%s,%s)',
            (psycopg2.Binary(body), safe_error(error)),
        )
