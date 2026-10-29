"""SCRUM-48 equipment notifications: trusted action-time snapshot boundary.

Story: Technical Support Staff and Event Coordinators receive equipment alerts.
AC1 submission, AC2 approval, AC3 rejection without the workflow reason are the
original three criteria. Cases here are supporting security/failure rules (DR).
Real public composite client adapters; HTTP is doubled. These assertions prove
requested context/token selection and fail-before-write, not commit-time
assignment, remote authorization, database persistence or durable delivery.
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


@pytest.mark.parametrize("operation", ["submit", "single-approve", "single-reject", "bulk-approve", "bulk-reject"])
def test_mutations_replace_attacker_context_with_trusted_lookup_and_token(upstream, operation):
    """AC1/AC2/AC3 + security DR: Arrange spoofed identity-adjacent headers;
    call adapter; assert fresh trusted context, configured token and no attacker
    cookie/context header forwarded; rejection reason only in workflow payload.

    Why: Trusted snapshot selection must not be delegated to an untrusted caller.
    """
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
    assert method == ("POST" if operation == "submit" else "PATCH")
    assert url.startswith("http://owner.invalid/")
    assert kwargs["headers"] == {"Authorization": "Bearer coordinator-token",
                                 "X-Internal-Token": "trusted-config-token"}
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


@pytest.mark.parametrize("configured", [None, ""])
def test_missing_internal_configuration_prevents_mutation(upstream, monkeypatch, configured):
    """DR security: Arrange absent/empty server token; submit; assert safe 503
    and no POST/PATCH, even if caller provides its own internal-token header.

    Why: Caller credentials must not bypass missing server configuration.
    """
    _, request = upstream
    if configured is None:
        monkeypatch.delenv("INTERNAL_SERVICE_TOKEN")
    else:
        monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", configured)
    with pytest.raises(clients.DownstreamError) as error, \
            create_app().test_request_context(headers={"X-Internal-Token": "attacker"}):
        clients.create_event_requests(EVENT, [])
    assert error.value.status == 503
    assert error.value.message == "Internal service authentication is not configured."
    assert all(c.args[0] == "GET" for c in request.call_args_list)


def test_mismatched_event_snapshot_prevents_owner_write(upstream):
    """DR context integrity: Arrange event service returning another event;
    review; assert 502 and no mutation, rather than misdirecting a notification.

    Why: An upstream identity mismatch must not create a misdirected decision.
    """
    state, request = upstream
    state["event"]["id"] = OTHER
    with pytest.raises(clients.DownstreamError) as error:
        clients.review_event_requests(EVENT, "Approved")
    assert error.value.status == 502
    assert error.value.message == "Event notification context does not match this event."
    assert all(c.args[0] == "GET" for c in request.call_args_list)


@pytest.mark.parametrize("failed_host", ["equipment", "event", "user"])
def test_snapshot_dependency_failure_produces_no_owner_mutation(upstream, failed_host):
    """DR failure: Arrange catalogue/event/user HTTP outage; submit; assert
    generic dependency failure with no owner write and no leaked credentials.

    Why: Incomplete upstream facts must not become partially enriched saved decisions.
    """
    _, request = upstream
    original = request.side_effect
    def fail(method, url, **kwargs):
        if url.startswith(f"http://{failed_host}.invalid"):
            raise httpx.ConnectError("password=private")
        return original(method, url, **kwargs)
    request.side_effect = fail
    with pytest.raises(clients.DownstreamError) as error:
        clients.create_event_requests(EVENT, [])
    assert error.value.status == 503
    assert "private" not in error.value.message
    assert all(c.args[0] == "GET" for c in request.call_args_list)


def test_zero_eligible_tss_keeps_submission_context_empty(upstream):
    """DR recipient selection: Arrange no eligible TSS; snapshot submission;
    assert empty recipients, never other-role users or a fallback coordinator.

    Why: An empty audience must not fall back to a different role.
    """
    state, _ = upstream
    state["users"] = [{"user_id": OTHER, "role": "Event Coordinator"}]
    assert clients.notification_snapshot(EVENT, submission=True)["recipientIds"] == []
