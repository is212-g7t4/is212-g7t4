"""User story (SCRUM-45): As an Event Organiser, I want in-app notification
when the Lead Coordinator rejects my event request, so I know the outcome
and who coordinates it. AC2/AC3: rejection reason, event name and details link.
DR2/DR3/DR4/DR5: atomic intent, retry identity, frozen facts and legacy diagnosis.
"""

import pytest
import subprocess
from uuid import uuid4
from tests.integration.delivery_system import (system, command, wait, HEADERS, TOKEN, ORGANISER, ACTOR, REASON)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

@pytest.mark.parametrize("route", ["reject", "progress"])
def test_real_rejection_outage_recovery_deduplication_and_recipient_isolation(system, route):
    """AC2/AC3/DR3/DR4/DR8: real mutation, PostgreSQL, Event Workflow HTTP
    worker, stopped/recovered RabbitMQ, consumer and inbox HTTP. Replay frozen
    publication and verify one read-preserving inbox row plus organiser details.
    """
    s = system
    command(["docker", "stop", s["rabbit"]])
    body = dict(coordinatorId=ACTOR)
    body.update(dict(reason=REASON) if route == "reject" else dict(status="Rejected", actionDetails=REASON))
    result = s["http"]("event-service", "PATCH", f"/events/{s['event']}/{route}", json=body)
    assert result.status_code == 200, result.text
    assert s["worker"](failure=True)  # Real publish outage; durable state survives.
    details = s["http"]("event-service", "GET", f"/events/{s['event']}?organiserId={ORGANISER}")
    assert details.json()["decision"]["reason"] == REASON
    command(["docker", "start", s["rabbit"]])
    wait(lambda: subprocess.run(["docker", "exec", "-u", "rabbitmq", s["rabbit"], "rabbitmq-diagnostics", "-q", "check_running"], capture_output=True, timeout=15).returncode == 0)
    s["start"]("notification-service", ["-m", "app.consumer"], "notifications")
    job = wait(lambda: s["http"]("event-service", "POST", "/internal/notification-outbox/claim", headers=HEADERS, json={}).json()["jobs"])[0]
    # The worker frozen envelope is immutable across the outage.
    envelope = job["envelope"]
    assert s["http"]("event-service", "POST", "/internal/notification-outbox/claim", headers=HEADERS, json={}).json()["jobs"] == []
    stale = s["http"]("event-service", "POST", f"/internal/notification-outbox/{job['id']}/published", headers=HEADERS,
                      json=dict(leaseToken=str(uuid4())))
    assert stale.status_code == 409
    freeze = s["http"]("event-service", "POST", f"/internal/notification-outbox/{job['id']}/freeze", headers=HEADERS,
                       json=dict(leaseToken=job["leaseToken"], envelope={"replacement": True}))
    assert freeze.json()["envelope"] == envelope
    assert envelope["recipientId"] == ORGANISER
    assert envelope["details"]["reason"] == REASON
    assert envelope["destination"] == dict(kind="event-details", eventId=s["event"])
    retry = s["http"]("event-service", "POST", f"/internal/notification-outbox/{job['id']}/retry", headers=HEADERS,
                      json=dict(leaseToken=job["leaseToken"], error="integration retry"))
    assert retry.status_code == 200
    # Empty claim exits 3 until retry availability; execute worker conditionally,
    # without stealing its lease or modifying the owner's scheduling table.
    wait(s["worker"])
    own = {"X-Dev-User-Id": ORGANISER, "X-Dev-Role": "Event Organiser"}
    inbox = lambda: s["http"]("notification-service", "GET", "/notifications", headers=own).json()["notifications"]
    items = wait(inbox)
    assert len(items) == 1
    assert items[0]["payload"] == envelope
    notification_id = items[0]["id"]
    assert s["http"]("notification-service", "PATCH", f"/notifications/{notification_id}", headers=own, json=dict(read=True)).status_code == 200
    read_at = inbox()[0]["readAt"]
    # Simulate lost published receipt: same immutable identity must deduplicate.
    s["replay"](envelope)
    wait(lambda: "notifications.v1\t0" in command(["docker", "exec", "-u", "rabbitmq", s["rabbit"], "rabbitmqctl", "list_queues", "-q", "name", "messages"]))
    assert inbox()[0]["readAt"] == read_at
    assert len(inbox()) == 1
    other = {"X-Dev-User-Id": ACTOR, "X-Dev-Role": "Event Coordinator"}
    assert s["http"]("notification-service", "GET", "/notifications", headers=other).json()["notifications"] == []
    assert s["http"]("event-service", "POST", "/internal/notification-outbox/claim", headers=HEADERS, json={}).json()["jobs"] == []


@pytest.mark.parametrize("route", ["reject", "progress"])
def test_failed_rejection_rolls_back_event_and_pending_work(system, route):
    """DR2: a real PostgreSQL intent-insert failure rolls back the mutation;
    observe original decision/status and no pending work via owner HTTP APIs.
    """
    s = system
    s["sql"]("events", '''CREATE FUNCTION fail_intent() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected isolated failure'; END $$;
        CREATE TRIGGER fail_intent BEFORE INSERT ON public."EventNotificationOutbox" FOR EACH ROW EXECUTE FUNCTION fail_intent();''')
    body = dict(coordinatorId=ACTOR)
    body.update(dict(reason=REASON) if route == "reject" else dict(status="Rejected", actionDetails=REASON))
    result = s["http"]("event-service", "PATCH", f"/events/{s['event']}/{route}", json=body)
    assert result.status_code == 503
    event = s["http"]("event-service", "GET", f"/events/{s['event']}?organiserId={ORGANISER}").json()
    assert event["status"] == "Under Review" and event["decision"] is None
    assert s["http"]("event-service", "POST", "/internal/notification-outbox/claim", headers=HEADERS, json={}).json()["jobs"] == []
