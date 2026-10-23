"""SCRUM-45 user story: As an Event Organiser, I want to receive an in-app
notification when the Lead Coordinator approves or rejects my event request,
so that I know the outcome and who is responsible for coordinating my event.
AC1/AC3/AC4; DR1 separate messages, DR2 durable intent, DR3 deduplication.
Uses isolated PostgreSQL/RabbitMQ and actual local User Service, never remote DB.
"""
from uuid import uuid4
import pytest
from e2e.scrum45.system import ACTOR, ORGANISER, ROOT, wait



@pytest.mark.parametrize("existing_rejection", [False, True], ids=["clean", "existing-rejection"])
@pytest.mark.parametrize("assignment_first", [False, True], ids=["chronological", "independent-order"])
def test_forward_migrations_preserve_all_notification_types(system, existing_rejection, assignment_first):
    """DR2: apply both forwards to clean/existing rejection-only PostgreSQL;
    both independent orders retain old work and accept all three new intents.
    """
    s = system
    migrations = ROOT / "database/supabase/migrations"
    s["sql"]("events", 'DROP TABLE public."EventNotificationOutbox"')
    s["sql"]("events", (migrations / "20261021000000_event_notification_outbox.sql").read_text())
    old_id = str(uuid4())
    if existing_rejection:
        s["sql"]("events", '''INSERT INTO public."EventNotificationOutbox" (source_id,type,source)
            VALUES (%s,'event.rejection','{"preserved":true}')''', (old_id,))
    forwards = ["20261021000100_event_approval_notifications.sql", "20261021020000_event_notification_assignments.sql"]
    if assignment_first:
        forwards.reverse()
    for migration in forwards:
        s["sql"]("events", (migrations / migration).read_text())
    for kind in ("event.rejection", "event.approval", "event.coordinator-assignment"):
        s["sql"]("events", 'INSERT INTO public."EventNotificationOutbox" (type,source) VALUES (%s,\'{}\')', (kind,))
    # Make the preservation assertion within PostgreSQL, rather than expose a
    # private raw database read API solely for this migration-only verification.
    if existing_rejection:
        s["sql"]("events", """DO $$ BEGIN IF NOT EXISTS (
            SELECT 1 FROM public."EventNotificationOutbox" WHERE source_id='%s'::uuid
            AND source='{"preserved":true}'::jsonb AND type='event.rejection')
            THEN RAISE EXCEPTION 'Existing rejection lost'; END IF; END $$;""" % old_id)


def test_initial_assignment_and_approval_deliver_distinct_updates(system):
    """DR1/AC1/AC4: record initial assignment then approval before delivery;
    real User lookup, broker and inbox preserve two distinct source identities.
    """
    s = system
    s["sql"]("events", '''UPDATE public."Event" SET coordinator_id=NULL,status='Submitted'
        WHERE event_id=%s''', (s["event"],))
    assigned = s["http"]("event-service", "PATCH", f"/events/{s['event']}",
        json=dict(assignedCoordinatorId=ACTOR, assignedBy=ORGANISER))
    assert assigned.status_code == 200, assigned.text
    approved = s["http"]("event-service", "PATCH", f"/events/{s['event']}/approve",
        json=dict(coordinatorId=ACTOR))
    assert approved.status_code == 200, approved.text
    s["start"]("notification-service", ["-m", "app.consumer"], "notifications")
    assert s["worker"]()
    assert s["worker"]()
    assert not s["worker"]()
    def inbox():
        return s["http"]("notification-service", "GET", "/notifications", headers={
            "X-Dev-User-Id": ORGANISER, "X-Dev-Role": "Event Organiser"}).json()["notifications"]
    wait(lambda: len(inbox()) == 2)
    updates = [item["payload"] for item in inbox()]
    assert {item["type"] for item in updates} == {"event.approval", "event.coordinator-assignment"}
    assert len({item["id"] for item in updates}) == 2
    for item in updates:
        assert item["recipientId"] == ORGANISER
        assert item["destination"] == dict(kind="event-details", eventId=s["event"])
        assert item["details"]["eventName"] == "Community Workshop"
    assignment = next(item for item in updates if item["type"] == "event.coordinator-assignment")
    assert assignment["details"]["coordinatorName"] == "Synthetic Event Coordinator"
    approval = next(item for item in updates if item["type"] == "event.approval")
    assert approval["details"]["decision"] == "Approved"
