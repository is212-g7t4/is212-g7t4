"""SCRUM-45 Event Organiser Status and Update Notifications: Event integration tests.

Story: As an Event Organiser, I want to receive an in-app notification when the Lead Coordinator approves or rejects my event request, so that I know the outcome and who is responsible for coordinating my event.
Real: own Flask routes, mutation/outbox SQL and disposable postgres:17.6; complete unmodified migration chain.
Doubled: no external services are called; a test-owned SQL trigger injects storage failure.
Not proven: Workflow name lookup/publication, Notification inbox, UI/E2E or production authentication.
AC = acceptance criterion; DR = supporting design rule, not another AC.

AC1 A successfully recorded approval sends an in-app approval notification to the submitting Event Organiser.
  Owned: committed approval intent; sending/inbox is not covered here (Workflow/Notification).
AC2 A successfully recorded rejection sends an in-app rejection notification to the submitting Event Organiser, including the rejection reason.
  Owned: committed rejection intent/reason; sending/inbox is not covered here (Workflow/Notification).
AC3 Both decision notifications include event name, decision, and a link to the event request and its decision details.
  Owned: historical facts and frozen destination plus owner detail retrieval; UI navigation not covered here.
AC4 A successfully recorded initial assignment or reassignment sends the submitting Event Organiser an in-app notification with event name, newly assigned coordinator name, and an event-details link.
  Owned: distinct saved coordinator IDs/intent for both changes; name lookup and delivery not covered here (Workflow/Notification).
"""

import time
from uuid import uuid4

import pytest

from tests.integration.factories import (
    ORGANISER_ID, OTHER_ORGANISER_ID, COORDINATOR_ID, LEAD_ID,
    make_event, make_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
HEADERS = {"X-Internal-Token": "scrum45-isolated-token"}
REASON = "The proposal needs a revised accessibility plan.\nPlease include transport arrangements."


@pytest.fixture(autouse=True)
def notification_actors(client, db):
    """Configure the internal token and insert synthetic organiser/coordinator parents for each
    story test.
    """
    client.application.config["INTERNAL_SERVICE_TOKEN"] = HEADERS["X-Internal-Token"]
    for identifier, role in [(ORGANISER_ID, "Event Organiser"),
                             (OTHER_ORGANISER_ID, "Event Organiser"),
                             (COORDINATOR_ID, "Event Coordinator"),
                             (LEAD_ID, "Event Coordinator")]:
        make_user(db, identifier, role)


def decision(client, event_id, outcome, entry="dedicated", actor=COORDINATOR_ID):
    """Send the chosen outcome through the dedicated or progress route and return its HTTP
    response.
    """
    body = {"coordinatorId": actor}
    if outcome == "Rejected":
        body["reason"] = REASON
    if entry == "progress":
        return client.patch(f"/events/{event_id}/progress", json={**body, "status": outcome,
                           "actionDetails": REASON if outcome == "Rejected" else "Ready for approval"})
    return client.patch(f"/events/{event_id}/{'approve' if outcome == 'Approved' else 'reject'}", json=body)


def assignment(client, event_id, coordinator):
    # This is Event's own mutation boundary, not the different service's Lead journey.
    """Send a coordinator change through Event's own API and return its response; the Lead
    composite journey is not exercised.
    """
    return client.patch(f"/events/{event_id}", json={
        "assignedCoordinatorId": coordinator, "assignedBy": LEAD_ID})


def pending(db, *, coordinator_rejection=False):
    """Read outbox rows in creation order, excluding only legitimate companion alerts."""
    rows = db.execute('SELECT * FROM public."EventNotificationOutbox" ORDER BY created_at,source_id')
    return [row for row in rows
            if row["type"] not in ("event.coordinator-assigned", "event.coordinator-removed")
            and not (coordinator_rejection and row["type"] == "event.rejection"
                     and row["source"].get("recipientId") == COORDINATOR_ID)]


def claim(client, *, coordinator_rejection=False):
    """Claim work with the test token, require HTTP success and return the owner's leased jobs."""
    for _ in range(10):
        response = client.post("/internal/notification-outbox/claim", headers=HEADERS, json={})
        assert response.status_code == 200, response.json
        jobs = response.json["jobs"]
        if not jobs or (jobs[0]["type"] not in ("event.coordinator-assigned", "event.coordinator-removed")
                        and not (coordinator_rejection and jobs[0]["type"] == "event.rejection"
                                 and jobs[0]["source"].get("recipientId") == COORDINATOR_ID)):
            return jobs
    pytest.fail("SCRUM-45 claim exhausted its bounded coordinator-delivery skip")


def operation(client, job, action, **body):
    """Return the chosen owner operation's HTTP response using the supplied job identity and lease."""
    return client.post(f"/internal/notification-outbox/{job['id']}/{action}",
                       headers=HEADERS, json={"leaseToken": job["leaseToken"], **body})


def envelope_for(job):
    """Build expected content from saved job facts; assignment uses a synthetic name, not Workflow
    or User lookup.
    """
    source = job["source"]
    details = source
    if job["type"] == "event.coordinator-assignment":
        details = {**source, "coordinatorName": "Synthetic Coordinator"}
        message = f"Synthetic Coordinator has been assigned to coordinate {source['eventName']}."
    elif job["type"] == "event.approval":
        message = f"{source['eventName']} was approved"
    else:
        message = f"{source['eventName']} was rejected: {source['reason']}"
    return dict(version=1, id=job["id"], type=job["type"], recipientId=ORGANISER_ID,
                createdAt=job["createdAt"], message=message, details=details,
                destination={"kind": "event-details", "eventId": source["eventId"]})


# AC1 — Approval
@pytest.mark.parametrize("entry", ["dedicated", "progress"])
def test_ac1_approval_commits_one_historical_intent(client, db, entry):
    """Normal: approve through either route and repeat it; fresh SQL reads show the decision and
    one unchanged historical intent, so retries cannot enqueue a duplicate approval.
    """
    event_id = make_event(db, status="Under Review", coordinator_id=COORDINATOR_ID,
                          event_name="Accessible Community Workshop")
    response = decision(client, event_id, "Approved", entry)
    assert response.status_code == 200, response.json
    assert db.event(event_id)["status"] == "Approved"
    rows = pending(db)
    assert len(rows) == 1
    assert rows[0]["type"] == "event.approval"
    assert rows[0]["source"] == dict(eventId=event_id, eventName="Accessible Community Workshop",
                                     recipientId=ORGANISER_ID, decision="Approved")
    assert rows[0]["envelope"] is None
    assert rows[0]["published_at"] is None
    again = decision(client, event_id, "Approved", entry)
    assert again.status_code in (200, 409)
    assert pending(db) == rows


# AC2 — Rejection/reason
@pytest.mark.parametrize("entry", ["dedicated", "progress"])
def test_ac2_rejection_commits_exact_reason_and_no_duplicate(client, db, entry):
    """Normal: reject through either route and repeat it; fresh SQL reads retain the exact
    multiline reason in one intent, preventing reason loss or duplicate work.
    """
    event_id = make_event(db, status="Under Review", coordinator_id=COORDINATOR_ID)
    response = decision(client, event_id, "Rejected", entry)
    assert response.status_code == 200, response.json
    assert db.event(event_id)["status"] == "Rejected"
    rows = pending(db, coordinator_rejection=True)
    assert len(rows) == 1
    assert rows[0]["type"] == "event.rejection"
    assert rows[0]["source"] == dict(eventId=event_id, eventName="Spring Fair", recipientId=ORGANISER_ID,
                                     decision="Rejected", reason=REASON)
    again = decision(client, event_id, "Rejected", entry)
    assert again.status_code in (200, 409)
    assert pending(db, coordinator_rejection=True) == rows


@pytest.mark.parametrize('character', ['x', '界', '😀', '"', '\\', '\n'],
                         ids=['ascii', 'chinese', 'emoji', 'quote', 'backslash', 'newline'])
def test_ac2_maximum_public_reason_freezes_without_loss(client, db, character):
    """Boundary: reject with text filling the public request budget and freeze the larger envelope;
    SQL preserves it exactly and rejected freeze requests leave it unchanged, preventing an
    accepted reason from becoming stuck.
    """
    import json
    encode = lambda value: json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
    event_id = make_event(db, status="Under Review", coordinator_id=COORDINATOR_ID,
                          event_name=('\x01' if character == '"' else '😀') * 255)
    base = dict(coordinatorId=COORDINATOR_ID, reason='')
    budget = 65536 - len(encode(base))
    cost = len(encode(character)) - 2
    # Leading/trailing x prevents the public route's intentional whitespace trim.
    reason = 'x' + character * ((budget - 2) // cost) + 'x'
    body = encode({**base, 'reason': reason})
    assert 65536 - cost < len(body) <= 65536
    response = client.patch(f'/events/{event_id}/reject', data=body, content_type='application/json')
    assert response.status_code == 200, response.json
    assert pending(db, coordinator_rejection=True)[0]['source']['reason'] == reason
    job = claim(client, coordinator_rejection=True)[0]
    expected = envelope_for(job)
    freeze = encode(dict(leaseToken=job['leaseToken'], envelope=expected))
    assert 65536 < len(freeze) <= 135168
    result = client.post(f"/internal/notification-outbox/{job['id']}/freeze", headers=HEADERS,
                         data=freeze, content_type='application/json')
    assert result.status_code == 200, result.json
    assert result.json['envelope'] == expected
    assert pending(db, coordinator_rejection=True)[0]['envelope'] == expected
    # Refused requests do not overwrite the saved envelope.
    before = pending(db, coordinator_rejection=True)
    assert client.post(f"/internal/notification-outbox/{job['id']}/freeze", headers=HEADERS,
                       data=b' ' * 135169, content_type='application/json').status_code == 413
    assert client.post(f"/internal/notification-outbox/{job['id']}/freeze",
                       data=freeze, content_type='application/json').status_code == 401
    assert pending(db, coordinator_rejection=True) == before


# AC3 — Shared decision content and linked details
@pytest.mark.parametrize("outcome", ["Approved", "Rejected"])
def test_ac3_decision_freezes_original_facts_and_owner_can_read_details(client, db, outcome):
    """Normal: record and freeze either decision, then read its event as the organiser; SQL retains
    the exact envelope and the target exposes the outcome/reason, making the saved link
    meaningful.
    """
    event_id = make_event(db, status="Under Review", coordinator_id=COORDINATOR_ID)
    assert decision(client, event_id, outcome).status_code == 200
    job = claim(client, coordinator_rejection=outcome == "Rejected")[0]
    expected = envelope_for(job)
    frozen = operation(client, job, "freeze", envelope=expected)
    assert frozen.status_code == 200, frozen.json
    assert frozen.json["envelope"] == expected
    assert pending(db, coordinator_rejection=outcome == "Rejected")[0]["envelope"] == expected  # independent new DB transaction
    target = client.get(f"/events/{event_id}?organiserId={ORGANISER_ID}")
    assert target.status_code == 200, target.json
    assert target.json["eventName"] == "Spring Fair"
    assert target.json["status"] == outcome
    if outcome == "Rejected":
        assert target.json["decision"]["reason"] == REASON
    assert expected["destination"] == dict(kind="event-details", eventId=event_id)


# AC4 — Initial assignment and reassignment

def test_ac4_initial_and_reassignment_record_separate_saved_coordinators(client, db):
    """Normal: assign then replace the coordinator; SQL shows two distinct saved IDs, preserving
    both changes for the organiser.
    """
    event_id = make_event(db, status="Submitted")
    assert assignment(client, event_id, COORDINATOR_ID).status_code == 200
    assert assignment(client, event_id, LEAD_ID).status_code == 200
    rows = pending(db)
    assert len(rows) == 2
    assert len({row["source_id"] for row in rows}) == 2
    assert [row["source"]["coordinatorId"] for row in rows] == [COORDINATOR_ID, LEAD_ID]
    assert all(row["type"] == "event.coordinator-assignment" for row in rows)
    for row in rows:
        assert row["source"]["recipientId"] == ORGANISER_ID
        assert row["source"]["eventName"] == "Spring Fair"
        assert row["source"]["eventId"] == event_id
    assert str(db.event(event_id)["coordinator_id"]) == LEAD_ID
    # Repeating the same coordinator is a no-op; see test_scrum166-coordinator_assignment_notifications.py.


# Supporting DR1/DR2/DR3/DR4/DR5/DR6/DR8 — owner transaction, recovery and identity

def test_ac1_dr_approval_and_assignment_are_distinct_intents(client, db):
    """Normal: assign and approve the same event; SQL contains two types with distinct source IDs,
    so approval cannot overwrite the separate coordinator update (DR1).
    """
    event_id = make_event(db, status="Submitted")
    assert assignment(client, event_id, COORDINATOR_ID).status_code == 200
    assert decision(client, event_id, "Approved").status_code == 200
    rows = pending(db)
    assert len(rows) == 2
    assert {row["type"] for row in rows} == {"event.approval", "event.coordinator-assignment"}
    assert len({row["source_id"] for row in rows}) == 2


@pytest.mark.parametrize("change", ["approval", "rejection", "initial"])
def test_ac4_dr_intent_insert_failure_rolls_back_entire_mutation(client, db, change):
    """Failure: a PostgreSQL trigger rejects the intent INSERT for each change; HTTP fails and
    fresh SQL reads show unchanged event state and no outbox row, proving atomic rollback (DR2).
    Reassignment rollback is covered in test_scrum166-coordinator_assignment_notifications.py.
    """
    event_id = make_event(db, status="Submitted" if change == "initial" else "Under Review",
                          coordinator_id=None if change == "initial" else COORDINATOR_ID)
    before = db.event(event_id)
    # Arrange a database-boundary outage after the business UPDATE; never patch app logic.
    db.execute('''CREATE FUNCTION scrum45_fail_intent() RETURNS trigger LANGUAGE plpgsql AS $$
                   BEGIN RAISE EXCEPTION 'synthetic intent storage failure'; END $$;
                  CREATE TRIGGER scrum45_fail_intent BEFORE INSERT ON public."EventNotificationOutbox"
                  FOR EACH ROW EXECUTE FUNCTION scrum45_fail_intent()''')
    try:
        response = (decision(client, event_id, "Approved" if change == "approval" else "Rejected")
                    if change in ("approval", "rejection") else
                    assignment(client, event_id, COORDINATOR_ID))
        assert response.status_code >= 400
        assert db.event(event_id) == before
        assert db.execute('SELECT * FROM public."EventNotificationOutbox"') == []
    finally:
        db.execute('DROP TRIGGER scrum45_fail_intent ON public."EventNotificationOutbox"; DROP FUNCTION scrum45_fail_intent()')


@pytest.mark.parametrize("kind", ["approval", "rejection", "coordinator-assignment"])
def test_ac3_dr_frozen_envelope_survives_retry_reclaim_and_second_freeze(client, db, kind):
    """Conflict: freeze, retry and reclaim each job type, then freeze again; SQL retains the first
    envelope and only the new lease can complete, protecting content and ownership across
    retries (DR3/DR4).
    """
    event_id = make_event(db, status="Submitted" if kind == "coordinator-assignment" else "Under Review",
                          coordinator_id=None if kind == "coordinator-assignment" else COORDINATOR_ID)
    response = (assignment(client, event_id, COORDINATOR_ID) if kind == "coordinator-assignment"
                else decision(client, event_id, "Approved" if kind == "approval" else "Rejected"))
    assert response.status_code == 200
    job = claim(client, coordinator_rejection=kind == "rejection")[0]
    expected = envelope_for(job)
    assert operation(client, job, "freeze", envelope=expected).status_code == 200
    assert pending(db, coordinator_rejection=kind == "rejection")[0]["envelope"] == expected
    # Act: release the first lease, then wait for the owner's persisted retry backoff.
    assert operation(client, job, "retry", error="synthetic publication ambiguity").status_code == 200
    deadline = time.monotonic() + 8
    jobs = []
    while time.monotonic() < deadline:
        jobs = claim(client, coordinator_rejection=kind == "rejection")
        if jobs:
            break
        time.sleep(0.05)  # bounded condition polling of the owner's real backoff
    assert len(jobs) == 1, "Owner retry did not become claimable"
    # Assert: the replacement lease retains the first envelope and fences out the old worker.
    reclaimed = jobs[0]
    assert reclaimed["leaseToken"] != job["leaseToken"]
    assert reclaimed["envelope"] == expected
    again = operation(client, reclaimed, "freeze", envelope={"replacement": True})
    assert again.status_code == 200
    assert again.json["envelope"] == expected
    assert operation(client, job, "published").status_code == 409
    assert operation(client, reclaimed, "published").status_code == 200
    row = pending(db, coordinator_rejection=kind == "rejection")[0]
    assert row["envelope"] == expected
    assert row["published_at"] is not None
    assert row["lease_token"] is None
    assert claim(client, coordinator_rejection=kind == "rejection") == []


def test_ac3_dr_expired_lease_is_refused_before_and_after_reclaim(client, db):
    """Boundary: expire a frozen job in PostgreSQL and reclaim it; the old lease cannot complete or
    freeze while the new lease can complete, preventing stale-worker completion even before
    reclaim (DR3).
    """
    event_id = make_event(db, status="Under Review", coordinator_id=COORDINATOR_ID)
    assert decision(client, event_id, "Approved").status_code == 200
    job = claim(client)[0]
    expected = envelope_for(job)
    assert operation(client, job, "freeze", envelope=expected).status_code == 200
    db.execute('UPDATE public."EventNotificationOutbox" SET lease_until=clock_timestamp()-interval \'1 second\' WHERE source_id=%s', [job["id"]])
    assert operation(client, job, "published").status_code == 409
    assert pending(db)[0]["published_at"] is None
    reclaimed = claim(client)[0]
    assert reclaimed["leaseToken"] != job["leaseToken"]
    assert reclaimed["envelope"] == expected
    assert operation(client, job, "freeze", envelope=expected).status_code == 409
    assert operation(client, reclaimed, "published").status_code == 200


def test_ac4_dr_held_work_is_excluded_inspectable_and_releasable(client, db):
    """Boundary: hold an assignment, process another event and explicitly release the hold; SQL and
    owner APIs retain the diagnosis and requeue the same job, allowing repair without blocking
    unrelated work (DR6).
    """
    event_id = make_event(db, status="Submitted")
    assert assignment(client, event_id, COORDINATOR_ID).status_code == 200
    job = claim(client)[0]
    assert operation(client, job, "hold", error="CoordinatorNameUnavailable").status_code == 200
    row = pending(db)[0]
    assert row["held_at"] is not None and row["lease_token"] is None
    assert claim(client) == []
    other = make_event(db, status="Under Review", coordinator_id=COORDINATOR_ID)
    assert decision(client, other, "Approved").status_code == 200
    assert claim(client)[0]["source"]["eventId"] == other
    held = client.get("/internal/notification-outbox/held", headers=HEADERS)
    assert held.status_code == 200
    assert held.json["jobs"][0]["id"] == job["id"]
    assert held.json["jobs"][0]["error"] == "CoordinatorNameUnavailable"
    assert client.post(f"/internal/notification-outbox/{job['id']}/release", headers=HEADERS, json={}).status_code == 200
    assert claim(client)[0]["id"] == job["id"]


@pytest.mark.parametrize("outcome", ["Approved", "Rejected"])
def test_ac1_dr_wrong_actor_cannot_mutate_or_notify(client, db, outcome):
    """Failure: request either decision with the wrong coordinator ID; HTTP 403, unchanged event
    SQL and an empty outbox prevent unauthorised decisions and notifications (DR8).
    """
    event_id = make_event(db, status="Under Review", coordinator_id=COORDINATOR_ID)
    before = db.event(event_id)
    assert decision(client, event_id, outcome, actor=LEAD_ID).status_code == 403
    assert db.event(event_id) == before
    assert db.execute('SELECT * FROM public."EventNotificationOutbox"') == []


def test_ac4_dr_ownerless_legacy_assignment_has_no_guessed_recipient(client, db, caplog):
    """Boundary: assign a legacy event without an organiser; SQL saves the assignment but no intent
    and logs the missing owner, avoiding disclosure to a guessed recipient (DR5).
    """
    event_id = make_event(db, status="Submitted", organiser_id=None)
    assert assignment(client, event_id, COORDINATOR_ID).status_code == 200
    assert str(db.event(event_id)["coordinator_id"]) == COORDINATOR_ID
    assert pending(db) == []
    assert "missing organiser" in caplog.text
