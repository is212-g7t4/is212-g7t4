"""Owning-service outbox. A lease token fences every mutation; freeze is once-only."""

import hmac
import os
from uuid import UUID, uuid4, uuid5
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
        type=row["type"],
        source=row["source"],
        envelope=row["envelope"],
        leaseToken=str(row["lease_token"]),
        attempts=row["attempts"],
        createdAt=row["created_at"].isoformat(),
    )


def claim(dsn):
    with transaction(dsn) as cursor:
        cursor.execute(
            """WITH candidate AS (
            SELECT source_id FROM public."VenueNotificationOutbox"
            WHERE published_at IS NULL AND available_at<=now() AND (lease_until IS NULL OR lease_until<=now())
            ORDER BY available_at,source_id FOR UPDATE SKIP LOCKED LIMIT 1
        ) UPDATE public."VenueNotificationOutbox" o SET lease_token=%s,lease_until=now()+interval '60 seconds',attempts=attempts+1
          FROM candidate c WHERE o.source_id=c.source_id RETURNING o.*""",
            (str(uuid4()),),
        )
        return [serialize(row) for row in cursor.fetchall()]


def mutate(dsn, identifier, token, action, data):
    with transaction(dsn) as cursor:
        cursor.execute(
            'WITH locked AS MATERIALIZED (SELECT * FROM public."VenueNotificationOutbox" WHERE source_id=%s AND lease_token=%s AND published_at IS NULL FOR UPDATE) SELECT locked.*, lease_until>clock_timestamp() AS lease_valid FROM locked',
            (identifier, token),
        )
        row = cursor.fetchone()
        if row is None or not row["lease_valid"]:
            return None
        if action == "expand":
            # Freeze lookup and child identities in one fenced owner transaction.
            if row["type"] != "venue.booking-submission-fanout":
                raise ValueError("Only submission intents can expand")
            recipients = data.get("recipientIds")
            if not isinstance(recipients, list) or not recipients:
                raise ValueError("Missing Venue Staff recipients")
            recipients = sorted({str(UUID(value)) for value in recipients})
            for key in ("eventName", "venueName"):
                if not isinstance(data.get(key), str) or not data[key].strip():
                    raise ValueError("Missing display name")
            for recipient in recipients:
                source = {**row["source"], "recipientId": recipient,
                          "eventName": data["eventName"], "venueName": data["venueName"]}
                cursor.execute(
                    'INSERT INTO public."VenueNotificationOutbox" (source_id,type,booking_id,source,created_at) VALUES (%s,%s,%s,%s,%s)',
                    (str(uuid5(UUID(identifier), recipient)), "venue.booking-submission",
                     row["booking_id"], Json(source), row["created_at"]),
                )
            cursor.execute(
                'UPDATE public."VenueNotificationOutbox" SET published_at=now(),lease_until=NULL,lease_token=NULL,last_error=NULL WHERE source_id=%s',
                (identifier,),
            )
            return {"id": identifier, "status": "expanded", "recipients": len(recipients)}
        if action == "freeze":
            if row["envelope"] is None:
                envelope = data.get("envelope")
                validate_envelope(envelope, row)
                cursor.execute(
                    'UPDATE public."VenueNotificationOutbox" SET envelope=%s WHERE source_id=%s RETURNING *',
                    (Json(envelope), identifier),
                )
                row = cursor.fetchone()
            return serialize(row)
        if action == "published":
            if row["envelope"] is None:
                raise ValueError("Freeze before publish")
            cursor.execute(
                'UPDATE public."VenueNotificationOutbox" SET published_at=now(),lease_until=NULL,lease_token=NULL,last_error=NULL WHERE source_id=%s',
                (identifier,),
            )
        else:
            error = data.get("error")
            if not isinstance(error, str):
                raise ValueError("error must be text")
            delay = min(300, 2 ** min(row["attempts"], 9))
            cursor.execute(
                """UPDATE public."VenueNotificationOutbox" SET available_at=now()+(%s * interval '1 second'),lease_until=NULL,lease_token=NULL,last_error=%s WHERE source_id=%s""",
                (delay, error[:2000], identifier),
            )
        return {"id": identifier, "status": action}


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
    UUID(value.get("recipientId", ""))
    if value.get("createdAt") != row["created_at"].isoformat():
        raise ValueError("Invalid creation instant")
    expected_destination = (
        dict(kind="venue-requests") if row["type"] == "venue.booking-submission"
        else dict(kind="event-venue-request", eventId=source["eventId"], bookingId=source["bookingId"])
    )
    if row["type"] == "venue.booking-decision":
        if source["decision"] not in ("Approved", "Rejected") or value["recipientId"] != source["requestedBy"]:
            raise ValueError("Invalid booking decision recipient/content")
    if row["type"] == "venue.booking-submission" and value["recipientId"] != source["recipientId"]:
        raise ValueError("Invalid submission recipient")
    if destination != expected_destination:
        raise ValueError("Invalid destination")
    if not isinstance(value.get("message"), str) or not value["message"].strip():
        raise ValueError("Missing message")
    details = value.get("details")
    if not isinstance(details, dict) or any(
        details.get(key) != source[key] for key in source
    ):
        raise ValueError("Invalid historical content")
    if any(
        not isinstance(details.get(key), str) or not details[key].strip()
        for key in ("eventName", "venueName")
    ):
        raise ValueError("Missing display names")


@bp.before_request
def authenticate():
    expected = os.getenv("INTERNAL_SERVICE_TOKEN", "")
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
        if identifier is None:
            return jsonify(jobs=claim(dsn))
        if action not in {"freeze", "published", "retry", "expand"}:
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
