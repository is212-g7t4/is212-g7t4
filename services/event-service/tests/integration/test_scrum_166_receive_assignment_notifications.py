"""SCRUM-166 — Receive assignment notifications.

As an Event Coordinator, I want to receive in-app notifications when I am assigned to or removed from an event, so that I know which events I am responsible for.

- **AC1:** Given the Lead Coordinator successfully assigns an Event Coordinator to an event that previously had no assigned coordinator, the assigned coordinator receives an in-app assignment notification.
- **AC2:** Given the Lead Coordinator successfully reassigns an event from one coordinator to a different coordinator:
  - The new coordinator receives an in-app notification that they have been assigned.
  - The previous coordinator receives an in-app notification that they have been removed.
- **AC3:** Assignment notifications include the event name, Event Organiser name, proposed event date/time, and a link to view the newly assigned event.
- **AC4:** Removal notifications include the event name, Event Organiser name, proposed event date/time, and a clear statement that the recipient is no longer assigned to the event.
- **AC5:** Saving an assignment without changing the assigned coordinator does not create new assignment or removal notifications.

AC = acceptance criterion; DR = supporting design rule.
AC1/AC2: covered through saved coordinator obligations, not end-to-end delivery;
Notification integration verifies the private committed inbox. AC3/AC4: saved
facts/freeze only; Workflow unit/adapter tests verify enriched display content,
and frontend component tests cover presentation, not live event navigation.
AC5: covered here through unchanged Event/outbox snapshots.

Real: Event Flask API, SQL and fixture-owned PostgreSQL with full migrations.
Doubled: no outside service is called. Not proven: Lead composite, broker, inbox or UI.
"""

import pytest
from tests.integration.factories import (
    ORGANISER_ID, COORDINATOR_ID, LEAD_ID, make_event, make_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
HEADERS = {"X-Internal-Token": "scrum166-isolated-token"}

@pytest.fixture(autouse=True)
def actors(client, db):
    client.application.config["INTERNAL_SERVICE_TOKEN"] = HEADERS["X-Internal-Token"]
    for identifier, role in [(ORGANISER_ID, "Event Organiser"),
                             (COORDINATOR_ID, "Event Coordinator"),
                             (LEAD_ID, "Event Coordinator Lead")]:
        make_user(db, identifier, role)


def assign(client, event, recipient):
    return client.patch(f"/events/{event}", json={
        "assignedCoordinatorId": recipient, "assignedBy": LEAD_ID})


def pending(db):
    return db.execute('SELECT * FROM public."EventNotificationOutbox" ORDER BY created_at,source_id')


def coordinator_rows(db):
    return [row for row in pending(db) if row["type"] in
            ("event.coordinator-assigned", "event.coordinator-removed")]


# AC1 — Initial assignment

def test_ac1_initial_assignment_saves_coordinator_obligation(client, db):
    """Assign an unassigned event through Event's API.
    The saved event and coordinator obligation agree; organiser work is retained.
    """
    event = make_event(db, status="Submitted", event_name="Community Workshop",
                       start="2030-03-01T01:00:00Z", end="2030-03-01T09:00:00Z")
    response = assign(client, event, COORDINATOR_ID)
    assert response.status_code == 200, response.json
    assert str(db.event(event)["coordinator_id"]) == COORDINATOR_ID
    rows = coordinator_rows(db)
    assert len(rows) == 1
    assert rows[0]["type"] == "event.coordinator-assigned"
    assert rows[0]["source"] == dict(eventId=event, eventName="Community Workshop",
        organiserId=ORGANISER_ID, recipientId=COORDINATOR_ID,
        startDateTime="2030-03-01T09:00:00+08:00", endDateTime="2030-03-01T17:00:00+08:00")
    organiser = [row for row in pending(db) if row["type"] == "event.coordinator-assignment"]
    assert len(organiser) == 1
    assert organiser[0]["source"]["recipientId"] == ORGANISER_ID
    job = None
    for _ in range(2):
        jobs = client.post("/internal/notification-outbox/claim", headers=HEADERS, json={}).json["jobs"]
        if jobs[0]["type"] == "event.coordinator-assigned":
            job = jobs[0]
            break
    assert job is not None
    envelope = dict(version=1, id=job["id"], type=job["type"], recipientId=COORDINATOR_ID,
        createdAt=job["createdAt"], destination=dict(kind="event-details", eventId=event),
        details={**job["source"], "organiserName": "Synthetic Organiser"},
        message="You have been assigned to Community Workshop. Event Organiser: Synthetic Organiser. "
                "Proposed: 01 Mar 2030, 09:00 SGT – 01 Mar 2030, 17:00 SGT.")
    frozen = client.post(f"/internal/notification-outbox/{job['id']}/freeze", headers=HEADERS,
                         json=dict(leaseToken=job["leaseToken"], envelope=envelope))
    assert frozen.status_code == 200, frozen.json
    assert frozen.json["envelope"] == envelope
    assert coordinator_rows(db)[0]["envelope"] == envelope
    linked = client.get(f"/events/{envelope['destination']['eventId']}",
                        query_string={"coordinatorId": COORDINATOR_ID})
    assert linked.status_code == 200
    assert linked.json["id"] == event

# AC2 — Reassignment

def test_ac2_reassignment_saves_both_recipients_and_removal_can_freeze(client, db):
    """Reassign A to B and freeze the old recipient's content-only removal.
    Two independent coordinator obligations and the organiser update remain saved.
    """
    event = make_event(db, status="Under Review", coordinator_id=COORDINATOR_ID)
    response = assign(client, event, LEAD_ID)
    assert response.status_code == 200, response.json
    assert str(db.event(event)["coordinator_id"]) == LEAD_ID
    current = client.get(f"/events/{event}", query_string={"coordinatorId": LEAD_ID})
    former = client.get(f"/events/{event}", query_string={"coordinatorId": COORDINATOR_ID})
    assert current.status_code == 200 and current.json["id"] == event
    assert former.status_code == 403  # No viewerRole bypass for either request.
    rows = coordinator_rows(db)
    assert {(row["type"], row["source"]["recipientId"]) for row in rows} == {
        ("event.coordinator-assigned", LEAD_ID), ("event.coordinator-removed", COORDINATOR_ID)}
    assert len({row["source_id"] for row in pending(db)}) == 3
    assert len([row for row in pending(db) if row["type"] == "event.coordinator-assignment"
                and row["source"]["recipientId"] == ORGANISER_ID]) == 1
    job = None
    for _ in range(3):
        claimed = client.post("/internal/notification-outbox/claim", headers=HEADERS, json={}).json["jobs"]
        if claimed[0]["type"] == "event.coordinator-removed":
            job = claimed[0]
            break
    assert job is not None
    envelope = dict(version=1, id=job["id"], type=job["type"], recipientId=COORDINATOR_ID,
        createdAt=job["createdAt"], destination=None,
        details={**job["source"], "organiserName": "Synthetic Organiser"},
        message="You are no longer assigned to Spring Fair. Event Organiser: Synthetic Organiser. Proposed: Not provided.")
    frozen = client.post(f"/internal/notification-outbox/{job['id']}/freeze", headers=HEADERS,
                         json=dict(leaseToken=job["leaseToken"], envelope=envelope))
    assert frozen.status_code == 200, frozen.json
    assert frozen.json["envelope"] == envelope
    assert next(row for row in coordinator_rows(db) if row["type"] == "event.coordinator-removed")["envelope"] == envelope


# AC3/AC4 — Historical owner facts survive subsequent detail edits

def test_ac3_ac4_captured_facts_survive_later_event_edits(client, db):
    """Edit name and proposed schedule after reassignment, before dispatch preparation.
    Both recipients' saved facts and frozen messages retain the assignment-time values.
    """
    # Arrange: capture obligations before any later detail mutation.
    event = make_event(db, status="Under Review", coordinator_id=COORDINATOR_ID,
                       event_name="Community Workshop", description="Hands-on activities", purpose="Learning",
                       expected_attendance=25, start="2030-03-01T01:00:00Z", end="2030-03-01T09:00:00Z")
    assert assign(client, event, LEAD_ID).status_code == 200
    original = pending(db)
    # Act: edit through the owning public API, not a mutable dispatcher lookup.
    changed = client.patch(f"/events/{event}/details", json={"coordinatorId": LEAD_ID,
        "changes": {"eventName": "Later exhibition", "preferredStartDate": "2031-04-02T10:00",
                    "preferredEndDate": "2031-04-02T18:00"}})
    assert changed.status_code == 200, changed.json
    assert changed.json["eventName"] == "Later exhibition"
    assert changed.json["preferredStartDate"].startswith("2031-04-02T10:00")
    assert changed.json["preferredEndDate"].startswith("2031-04-02T18:00")
    # Assert: original source rows survive; owner freeze accepts only those saved facts.
    assert pending(db) == original
    jobs = []
    for _ in range(3):
        jobs.extend(client.post("/internal/notification-outbox/claim", headers=HEADERS, json={}).json["jobs"])
    captured = [job for job in jobs if job["type"] in ("event.coordinator-assigned", "event.coordinator-removed")]
    assert len(captured) == 2
    for job in captured:
        removed = job["type"] == "event.coordinator-removed"
        recipient = COORDINATOR_ID if removed else LEAD_ID
        facts = dict(eventId=event, eventName="Community Workshop", organiserId=ORGANISER_ID,
                     recipientId=recipient, startDateTime="2030-03-01T09:00:00+08:00",
                     endDateTime="2030-03-01T17:00:00+08:00")
        assert job["source"] == facts
        action = "You are no longer assigned to" if removed else "You have been assigned to"
        envelope = dict(version=1, id=job["id"], type=job["type"], recipientId=recipient,
                        createdAt=job["createdAt"], details={**facts, "organiserName": "Synthetic Organiser"},
                        destination=None if removed else dict(kind="event-details", eventId=event),
                        message=f"{action} Community Workshop. Event Organiser: Synthetic Organiser. "
                                "Proposed: 01 Mar 2030, 09:00 SGT – 01 Mar 2030, 17:00 SGT.")
        response = client.post(f"/internal/notification-outbox/{job['id']}/freeze", headers=HEADERS,
                               json=dict(leaseToken=job["leaseToken"], envelope=envelope))
        assert response.status_code == 200, response.json
        saved = db.execute('SELECT source,envelope FROM public."EventNotificationOutbox" WHERE source_id=%s', [job["id"]])
        assert saved == [dict(source=facts, envelope=envelope)]

# AC5 — Unchanged assignment

def test_ac5_unchanged_assignment_leaves_event_and_all_obligations_untouched(client, db):
    """Save the same coordinator after a successful assignment.
    Complete event and outbox snapshots stay identical, including organiser work.
    """
    event = make_event(db, status="Submitted")
    assert assign(client, event, COORDINATOR_ID).status_code == 200
    before_event, before_outbox = db.event(event), pending(db)
    assert assign(client, event, COORDINATOR_ID).status_code == 409
    assert db.event(event) == before_event
    assert pending(db) == before_outbox


# Supporting design rule — atomic fanout rollback

def test_dr_second_recipient_insert_failure_rolls_back_assignment_and_all_intents(client, db):
    """Reject removal insertion after assignment and organiser inserts during reassignment.
    PostgreSQL rolls back the event and every new intent, not merely the failed row.
    """
    event = make_event(db, status="Under Review", coordinator_id=COORDINATOR_ID)
    before_event, before_outbox = db.event(event), pending(db)
    db.execute('''CREATE SEQUENCE scrum166_insertion_observed;
       CREATE FUNCTION scrum166_fail_second_recipient() RETURNS trigger LANGUAGE plpgsql AS $$
       BEGIN IF NEW.type = 'event.coordinator-removed' THEN
         IF (SELECT count(*) FROM public."EventNotificationOutbox"
             WHERE type = 'event.coordinator-assigned') <> 1 THEN
           RAISE EXCEPTION 'first recipient was not inserted';
         END IF;
         PERFORM nextval('scrum166_insertion_observed');
         RAISE EXCEPTION 'synthetic second recipient failure';
       END IF; RETURN NEW; END $$;
       CREATE TRIGGER scrum166_fail_second_recipient BEFORE INSERT ON public."EventNotificationOutbox"
       FOR EACH ROW EXECUTE FUNCTION scrum166_fail_second_recipient()''')
    try:
        response = assign(client, event, LEAD_ID)
        assert response.status_code == 503, response.json
        # Sequences are not rolled back: prove failure followed the first recipient INSERT.
        assert db.execute('SELECT is_called FROM scrum166_insertion_observed') == [{"is_called": True}]
        assert db.event(event) == before_event
        assert pending(db) == before_outbox
    finally:
        db.execute('DROP TRIGGER scrum166_fail_second_recipient ON public."EventNotificationOutbox"; '
                   'DROP FUNCTION scrum166_fail_second_recipient(); DROP SEQUENCE scrum166_insertion_observed')

def test_dr_initial_coordinator_insert_failure_rolls_back_organiser_work(client, db):
    """Fail initial coordinator insertion only after the organiser intent was inserted.
    The event and every intent roll back together, including that earlier organiser row.
    """
    event = make_event(db, status="Submitted")
    before_event, before_outbox = db.event(event), pending(db)
    db.execute('''CREATE SEQUENCE scrum166_initial_insert_observed;
        CREATE FUNCTION scrum166_fail_initial_recipient() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN IF NEW.type = 'event.coordinator-assigned' THEN
          IF (SELECT count(*) FROM public."EventNotificationOutbox"
              WHERE type = 'event.coordinator-assignment') <> 1 THEN
            RAISE EXCEPTION 'organiser was not inserted first';
          END IF;
          PERFORM nextval('scrum166_initial_insert_observed');
          RAISE EXCEPTION 'synthetic initial coordinator failure';
        END IF; RETURN NEW; END $$;
        CREATE TRIGGER scrum166_fail_initial_recipient BEFORE INSERT ON public."EventNotificationOutbox"
        FOR EACH ROW EXECUTE FUNCTION scrum166_fail_initial_recipient()''')
    try:
        response = assign(client, event, COORDINATOR_ID)
        assert response.status_code == 503, response.json
        assert db.execute('SELECT is_called FROM scrum166_initial_insert_observed') == [{"is_called": True}]
        assert db.event(event) == before_event
        assert pending(db) == before_outbox
    finally:
        db.execute('DROP TRIGGER scrum166_fail_initial_recipient ON public."EventNotificationOutbox"; '
                   'DROP FUNCTION scrum166_fail_initial_recipient(); DROP SEQUENCE scrum166_initial_insert_observed')



