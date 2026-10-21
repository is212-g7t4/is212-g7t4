"""SCRUM-45 user story: As a submitting Event Organiser I want an in-app
update naming my replacement coordinator, without rewriting earlier updates.
AC4 reassignment; DR2 no-op/rollback; DR3 retry/deduplication; DR4 frozen history.
Real Event/User/Notification HTTP services, isolated PostgreSQL and RabbitMQ.
"""
from uuid import uuid4

import pytest

from tests.integration.system import ACTOR, HEADERS, ORGANISER, command, wait

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
ALICE = "10000000-0000-0000-0000-000000000003"
BOB = "10000000-0000-0000-0000-000000000004"


def assign(s, coordinator):
    return s["http"]("event-service", "PATCH", f"/events/{s['event']}",
        json=dict(assignedCoordinatorId=coordinator, assignedBy=ORGANISER))


def inbox(s, recipient=ORGANISER):
    return s["http"]("notification-service", "GET", "/notifications", headers={
        "X-Dev-User-Id": recipient, "X-Dev-Role": "Event Organiser"}).json()["notifications"]


def seed_replacements(s):
    for database in ("events", "users"):
        for identity, name in ((ALICE, "Alice Tan"), (BOB, "Bob Lim")):
            s["sql"](database, 'INSERT INTO public."User"(user_id,username,role) VALUES (%s,%s,%s)',
                (identity, name, "Event Coordinator"))


def test_rapid_reassignments_keep_saved_identity_and_frozen_name_across_retry(system):
    """AC4/DR3/DR4: record Alice then Bob on one event before preparation;
    freeze both during a real broker outage, rename users/event, recover and
    observe independent historical names/IDs/content through the inbox API.
    """
    import subprocess
    s = system
    seed_replacements(s)
    assert assign(s, ALICE).status_code == 200
    assert assign(s, BOB).status_code == 200
    assert assign(s, BOB).status_code == 409
    current = s["http"]("event-service", "GET", f"/events/{s['event']}?organiserId={ORGANISER}")
    assert current.json()["coordinatorId"] == BOB
    command(["docker", "stop", s["rabbit"]])
    assert s["worker"](failure=True)
    assert s["worker"](failure=True)
    # Claims deliberately return one leased change at a time. Keep each lease
    # until both historical envelopes have been observed through Event's API.
    jobs = []
    for _ in range(2):
        jobs.extend(wait(lambda: s["http"]("event-service", "POST",
            "/internal/notification-outbox/claim", headers=HEADERS, json={}).json()["jobs"]))
    assert len(jobs) == 2
    frozen = {job["source"]["coordinatorId"]: job["envelope"] for job in jobs}
    assert set(frozen) == {ALICE, BOB}
    assert len({job["id"] for job in jobs}) == 2
    for identity, name in ((ALICE, "Alice Tan"), (BOB, "Bob Lim")):
        payload = frozen[identity]
        assert payload["details"] == dict(eventId=s["event"], eventName="Community Workshop",
            recipientId=ORGANISER, coordinatorId=identity, coordinatorName=name)
        assert payload["message"] == f"{name} has been assigned to coordinate Community Workshop."
        assert payload["destination"] == dict(kind="event-details", eventId=s["event"])
        assert payload["type"] == "event.coordinator-assignment"
    for job in jobs:
        result = s["http"]("event-service", "POST", f"/internal/notification-outbox/{job['id']}/retry",
            headers=HEADERS, json=dict(leaseToken=job["leaseToken"], error="isolated retry"))
        assert result.status_code == 200
    s["sql"]("users", 'UPDATE public."User" SET username=%s WHERE user_id IN (%s,%s)',
        ("Renamed after freeze", ALICE, BOB))
    s["sql"]("events", 'UPDATE public."Event" SET event_name=%s WHERE event_id=%s',
        ("Renamed after assignment", s["event"]))
    command(["docker", "start", s["rabbit"]])
    wait(lambda: subprocess.run(["docker", "exec", "-u", "rabbitmq", s["rabbit"], "rabbitmq-diagnostics", "-q", "check_running"], capture_output=True, timeout=15).returncode == 0)
    s["start"]("notification-service", ["-m", "app.consumer"], "notifications")
    wait(s["worker"])
    wait(s["worker"])
    wait(lambda: len(inbox(s)) == 2)
    assert {item["payload"]["details"]["coordinatorId"]: item["payload"] for item in inbox(s)} == frozen
    assert inbox(s, ACTOR) == []
    assert not s["worker"](), "No-op must not add notification work"
    # Replay both changes plus a FIFO sentinel; observing the sentinel proves
    # the consumer has processed the preceding duplicates, without fixed sleeps.
    for payload in frozen.values():
        s["replay"](payload)
    sentinel = {**frozen[BOB], "id": str(uuid4()), "message": "FIFO sentinel"}
    s["replay"](sentinel)
    wait(lambda: len(inbox(s)) == 3)
    for payload in frozen.values():
        assert len([item for item in inbox(s) if item["payload"]["id"] == payload["id"]]) == 1


def test_failed_reassignment_rolls_back_current_coordinator_and_leaves_no_delivery(system):
    """DR2: force real outbox insertion failure after mutation; owning event
    read and pending API show original coordinator, no work and no inbox item.
    """
    s = system
    seed_replacements(s)
    s["sql"]("events", """CREATE FUNCTION fail_reassignment_intent() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'isolated test failure'; END $$;
        CREATE TRIGGER fail_reassignment_intent BEFORE INSERT ON public."EventNotificationOutbox" FOR EACH ROW EXECUTE FUNCTION fail_reassignment_intent();""")
    assert assign(s, ALICE).status_code == 503
    event = s["http"]("event-service", "GET", f"/events/{s['event']}?organiserId={ORGANISER}").json()
    assert event["coordinatorId"] == ACTOR and event["status"] == "Under Review"
    assert s["http"]("event-service", "POST", "/internal/notification-outbox/claim", headers=HEADERS, json={}).json()["jobs"] == []
    assert not s["worker"]()
    assert inbox(s) == []
