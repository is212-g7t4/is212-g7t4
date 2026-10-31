"""SCRUM-48: Equipment Request Notification and Decision Alerts

User Story
----------
As an Event Coordinator and Technical Support Staff, I want to receive notifications about equipment requests and decisions, so that I can coordinate equipment arrangements efficiently.

Acceptance Criteria
-------------------
AC1: Given an Event Coordinator submits an equipment request, the system sends an in-app notification to Technical Support Staff with the event name, requested equipment list, and a link to review the request.
AC2: Given Technical Support Staff approves or rejects an Equipment Request, the system sends an in-app notification to the Event Coordinator assigned to that event with the event name, the equipment covered by the decision, and the decision status (Approved or Rejected).
AC3: Given a Technical Support Staff rejects the equipment request, the system sends an in-app notification to the Event Coordinator with the rejection message, event name, equipment request and link to the equipment request.

Real
----
- Purpose: check what submission and review actions send for notifications,
  and when those actions must send no change.
- The real submission/review routes and app.clients build event, equipment
  and recipient context, forward single/bulk decisions and check stock before
  approval. Caller-supplied notification context and internal tokens are replaced.
- Assertions inspect owner POST/PATCH context, token handling, unchanged owner
  results, propagated refusal and the absence of writes when stock is short.

Doubled
-------
- Event, Equipment, User and Equipment Request Services: Stub (`boundary`
  fixture) - fresh canned HTTP replies; outgoing mutations are inspected or
  asserted absent. Both original groups retain this same fixture boundary.

Not proven
----------
- AC3 "rejection message" means a statement that the Equipment Request was rejected, not that the whole event was rejected and not the private rejectionReason/why. Existing reason-exclusion assertions are intentional; the private reason remains in the review workflow.
- Only local routes/adapters and outgoing HTTP context are real. Other services are doubled; owner persistence, generated message text, publication, inbox receipt and browser navigation are not proved. AC3 mapping is rejection-context support, not proof of a delivered rejection statement or working browser link.
- Exact validation, stock-refusal, authentication configuration and defensive failure contracts are supporting regressions, not extra Jira ACs; Product Owner ownership/acceptance remains pending.
- `test_bulk_review_sends_one_decision_and_returns_only_changed_requests`: AC2 applies to both decision parameters; AC3 only to decision=Rejected, never Approved.
"""
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from app import create_app, clients
from tests.unit.factories import (
    EVENT, MIC, PROJECTOR, A, B, TSS1, TSS2, R1, R2,
    identity, boundary, row, mutations,
)


def test_submit_request_sends_full_list_and_technical_support_recipients(boundary):
    """Summary: A submission carries the event, the whole equipment list and every Technical Support recipient to the owner.
    AC1: Given an Event Coordinator submits an equipment request, the system sends an in-app notification to Technical Support Staff with the event name, requested equipment list, and a link to review the request.
    Double: Stub (downstream replies), Mock (owner POST inspected)
    """
    # Arrange (Given)
    items = [dict(equipmentId=MIC,quantityRequested=5),dict(equipmentId=PROJECTOR,quantityRequested=2)]
    boundary.saved = [row(), row(R2, PROJECTOR, 2)]

    # Act (When)
    response = boundary.client.post(f"/equipment-reservations/events/{EVENT}/requests",
        headers=identity(A,"Event Coordinator"),json={"items":items})

    # Assert (Then)
    assert response.status_code == 201
    [call] = mutations(boundary)
    assert call.args == ("POST",f"http://owner.invalid/events/{EVENT}/equipment-requests")
    assert call.kwargs["json"] == dict(items=[
        dict(equipmentId=MIC,quantityRequested=5,technicalRequirements=""),
        dict(equipmentId=PROJECTOR,quantityRequested=2,technicalRequirements="")],notificationContext=dict(
        eventId=EVENT,eventName="Community Fair",equipmentNames={MIC:"Microphone",PROJECTOR:"Projector"},recipientIds=[TSS1,TSS2]))
    assert "X-Internal-Token" not in call.kwargs["headers"]  # the owner authenticates the forwarded user (SCRUM-10)
    assert response.json["requests"] == boundary.saved


def test_approve_request_alerts_current_coordinator_not_original_requester(boundary):
    """Summary: Approval context names the event's current coordinator rather than the original requester.
    AC2: Given Technical Support Staff approves or rejects an Equipment Request, the system sends an in-app notification to the Event Coordinator assigned to that event with the event name, the equipment covered by the decision, and the decision status (Approved or Rejected).
    Double: Stub (Event Service names a new coordinator), Mock (owner PATCH inspected)
    """
    # Arrange (Given)
    boundary.event["coordinatorId"] = B
    boundary.saved = [row(status="Approved")]

    # Act (When)
    response = boundary.client.patch(f"/equipment-reservations/requests/{R1}",
        headers=identity(TSS1,"Technical Support"),json={"status":"Approved"})

    # Assert (Then)
    assert response.status_code == 200
    [call] = mutations(boundary)
    assert call.args == ("PATCH",f"http://owner.invalid/equipment-requests/{R1}")
    assert call.kwargs["json"]["status"] == "Approved"
    assert call.kwargs["json"]["notificationContext"] == dict(
        eventId=EVENT,eventName="Community Fair",equipmentNames={MIC:"Microphone",PROJECTOR:"Projector"},coordinatorId=B)
    assert call.kwargs["json"]["approvalContext"]["requestIds"] == [R1]
    assert response.json["request"] == boundary.saved[0]


def test_reject_request_keeps_reason_out_of_alert_details(boundary):
    """Summary: A rejection's private reason is saved with the decision but kept out of the alert details.
    AC2: Given Technical Support Staff approves or rejects an Equipment Request, the system sends an in-app notification to the Event Coordinator assigned to that event with the event name, the equipment covered by the decision, and the decision status (Approved or Rejected).
    AC3: Given a Technical Support Staff rejects the equipment request, the system sends an in-app notification to the Event Coordinator with the rejection message, event name, equipment request and link to the equipment request.
    Double: Stub (downstream replies), Mock (owner PATCH inspected)
    """
    # Arrange (Given)
    boundary.rows = [row(R2,PROJECTOR,2)]
    reason = "No technician available for the projector."
    boundary.saved = [{**row(R2,PROJECTOR,2,"Rejected"),"rejectionReason":reason}]

    # Act (When)
    response = boundary.client.patch(f"/equipment-reservations/requests/{R2}",
        headers=identity(TSS1,"Technical Support"),json={"status":"Rejected","rejectionReason":reason})

    # Assert (Then)
    assert response.status_code == 200
    [call] = mutations(boundary)
    assert call.kwargs["json"] == dict(status="Rejected",rejectionReason=reason,notificationContext=dict(
        eventId=EVENT,eventName="Community Fair",equipmentNames={MIC:"Microphone",PROJECTOR:"Projector"},coordinatorId=A))
    assert response.json["request"]["rejectionReason"] == reason


@pytest.mark.parametrize("decision", ["Approved", "Rejected"], ids=["approved", "rejected"])
def test_bulk_review_sends_one_decision_and_returns_only_changed_requests(boundary, decision):
    """Summary: A bulk decision is sent once and only the requests the owner changed come back for alerting.
    AC2: Given Technical Support Staff approves or rejects an Equipment Request, the system sends an in-app notification to the Event Coordinator assigned to that event with the event name, the equipment covered by the decision, and the decision status (Approved or Rejected).
    AC3: Given a Technical Support Staff rejects the equipment request, the system sends an in-app notification to the Event Coordinator with the rejection message, event name, equipment request and link to the equipment request.
    Double: Stub (owner reports two changed rows), Mock (one PATCH)
    """
    # Arrange (Given)
    boundary.rows = [row(), row(R2, PROJECTOR, 2)]
    boundary.saved = [{**r,"status":decision} for r in boundary.rows]

    # Act (When)
    response = boundary.client.patch(f"/equipment-reservations/events/{EVENT}",
        headers=identity(TSS1,"Technical Support"),json={"status":decision,"rejectionReason":"Private workflow reason"})

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["requests"] == boundary.saved
    [call] = mutations(boundary)
    assert call.args == ("PATCH",f"http://owner.invalid/events/{EVENT}/equipment-requests")
    payload = call.kwargs["json"]
    assert payload["status"] == decision
    assert payload["notificationContext"] == dict(eventId=EVENT,eventName="Community Fair",
        equipmentNames={MIC:"Microphone",PROJECTOR:"Projector"},coordinatorId=A)
    assert ("rejectionReason" in payload) == (decision == "Rejected")
    # Explicit downstream refusal, not an emulated owner state transition.
    boundary.write_code = 409
    refused = boundary.client.patch(f"/equipment-reservations/events/{EVENT}",
        headers=identity(TSS1,"Technical Support"),json={"status":decision,"rejectionReason":"Private workflow reason"})
    assert refused.status_code == 409


@pytest.mark.parametrize("bulk", [False, True], ids=["single", "bulk"])
def test_approve_when_stock_insufficient_sends_no_decision_or_alert(boundary, bulk):
    """Summary: An approval blocked by stock sends no decision and so no alert.
    AC2: Given Technical Support Staff approves or rejects an Equipment Request, the system sends an in-app notification to the Event Coordinator assigned to that event with the event name, the equipment covered by the decision, and the decision status (Approved or Rejected).
    Double: Stub (demand 21 against stock 20), Mock (no PATCH)
    """
    # Arrange (Given)
    boundary.rows = [row(quantity=21)]
    before = deepcopy(boundary.rows)

    # Act (When)
    response = boundary.client.patch(f"/equipment-reservations/events/{EVENT}" if bulk else f"/equipment-reservations/requests/{R1}",
        headers=identity(TSS1,"Technical Support"),json={"status":"Approved"})

    # Assert (Then)
    assert response.status_code == 409
    assert "insufficient stock" in response.json["message"]
    assert mutations(boundary) == []
    assert boundary.rows == before




def test_submit_request_with_forged_context_sends_only_server_resolved_recipients(boundary):
    """Summary: Recipients and the internal token a caller sends are ignored; only server-looked-up ones are used.
    AC1: Given an Event Coordinator submits an equipment request, the system sends an in-app notification to Technical Support Staff with the event name, requested equipment list, and a link to review the request.
    Double: Stub (downstream replies), Mock (owner POST inspected)
    """
    # Arrange (Given): boundary, from fixtures

    # Act (When)
    response = boundary.client.post(f"/equipment-reservations/events/{EVENT}/requests",
        headers={**identity(A,"Event Coordinator"),"X-Internal-Token":"attacker"},
        json={"items":[dict(equipmentId=MIC,quantityRequested=5)],
              "notificationContext":dict(eventName="Forged event",recipientIds=[B])})

    # Assert (Then)
    assert response.status_code == 201
    [call] = mutations(boundary)
    assert "X-Internal-Token" not in call.kwargs["headers"]  # the forged token is not forwarded (SCRUM-10)
    assert call.kwargs["json"]["notificationContext"]["recipientIds"] == [
        "10000000-0000-4000-8000-000000000006", "10000000-0000-4000-8000-000000000007"]
    assert call.kwargs["json"]["notificationContext"]["eventName"] == "Community Fair"
