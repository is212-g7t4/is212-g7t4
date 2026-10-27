"""Event Workflow notification worker public boundary."""

import json
import logging
import os
import subprocess
import sys
import time
from uuid import UUID
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pika

QUEUE = "notifications.v1"

LOG = logging.getLogger(__name__)

class CoordinatorNameUnavailable(Exception):
    """Saved coordinator cannot be named; retain intent for operator repair."""


class OrganiserNameUnavailable(Exception):
    """Coordinator delivery remains held until its organiser can be named."""


class OutboxAPI:
    def __init__(self):
        self.base = os.environ["EVENT_SERVICE_URL"].rstrip("/")
        self.headers = {"X-Internal-Token": os.environ["INTERNAL_SERVICE_TOKEN"]}

    def call(self, method, url, **kwargs):
        response = httpx.request(method, url, headers=self.headers, timeout=5, **kwargs)
        response.raise_for_status()
        return response.json()

    def coordinator_name(self, identifier):
        try:
            user = self.call("GET", os.environ["USER_SERVICE_URL"].rstrip("/") + f"/users/{identifier}")
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 404:
                raise CoordinatorNameUnavailable from error
            raise
        name = user.get("username") if isinstance(user, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise CoordinatorNameUnavailable
        return name

    def submission_recipients(self):
        users = self.call("GET", os.environ["USER_SERVICE_URL"].rstrip("/") + "/users",
                          params={"role": "Event Coordinator Lead"})["users"]
        if not isinstance(users, list):
            raise ValueError("Invalid Lead lookup")
        # Validate the entire response before acknowledging zero recipients.
        recipients = []
        for user in users:
            if user.get("role") != "Event Coordinator Lead":
                raise ValueError("Invalid Lead role")
            recipients.append(str(UUID(user["user_id"])))
        return recipients

    def organiser_name(self, identifier):
        user = self.call("GET", os.environ["USER_SERVICE_URL"].rstrip("/") + f"/users/{identifier}")
        name = user.get("username") if isinstance(user, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Missing organiser name")
        return name

    def claim(self):
        return self.call(
            "POST", self.base + "/internal/notification-outbox/claim", json={}
        )["jobs"]

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

    def hold(self, job, error):
        return self.operation(job, "hold", error=error)

    def retry(self, job, error):
        return self.operation(job, "retry", error=error)

def coordinator_message(source, name, removed=False):
    """Freeze a complete, UI-independent proposed-period description in Singapore time."""
    def stamp(value):
        return datetime.fromisoformat(value).astimezone(ZoneInfo("Asia/Singapore")).strftime("%d %b %Y, %H:%M SGT")

    period = (stamp(source["startDateTime"]) + " – " + stamp(source["endDateTime"])
              if source.get("startDateTime") and source.get("endDateTime") else "Not provided")
    action = "You are no longer assigned to" if removed else "You have been assigned to"
    return f"{action} {source['eventName']}. Event Organiser: {name}. Proposed: {period}."


def dispatch_once(api, publish):
    jobs = api.claim()
    for job in jobs:
        try:
            if job.get("type") == "event.submission-fanout":
                recipients = api.submission_recipients()
                if not recipients:
                    LOG.warning("Submission skipped: no Event Coordinator Lead source=%s", job["id"])
                # No recipient means no user-visible content needs enrichment.
                name = api.organiser_name(job["source"]["organiserId"]) if recipients else "No recipients"
                api.operation(job, "expand", recipientIds=recipients, organiserName=name)
                continue
            envelope = job["envelope"]
            if envelope is None:
                source = job["source"]
                kind = job.get("type", "event.approval" if source.get("decision") == "Approved" else "event.rejection")
                details = source
                if kind == "event.submission":
                    message = f"{source['organiserName']} submitted {source['eventName']}. Review required."
                elif kind == "event.coordinator-assignment":
                    name = api.coordinator_name(source["coordinatorId"])
                    details = {**source, "coordinatorName": name}
                    message = f"{name} has been assigned to coordinate {source['eventName']}."
                elif kind in ("event.coordinator-assigned", "event.coordinator-removed"):
                    if not source.get("organiserId"):
                        raise OrganiserNameUnavailable
                    try:
                        name = api.organiser_name(source["organiserId"])
                    except httpx.HTTPStatusError as error:
                        if error.response.status_code == 404:
                            raise OrganiserNameUnavailable from error
                        raise
                    except ValueError as error:
                        raise OrganiserNameUnavailable from error
                    details = {**source, "organiserName": name}
                    message = coordinator_message(source, name, kind == "event.coordinator-removed")
                elif kind == "event.approval":
                    message = f"{source['eventName']} was approved"
                else:
                    message = f"{source['eventName']} was rejected: {source['reason']}"
                envelope = dict(
                    version=1, id=job["id"], type=kind,
                    recipientId=source["recipientId"], createdAt=job["createdAt"],
                    message=message,
                    destination=(None if kind == "event.coordinator-removed" else
                                 dict(kind="event-details", eventId=source["eventId"])),
                    details=details,
                )
                envelope = api.freeze(job, envelope)
            publish(envelope)
            api.published(job)
        except OrganiserNameUnavailable:
            diagnosis = f"OrganiserNameUnavailable organiserId={job['source'].get('organiserId')}"
            LOG.warning("Dispatch hold source=%s error=%s", job["id"], diagnosis)
            try:
                api.hold(job, diagnosis)
            except Exception:
                LOG.warning("Hold update failed; lease will recover source=%s", job["id"])
        except CoordinatorNameUnavailable:
            diagnosis = f"CoordinatorNameUnavailable coordinatorId={job['source']['coordinatorId']}"
            LOG.warning("Dispatch hold source=%s error=%s", job["id"], diagnosis)
            try:
                api.hold(job, diagnosis)
            except Exception:
                LOG.warning("Hold update failed; lease will recover source=%s", job["id"])
        except Exception as error:
            LOG.warning("Dispatch retry source=%s error=%s", job["id"], type(error).__name__)
            try:
                api.retry(job, type(error).__name__)
            except Exception:
                LOG.warning("Retry update failed; lease will recover source=%s", job["id"])
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
