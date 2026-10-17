"""Closure notification orchestration; only HTTP accesses atomic state.
Run separately with python -m app.dispatcher. Unknown publication is retried
with the same frozen identity; broker acceptance is not inbox delivery.
"""

import json
import logging
import os
import subprocess
import sys
import time
from uuid import UUID
import httpx
import pika

LOG = logging.getLogger(__name__)
QUEUE = "notifications.v1"


class OutboxAPI:
    def __init__(self):
        self.base = os.environ["VENUE_AVAILABILITY_SERVICE_URL"].rstrip("/")
        self.event = os.environ["EVENT_SERVICE_URL"].rstrip("/")
        self.venue = os.environ["VENUE_SERVICE_URL"].rstrip("/")
        self.headers = {"X-Internal-Token": os.environ["INTERNAL_SERVICE_TOKEN"]}

    def call(self, method, url, **kwargs):
        response = httpx.request(method, url, headers=self.headers, timeout=5, **kwargs)
        response.raise_for_status()
        return response.json()

    def claim(self):
        return self.call(
            "POST", self.base + "/internal/notification-outbox/claim", json={}
        )["jobs"]

    def context(self, source):
        event = self.call(
            "GET",
            self.event + f"/internal/events/{source['eventId']}/notification-context",
        )
        venue = self.call("GET", self.venue + f"/venues/{source['venueId']}")["venue"]
        if event["id"] != source["eventId"] or venue["id"] != source["venueId"]:
            raise ValueError("Mismatched enrichment identity")
        UUID(event["coordinatorId"])
        for name in (event["eventName"], venue["name"]):
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Missing display name")
        return event, venue

    def operation(self, job, action, **data):
        return self.call(
            "POST",
            self.base + f"/internal/notification-outbox/{job['id']}/{action}",
            json={"leaseToken": job["leaseToken"], **data},
        )

    def freeze(self, job, envelope):
        return self.operation(job, "freeze", envelope=envelope)["envelope"]

    def published(self, job):
        return self.operation(job, "published")

    def retry(self, job, error):
        return self.operation(job, "retry", error=error)


def dispatch_once(api, publish):
    jobs = api.claim()
    for job in jobs:
        try:
            envelope = job["envelope"]
            if envelope is None:
                source = job["source"]
                event, venue = api.context(source)
                envelope = dict(
                    version=1,
                    id=job["id"],
                    type="venue.closure-rejection",
                    recipientId=event["coordinatorId"],
                    createdAt=job["createdAt"],
                    message=f"{event['eventName']}: venue request for {venue['name']} rejected. Closure {source['startDateTime']} to {source['endDateTime']}. Reason: {source['reason']}",
                    destination=dict(
                        kind="event-venue-request",
                        eventId=source["eventId"],
                        bookingId=source["bookingId"],
                    ),
                    details={
                        **source,
                        "eventName": event["eventName"],
                        "venueName": venue["name"],
                    },
                )
                # Use the owner's readback: a competing freeze can never replace history.
                envelope = api.freeze(job, envelope)
            publish(envelope)
            api.published(job)
            LOG.info(
                "broker accepted source=%s (not an inbox delivery receipt)", job["id"]
            )
        except Exception as error:
            LOG.warning(
                "dispatch retry source=%s error=%s", job["id"], type(error).__name__
            )
            try:
                api.retry(job, type(error).__name__)
            except Exception:
                LOG.warning(
                    "retry update failed; lease will recover source=%s", job["id"]
                )
    return len(jobs)


def publish(envelope):
    params = pika.URLParameters(os.environ["RABBITMQ_URL"])
    params.heartbeat = 30
    params.blocked_connection_timeout = 10
    params.socket_timeout = 5
    params.stack_timeout = 15
    params.connection_attempts = 1
    connection = pika.BlockingConnection(params)
    try:
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE, durable=True)
        channel.confirm_delivery()
        channel.basic_publish(
            exchange="",
            routing_key=QUEUE,
            body=json.dumps(envelope).encode(),
            mandatory=True,
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
                message_id=envelope["id"],
                type=envelope["type"],
            ),
        )
    finally:
        if connection.is_open:
            connection.close()


def attempt(timeout=50):
    """One bounded process owns all I/O, starting BEFORE its single-job claim.

    The owner grants 60 seconds. Claim time is included conservatively, leaving
    >=10 seconds of lease margin; preparation never earns a fresh publish budget.
    Pika BlockingChannel waits indefinitely for a missing Basic.Ack even with
    socket/blocked timeouts. subprocess.run kills AND reaps the child on timeout:
    the OS closes its sockets without cross-thread Pika calls or a hanging close.
    Any killed/unknown outcome recovers by lease expiry with the same frozen ID.
    No grandchildren are spawned by this one-shot worker.
    """
    try:
        subprocess.run(
            [sys.executable, "-m", "app.dispatcher", "--attempt"],
            timeout=timeout, check=True,
        )
        return 1
    except subprocess.CalledProcessError as error:
        if error.returncode == 3:  # empty claim, not an operational failure
            return 0
        raise


def run():
    logging.basicConfig(level=logging.INFO)
    delay = 1
    while True:
        try:
            count = attempt()
            delay = 1
            if not count:
                time.sleep(1)
        except KeyboardInterrupt:
            return
        except Exception:
            LOG.exception("outbox unavailable; backoff=%s", delay)
            time.sleep(delay)
            delay = min(delay * 2, 60)


if __name__ == "__main__":
    if sys.argv[1:] == ["--attempt"]:
        logging.basicConfig(level=logging.INFO)
        sys.exit(0 if dispatch_once(OutboxAPI(), publish) else 3)
    run()
