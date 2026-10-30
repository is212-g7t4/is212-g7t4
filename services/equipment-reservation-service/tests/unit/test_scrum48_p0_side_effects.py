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
- The real reservation routes and app.clients: bulk review forwarding, the
  stock check before approval, rejection-reason validation and the replacement
  of caller-supplied notification context run for real.
- Assertions are on the status and on which downstream mutations are sent.

Doubled
-------
- Downstream services: Stub (`boundary` fixture or httpx.request) - canned
  replies; mutations are inspected or asserted absent.

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
from copy import deepcopy
from unittest.mock import MagicMock
import pytest
from app import create_app, clients
from tests.unit.factories import (
    EVENT, MIC, PROJECTOR, A, B, TSS1, R1, R2, identity, boundary, row, mutations,
)


@pytest.mark.parametrize("decision", ["Approved", "Rejected"], ids=["approved", "rejected"])
def test_bulk_review_sends_one_decision_and_returns_only_changed_requests(boundary, decision):
    """
    Summary: A bulk decision is sent once and only the requests the owner changed come back for alerting.
    AC2: Given equipment is confirmed as available or found to be unavailable,
        the system sends an in-app notification to the Event Coordinator with
        the event name, equipment list, and availability status.
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
    """
    Summary: An approval blocked by stock sends no decision and so no alert.
    AC2: Given equipment is confirmed as available or found to be unavailable,
        the system sends an in-app notification to the Event Coordinator with
        the event name, equipment list, and availability status.
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


@pytest.mark.parametrize("route", ["single", "bulk"], ids=["single", "bulk"])
@pytest.mark.parametrize("reason", [None, " ", 12, "x" * 501], ids=["missing", "blank", "non_text", "too_long"])
def test_reject_with_invalid_reason_returns_400_before_any_call(monkeypatch, route, reason):
    """
    Summary: A rejection with a missing or bad reason is refused before any downstream call or alert.
    AC2: Given equipment is confirmed as available or found to be unavailable,
        the system sends an in-app notification to the Event Coordinator with
        the event name, equipment list, and availability status.
    Double: Stub (httpx.request fails the test if called)
    """
    # Arrange (Given)
    http = MagicMock(side_effect=AssertionError("must reject before HTTP"))
    monkeypatch.setattr(clients.httpx, "request", http)
    url = f"/equipment-reservations/requests/{R1}" if route == "single" else f"/equipment-reservations/events/{EVENT}"

    # Act (When)
    response = create_app({"TESTING": True}).test_client().patch(url,
        headers=identity(TSS1, "Technical Support"), json={"status": "Rejected", "rejectionReason": reason})

    # Assert (Then)
    assert response.status_code == 400
    assert response.json == {"message": "A rejection reason between 1 and 500 characters is required."}
    http.assert_not_called()


def test_submit_request_with_forged_context_sends_only_server_resolved_recipients(boundary):
    """
    Summary: Recipients and the internal token a caller sends are ignored; only server-looked-up ones are used.
    AC1: Given an Event Coordinator submits an equipment request, the system
        sends an in-app notification to Technical Support Staff with the event
        name, requested equipment list, and a link to review the request.
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


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_health_when_frontend_origin_unset_allows_no_browser_origin():
    """
    Summary: With no frontend origin configured, no website gets browser access.
    Supporting design check: an unset FRONTEND_ORIGIN grants no origin
    Double: None
    """
    client = create_app({"FRONTEND_ORIGIN": None}).test_client()
    response = client.get("/health", headers={"Origin": "https://untrusted.invalid"})
    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers
