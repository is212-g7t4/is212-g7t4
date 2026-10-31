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
- The real app.clients submission and review adapters: the trusted context
  lookup (event, equipment names, Technical Support users), the configured
  internal token and the fail-before-write checks run for real.
- Assertions are on the outgoing requests and on no owner write happening.

Doubled
-------
- httpx.request: Stub (`upstream` fixture) - deterministic Event, Equipment,
  User and Equipment Request replies; outgoing requests are inspected.

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

import httpx
import pytest

from app import clients, create_app

EVENT, OTHER, COORDINATOR, TSS1, TSS2, MIC = [
    f"10000000-0000-4000-8000-{i:012d}" for i in range(1, 7)]


@pytest.fixture
def upstream(monkeypatch):
    """Fresh deterministic external HTTP responses; no monkeypatch of snapshot logic."""
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "trusted-config-token")
    for name, host in [("EQUIPMENT_REQUEST", "owner"), ("EVENT", "event"),
                       ("EQUIPMENT", "equipment"), ("USER", "user")]:
        monkeypatch.setenv(name + "_SERVICE_URL", f"http://{host}.invalid")
    state = dict(event={"id": EVENT, "eventName": "Community Fair", "coordinatorId": COORDINATOR},
        catalogue=[{"id": MIC, "description": "Microphone"}], users=[
            {"user_id": TSS2, "role": "Technical Support"},
            {"user_id": TSS1, "role": "Technical Support Staff"},
            {"user_id": TSS2, "role": "Technical Support"},
            {"user_id": OTHER, "role": "Event Coordinator"}, {"user_id": OTHER}])
    def http(method, url, **kwargs):
        if url == "http://equipment.invalid/equipment":
            body = {"equipment": deepcopy(state["catalogue"])}
        elif url.endswith("/notification-context"):
            body = deepcopy(state["event"])
        elif url == "http://user.invalid/users":
            body = {"users": deepcopy(state["users"])}
        elif method == "GET":
            body = {"request": {"id": OTHER, "eventId": EVENT}}
        else:
            body = {"requests": [{"id": OTHER}], "request": {"id": OTHER}}
        return httpx.Response(200, json=body, request=httpx.Request(method, url))
    request = MagicMock(side_effect=http)
    monkeypatch.setattr(httpx, "request", request)
    return state, request


@pytest.mark.parametrize("operation", ["submit", "single-approve", "single-reject", "bulk-approve", "bulk-reject"], ids=["submit", "single_approve", "single_reject", "bulk_approve", "bulk_reject"])
def test_change_request_with_spoofed_headers_sends_trusted_context_and_token(upstream, operation):
    """
    Summary: Spoofed tokens, cookies or context from the caller never reach the owner; trusted ones do.
    AC1: Given an Event Coordinator submits an equipment request, the system
        sends an in-app notification to Technical Support Staff with the event
        name, requested equipment list, and a link to review the request.
    AC2: Given equipment is confirmed as available or found to be unavailable,
        the system sends an in-app notification to the Event Coordinator with
        the event name, equipment list, and availability status.
    Double: Stub (upstream replies), Mock (owner request inspected)
    """
    # Arrange (Given)
    _, request = upstream
    headers = {"Authorization": "Bearer coordinator-token",
               "X-Internal-Token": "attacker-token", "Cookie": "attacker-cookie",
               "notificationContext": "attacker-snapshot"}
    with create_app().test_request_context(headers=headers):
        if operation == "submit":
            clients.create_event_requests(EVENT, [{"equipmentId": MIC, "quantityRequested": 5}])
        else:
            decision = "Rejected" if operation.endswith("reject") else "Approved"
            if operation.startswith("bulk"):
                clients.review_event_requests(EVENT, decision, "Private workflow reason")
            else:
                clients.review_request(OTHER, decision, "Private workflow reason")
    method, url = request.call_args.args

    kwargs = request.call_args.kwargs

    # Act + Assert (When / Then)
    assert method == ("POST" if operation == "submit" else "PATCH")
    assert url.startswith("http://owner.invalid/")
    # Reviews carry the configured credential, never a caller-supplied token.
    expected_headers = {"Authorization": "Bearer coordinator-token"}
    if operation != "submit":
        expected_headers["X-Internal-Token"] = "trusted-config-token"
    assert kwargs["headers"] == expected_headers
    expected = dict(eventId=EVENT, eventName="Community Fair", equipmentNames={MIC: "Microphone"})
    if operation == "submit":
        expected["recipientIds"] = [TSS1, TSS2]
    else:
        expected["coordinatorId"] = COORDINATOR
    assert kwargs["json"]["notificationContext"] == expected
    assert ("rejectionReason" in kwargs["json"]) is operation.endswith("reject")
    reads = [c for c in request.call_args_list if c.args[1].endswith("/notification-context")]
    assert len(reads) == 1
    assert reads[0].kwargs["headers"] == {"Authorization": "Bearer coordinator-token",
                                          "X-Internal-Token": "trusted-config-token"}
    assert request.call_args_list.index(reads[0]) < len(request.call_args_list) - 1


@pytest.mark.parametrize("configured", [None, ""], ids=["unset", "blank"])
def test_submit_when_internal_token_unconfigured_returns_503_without_write(upstream, monkeypatch, configured):
    """
    Summary: Without a configured internal token nothing is saved, whatever the caller sends.
    AC1: Given an Event Coordinator submits an equipment request, the system
        sends an in-app notification to Technical Support Staff with the event
        name, requested equipment list, and a link to review the request.
    Double: Stub (upstream replies), Mock (no POST/PATCH)
    """
    # Arrange (Given)
    _, request = upstream
    if configured is None:
        monkeypatch.delenv("INTERNAL_SERVICE_TOKEN")
    else:
        monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", configured)

    # Act + Assert (When / Then)
    with pytest.raises(clients.DownstreamError) as error, \
            create_app().test_request_context(headers={"X-Internal-Token": "attacker"}):
        clients.create_event_requests(EVENT, [])

    # Assert (Then)
    assert error.value.status == 503
    assert error.value.message == "Internal service authentication is not configured."
    assert all(c.args[0] == "GET" for c in request.call_args_list)


def test_review_when_event_lookup_returns_other_event_returns_502_without_write(upstream):
    """
    Summary: If Event Service answers with a different event, the decision is not saved or alerted.
    AC2: Given equipment is confirmed as available or found to be unavailable,
        the system sends an in-app notification to the Event Coordinator with
        the event name, equipment list, and availability status.
    Double: Stub (Event Service returns another event), Mock (no PATCH)
    """
    # Arrange (Given)
    state, request = upstream
    state["event"]["id"] = OTHER

    # Act + Assert (When / Then)
    with pytest.raises(clients.DownstreamError) as error:
        clients.review_event_requests(EVENT, "Approved")

    # Assert (Then)
    assert error.value.status == 502
    assert error.value.message == "Event notification context does not match this event."
    assert all(c.args[0] == "GET" for c in request.call_args_list)


@pytest.mark.parametrize("failed_host", ["equipment", "event", "user"], ids=["equipment", "event", "user"])
def test_submit_when_lookup_service_fails_returns_error_without_write(upstream, failed_host):
    """
    Summary: If the catalogue, event or user lookup fails, nothing is saved.
    AC1: Given an Event Coordinator submits an equipment request, the system
        sends an in-app notification to Technical Support Staff with the event
        name, requested equipment list, and a link to review the request.
    Double: Stub (one upstream host fails), Mock (no POST)
    """
    # Arrange (Given)
    _, request = upstream
    original = request.side_effect
    def fail(method, url, **kwargs):
        if url.startswith(f"http://{failed_host}.invalid"):
            raise httpx.ConnectError("password=private")
        return original(method, url, **kwargs)
    request.side_effect = fail

    # Act + Assert (When / Then)
    with pytest.raises(clients.DownstreamError) as error:
        clients.create_event_requests(EVENT, [])

    # Assert (Then)
    assert error.value.status == 503
    assert "private" not in error.value.message
    assert all(c.args[0] == "GET" for c in request.call_args_list)


def test_submit_when_no_technical_support_users_sends_no_recipients(upstream):
    """
    Summary: With no Technical Support users, the submission names no recipients rather than another role.
    AC1: Given an Event Coordinator submits an equipment request, the system
        sends an in-app notification to Technical Support Staff with the event
        name, requested equipment list, and a link to review the request.
    Double: Stub (User Service lists only a coordinator)
    """
    # Arrange (Given)
    state, _ = upstream

    state["users"] = [{"user_id": OTHER, "role": "Event Coordinator"}]

    # Act + Assert (When / Then)
    assert clients.notification_snapshot(EVENT, submission=True)["recipientIds"] == []
