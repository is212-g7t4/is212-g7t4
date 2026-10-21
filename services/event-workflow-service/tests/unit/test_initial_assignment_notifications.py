"""SCRUM-45 user story: As an Event Organiser I want to know who coordinates
my event through the existing in-app inbox. AC4 initial assignment; DR3 retry,
DR4 frozen saved identity, DR6 missing-name diagnosis. Worker public boundary.
"""
from unittest.mock import Mock, patch
import httpx
import pytest
from app.dispatcher import OutboxAPI, dispatch_once

COORDINATOR = "10000000-0000-0000-0000-000000000002"
SOURCE = dict(eventId="30000000-0000-0000-0000-000000000001",
              recipientId="10000000-0000-0000-0000-000000000001",
              eventName="Community Workshop", coordinatorId=COORDINATOR)
JOB = dict(id="20000000-0000-0000-0000-000000000001", source=SOURCE,
           type="event.coordinator-assignment", envelope=None,
           createdAt="2026-10-21T00:00:00+00:00", leaseToken="lease")

@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("EVENT_SERVICE_URL", "http://event.test")
    monkeypatch.setenv("USER_SERVICE_URL", "http://user.test/")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "test-token")
    return OutboxAPI()

def transport(request):
    if request.method == "GET":
        assert str(request.url) == f"http://user.test/users/{COORDINATOR}"
        return httpx.Response(200, json=dict(user_id=COORDINATOR, username="Alice Tan"))
    if request.url.path.endswith("claim"):
        return httpx.Response(200, json=dict(jobs=[JOB]))
    if request.url.path.endswith("freeze"):
        import json
        return httpx.Response(200, json=dict(envelope=json.loads(request.content)["envelope"]))
    return httpx.Response(200, json={})

def test_worker_resolves_saved_id_using_user_username_and_freezes_before_publish(api):
    """AC4/DR4: exercise worker with HTTP transport and broker I/O mocked;
    User's actual username field supplies name for saved coordinator ID.
    """
    published = []
    with httpx.Client(transport=httpx.MockTransport(transport)) as client, patch("httpx.request", side_effect=client.request):
        assert dispatch_once(api, published.append) == 1
    assert len(published) == 1, "Initial assignment must publish after User lookup"
    assert published[0] == dict(version=1, id=JOB["id"], type="event.coordinator-assignment",
        recipientId=SOURCE["recipientId"], createdAt=JOB["createdAt"],
        message="Alice Tan has been assigned to coordinate Community Workshop.",
        destination=dict(kind="event-details", eventId=SOURCE["eventId"]),
        details={**SOURCE, "coordinatorName": "Alice Tan"})


@pytest.mark.parametrize("status,body", [(404, {"message": "User not found."}),
    (200, {"username": "   "}), (200, {}), (200, {"username": None}), (200, {"username": 23})])
def test_unusable_user_is_held_for_repair_without_blocking_other_work(api, status, body):
    """DR6: missing user/blank or unusable username is a diagnosed hold;
    unrelated rejection still publishes. HTTP mocked, not worker behavior.
    """
    good = {**JOB, "id": "20000000-0000-0000-0000-000000000002", "type": "event.rejection",
            "source": {**SOURCE, "reason": "Missing plan", "decision": "Rejected"}}
    calls, published = [], []
    def respond(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(status, json=body)
        if request.url.path.endswith("claim"):
            return httpx.Response(200, json={"jobs": [JOB, good]})
        return transport(request)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client, patch("httpx.request", side_effect=client.request):
        assert dispatch_once(api, published.append) == 2
    held = [request for request in calls if request.url.path.endswith("/hold")]
    assert len(held) == 1, "Unusable coordinator name must be held, not endlessly retried"
    import json
    assert json.loads(held[0].content) == {"leaseToken": "lease", "error": f"CoordinatorNameUnavailable coordinatorId={COORDINATOR}"}
    assert len(published) == 1 and published[0]["id"] == good["id"]


@pytest.mark.parametrize("outcome", [503, "timeout"])
def test_temporary_lookup_failure_retries_same_change_then_delivers(api, outcome):
    """DR3/DR6: transient HTTP failure retries without freeze/publish; recovery
    resolves same saved ID and delivers original identity/name.
    """
    actions, published = [], []
    failed = True
    def respond(request):
        actions.append(request.url.path)
        if request.method == "GET" and failed:
            if outcome == "timeout":
                raise httpx.ReadTimeout("temporary", request=request)
            return httpx.Response(503, json={})
        return transport(request)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client, patch("httpx.request", side_effect=client.request):
        dispatch_once(api, published.append)
        assert published == []
        assert actions[-1].endswith("/retry")
        assert not any(path.endswith("/freeze") or path.endswith("/hold") for path in actions)
        failed = False
        dispatch_once(api, published.append)
    assert published[0]["id"] == JOB["id"]
    assert published[0]["details"]["coordinatorName"] == "Alice Tan"


def test_assignment_publish_retry_uses_frozen_name_without_user_lookup(api):
    """DR4: after failed publish, reclaim with frozen envelope and changed
    user name; verify retry publishes first prepared name without another GET.
    """
    frozen, looked_up = [], []
    def respond(request):
        if request.method == "GET":
            looked_up.append(request.url.path)
        if request.url.path.endswith("claim") and frozen:
            return httpx.Response(200, json={"jobs": [{**JOB, "envelope": frozen[0]}]})
        return transport(request)
    def outage(envelope):
        frozen.append(envelope)
        raise RuntimeError("broker outage")
    published = []
    with httpx.Client(transport=httpx.MockTransport(respond)) as client, patch("httpx.request", side_effect=client.request):
        dispatch_once(api, outage)
        dispatch_once(api, published.append)
    assert len(looked_up) == 1
    assert published == frozen
    assert published[0]["details"]["coordinatorName"] == "Alice Tan"


def test_hold_storage_outage_does_not_stop_unrelated_work(api, caplog):
    """DR6: failed hold write remains lease-recoverable and does not abort batch."""
    calls = []
    def respond(request):
        calls.append(request.url.path)
        if request.method == "GET":
            return httpx.Response(404, json={})
        if request.url.path.endswith("/hold"):
            return httpx.Response(503, json={})
        return transport(request)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client, patch("httpx.request", side_effect=client.request):
        assert dispatch_once(api, Mock()) == 1
    assert "Hold update failed; lease will recover" in caplog.text
