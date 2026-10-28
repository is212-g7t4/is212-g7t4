"""Owning-service outbox. A lease token fences every mutation; freeze is once-only."""

import hmac
from uuid import UUID, uuid4, uuid5
from datetime import datetime, UTC
from zoneinfo import ZoneInfo
from contextlib import contextmanager
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from flask import Blueprint, current_app, request, jsonify

bp = Blueprint("notification_outbox", __name__)


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
        id=str(row["source_id"]),
        source=row["source"],
        type=row.get("type", "event.rejection"),
        envelope=row["envelope"],
        leaseToken=str(row["lease_token"]),
        attempts=row["attempts"],
        createdAt=row["created_at"].isoformat(),
    )


def claim(dsn):
    with transaction(dsn) as cursor:
        cursor.execute(
            """WITH candidate AS (
            SELECT source_id FROM public."EventNotificationOutbox"
            WHERE published_at IS NULL AND held_at IS NULL AND available_at<=now() AND (lease_until IS NULL OR lease_until<=now())
            ORDER BY available_at,source_id FOR UPDATE SKIP LOCKED LIMIT 1
        ) UPDATE public."EventNotificationOutbox" o SET lease_token=%s,lease_until=now()+interval '60 seconds',attempts=attempts+1
          FROM candidate c WHERE o.source_id=c.source_id RETURNING o.*""",
            (str(uuid4()),),
        )
        return [serialize(row) for row in cursor.fetchall()]


def mutate(dsn, identifier, token, action, data):
    with transaction(dsn) as cursor:
        cursor.execute(
            'WITH locked AS MATERIALIZED (SELECT * FROM public."EventNotificationOutbox" WHERE source_id=%s AND lease_token=%s AND published_at IS NULL FOR UPDATE) SELECT locked.*, lease_until>clock_timestamp() AS lease_valid FROM locked',
            (identifier, token),
        )
        row = cursor.fetchone()
        if row is None or not row["lease_valid"]:
            return None
        if action == "expand":
            # One fenced transaction freezes the lookup result and all recipients.
            # A lost HTTP response cannot create duplicate children on lease recovery.
            safety = row["type"] == "safety.review-fanout"
            if row["type"] != "event.submission-fanout" and not safety:
                raise ValueError("Only submission intents can expand")
            recipients = data.get("recipientIds")
            name = data.get("organiserName")
            if not isinstance(recipients, list) or (not safety and (not isinstance(name, str) or not name.strip())):
                raise ValueError("Invalid submission recipients/name")
            recipients = sorted({str(UUID(value)) for value in recipients})
            captured = datetime.now(UTC).isoformat()
            for recipient in recipients:
                source = {**row["source"], "recipientId": recipient}
                if not safety:
                    source.update(organiserName=name, organiserNameCapturedAt=captured)
                cursor.execute(
                    'INSERT INTO public."EventNotificationOutbox" (source_id,type,source,created_at) VALUES (%s,%s,%s,%s)',
                    (str(uuid5(UUID(identifier), recipient)), "safety.review-submitted" if safety else "event.submission", Json(source), row["created_at"]),
                )
            cursor.execute(
                'UPDATE public."EventNotificationOutbox" SET published_at=now(),lease_token=NULL,lease_until=NULL,last_error=NULL WHERE source_id=%s',
                (identifier,),
            )
            return {"id": identifier, "status": "expanded", "recipients": len(recipients)}
        if action == "freeze":
            if row["envelope"] is None:
                envelope = data.get("envelope")
                validate_envelope(envelope, row)
                cursor.execute(
                    'UPDATE public."EventNotificationOutbox" SET envelope=%s WHERE source_id=%s RETURNING *',
                    (Json(envelope), identifier),
                )
                row = cursor.fetchone()
            return serialize(row)
        if action == "published":
            if row["envelope"] is None:
                raise ValueError("Freeze before publish")
            cursor.execute(
                'UPDATE public."EventNotificationOutbox" SET published_at=now(),lease_until=NULL,lease_token=NULL,last_error=NULL WHERE source_id=%s',
                (identifier,),
            )
        elif action == "hold":
            error = data.get("error")
            if not isinstance(error, str):
                raise ValueError("error must be text")
            cursor.execute(
                'UPDATE public."EventNotificationOutbox" SET held_at=now(),lease_until=NULL,lease_token=NULL,last_error=%s WHERE source_id=%s',
                (error[:2000], identifier),
            )
        else:
            error = data.get("error")
            if not isinstance(error, str):
                raise ValueError("error must be text")
            delay = min(300, 2 ** min(row["attempts"], 9))
            cursor.execute(
                """UPDATE public."EventNotificationOutbox" SET available_at=now()+(%s * interval '1 second'),lease_until=NULL,lease_token=NULL,last_error=%s WHERE source_id=%s""",
                (delay, error[:2000], identifier),
            )
        return {"id": identifier, "status": action}


def _proposed_period(source):
    """Return the source's ISO date/time range in Singapore time, or 'Not provided'."""
    def stamp(value):
        return datetime.fromisoformat(value).astimezone(ZoneInfo("Asia/Singapore")).strftime("%d %b %Y, %H:%M SGT")

    return (stamp(source["startDateTime"]) + " – " + stamp(source["endDateTime"])
            if source.get("startDateTime") and source.get("endDateTime") else "Not provided")


def coordinator_message(source, name, removed=False):
    """Freeze a complete, UI-independent proposed-period description in Singapore time."""
    period = _proposed_period(source)
    action = "You are no longer assigned to" if removed else "You have been assigned to"
    return f"{action} {source['eventName']}. Event Organiser: {name}. Proposed: {period}."


def safety_review_message(source):
    """Describe the submitted round and original proposed interval in Singapore time."""
    period = _proposed_period(source)
    return f"{source['eventName']} requires safety review (round {source['round']}). Proposed: {period}."


def safety_decision_message(source):
    """Retain full existing decision text; approval has no invented reason."""
    message = f"{source['eventName']} safety review: {source['decision']} (round {source['round']})."
    if source.get("reason"):
        message += f" {source['reason']}"
    if source.get("areas"):
        message += f" Affected areas: {', '.join(source['areas'])}."
    return message


def validate_envelope(value, row):
    if (
        not isinstance(value, dict)
        or type(value.get("version")) is not int
        or value.get("version") != 1
    ):
        raise ValueError("Invalid envelope")
    source = row["source"]
    destination = value.get("destination")
    if value.get("id") != str(row["source_id"]) or value.get("type") != row["type"]:
        raise ValueError("Invalid source identity")
    if value.get("recipientId") != source["recipientId"]:
        raise ValueError("Invalid recipient")
    if value.get("createdAt") != row["created_at"].isoformat():
        raise ValueError("Invalid creation instant")
    expected_destination = (None if row["type"] == "event.coordinator-removed"
                            else dict(kind="event-details", eventId=source["eventId"]))
    if "destination" not in value or destination != expected_destination:
        raise ValueError("Invalid destination")
    details = value.get("details")
    if row["type"] == "safety.review-submitted":
        expected_details = source
        message = safety_review_message(source)
    elif row["type"] == "safety.review-decision":
        expected_details = source
        message = safety_decision_message(source)
    elif row["type"] == "event.submission":
        expected_details = source
        message = f"{source['organiserName']} submitted {source['eventName']}. Review required."
    elif row["type"] == "event.coordinator-assignment":
        name = details.get("coordinatorName") if isinstance(details, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Missing coordinator name")
        expected_details = {**source, "coordinatorName": name}
        message = f"{name} has been assigned to coordinate {source['eventName']}."
    elif row["type"] in ("event.coordinator-assigned", "event.coordinator-removed"):
        name = details.get("organiserName") if isinstance(details, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Missing organiser name")
        expected_details = {**source, "organiserName": name}
        message = coordinator_message(source, name, row["type"] == "event.coordinator-removed")
    elif row["type"] == "event.approval":
        expected_details = source
        message = f"{source['eventName']} was approved"
    else:
        expected_details = source
        message = f"{source['eventName']} was rejected: {source['reason']}"
    if details != expected_details:
        raise ValueError("Invalid historical content")
    if value.get("message") != message:
        raise ValueError("Invalid notification message")


@bp.before_request
def authenticate():
    expected = current_app.config.get("INTERNAL_SERVICE_TOKEN") or ""
    supplied = request.headers.get("X-Internal-Token", "")
    if not expected or not hmac.compare_digest(expected.encode(), supplied.encode()):
        return jsonify(message="Internal token required."), 401
    if request.endpoint == "notification_outbox.operate" and (request.view_args or {}).get("action") == "freeze":
        # HTTPX duplicates the accepted reason in message/details (2 * 64 KiB).
        # 4 KiB covers the twice-escaped varchar(255) name (at most 3060
        # bytes), UUIDs, timestamp, lease token and JSON keys. Only authenticated
        # freeze gets this bounded allowance; the public 64 KiB cap is unchanged.
        request.max_content_length = 2 * 65536 + 4096


@bp.get("/internal/notification-outbox/held")
def held():
    dsn = current_app.config.get("DATABASE_URL")
    if not dsn:
        return jsonify(message="Outbox database unavailable."), 503
    try:
        with transaction(dsn) as cursor:
            cursor.execute('SELECT source_id,source,last_error,held_at FROM public."EventNotificationOutbox" WHERE held_at IS NOT NULL AND published_at IS NULL ORDER BY held_at,source_id')
            jobs = [dict(id=str(row["source_id"]), source=row["source"], error=row["last_error"],
                         heldAt=row["held_at"].isoformat()) for row in cursor.fetchall()]
        return jsonify(jobs=jobs)
    except psycopg2.Error:
        return jsonify(message="Outbox storage unavailable."), 503


@bp.post("/internal/notification-outbox/claim")
@bp.post("/internal/notification-outbox/<uuid:identifier>/<action>")
def operate(identifier=None, action=None):
    dsn = current_app.config.get("DATABASE_URL")
    if not dsn:
        return jsonify(message="Outbox database unavailable."), 503
    try:
        if identifier is None:
            return jsonify(jobs=claim(dsn))
        if action == "release":
            with transaction(dsn) as cursor:
                cursor.execute(
                    'UPDATE public."EventNotificationOutbox" SET held_at=NULL,last_error=NULL,available_at=now() WHERE source_id=%s AND held_at IS NOT NULL AND published_at IS NULL RETURNING source_id',
                    (str(identifier),),
                )
                released = cursor.fetchone()
            return ((jsonify(id=str(identifier), status="released"), 200) if released
                    else (jsonify(message="Held work not found."), 409))
        if action not in {"freeze", "published", "retry", "hold", "expand"}:
            return jsonify(message="Unknown operation."), 404
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError()
        token = str(UUID(data.get("leaseToken", "")))
        result = mutate(dsn, str(identifier), token, action, data)
        return (
            (jsonify(result), 200) if result else (jsonify(message="Lease lost."), 409)
        )
    except (ValueError, TypeError, AttributeError):
        return jsonify(message="Invalid outbox input."), 400
    except psycopg2.Error:
        return jsonify(message="Outbox storage unavailable."), 503
