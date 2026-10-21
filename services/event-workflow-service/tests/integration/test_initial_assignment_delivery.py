"""SCRUM-45 user story: As an Event Organiser I want an in-app update naming
my initial coordinator. AC4; DR2 transaction, DR3 real delivery/deduplication,
DR4 historical identity and DR6 name repair. Real PostgreSQL/RabbitMQ and real
User Service HTTP against its own isolated local database; no mock User server.
"""
import pytest
from tests.integration.delivery_system import system, wait, HEADERS, ORGANISER, ACTOR

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


def initial_event(s):
    s["sql"]("events", """UPDATE public."Event" SET coordinator_id=NULL,status='Submitted' WHERE event_id=%s""", (s["event"],))

def assign(s):
    return s["http"]("event-service", "PATCH", f"/events/{s['event']}",
        json=dict(assignedCoordinatorId=ACTOR, assignedBy=ORGANISER))

def inbox(s):
    return s["http"]("notification-service", "GET", "/notifications", headers={
        "X-Dev-User-Id": ORGANISER, "X-Dev-Role": "Event Organiser"}).json()["notifications"]


def test_real_initial_assignment_delivers_username_event_link_and_deduplicates(system):
    """AC4/DR3/DR4: real assignment -> owner DB -> HTTP worker -> real User
    lookup -> RabbitMQ -> consumer -> inbox API; replay yields one inbox item.
    """
    s = system
    initial_event(s)
    user = s["http"]("user-service", "GET", f"/users/{ACTOR}")
    assert user.status_code == 200 and user.json()["username"] == "Synthetic Event Coordinator"
    assert "name" not in user.json()
    result = assign(s)
    assert result.status_code == 200, result.text
    assert s["worker"]()
    s["start"]("notification-service", ["-m", "app.consumer"], "notifications")
    items = wait(lambda: inbox(s))
    assert len(items) == 1
    payload = items[0]["payload"]
    assert payload["type"] == "event.coordinator-assignment"
    assert payload["details"] == dict(eventId=s["event"], eventName="Community Workshop",
        recipientId=ORGANISER, coordinatorId=ACTOR, coordinatorName="Synthetic Event Coordinator")
    assert payload["message"] == "Synthetic Event Coordinator has been assigned to coordinate Community Workshop."
    assert payload["destination"] == dict(kind="event-details", eventId=s["event"])
    assert assign(s).status_code == 409
    assert not s["worker"]()
    s["replay"](payload)
    # A subsequent FIFO sentinel publication makes duplicate consumption observable.
    from uuid import uuid4
    sentinel = {**payload, "id": str(uuid4()), "message": payload["message"] + " sentinel"}
    s["replay"](sentinel)
    wait(lambda: len(inbox(s)) == 2)
    assert len([item for item in inbox(s) if item["payload"]["id"] == payload["id"]]) == 1
    other = s["http"]("notification-service", "GET", "/notifications", headers={
        "X-Dev-User-Id": ACTOR, "X-Dev-Role": "Event Coordinator"})
    assert other.json()["notifications"] == []


@pytest.mark.parametrize("missing", [True, False], ids=["missing-user", "blank-username"])
def test_real_name_hold_does_not_block_rejection_and_can_be_repaired(system, missing):
    """DR6/AC4: real User 404/blank username holds initial assignment in Event;
    rejection still reaches inbox; authenticated repair release delivers saved ID.
    """
    s = system
    initial_event(s)
    if missing:
        s["sql"]("users", 'DELETE FROM public."User" WHERE user_id=%s', (ACTOR,))
    else:
        s["sql"]("users", 'UPDATE public."User" SET username=%s WHERE user_id=%s', ("   ", ACTOR))
    assert assign(s).status_code == 200
    assert s["worker"]()
    held = s["http"]("event-service", "GET", "/internal/notification-outbox/held", headers=HEADERS)
    assert held.status_code == 200
    jobs = held.json()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["error"] == f"CoordinatorNameUnavailable coordinatorId={ACTOR}"
    assert jobs[0]["source"] == dict(eventId=s["event"], eventName="Community Workshop", recipientId=ORGANISER, coordinatorId=ACTOR)
    assert not s["worker"]()
    assert inbox(s) == []
    rejection = s["http"]("event-service", "PATCH", f"/events/{s['event']}/reject",
        json=dict(coordinatorId=ACTOR, reason="Missing plan"))
    assert rejection.status_code == 200
    s["start"]("notification-service", ["-m", "app.consumer"], "notifications")
    assert s["worker"]()
    items = wait(lambda: inbox(s))
    assert len(items) == 1 and items[0]["payload"]["type"] == "event.rejection"
    if missing:
        s["sql"]("users", 'INSERT INTO public."User"(user_id,username,role) VALUES (%s,%s,%s)', (ACTOR, "Repaired Alice", "Event Coordinator"))
    else:
        s["sql"]("users", 'UPDATE public."User" SET username=%s WHERE user_id=%s', ("Repaired Alice", ACTOR))
    release = s["http"]("event-service", "POST", f"/internal/notification-outbox/{jobs[0]['id']}/release", headers=HEADERS, json={})
    assert release.status_code == 200
    assert s["http"]("event-service", "GET", "/internal/notification-outbox/held", headers=HEADERS).json()["jobs"] == []
    assert s["worker"]()
    wait(lambda: len(inbox(s)) == 2)
    assignment = next(item["payload"] for item in inbox(s) if item["payload"]["type"] == "event.coordinator-assignment")
    assert assignment["id"] == jobs[0]["id"]
    assert assignment["details"]["coordinatorName"] == "Repaired Alice"
    assert assignment["details"]["coordinatorId"] == ACTOR


def test_real_failed_assignment_rolls_back_event_and_intent(system):
    """DR2: actual PostgreSQL trigger failure on intent insert rolls back
    coordinator/status change; owning read/claim APIs expose original state.
    """
    s = system
    initial_event(s)
    s["sql"]("events", """CREATE FUNCTION fail_assignment_intent() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'isolated test failure'; END $$;
        CREATE TRIGGER fail_assignment_intent BEFORE INSERT ON public."EventNotificationOutbox" FOR EACH ROW EXECUTE FUNCTION fail_assignment_intent();""")
    assert assign(s).status_code == 503
    event = s["http"]("event-service", "GET", f"/events/{s['event']}?organiserId={ORGANISER}").json()
    assert event["coordinatorId"] is None and event["status"] == "Submitted"
    assert s["http"]("event-service", "POST", "/internal/notification-outbox/claim", headers=HEADERS, json={}).json()["jobs"] == []


def test_real_user_outage_retries_and_broker_retry_preserves_first_prepared_name(system):
    """AC4/DR3/DR4/DR6: real User 503 retries; recovery prepares saved user,
    real broker outage freezes name; rename user and recover broker, inbox keeps
    the first prepared name without depending on current User display content.
    """
    from tests.integration.delivery_system import command
    import subprocess
    s = system
    initial_event(s)
    s["sql"]("users", 'ALTER TABLE public."User" RENAME TO "RepairUser"')
    assert assign(s).status_code == 200
    assert s["worker"](failure=True)
    assert inbox(s) == []
    assert s["http"]("event-service", "GET", "/internal/notification-outbox/held", headers=HEADERS).json()["jobs"] == []
    s["sql"]("users", 'ALTER TABLE public."RepairUser" RENAME TO "User"')
    command(["docker", "stop", s["rabbit"]])
    wait(lambda: s["worker"](failure=True))
    s["sql"]("users", 'UPDATE public."User" SET username=%s WHERE user_id=%s', ("Renamed after freeze", ACTOR))
    command(["docker", "start", s["rabbit"]])
    wait(lambda: subprocess.run(["docker", "exec", "-u", "rabbitmq", s["rabbit"], "rabbitmq-diagnostics", "-q", "check_running"], capture_output=True, timeout=15).returncode == 0)
    s["start"]("notification-service", ["-m", "app.consumer"], "notifications")
    wait(s["worker"])
    items = wait(lambda: inbox(s))
    assert len(items) == 1
    assert items[0]["payload"]["details"]["coordinatorName"] == "Synthetic Event Coordinator"
    assert items[0]["payload"]["message"] == "Synthetic Event Coordinator has been assigned to coordinate Community Workshop."
