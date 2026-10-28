"""SCRUM-49 Event Change and Modification Notifications: Event Workflow integration tests.

Story: As an Event Organiser and Event Coordinator, I want to receive notifications about event changes that affect me, so that I can respond to changes promptly.
Real: dispatcher, OutboxAPI and HTTPX request serialization.
Doubled: Event/User HTTP APIs via respx and recording publisher.
Not proven: cross-service E2E, live broker delivery, authentication or browser navigation.
AC = acceptance criterion; DR = supporting design rule, not an extra AC.

AC1 Given an Event Organiser submits a change request, the system sends an in-app notification to the Event Coordinator with the event name, proposed changes, and a link to review the request.
AC2 Given an approval or rejection of a change request is successfully recorded, the Event Organiser receives an in-app notification with the event name, decision, and reason if rejected.
AC3 Given an event is cancelled or rejected, the system sends an in-app notification to both the Event Coordinator and Event Organiser confirming the cancellation or rejection respectively with the event name.
Coverage: AC1-3 preparation/formatting/publication only; mutations and SQL/inbox are covered in owner suites.
"""
import json
from uuid import uuid4

import httpx
import pytest
from app.dispatcher import dispatch_once

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
EVENT = "20000000-0000-4000-8000-000000000001"
REQUEST = "30000000-0000-4000-8000-000000000001"
COORDINATOR = "10000000-0000-4000-8000-000000000001"
ORGANISER = "10000000-0000-4000-8000-000000000002"
LEAD = "10000000-0000-4000-8000-000000000003"
BASE = "https://event.test/internal/notification-outbox"


def job(kind, role="coordinator", **facts):
    return dict(id=str(uuid4()), type=kind, leaseToken=str(uuid4()), createdAt="2026-10-28T01:00:00+00:00",
                envelope=None, attempts=1, source=dict(eventId=EVENT, eventName="Workshop", recipientRole=role, **facts))


def prepare(http, item, recipient, message, *, unassigned=False):
    # Event app/__init__.py notification_context (opt-in owner ID); User GET /users role lookup.
    http.post(BASE + "/claim").respond(200, json={"jobs": [item]})
    http.get(f"https://event.test/internal/events/{EVENT}/notification-context", params={"includeOrganiser": "true"}).respond(
        200, json=dict(id=EVENT, eventName="Later renamed event", coordinatorId=None if unassigned else COORDINATOR, organiserId=ORGANISER))
    if unassigned:
        http.get("https://user.test/users", params={"role": "Event Coordinator Lead"}).respond(
            200, json={"users": [{"user_id": LEAD, "role": "Event Coordinator Lead", "username": "Lead"}]})
    source = dict(item["source"], recipientId=recipient)
    destination = dict(kind="event-details", eventId=EVENT)
    if item["type"] == "event.change-request-submitted":
        destination = dict(kind="change-request-review", eventId=EVENT, changeRequestId=REQUEST)
    expected = dict(version=1, id=item["id"], type=item["type"], createdAt=item["createdAt"],
                    recipientId=recipient, message=message, details=source, destination=destination)
    def freeze(request):
        assert request.headers["X-Internal-Token"] == "scrum45-test-token"
        assert json.loads(request.content) == dict(leaseToken=item["leaseToken"], envelope=expected)
        return httpx.Response(200, json={"envelope": {**expected, "ownerRevision": "frozen"}})
    http.post(f"{BASE}/{item['id']}/freeze").mock(side_effect=freeze)
    http.post(f"{BASE}/{item['id']}/published", json={"leaseToken": item["leaseToken"]}).respond(200, json={})
    return {**expected, "ownerRevision": "frozen"}


# AC1 ---- assigned coordinator, all proposed fields, review destination

def test_ac1_assigned_coordinator_receives_original_name_all_changes_and_request_link(api, http):
    """Normal: assigned coordinator receives both readable changes and the exact review link."""
    # Arrange
    item = job("event.change-request-submitted", changeRequestId=REQUEST,
               proposedChanges={"eventName": "New Workshop", "expectedAttendance": "40"})
    expected = prepare(http, item, COORDINATOR,
        "Change requested for Workshop. Proposed changes: Event Name: New Workshop; Expected Attendance: 40.")
    published = []
    # Act
    assert dispatch_once(api, published.append) == 1
    # Assert
    assert published == [expected]
    assert published[0]["recipientId"] != LEAD

# AC2 ---- current owner, rename and exact rejection reason
@pytest.mark.parametrize("decision", ["Approved", "Rejected"])
def test_ac2_current_organiser_receives_decision_and_historical_name_or_reason(api, http, decision):
    """Normal: current owner receives the renamed approval or unchanged-name rejection with exact reason."""
    # Arrange
    facts = dict(changeRequestId=REQUEST, decision=decision)
    if decision == "Approved":
        facts.update(previousEventName="Workshop")
    else:
        facts.update(reason="Keep accessible transport.\n交通安排需完善。")
    item = job("event.change-request-" + decision.lower(), "organiser", **facts)
    if decision == "Approved":
        item["source"]["eventName"] = "New Workshop"
    message = ("Change request for New Workshop (formerly Workshop) was approved." if decision == "Approved" else
               "Change request for Workshop was rejected: Keep accessible transport.\n交通安排需完善。")
    expected = prepare(http, item, ORGANISER, message)
    published = []
    # Act
    assert dispatch_once(api, published.append) == 1
    # Assert
    assert published == [expected]

# AC3 ---- cancellation and event rejection are distinct independent deliveries
def test_ac3_event_rejection_publishes_existing_envelopes_to_both_saved_recipients(api, http):
    """Normal: organiser and coordinator rejection jobs reuse the same reason/link without recipient lookup."""
    # Arrange: independent wire examples of Event's existing fixed-recipient contract.
    reason = "Keep accessible transport.\n交通安排需完善。"
    jobs = []
    expected = []
    for recipient in (ORGANISER, COORDINATOR):
        item = dict(id=str(uuid4()), type="event.rejection", leaseToken=str(uuid4()),
            createdAt="2026-10-28T01:00:00+00:00", envelope=None, attempts=1,
            source=dict(eventId=EVENT, eventName="Workshop", recipientId=recipient,
                        decision="Rejected", reason=reason))
        envelope = dict(version=1, id=item["id"], type="event.rejection", recipientId=recipient,
            createdAt=item["createdAt"], message="Workshop was rejected: " + reason,
            details=item["source"], destination=dict(kind="event-details", eventId=EVENT))
        # Event app/outbox.py freeze returns the validated saved envelope.
        http.post(f"{BASE}/{item['id']}/freeze", json=dict(
            leaseToken=item["leaseToken"], envelope=envelope)).respond(200, json={"envelope": envelope})
        http.post(f"{BASE}/{item['id']}/published", json=dict(
            leaseToken=item["leaseToken"])).respond(200, json={})
        jobs.append(item)
        expected.append(envelope)
    # Event app/outbox.py claim serializes these independent recipient jobs.
    http.post(BASE + "/claim").respond(200, json={"jobs": jobs})
    published = []
    # Act/Assert: strict HTTP stubs prohibit any User/recipient lookup or extra organiser job.
    assert dispatch_once(api, published.append) == 2
    assert published == expected


@pytest.mark.parametrize("role,recipient", [("coordinator", COORDINATOR), ("organiser", ORGANISER)])
def test_ac3_cancellation_reaches_each_current_recipient_with_event_details(api, http, role, recipient):
    """Normal: each cancellation job reaches its current recipient with event name and details link."""
    # Arrange
    item = job("event.cancelled", role)
    expected = prepare(http, item, recipient, "Workshop was cancelled.")
    published = []
    # Act
    assert dispatch_once(api, published.append) == 1
    # Assert
    assert published == [expected]

# DR ---- sole Lead fallback; no assignment writes or waiting
@pytest.mark.parametrize("kind", ["event.change-request-submitted", "event.cancelled"])
def test_dr_unassigned_event_delivers_to_sole_lead_without_waiting(api, http, kind):
    """Normal: unassigned coordinator-side delivery goes directly to the sole Lead."""
    # Arrange
    facts = dict(changeRequestId=REQUEST, proposedChanges={"eventName": "New Workshop", "expectedAttendance": "40"}) if kind.endswith("submitted") else {}
    item = job(kind, **facts)
    message = ("Change requested for Workshop. Proposed changes: Event Name: New Workshop; Expected Attendance: 40."
               if kind.endswith("submitted") else "Workshop was cancelled.")
    expected = prepare(http, item, LEAD, message, unassigned=True)
    published = []
    # Act
    assert dispatch_once(api, published.append) == 1
    # Assert: strict respx only allows context GET, Lead GET, freeze and completion, never assignment writes.
    assert published == [expected]
