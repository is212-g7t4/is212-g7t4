"""SCRUM-49 Event Change and Modification Notifications: Event integration tests.

Story: As an Event Organiser and Event Coordinator, I want to receive notifications about event changes that affect me, so that I can respond to changes promptly.
Real: Flask mutation/context/outbox routes, SQL and disposable postgres:17.6, full unmodified migrations.
Doubled: recipient lookup inputs only; no other service runs.
Not proven: cross-service E2E, live broker delivery, authentication or browser navigation.
AC = acceptance criterion; DR = supporting design rule, not an extra AC.

AC1 Given an Event Organiser submits a change request, the system sends an in-app notification to the Event Coordinator with the event name, proposed changes, and a link to review the request.
AC2 Given an approval or rejection of a change request is successfully recorded, the Event Organiser receives an in-app notification with the event name, decision, and reason if rejected.
AC3 Given an event is cancelled or rejected, the system sends an in-app notification to both the Event Coordinator and Event Organiser confirming the cancellation or rejection respectively with the event name.
Coverage: AC1-3 own mutation/intent/freeze persistence; dispatcher sending and inbox belong to their respective service suites.
"""
from uuid import uuid4

import pytest
from tests.integration.factories import make_event_change_event, CHANGE_ORGANISER, SAFETY_COORDINATOR

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
HEADERS = {"X-Internal-Token": "synthetic"}
BUSINESS = {"X-Internal-Token": "synthetic"}


def submit(client, identifier):
    return client.post(f"/events/{identifier}/change-requests", json=dict(
        organiserId=CHANGE_ORGANISER, reason="Community feedback",
        changes={"eventName": "New Workshop", "expectedAttendance": "40"}))


# AC1 ---- successful mutation saves complete intent

def test_ac1_submission_saves_original_name_all_changes_and_freezable_intent(event_change_notification_owner):
    """Normal: submission commits original name and both proposed fields beside the request."""
    # Arrange
    client, db = event_change_notification_owner
    identifier = make_event_change_event(db)
    # Act
    response = submit(client, identifier)
    # Assert
    assert response.status_code == 201, response.json
    rows = db.query('SELECT type,source FROM public."EventNotificationOutbox"')
    assert len(rows) == 1
    assert rows[0][0] == "event.change-request-submitted"
    assert rows[0][1] == dict(eventId=identifier, eventName="Workshop", recipientRole="coordinator",
        changeRequestId=response.json["id"], proposedChanges={"eventName": "New Workshop", "expectedAttendance": "40"})
    assert db.query('SELECT status FROM public."EventChangeReq" WHERE change_id=%s', [response.json["id"]]) == [("Pending Review",)]
    claimed = client.post("/internal/notification-outbox/claim", json={}, headers=HEADERS).json["jobs"][0]
    envelope = dict(version=1, id=claimed["id"], type=claimed["type"], createdAt=claimed["createdAt"],
        recipientId=SAFETY_COORDINATOR, details={**claimed["source"], "recipientId": SAFETY_COORDINATOR},
        destination=dict(kind="change-request-review", eventId=identifier, changeRequestId=response.json["id"]),
        message="Change requested for Workshop. Proposed changes: Event Name: New Workshop; Expected Attendance: 40.")
    frozen = client.post(f"/internal/notification-outbox/{claimed['id']}/freeze", headers=HEADERS,
                         json=dict(leaseToken=claimed["leaseToken"], envelope=envelope))
    assert frozen.status_code == 200, frozen.json
    assert frozen.json["envelope"] == envelope
    assert db.query('SELECT envelope FROM public."EventNotificationOutbox" WHERE source_id=%s', [claimed["id"]]) == [(envelope,)]
    context = client.get(f"/internal/events/{identifier}/notification-context?includeOrganiser=true", headers=HEADERS)
    assert context.json["coordinatorId"] == SAFETY_COORDINATOR
    assert context.json["organiserId"] == CHANGE_ORGANISER

# AC2 ---- recorded decisions atomically save organiser intent
@pytest.mark.parametrize("decision", ["Approved", "Rejected"])
def test_ac2_decision_saves_renamed_event_or_exact_rejection_reason(event_change_notification_owner, decision):
    """Normal: recorded decision saves the new name with former name, or unchanged name and reason."""
    # Arrange
    client, db = event_change_notification_owner
    identifier = make_event_change_event(db)
    created = submit(client, identifier)
    assert created.status_code == 201
    request_id = created.json["id"]
    reason = "Keep accessible transport.\n交通安排需完善。"
    # Act
    response = client.patch(f"/change-requests/{request_id}/decision", headers=BUSINESS,
        json=dict(coordinatorId=SAFETY_COORDINATOR, decision=decision, reason=reason))
    # Assert
    assert response.status_code == 200, response.json
    expected_name = "New Workshop" if decision == "Approved" else "Workshop"
    expected = dict(eventId=identifier, eventName=expected_name, recipientRole="organiser",
                    changeRequestId=request_id, decision=decision)
    if decision == "Approved":
        expected["previousEventName"] = "Workshop"
    else:
        expected["reason"] = reason
    rows = db.query('SELECT type,source FROM public."EventNotificationOutbox" WHERE type<>%s',
                    ["event.change-request-submitted"])
    assert rows == [("event.change-request-" + decision.lower(), expected)]
    assert db.query('SELECT status,rejection_reason FROM public."EventChangeReq" WHERE change_id=%s', [request_id]) == [(decision, None if decision == "Approved" else reason)]
    assert db.query('SELECT event_name FROM public."Event" WHERE event_id=%s', [identifier]) == [(expected_name,)]
    submission = client.post("/internal/notification-outbox/claim", headers=HEADERS, json={}).json["jobs"][0]
    assert submission["type"] == "event.change-request-submitted"
    assert client.post(f"/internal/notification-outbox/{submission['id']}/hold", headers=HEADERS,
        json=dict(leaseToken=submission["leaseToken"], error="Deferred submission in decision-boundary test")).status_code == 200
    claimed = client.post("/internal/notification-outbox/claim", headers=HEADERS, json={}).json["jobs"][0]
    message = ("Change request for New Workshop (formerly Workshop) was approved." if decision == "Approved" else
               "Change request for Workshop was rejected: " + reason)
    envelope = dict(version=1, id=claimed["id"], type=claimed["type"], createdAt=claimed["createdAt"],
        recipientId=CHANGE_ORGANISER, details={**expected, "recipientId": CHANGE_ORGANISER},
        destination=dict(kind="event-details", eventId=identifier), message=message)
    frozen = client.post(f"/internal/notification-outbox/{claimed['id']}/freeze", headers=HEADERS,
                         json=dict(leaseToken=claimed["leaseToken"], envelope=envelope))
    assert frozen.status_code == 200, frozen.json
    assert db.query('SELECT envelope FROM public."EventNotificationOutbox" WHERE source_id=%s', [claimed["id"]]) == [(envelope,)]


# AC3 ---- event cancellation or rejection, independent recipients

@pytest.mark.parametrize("entry", ["reject", "progress"])
def test_ac3_event_rejection_commits_both_recipients_once_with_unchanged_reason_and_link(event_change_notification_owner, entry):
    """Normal: either event-rejection route saves two distinct deliverable intents and repeated saves add none."""
    # Arrange: real Flask/SQL/PostgreSQL; no dispatcher, consumer or broker runs.
    client, db = event_change_notification_owner
    identifier = make_event_change_event(db)
    db.query('UPDATE public."Event" SET status=%s WHERE event_id=%s', ["Under Review", identifier])
    reason = "Keep accessible transport.\n交通安排需完善。"
    body = dict(coordinatorId=SAFETY_COORDINATOR, reason=reason)
    if entry == "progress":
        body = dict(coordinatorId=SAFETY_COORDINATOR, status="Rejected", actionDetails=reason)
    # Act
    response = client.patch(f"/events/{identifier}/{entry}", json=body)
    # Assert: exactly one existing organiser alert, plus the coordinator actor's alert.
    assert response.status_code == 200, response.json
    assert response.json["decision"]["reason"] == reason
    assert db.query('SELECT status FROM public."Event" WHERE event_id=%s', [identifier]) == [("Rejected",)]
    rows = db.query('SELECT source_id,type,source FROM public."EventNotificationOutbox" ORDER BY source->>%s',
                    ["recipientId"])
    assert len(rows) == 2
    assert len({row[0] for row in rows}) == 2
    assert {row[1] for row in rows} == {"event.rejection"}
    assert {row[2]["recipientId"] for row in rows} == {CHANGE_ORGANISER, SAFETY_COORDINATOR}
    for _, _, source in rows:
        assert source == dict(eventId=identifier, eventName="Workshop", recipientId=source["recipientId"],
                              decision="Rejected", reason=reason)
    # Both mutation paths keep their existing terminal-status rules; neither requeues intent.
    assert client.patch(f"/events/{identifier}/reject", json=dict(
        coordinatorId=SAFETY_COORDINATOR, reason="Later reason")).status_code == 409
    again = client.patch(f"/events/{identifier}/progress", json=dict(
        coordinatorId=SAFETY_COORDINATOR, status="Rejected", actionDetails="Later saved notes"))
    assert again.status_code == 200, again.json
    assert db.query('SELECT source_id,type,source FROM public."EventNotificationOutbox" ORDER BY source->>%s',
                    ["recipientId"]) == rows
    # Existing event.rejection freeze contract retains the reason and event-details link for BOTH.
    frozen_ids = set()
    for _ in range(2):
        claim = client.post("/internal/notification-outbox/claim", headers=HEADERS, json={})
        assert claim.status_code == 200, claim.json
        job = claim.json["jobs"][0]
        envelope = dict(version=1, id=job["id"], type="event.rejection", createdAt=job["createdAt"],
            recipientId=job["source"]["recipientId"], details=job["source"],
            destination=dict(kind="event-details", eventId=identifier), message="Workshop was rejected: " + reason)
        frozen = client.post(f"/internal/notification-outbox/{job['id']}/freeze", headers=HEADERS,
            json=dict(leaseToken=job["leaseToken"], envelope=envelope))
        assert frozen.status_code == 200, frozen.json
        assert frozen.json["envelope"] == envelope
        assert db.query('SELECT envelope FROM public."EventNotificationOutbox" WHERE source_id=%s',
                        [job["id"]]) == [(envelope,)]
        assert client.post(f"/internal/notification-outbox/{job['id']}/published", headers=HEADERS,
            json=dict(leaseToken=job["leaseToken"])).status_code == 200
        frozen_ids.add(job["id"])
    assert frozen_ids == {str(row[0]) for row in rows}
    assert client.post("/internal/notification-outbox/claim", headers=HEADERS, json={}).json == dict(jobs=[])



def test_ac3_actual_cancellation_saves_independent_coordinator_and_organiser_intents(event_change_notification_owner):
    """Normal: safety rejection cancels the event and independently queues both cancellation recipients."""
    # Arrange
    client, db = event_change_notification_owner
    identifier = make_event_change_event(db)
    round_id = str(uuid4())
    submitted = client.patch(f"/events/{identifier}/safety-status", headers=BUSINESS,
        json=dict(status="Pending Safety Check", coordinatorId=SAFETY_COORDINATOR,
                  safetyCheckId=round_id, roundNumber=1))
    assert submitted.status_code == 200, submitted.json
    # Act
    response = client.patch(f"/events/{identifier}/safety-status", headers=BUSINESS,
        json=dict(status="Cancelled", decidedBy=SAFETY_COORDINATOR,
                  safetyCheckId=round_id, roundNumber=1, remarks="Unsafe"))
    # Assert
    assert response.status_code == 200, response.json
    assert db.query('SELECT status FROM public."Event" WHERE event_id=%s', [identifier]) == [("Cancelled",)]
    rows = db.query('SELECT source_id,source FROM public."EventNotificationOutbox" WHERE type=%s ORDER BY source->>%s',
                    ["event.cancelled", "recipientRole"])
    assert len(rows) == 2
    assert rows[0][0] != rows[1][0]
    assert [row[1] for row in rows] == [dict(eventId=identifier,eventName="Workshop",recipientRole=role)
                                      for role in ("coordinator", "organiser")]
    # Existing SCRUM-168 safety decision still coexists.
    assert db.query('SELECT count(*) FROM public."EventNotificationOutbox" WHERE type=%s', ["safety.review-decision"]) == [(1,)]
    frozen_ids = set()
    # SCRUM-46 adds one attendee fanout sibling. Keep the bounded search large
    # enough for all coexisting jobs without weakening the exact alerts below.
    for _ in range(5):
        claimed = client.post("/internal/notification-outbox/claim", headers=HEADERS, json={}).json["jobs"][0]
        if claimed["type"] != "event.cancelled":
            assert client.post(f"/internal/notification-outbox/{claimed['id']}/hold", headers=HEADERS,
                json=dict(leaseToken=claimed["leaseToken"], error="Not this story's delivery")).status_code == 200
            continue
        recipient = SAFETY_COORDINATOR if claimed["source"]["recipientRole"] == "coordinator" else CHANGE_ORGANISER
        envelope = dict(version=1, id=claimed["id"], type=claimed["type"], createdAt=claimed["createdAt"],
            recipientId=recipient, details={**claimed["source"], "recipientId": recipient},
            destination=dict(kind="event-details", eventId=identifier), message="Workshop was cancelled.")
        frozen = client.post(f"/internal/notification-outbox/{claimed['id']}/freeze", headers=HEADERS,
                             json=dict(leaseToken=claimed["leaseToken"], envelope=envelope))
        assert frozen.status_code == 200, frozen.json
        assert db.query('SELECT envelope FROM public."EventNotificationOutbox" WHERE source_id=%s', [claimed["id"]]) == [(envelope,)]
        frozen_ids.add(claimed["id"])
    assert len(frozen_ids) == 2
