"""Registration-owned action outbox, leased and frozen through internal HTTP only."""

import hmac
from contextlib import contextmanager
from uuid import UUID, uuid4
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from flask import Blueprint, current_app, jsonify, request
from app.attendee_notifications import attendee_message

bp = Blueprint("registration_outbox", __name__)


@contextmanager
def transaction(dsn):
    connection = psycopg2.connect(
        dsn, connect_timeout=5, options="-c statement_timeout=5000 -c lock_timeout=2000"
    )
    try:
        with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            yield cursor
    finally:
        connection.close()


def serialize(row):
    return dict(
        id=str(row["source_id"]),
        type=row["type"],
        source=row["source"],
        envelope=row["envelope"],
        leaseToken=str(row["lease_token"]),
        attempts=row["attempts"],
        createdAt=row["created_at"].isoformat(),
    )


def validate_envelope(value, row):
    source = row["source"]
    if (
        not isinstance(value, dict)
        or type(value.get("version")) is not int
        or value["version"] != 1
    ):
        raise ValueError("Invalid envelope")
    if (
        value.get("id") != str(row["source_id"])
        or value.get("type") != row["type"]
        or value.get("recipientId") != source["recipientId"]
        or value.get("createdAt") != row["created_at"].isoformat()
    ):
        raise ValueError("Invalid identity")
    if value.get("destination") != dict(
        kind="attendee-registration", registrationId=source["registrationId"]
    ):
        raise ValueError("Invalid destination")
    details = value.get("details")
    if not isinstance(details, dict) or any(
        details.get(k) != v for k, v in source.items()
    ):
        raise ValueError("Invalid source facts")
    keys = (
        ("eventName", "startDateTime", "endDateTime", "venueName")
        if row["type"] == "registration.confirmed"
        else ("eventName",)
    )
    if any(not isinstance(details.get(k), str) or not details[k].strip() for k in keys):
        raise ValueError("Missing content")
    if value.get("message") != attendee_message(row["type"], details):
        raise ValueError("Invalid message")


@bp.before_request
def authenticate():
    expected = current_app.config.get("INTERNAL_SERVICE_TOKEN") or ""
    supplied = request.headers.get("X-Internal-Token", "")
    if not expected or not hmac.compare_digest(expected.encode(), supplied.encode()):
        return jsonify(message="Internal token required."), 401


@bp.post("/internal/notification-outbox/claim")
@bp.post("/internal/notification-outbox/<uuid:identifier>/<action>")
def operate(identifier=None, action=None):
    dsn = current_app.config.get("DATABASE_URL")
    if not dsn:
        return jsonify(message="Outbox database unavailable."), 503
    try:
        with transaction(dsn) as cursor:
            if identifier is None:
                cursor.execute(
                    """WITH candidate AS (
                    SELECT source_id FROM public."RegistrationNotificationOutbox"
                    WHERE published_at IS NULL AND available_at<=now() AND (lease_until IS NULL OR lease_until<=now())
                    ORDER BY available_at,source_id FOR UPDATE SKIP LOCKED LIMIT 1)
                    UPDATE public."RegistrationNotificationOutbox" o
                    SET lease_token=%s,lease_until=now()+interval '60 seconds',attempts=attempts+1
                    FROM candidate c WHERE o.source_id=c.source_id RETURNING o.*""",
                    (str(uuid4()),),
                )
                return jsonify(jobs=[serialize(row) for row in cursor.fetchall()])
            if action not in ("freeze", "published", "retry"):
                return jsonify(message="Unknown operation."), 404
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                raise ValueError("Invalid input")
            token = str(UUID(data.get("leaseToken", "")))
            cursor.execute(
                """WITH locked AS MATERIALIZED (
                SELECT * FROM public."RegistrationNotificationOutbox"
                WHERE source_id=%s AND lease_token=%s AND published_at IS NULL FOR UPDATE)
                SELECT locked.*,lease_until>clock_timestamp() AS lease_valid FROM locked""",
                (str(identifier), token),
            )
            row = cursor.fetchone()
            if row is None or not row["lease_valid"]:
                return jsonify(message="Lease lost."), 409
            if action == "freeze":
                if row["envelope"] is None:
                    value = data.get("envelope")
                    validate_envelope(value, row)
                    cursor.execute(
                        'UPDATE public."RegistrationNotificationOutbox" SET envelope=%s WHERE source_id=%s RETURNING *',
                        (Json(value), str(identifier)),
                    )
                    row = cursor.fetchone()
                return jsonify(envelope=row["envelope"])
            if action == "published":
                if row["envelope"] is None:
                    raise ValueError("Freeze before publish")
                cursor.execute(
                    'UPDATE public."RegistrationNotificationOutbox" SET published_at=now(),lease_token=NULL,lease_until=NULL,last_error=NULL WHERE source_id=%s',
                    (str(identifier),),
                )
            else:
                error = data.get("error")
                if not isinstance(error, str):
                    raise ValueError("Missing error")
                delay = min(300, 2 ** min(row["attempts"], 9))
                cursor.execute(
                    """UPDATE public."RegistrationNotificationOutbox" SET
                    available_at=now()+(%s * interval '1 second'),lease_token=NULL,lease_until=NULL,last_error=%s WHERE source_id=%s""",
                    (delay, error[:2000], str(identifier)),
                )
            return jsonify(id=str(identifier), status=action)
    except (ValueError, TypeError, AttributeError, KeyError):
        return jsonify(message="Invalid outbox input."), 400
    except psycopg2.Error:
        return jsonify(message="Outbox storage unavailable."), 503
