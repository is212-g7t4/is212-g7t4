"""
SCRUM-48: Equipment Request Notification and Decision Alerts

User Story
----------
As an Event Coordinator and Technical Support Staff, I want to receive
notifications about equipment requests and decisions, so that I can coordinate
equipment arrangements efficiently.

Acceptance Criteria
-------------------
AC1: Given an Event Coordinator submits an equipment request, the system sends
     an in-app notification to Technical Support Staff with the event name,
     requested equipment list, and a link to review the request.
AC2: Given equipment is confirmed as available or found to be unavailable, the
     system sends an in-app notification to the Event Coordinator with the
     event name, equipment list, and availability status.
AC3: Given an equipment request is submitted and pending review, the system
     sends an in-app notification to Technical Support Staff that a request
     requires their review.

Real
----
- The real submission and review routes and app.clients build the trusted
  notification context (event, equipment names, Technical Support and
  coordinator recipients) sent with each change.
- Assertions are on the context and token in the owner POST/PATCH.

Doubled
-------
- Event, Equipment, User and Equipment Request Services: Stub (`boundary`
  fixture) - canned HTTP replies; the outgoing requests are inspected.

Not proven
----------
- That Equipment Request Service freezes these facts into its outbox in the
  same transaction as the change (-> equipment-request-service
  test_scrum48_notifications.py and its integration tests).
- That Notification Service stores and shows the inbox item, and that the alert
  links to the request (AC1) (-> notification-service consumer tests and
  frontend EquipmentRequestsPage.scrum48.test.tsx).
- The availability-status part of AC2 (NOT COVERED ANYWHERE; raised as a
  finding).
"""
from tests.unit.factories import (
    EVENT, MIC, PROJECTOR, A, B, TSS1, TSS2, R1, R2,
    identity, boundary, row, mutations,
)


def test_submit_request_sends_full_list_and_technical_support_recipients(boundary):
    """
    Summary: A submission carries the event, the whole equipment list and every Technical Support recipient to the owner.
    AC1: Given an Event Coordinator submits an equipment request, the system
        sends an in-app notification to Technical Support Staff with the event
        name, requested equipment list, and a link to review the request.
    AC3: Given an equipment request is submitted and pending review, the system
        sends an in-app notification to Technical Support Staff that a request
        requires their review.
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
    """
    Summary: An approval alert goes to the event's current coordinator, not whoever first asked.
    AC2: Given equipment is confirmed as available or found to be unavailable,
        the system sends an in-app notification to the Event Coordinator with
        the event name, equipment list, and availability status.
    Double: Stub (Event Service names a new coordinator), Mock (owner PATCH
        inspected)
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
    """
    Summary: A rejection's private reason is saved with the decision but kept out of the alert details.
    AC2: Given equipment is confirmed as available or found to be unavailable,
        the system sends an in-app notification to the Event Coordinator with
        the event name, equipment list, and availability status.
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
