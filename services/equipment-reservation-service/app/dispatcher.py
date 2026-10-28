"""Equipment notification orchestration; only HTTP accesses atomic state.
Run separately with python -m app.dispatcher. Unknown publication is retried
with the same frozen identity; broker acceptance is not inbox delivery.
"""

import json
import logging
import os
import subprocess
import sys
import time
import httpx
import pika

LOG = logging.getLogger(__name__)
QUEUE = "notifications.v1"


class OutboxAPI:
    def __init__(self):
        self.base = os.environ["EQUIPMENT_REQUEST_SERVICE_URL"].rstrip("/")
        self.headers = {"X-Internal-Token": os.environ["INTERNAL_SERVICE_TOKEN"]}

    def call(self, path, data):
        response = httpx.request("POST", self.base + path, headers=self.headers, timeout=5, json=data)
        response.raise_for_status()
        return response.json()

    def claim(self):
        return self.call("/internal/notification-outbox/claim", {})["jobs"]

    def operation(self, job, action, **data):
        return self.call(f"/internal/notification-outbox/{job['id']}/{action}",
                         {"leaseToken": job["leaseToken"], **data})

    def published(self, job):
        return self.operation(job, "published")

    def retry(self, job, error):
        return self.operation(job, "retry", error=error)


def dispatch_once(api, publish):
    jobs = api.claim()
    for job in jobs:
        try:
            # The owning transaction already froze recipient, content and destination.
            envelope = job["envelope"]
            if envelope is None:
                raise ValueError("Missing frozen equipment envelope")
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
