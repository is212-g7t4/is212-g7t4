"""SCRUM48: Technical Support and coordinators receive equipment alerts.
AC1 submission, AC2 approval, AC3 rejection without workflow reason.
These three composite contract tests stop at external HTTP doubles. They verify
trusted context forwarding, not owner formatting, storage, delivery or inboxes.
Owner and Notification contracts are tested separately in their owning suites.
"""
from tests.unit.factories import (
    EVENT, MIC, PROJECTOR, A, B, TSS1, TSS2, R1, R2,
    identity, boundary, row, mutations,
)


def test_ac1_multi_item_submission_passes_trusted_full_list_and_tss(boundary):
    """AC1: Given two TSS and two items with quantities >1, when submitting,
    then the owner POST gets the full list, looked-up names/event and TSS IDs.
    Why: the composite must supply facts needed for the owner's full-list alert.
    """
    items = [dict(equipmentId=MIC,quantityRequested=5),dict(equipmentId=PROJECTOR,quantityRequested=2)]
    boundary.saved = [row(), row(R2, PROJECTOR, 2)]
    response = boundary.client.post(f"/equipment-reservations/events/{EVENT}/requests",
        headers=identity(A,"Event Coordinator"),json={"items":items})
    assert response.status_code == 201
    [call] = mutations(boundary)
    assert call.args == ("POST",f"http://owner.invalid/events/{EVENT}/equipment-requests")
    assert call.kwargs["json"] == dict(items=[
        dict(equipmentId=MIC,quantityRequested=5,technicalRequirements=""),
        dict(equipmentId=PROJECTOR,quantityRequested=2,technicalRequirements="")],notificationContext=dict(
        eventId=EVENT,eventName="Community Fair",equipmentNames={MIC:"Microphone",PROJECTOR:"Projector"},recipientIds=[TSS1,TSS2]))
    assert call.kwargs["headers"]["X-Internal-Token"] == "synthetic"
    assert response.json["requests"] == boundary.saved


def test_ac2_approval_selects_current_snapshot_not_original_requester(boundary):
    """AC2: Given requester A but current Event snapshot coordinator B, when
    approving, then the owner receives B and Approved; not commit-time proof.
    Why: retries must not substitute the original requester for the chosen actor.
    """
    boundary.event["coordinatorId"] = B
    boundary.saved = [row(status="Approved")]
    response = boundary.client.patch(f"/equipment-reservations/requests/{R1}",
        headers=identity(TSS1,"Technical Support"),json={"status":"Approved"})
    assert response.status_code == 200
    [call] = mutations(boundary)
    assert call.args == ("PATCH",f"http://owner.invalid/equipment-requests/{R1}")
    assert call.kwargs["json"] == dict(status="Approved",notificationContext=dict(
        eventId=EVENT,eventName="Community Fair",equipmentNames={MIC:"Microphone",PROJECTOR:"Projector"},coordinatorId=B))
    assert response.json["request"] == boundary.saved[0]


def test_ac3_rejection_keeps_reason_in_workflow_not_notification_context(boundary):
    """AC3: Given a private workflow reason, when rejecting, then the owner
    gets Rejected plus reason but the notification facts contain no reason.
    Why: owner tests separately require its final envelope to exclude the reason.
    """
    boundary.rows = [row(R2,PROJECTOR,2)]
    reason = "No technician available for the projector."
    boundary.saved = [{**row(R2,PROJECTOR,2,"Rejected"),"rejectionReason":reason}]
    response = boundary.client.patch(f"/equipment-reservations/requests/{R2}",
        headers=identity(TSS1,"Technical Support"),json={"status":"Rejected","rejectionReason":reason})
    assert response.status_code == 200
    [call] = mutations(boundary)
    assert call.kwargs["json"] == dict(status="Rejected",rejectionReason=reason,notificationContext=dict(
        eventId=EVENT,eventName="Community Fair",equipmentNames={MIC:"Microphone",PROJECTOR:"Projector"},coordinatorId=A))
    assert response.json["request"]["rejectionReason"] == reason
