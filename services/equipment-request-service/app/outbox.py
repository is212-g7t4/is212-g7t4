"""Equipment owns action-time frozen envelopes; leased delivery adapts SCRUM-47."""

import hmac
from uuid import UUID, uuid4, uuid5
from datetime import datetime, timezone
from contextlib import contextmanager
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from flask import Blueprint, current_app, request, jsonify

bp = Blueprint("notification_outbox", __name__)


class NotificationValidationError(Exception):
    """Expected caller-input failure with a safe public validation message."""


def notification_uuid(value, field):
    if not isinstance(value, str):
        raise NotificationValidationError(f"{field} must be a valid UUID")
    try:
        return str(UUID(value))
    except ValueError:
        raise NotificationValidationError(f"{field} must be a valid UUID") from None


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
            SELECT source_id FROM public."EquipmentNotificationOutbox"
            WHERE published_at IS NULL AND available_at<=now() AND (lease_until IS NULL OR lease_until<=now())
            ORDER BY available_at,source_id FOR UPDATE SKIP LOCKED LIMIT 1
        ) UPDATE public."EquipmentNotificationOutbox" o SET lease_token=%s,lease_until=now()+interval '60 seconds',attempts=attempts+1
          FROM candidate c WHERE o.source_id=c.source_id RETURNING o.*""",
            (str(uuid4()),),
        )
        return [serialize(row) for row in cursor.fetchall()]


def mutate(dsn, identifier, token, action, data):
    with transaction(dsn) as cursor:
        cursor.execute(
            'WITH locked AS MATERIALIZED (SELECT * FROM public."EquipmentNotificationOutbox" WHERE source_id=%s AND lease_token=%s AND published_at IS NULL FOR UPDATE) SELECT locked.*, lease_until>clock_timestamp() AS lease_valid FROM locked',
            (identifier, token),
        )
        row = cursor.fetchone()
        if row is None or not row["lease_valid"]:
            return None
        if action == "published":
            if row["envelope"] is None:
                raise NotificationValidationError("Freeze before publish")
            cursor.execute(
                'UPDATE public."EquipmentNotificationOutbox" SET published_at=now(),lease_until=NULL,lease_token=NULL,last_error=NULL WHERE source_id=%s',
                (identifier,),
            )
        else:
            error = data.get("error")
            if not isinstance(error, str):
                raise NotificationValidationError("error must be text")
            delay = min(300, 2 ** min(row["attempts"], 9))
            cursor.execute(
                """UPDATE public."EquipmentNotificationOutbox" SET available_at=now()+(%s * interval '1 second'),lease_until=NULL,lease_token=NULL,last_error=%s WHERE source_id=%s""",
                (delay, error[:2000], identifier),
            )
        return {"id": identifier, "status": action}


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
        if identifier is None:
            return jsonify(jobs=claim(dsn))
        if action not in {"published", "retry"}:
            return jsonify(message="Unknown operation."), 404
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise NotificationValidationError("Outbox input must be an object")
        token = notification_uuid(data.get("leaseToken"), "leaseToken")
        result = mutate(dsn, str(identifier), token, action, data)
        return (
            (jsonify(result), 200) if result else (jsonify(message="Lease lost."), 409)
        )
    except NotificationValidationError:
        return jsonify(message="Invalid outbox input."), 400
    except psycopg2.Error:
        return jsonify(message="Outbox storage unavailable."), 503


def submission_context(payload, event_id, items):
    """Only the composite can supply cross-service action-time snapshots."""
    expected = current_app.config.get("INTERNAL_SERVICE_TOKEN") or ""
    supplied = request.headers.get("X-Internal-Token", "")
    if not expected or not hmac.compare_digest(expected.encode(), supplied.encode()):
        raise NotificationValidationError("Submit or review equipment through Equipment Reservation Service.")
    context = payload.get("notificationContext")
    if not isinstance(context, dict) or context.get("eventId") != event_id:
        raise NotificationValidationError("Missing equipment notification context")
    if not isinstance(context.get("eventName"), str) or not context["eventName"].strip():
        raise NotificationValidationError("Missing event name")
    names = context.get("equipmentNames")
    if not isinstance(names, dict):
        raise NotificationValidationError("Missing equipment names")
    for item in items:
        if not isinstance(names.get(item["equipmentId"]), str) or not names[item["equipmentId"]].strip():
            raise NotificationValidationError("Missing equipment name")
    recipients = context.get("recipientIds")
    if not isinstance(recipients, list):
        raise NotificationValidationError("Missing Technical Support recipients")
    context = {"eventId": event_id, "eventName": context["eventName"],
               "equipmentNames": names, "recipientIds": sorted({notification_uuid(uid, "recipientId") for uid in recipients})}
    return context


def record_submission(cursor, event_id, created, context):
    """One full submitted list per eligible TSS; not one alert per quantity/line."""
    submission_id = uuid4()
    items = [dict(requestId=row["id"], equipmentId=row["equipmentId"],
                  equipmentName=context["equipmentNames"][row["equipmentId"]],
                  quantityRequested=row["quantityRequested"]) for row in created]
    summary = ", ".join(f"{item['equipmentName']} x{item['quantityRequested']}" for item in items)
    for recipient in context["recipientIds"]:
        identifier = str(uuid5(submission_id, recipient))
        source = dict(eventId=event_id, eventName=context["eventName"], recipientId=recipient, items=items)
        envelope = dict(version=1, id=identifier, type="equipment.request-submission",
            recipientId=recipient, createdAt=datetime.now(timezone.utc).isoformat(),
            message=f"{context['eventName']}: equipment requested: {summary}. Review required.",
            destination=dict(kind="equipment-requests", eventId=event_id, requestIds=[row["id"] for row in created]),
            details=source)
        enqueue(cursor, identifier, envelope, source)


def enqueue(cursor, identifier, envelope, source):
    cursor.execute(
        'INSERT INTO public."EquipmentNotificationOutbox" (source_id,type,source,envelope) VALUES (%s,%s,%s,%s)',
        (identifier, envelope["type"], Json(source), Json(envelope)))


def decision_context(payload):
    context = payload.get("notificationContext")
    if not isinstance(context, dict):
        raise NotificationValidationError("Missing equipment notification context")
    # Reuse trusted context/name validation; item/event consistency is checked in
    # the owning mutation transaction using the rows actually changed.
    checked = submission_context({"notificationContext": {**context, "recipientIds": []}},
                                 notification_uuid(context.get("eventId"), "eventId"), [])
    checked["coordinatorId"] = notification_uuid(context["coordinatorId"], "coordinatorId") if context.get("coordinatorId") else None
    return checked


def record_decisions(cursor, rows, context):
    """Record review UPDATE RETURNING rows, already set to Approved/Rejected.

    Both review routes validate the decision before their owning model updates
    Pending rows. Safety resets do not call this recorder.
    """
    for row in rows:
        if row["eventId"] != context["eventId"]:
            raise NotificationValidationError("Mismatched equipment event snapshot")
        recipient = context["coordinatorId"]
        if recipient is None:
            continue
        name = context["equipmentNames"].get(row["equipmentId"])
        if not isinstance(name, str) or not name.strip():
            raise NotificationValidationError("Missing equipment name")
        item = dict(requestId=row["id"], equipmentId=row["equipmentId"],
                    equipmentName=name, quantityRequested=row["quantityRequested"])
        identifier = str(uuid4())
        source = dict(eventId=row["eventId"], eventName=context["eventName"],
                      recipientId=recipient, decision=row["status"], items=[item])
        envelope = dict(version=1, id=identifier, type="equipment.request-decision",
            recipientId=recipient, createdAt=datetime.now(timezone.utc).isoformat(),
            message=f"{context['eventName']}: equipment request for {name} x{row['quantityRequested']} {row['status'].lower()}.",
            destination=dict(kind="equipment-requests", eventId=row["eventId"], requestIds=[row["id"]]),
            details=source)
        enqueue(cursor, identifier, envelope, source)
