"""SCRUM-45 user story: As an Event Organiser, I want to receive an in-app
notification when the Lead Coordinator approves or rejects my event request,
so that I know the outcome and who is responsible for coordinating my event.
AC1/AC3 approval delivery and details; DR2 atomic intent; DR4 saved facts.
"""
import subprocess
import pytest
from tests.integration.system import ACTOR, ORGANISER, HEADERS, command, wait

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


@pytest.mark.parametrize("route", ["approve", "progress"])
def test_real_approval_is_retrievable_after_broker_outage_with_saved_facts(system, route):
    """AC1/AC3/DR3/DR4/DR8: real owner HTTP, isolated PostgreSQL, worker,
    stopped/recovered RabbitMQ and consumer inbox API prove saved historical
    name/recipient, persistent delivery, read-preserving replay and isolation.
    """
    s = system
    command(["docker", "stop", s["rabbit"]])
    body = dict(coordinatorId=ACTOR)
    if route == "progress":
        body.update(status="Approved", actionDetails="Ready for approval")
    result = s["http"]("event-service", "PATCH", f"/events/{s['event']}/{route}", json=body)
    assert result.status_code == 200, result.text
    details = s["http"]("event-service", "GET", f"/events/{s['event']}?organiserId={ORGANISER}").json()
    assert details["decision"]["status"] == "Approved"
    assert details["decision"]["reason"] is None
    # Fixture-only concurrent changes must not rewrite the saved notification facts.
    s["sql"]("events", 'UPDATE public."Event" SET event_name=%s, organiser_id=%s WHERE event_id=%s',
             ("Renamed after approval", ACTOR, s["event"]))
    assert s["worker"](failure=True)
    command(["docker", "start", s["rabbit"]])
    wait(lambda: subprocess.run(["docker", "exec", "-u", "rabbitmq", s["rabbit"], "rabbitmq-diagnostics", "-q", "check_running"], capture_output=True, timeout=15).returncode == 0)
    s["start"]("notification-service", ["-m", "app.consumer"], "notifications")
    wait(s["worker"])
    own = {"X-Dev-User-Id": ORGANISER, "X-Dev-Role": "Event Organiser"}
    def inbox():
        return s["http"]("notification-service", "GET", "/notifications", headers=own).json()["notifications"]
    items = wait(inbox)
    assert len(items) == 1
    envelope = items[0]["payload"]
    assert envelope["type"] == "event.approval"
    assert envelope["recipientId"] == ORGANISER
    assert envelope["message"] == "Community Workshop was approved"
    assert envelope["details"] == dict(eventId=s["event"], eventName="Community Workshop",
                                        recipientId=ORGANISER, decision="Approved")
    assert envelope["destination"] == dict(kind="event-details", eventId=s["event"])
    assert s["http"]("notification-service", "PATCH", f"/notifications/{items[0]['id']}", headers=own, json=dict(read=True)).status_code == 200
    read_at = inbox()[0]["readAt"]
    s["replay"](envelope)
    wait(lambda: "notifications.v1\t0" in command(["docker", "exec", "-u", "rabbitmq", s["rabbit"], "rabbitmqctl", "list_queues", "-q", "name", "messages"]))
    assert len(inbox()) == 1
    assert inbox()[0]["readAt"] == read_at
    other = {"X-Dev-User-Id": ACTOR, "X-Dev-Role": "Event Coordinator"}
    assert s["http"]("notification-service", "GET", "/notifications", headers=other).json()["notifications"] == []
    assert s["http"]("event-service", "POST", "/internal/notification-outbox/claim", headers=HEADERS, json={}).json()["jobs"] == []


@pytest.mark.parametrize("route", ["approve", "progress"])
def test_failed_approval_rolls_back_event_and_pending_work(system, route):
    """DR2: PostgreSQL intent trigger fails; owner APIs show original status,
    no decision and no pending work, proving event and intent roll back together.
    """
    s = system
    s["sql"]("events", '''CREATE FUNCTION fail_intent() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'isolated injected failure'; END $$;
        CREATE TRIGGER fail_intent BEFORE INSERT ON public."EventNotificationOutbox" FOR EACH ROW EXECUTE FUNCTION fail_intent();''')
    body = dict(coordinatorId=ACTOR)
    if route == "progress":
        body.update(status="Approved", actionDetails="Ready for approval")
    result = s["http"]("event-service", "PATCH", f"/events/{s['event']}/{route}", json=body)
    assert result.status_code == 503
    event = s["http"]("event-service", "GET", f"/events/{s['event']}?organiserId={ORGANISER}").json()
    assert event["status"] == "Under Review" and event["decision"] is None
    assert s["http"]("event-service", "POST", "/internal/notification-outbox/claim", headers=HEADERS, json={}).json()["jobs"] == []
