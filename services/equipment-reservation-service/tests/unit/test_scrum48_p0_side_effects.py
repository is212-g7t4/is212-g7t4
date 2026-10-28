"""SCRUM48 supporting bulk, validation and security rules (not new ACs).
Real reservation routes/adapters only; every other service is an HTTP double.
No outbox/inbox, SQL, consumer or delivery code from another owner runs here.
"""
from copy import deepcopy
from unittest.mock import MagicMock
import pytest
from app import create_app, clients
from tests.unit.factories import (
    EVENT, MIC, PROJECTOR, A, B, TSS1, R1, R2, identity, boundary, row, mutations,
)


@pytest.mark.parametrize("decision", ["Approved", "Rejected"])
def test_bulk_forwards_one_action_and_returns_only_owner_reported_changes(boundary, decision):
    """AC2/3 supporting bulk rule: Given two owner-reported changed rows,
    when bulk review runs, then one trusted PATCH returns exactly those rows.
    Why: the composite must preserve owner result granularity, not invent alerts.
    Pending-only writes/per-record alerts/no-op state are separately owner-tested.
    """
    boundary.rows = [row(), row(R2, PROJECTOR, 2)]
    boundary.saved = [{**r,"status":decision} for r in boundary.rows]
    response = boundary.client.patch(f"/equipment-reservations/events/{EVENT}",
        headers=identity(TSS1,"Technical Support"),json={"status":decision,"rejectionReason":"Private workflow reason"})
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
def test_insufficient_stock_approval_never_calls_owner_mutation(boundary, bulk):
    """DR: Given demand 21 against stock 20, when single/bulk approval runs,
    then 409 occurs without downstream mutation. Why: failed stock checks must
    not request a decision; persistence and delivery are not simulated here.
    """
    boundary.rows = [row(quantity=21)]
    before = deepcopy(boundary.rows)
    response = boundary.client.patch(f"/equipment-reservations/events/{EVENT}" if bulk else f"/equipment-reservations/requests/{R1}",
        headers=identity(TSS1,"Technical Support"),json={"status":"Approved"})
    assert response.status_code == 409
    assert "insufficient stock" in response.json["message"]
    assert mutations(boundary) == []
    assert boundary.rows == before


@pytest.mark.parametrize("route", ["single", "bulk"])
@pytest.mark.parametrize("reason", [None, " ", 12, "x" * 501])
def test_invalid_rejection_has_no_notification_or_downstream_mutation(monkeypatch, route, reason):
    """DR validation: Arrange invalid rejection reason; call real route;
    assert clear 400 before any downstream HTTP work or notification mutation.

    Why: Invalid workflow input must not create decision side effects.
    """
    http = MagicMock(side_effect=AssertionError("must reject before HTTP"))
    monkeypatch.setattr(clients.httpx, "request", http)
    url = f"/equipment-reservations/requests/{R1}" if route == "single" else f"/equipment-reservations/events/{EVENT}"
    response = create_app({"TESTING": True}).test_client().patch(url,
        headers=identity(TSS1, "Technical Support"), json={"status": "Rejected", "rejectionReason": reason})
    assert response.status_code == 400
    assert response.json == {"message": "A rejection reason between 1 and 500 characters is required."}
    http.assert_not_called()



def test_public_submission_discards_forged_recipient_and_internal_token(boundary):
    """AC1 security DR: Given forged public context/token, when submitting,
    then the owner gets only server-resolved TSS/event facts and configured token.
    Why: public input must not redirect notification intent to another user.
    """
    response = boundary.client.post(f"/equipment-reservations/events/{EVENT}/requests",
        headers={**identity(A,"Event Coordinator"),"X-Internal-Token":"attacker"},
        json={"items":[dict(equipmentId=MIC,quantityRequested=5)],
              "notificationContext":dict(eventName="Forged event",recipientIds=[B])})
    assert response.status_code == 201
    [call] = mutations(boundary)
    assert call.kwargs["headers"]["X-Internal-Token"] == "synthetic"
    assert call.kwargs["json"]["notificationContext"]["recipientIds"] == [
        "10000000-0000-4000-8000-000000000006", "10000000-0000-4000-8000-000000000007"]
    assert call.kwargs["json"]["notificationContext"]["eventName"] == "Community Fair"


def test_no_frontend_origin_configuration_does_not_grant_arbitrary_cors():
    """DR transport: Arrange no configured browser origin; health request;
    assert no arbitrary cross-origin grant while service remains healthy.

    Why: Missing configuration must not silently broaden browser access.
    """
    client = create_app({"FRONTEND_ORIGIN": None}).test_client()
    response = client.get("/health", headers={"Origin": "https://untrusted.invalid"})
    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers
