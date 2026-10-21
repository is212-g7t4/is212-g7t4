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
    if (
        not isinstance(destination, dict)
        or destination.get("kind") not in ("event-venue-request", "event-details")
    ):
        raise ValueError("Unknown destination")
    for key in (("eventId",) if destination["kind"] == "event-details" else ("eventId", "bookingId")):
        UUID(destination[key])
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
