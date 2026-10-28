"""Manual acknowledgement only after committed inbox/quarantine persistence.
Storage outages close the connection and back off instead of busy requeueing.
"""

import json
import logging
import math
import os
import time
from datetime import datetime
from uuid import UUID
import pika
from app import store

LOG = logging.getLogger(__name__)
QUEUE = "notifications.v1"


def reject_constant(value):
    raise ValueError("Non-finite JSON number")


def parse(body):
    # json.loads otherwise accepts JavaScript constants which PostgreSQL JSONB rejects.
    return validate(json.loads(body, parse_constant=reject_constant))


def json_safe(value):
    """Validate the entire payload, including future fields and object keys, before SQL."""
    if isinstance(value, str):
        if "\x00" in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueError("JSON text contains a NUL or lone surrogate")
    elif isinstance(value, dict):
        for key, item in value.items():
            json_safe(key)
            json_safe(item)
    elif isinstance(value, list):
        for item in value:
            json_safe(item)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite JSON number")


def validate(value):
    json_safe(value)
    if (
        not isinstance(value, dict)
        or type(value.get("version")) is not int
        or value.get("version") != 1
    ):
        raise ValueError("Unsupported envelope")
    for key in ("id", "recipientId"):
        UUID(value[key])
    if not isinstance(value["type"], str) or not 1 <= len(value["type"]) <= 50:
        raise ValueError("Invalid type")
    if not isinstance(value["message"], str) or not value["message"].strip():
        raise ValueError("Missing message")
    if not datetime.fromisoformat(value["createdAt"]).tzinfo:
        raise ValueError("Timezone required")
    destination = value["destination"]
    if value["type"] == "event.coordinator-removed":
        if destination is not None:
            raise ValueError("Removal must not link to the event")
    else:
        if (
            not isinstance(destination, dict)
            or destination.get("kind") not in ("event-venue-request", "event-details", "venue-requests", "equipment-requests")
        ):
            raise ValueError("Unknown destination")
        reference_keys = {
            "venue-requests": (),
            "equipment-requests": ("eventId",),
            "event-details": ("eventId",),
            "event-venue-request": ("eventId", "bookingId"),
        }
        for key in reference_keys[destination["kind"]]:
            UUID(destination[key])
    if value["type"] in ("event.coordinator-assigned", "event.coordinator-removed"):
        details = value.get("details")
        if not isinstance(details, dict):
            raise ValueError("Missing coordinator notification details")
        for key in ("eventName", "organiserName"):
            if not isinstance(details.get(key), str) or not details[key].strip():
                raise ValueError("Missing coordinator display content")
        for key in ("eventId", "organiserId", "recipientId"):
            UUID(details[key])
        if details["recipientId"] != value["recipientId"]:
            raise ValueError("Inconsistent coordinator recipient")
        if value["type"] == "event.coordinator-assigned" and destination != dict(kind="event-details", eventId=details["eventId"]):
            raise ValueError("Coordinator assignment requires matching event details")
        start, end = details["startDateTime"], details["endDateTime"]
        if start is not None or end is not None:
            start, end = datetime.fromisoformat(start), datetime.fromisoformat(end)
            if start.tzinfo is None or end.tzinfo is None or end <= start:
                raise ValueError("Proposed period requires an ordered timezone-aware interval")
    if value["type"] == "event.approval":
        if destination["kind"] != "event-details":
            raise ValueError("Approval requires event details")
        details = value["details"]
        if not isinstance(details.get("eventName"), str) or not details["eventName"].strip():
            raise ValueError("Missing approval event name")
        if details.get("decision") != "Approved":
            raise ValueError("Invalid approval decision")
    if value["type"] == "event.rejection":
        if destination["kind"] != "event-details":
            raise ValueError("Rejection requires event details")
        details = value["details"]
        for key in ("eventName", "reason"):
            if not isinstance(details.get(key), str) or not details[key].strip():
                raise ValueError("Missing rejection display content")
    if value["type"] == "event.coordinator-assignment":
        if destination["kind"] != "event-details":
            raise ValueError("Assignment requires event details")
        details = value.get("details")
        if not isinstance(details, dict):
            raise ValueError("Missing assignment details")
        for key in ("eventName", "coordinatorName"):
            if not isinstance(details.get(key), str) or not details[key].strip():
                raise ValueError("Missing assignment display content")
    if value["type"] in ("equipment.request-submission", "equipment.request-decision"):
        details = value["details"]
        if value["recipientId"] != details["recipientId"]:
            raise ValueError("Inconsistent equipment recipient")
        if not isinstance(details["eventName"], str) or not details["eventName"].strip():
            raise ValueError("Missing equipment event name")
        if value["type"] == "equipment.request-decision" and details.get("decision") not in ("Approved", "Rejected"):
            raise ValueError("Invalid equipment decision")
        allowed = {"eventId", "eventName", "recipientId", "items"}
        if value["type"] == "equipment.request-decision":
            allowed.add("decision")
        if set(details) != allowed:
            raise ValueError("Unexpected equipment notification details")
        items = details["items"]
        if not isinstance(items, list) or not items:
            raise ValueError("Missing equipment items")
        for item in items:
            if set(item) != {"requestId", "equipmentId", "equipmentName", "quantityRequested"}:
                raise ValueError("Unexpected equipment item details")
            UUID(item["requestId"])
            UUID(item["equipmentId"])
            if not isinstance(item["equipmentName"], str) or not item["equipmentName"].strip():
                raise ValueError("Missing equipment name")
            if type(item["quantityRequested"]) is not int or item["quantityRequested"] < 1:
                raise ValueError("Invalid equipment quantity")
        if destination != dict(kind="equipment-requests", eventId=details["eventId"],
                               requestIds=[item["requestId"] for item in items]):
            raise ValueError("Equipment requires matching requests destination")
    if value["type"] in ("venue.booking-submission", "venue.booking-decision"):
        details = value["details"]
        if not isinstance(details, dict):
            raise ValueError("Missing booking details")
        for key in ("eventId", "bookingId", "venueId", "requestedBy"):
            UUID(details[key])
        if value["type"] == "venue.booking-submission":
            if destination != dict(kind="venue-requests"):
                raise ValueError("Submission requires staff review page")
            UUID(details["recipientId"])
            if details["recipientId"] != value["recipientId"]:
                raise ValueError("Inconsistent booking recipient")
        else:
            if details["decision"] not in ("Approved", "Rejected") or value["recipientId"] != details["requestedBy"]:
                raise ValueError("Invalid booking decision recipient/content")
            if destination != dict(kind="event-venue-request", eventId=details["eventId"], bookingId=details["bookingId"]):
                raise ValueError("Decision requires matching booking destination")
        for key in ("eventName", "venueName"):
            if not isinstance(details.get(key), str) or not details[key].strip():
                raise ValueError("Missing booking display content")
        start = datetime.fromisoformat(details["startDateTime"])
        end = datetime.fromisoformat(details["endDateTime"])
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError("Booking requires an ordered timezone-aware interval")
    if value["type"] == "venue.closure-rejection":
        details = value["details"]
        if not isinstance(details, dict):
            raise ValueError("Missing closure details")
        for key in ("closureId", "venueId", "bookingId", "eventId"):
            identifier = UUID(details[key])
            if key in ("bookingId", "eventId") and identifier != UUID(destination[key]):
                raise ValueError("Inconsistent destination reference")
        for key in ("eventName", "venueName", "reason"):
            if not isinstance(details[key], str) or not details[key].strip():
                raise ValueError("Missing closure display content")
        start = datetime.fromisoformat(details["startDateTime"])
        end = datetime.fromisoformat(details["endDateTime"])
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError("Closure requires an ordered timezone-aware interval")
    return value


def process(dsn, channel, method, body):
    try:
        envelope = parse(body)
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        UnicodeError,
        RecursionError,
    ) as error:
        store.quarantine(dsn, body, error)
        LOG.warning("notification quarantined: %s", store.safe_error(error))
    else:
        store.deliver(dsn, envelope)
        LOG.info("notification persisted id=%s", envelope["id"])
    channel.basic_ack(delivery_tag=method.delivery_tag)


def connect(url):
    params = pika.URLParameters(url)
    params.heartbeat = 30
    params.blocked_connection_timeout = 10
    params.socket_timeout = 5
    params.stack_timeout = 15
    params.connection_attempts = 1
    return pika.BlockingConnection(params)


def declare(channel):
    channel.queue_declare(queue=QUEUE, durable=True)


def run():
    logging.basicConfig(level=logging.INFO)
    delay = 1
    while True:
        connection = None
        try:
            connection = connect(os.environ["RABBITMQ_URL"])
            channel = connection.channel()
            declare(channel)
            channel.basic_qos(prefetch_count=10)

            def on_message(ch, method, props, body):
                nonlocal delay
                process(os.environ["DATABASE_URL"], ch, method, body)
                delay = 1

            channel.basic_consume(
                queue=QUEUE, on_message_callback=on_message, auto_ack=False
            )
            channel.start_consuming()
        except KeyboardInterrupt:
            return
        except Exception:
            LOG.exception("consumer disconnected; retrying in %ss", delay)
        finally:
            if connection is not None and connection.is_open:
                try:
                    connection.close()
                except Exception:
                    LOG.warning("consumer close failed; connection will be replaced")
        time.sleep(delay)
        delay = min(delay * 2, 60)


if __name__ == "__main__":
    run()
