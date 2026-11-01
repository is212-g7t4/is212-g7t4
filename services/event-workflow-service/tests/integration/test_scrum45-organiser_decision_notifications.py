"""SCRUM-45 Event Organiser Status and Update Notifications: Workflow integration tests.

Story: As an Event Organiser, I want to receive an in-app notification when the Lead Coordinator approves or rejects my event request, so that I know the outcome and who is responsible for coordinating my event.
Real: dispatch_once orchestration and OutboxAPI/httpx adapter.
Doubled: every external Event/User HTTP request (strict respx) and recording publisher. No DB, broker or service process.
Not proven: Event transactions, Notification inbox/deduplication, UI/E2E or production authentication.
AC = acceptance criterion; DR = supporting design rule, not another AC.

AC1 A successfully recorded approval sends an in-app approval notification to the submitting Event Organiser.
  Owned: approval preparation/freeze/publication; actual owner mutation and inbox not covered here.
AC2 A successfully recorded rejection sends an in-app rejection notification to the submitting Event Organiser, including the rejection reason.
  Owned: rejection preparation/reason/publication; actual owner mutation and inbox not covered here.
AC3 Both decision notifications include event name, decision, and a link to the event request and its decision details.
  Owned: exact prepared content/destination; target access and frontend navigation not covered here.
AC4 A successfully recorded initial assignment or reassignment sends the submitting Event Organiser an in-app notification with event name, newly assigned coordinator name, and an event-details link.
  Owned: saved-ID name lookup and publication for both changes; Event mutation and inbox not covered here.
"""
import json

import httpx
import pytest

from app.dispatcher import dispatch_once
from tests.integration.factories import (
    ALICE, BOB, EVENT, ORGANISER, make_job, expected_envelope,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
BASE = "https://event.test/internal/notification-outbox"


def post(http, action, body, response, *, job=None, status=200, effects=None):
    """Register one exact POST contract and return its respx route; validate body, token and
    timeout and optionally record order.
    """
    url = BASE + (f"/{job['id']}" if job else "") + "/" + action
    def reply(request):
        assert json.loads(request.content) == body
        assert request.headers["X-Internal-Token"] == "scrum45-test-token"
        assert request.extensions["timeout"] == dict(connect=5, read=5, write=5, pool=5)
        if effects is not None:
            effects.append(action)
        return httpx.Response(status, json=response)
    return http.post(url, json=body).mock(side_effect=reply)


def user(http, identifier, name="Synthetic Alice", status=200, *, body=None, error=None):
    # User's actual GET /users/<id> response uses username, not name (app/models.py).
    """Register a saved-ID User GET and return its route; supply username, malformed data, status
    failure or timeout without network I/O.
    """
    def reply(request):
        assert request.content == b""
        assert request.headers["X-Internal-Token"] == "scrum45-test-token"
        assert request.extensions["timeout"] == dict(connect=5, read=5, write=5, pool=5)
        if error:
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return httpx.Response(status, json=body if body is not None else {"user_id": identifier, "username": name})
    return http.get(f"https://user.test/users/{identifier}").mock(side_effect=reply)


def freeze(http, job, *, name="Synthetic Alice", status=200, effects=None):
    """Stub the exact draft POST and return a distinct owner-authoritative envelope plus route for
    publication and call-count assertions.
    """
    draft = expected_envelope(job, name)
    # Owner may already have frozen a valid richer envelope; worker must use its reply.
    authoritative = {**draft, "ownerRevision": "first-frozen"}
    route = post(http, "freeze", {"leaseToken": job["leaseToken"], "envelope": draft},
                 {"envelope": authoritative}, job=job, status=status, effects=effects)
    return authoritative, route


def complete(http, job, **kwargs):
    """Register the exact published POST for this job's lease and return its route for completion
    assertions.
    """
    return post(http, "published", {"leaseToken": job["leaseToken"]}, {}, job=job, **kwargs)


def retry(http, job, error, **kwargs):
    """Register the exact retry POST with lease and error and return its route for recovery
    assertions.
    """
    return post(http, "retry", {"leaseToken": job["leaseToken"], "error": error}, {}, job=job, **kwargs)


# AC1 — Approval

def test_ac1_approval_freezes_before_publish_and_completes_after_acceptance(api, http):
    """Normal: dispatch approval through the HTTP adapter; exact requests and recorded
    freeze/publish/complete order surround the correct organiser/message, preventing completion
    before publication.
    """
    job = make_job("approval")
    effects, published = [], []
    claimed = post(http, "claim", {}, {"jobs": [job]})
    expected, frozen = freeze(http, job, effects=effects)
    done = complete(http, job, effects=effects)
    def publish(envelope):
        effects.append("publish")
        published.append(envelope)
    assert dispatch_once(api, publish) == 1
    assert published == [expected]
    assert published[0]["recipientId"] == ORGANISER
    assert published[0]["message"] == "Community Workshop was approved"
    assert effects == ["freeze", "publish", "published"]
    assert claimed.call_count == frozen.call_count == done.call_count == 1


# AC2 — Rejection/reason

def test_ac2_rejection_keeps_independent_multiline_reason(api, http):
    """Boundary: dispatch a rejection through the HTTP adapter; the recording publisher receives
    the complete multiline reason in message and details, so preparation cannot silently shorten
    the explanation.
    """
    job = make_job("rejection")
    post(http, "claim", {}, {"jobs": [job]})
    expected, _ = freeze(http, job)
    complete(http, job)
    published = []
    assert dispatch_once(api, published.append) == 1
    assert published == [expected]
    assert published[0]["details"]["reason"] == "Needs accessible transport.\nPlease revise."
    assert published[0]["message"] == "Community Workshop was rejected: Needs accessible transport.\nPlease revise."


@pytest.mark.parametrize('reason', ['x' * 40000, '界' * 18000, '"\\\n' * 10000],
                         ids=['ascii', 'multibyte', 'escaped'])
def test_ac2_large_reason_uses_bounded_compact_httpx_bytes(api, http, reason):
    """Boundary: dispatch long ASCII, Unicode or escaped reasons; actual HTTPX bytes retain the
    exact text within the internal cap, showing serialization will not exceed the owner's freeze
    allowance.
    """
    job = make_job('rejection')
    job['source'].update(reason=reason, eventName='😀' * 255)
    post(http, 'claim', {}, {'jobs': [job]})
    expected = {**expected_envelope(job),
                'message': f"{job['source']['eventName']} was rejected: {reason}"}
    body = dict(leaseToken=job['leaseToken'], envelope=expected)
    frozen = post(http, 'freeze', body, {'envelope': expected}, job=job)
    complete(http, job)
    published = []
    assert dispatch_once(api, published.append) == 1
    assert published == [expected]
    wire = frozen.calls[0].request.content
    assert wire == json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()
    assert 65536 < len(wire) <= 135168


# AC3 — Shared decision content/link
@pytest.mark.parametrize("kind", ["approval", "rejection"])
def test_ac3_decision_publishes_owner_reply_not_local_draft(api, http, kind):
    """Normal: dispatch either decision with a richer freeze response; publication keeps the
    event/decision/link and owner-only field, proving the saved reply, not the local draft, is
    sent.
    """
    job = make_job(kind)
    post(http, "claim", {}, {"jobs": [job]})
    expected, frozen = freeze(http, job)
    complete(http, job)
    published = []
    dispatch_once(api, published.append)
    assert published == [expected]
    assert published[0]["ownerRevision"] == "first-frozen"
    assert "ownerRevision" not in json.loads(frozen.calls[0].request.content)["envelope"]
    assert published[0]["destination"] == dict(kind="event-details", eventId=EVENT)
    assert published[0]["details"]["eventName"] == "Community Workshop"
    assert published[0]["details"]["decision"] == ("Approved" if kind == "approval" else "Rejected")


@pytest.mark.parametrize("kind", ["approval", "coordinator-assignment"])
@pytest.mark.parametrize("status", [409, 503])
def test_ac3_freeze_conflict_or_failure_never_publishes(api, http, kind, status):
    """Conflict/Failure: return stale-lease 409 or freeze-outage 503 with and without a name lookup; no message
    publishes and the exact retry request is sent, protecting freeze-before-publish ordering.
    """
    job = make_job(kind)
    post(http, "claim", {}, {"jobs": [job]})
    if kind == "coordinator-assignment":
        user(http, ALICE)
    _, frozen = freeze(http, job, status=status)
    retried = retry(http, job, "HTTPStatusError")
    published = []
    assert dispatch_once(api, published.append) == 1
    assert published == []
    assert frozen.call_count == retried.call_count == 1


# AC4 — Initial assignment and reassignment

def test_ac4_initial_and_reassignment_use_each_saved_id_and_username(api, http):
    """Normal: dispatch Alice's assignment then Bob's replacement; separate saved-ID GETs produce
    two named messages with distinct IDs and the event link, preserving assignment history.
    """
    initial = make_job("coordinator-assignment", coordinator=ALICE)
    replacement = make_job("coordinator-assignment", coordinator=BOB)
    post(http, "claim", {}, {"jobs": [initial, replacement]})
    alice = user(http, ALICE, "Synthetic Alice")
    bob = user(http, BOB, "Synthetic Bob")
    first, _ = freeze(http, initial, name="Synthetic Alice")
    second, _ = freeze(http, replacement, name="Synthetic Bob")
    complete(http, initial)
    complete(http, replacement)
    published = []
    assert dispatch_once(api, published.append) == 2
    assert published == [first, second]
    assert len({message["id"] for message in published}) == 2
    assert [message["details"]["coordinatorName"] for message in published] == ["Synthetic Alice", "Synthetic Bob"]
    assert all(message["destination"] == dict(kind="event-details", eventId=EVENT) for message in published)
    assert alice.call_count == bob.call_count == 1


# Supporting DR3/DR4/DR6 — recovery and independent progress
@pytest.mark.parametrize("status,body", [(404, {}), (200, {"username": " "}),
                                        (200, {}), (200, {"username": None})])
def test_ac4_dr_missing_name_is_held_while_another_job_completes(api, http, status, body):
    """Failure: return a missing or unusable User name beside valid approval work; one diagnostic
    hold and only the approval publishes, avoiding an ID-only assignment or blocked batch (DR6).
    """
    bad, good = make_job("coordinator-assignment"), make_job("approval")
    post(http, "claim", {}, {"jobs": [bad, good]})
    user(http, ALICE, status=status, body=body)
    held = post(http, "hold", {"leaseToken": bad["leaseToken"],
                "error": "CoordinatorNameUnavailable coordinatorId=" + ALICE}, {}, job=bad)
    expected, _ = freeze(http, good)
    complete(http, good)
    published = []
    assert dispatch_once(api, published.append) == 2
    assert published == [expected]
    assert held.call_count == 1


@pytest.mark.parametrize("failure", ["503", "timeout"])
def test_ac4_dr_transient_lookup_retries_then_same_change_delivers(api, http, failure):
    """Failure: return User timeout or 503, then restore the response; first dispatch only retries
    and the next publishes the same change ID, preserving temporary failures as recoverable work
    (DR3/DR6).
    """
    job = make_job("coordinator-assignment")
    post(http, "claim", {}, {"jobs": [job]})
    lookup = user(http, ALICE, status=503, error=failure == "timeout")
    retried = retry(http, job, "ReadTimeout" if failure == "timeout" else "HTTPStatusError")
    published = []
    assert dispatch_once(api, published.append) == 1
    assert published == []
    assert lookup.call_count == retried.call_count == 1
    # Arrange recovery at the external HTTP response boundary only.
    user(http, ALICE, "Synthetic Alice")
    expected, _ = freeze(http, job)
    complete(http, job)
    assert dispatch_once(api, published.append) == 1
    assert published == [expected]
    assert published[0]["id"] == job["id"]


@pytest.mark.parametrize("kind", ["approval", "coordinator-assignment"])
def test_ac3_dr_successful_publish_then_completion_failure_replays_frozen_identity(api, http, kind):
    """Conflict: accept publication but fail completion, then reclaim with changed source; two
    identical frozen attempts and no second lookup/freeze preserve identity for downstream
    deduplication (DR3/DR4).
    """
    job = make_job(kind)
    claim_route = post(http, "claim", {}, {"jobs": [job]})
    lookup = user(http, ALICE) if kind == "coordinator-assignment" else None
    expected, frozen = freeze(http, job)
    done = complete(http, job, status=503)
    retried = retry(http, job, "HTTPStatusError")
    published = []
    assert dispatch_once(api, published.append) == 1
    assert published == [expected]
    assert done.call_count == retried.call_count == 1
    # Act again: simulate owner recovery after the broker accepted an uncompleted job.
    reclaim = {**job, "leaseToken": "new-lease", "envelope": expected,
               "source": {**job["source"], "eventName": "Later event name"}}
    claim_route.mock(return_value=httpx.Response(200, json={"jobs": [reclaim]}))
    new_done = complete(http, reclaim)
    assert dispatch_once(api, published.append) == 1
    # Assert: both attempts retain one source identity; deduplication belongs to Notification.
    assert published == [expected, expected]  # consumer, not this service, deduplicates these attempts
    assert frozen.call_count == 1
    assert lookup is None or lookup.call_count == 1
    assert new_done.call_count == 1


def test_ac4_dr_hold_write_failure_still_allows_independent_delivery(api, http, caplog):
    """Failure: make one assignment's hold POST fail; a lease-recovery warning and publication of
    the independent approval show recovery failure does not abort the batch (DR6).
    """
    bad, good = make_job("coordinator-assignment"), make_job("approval")
    post(http, "claim", {}, {"jobs": [bad, good]})
    user(http, ALICE, status=404)
    post(http, "hold", {"leaseToken": bad["leaseToken"],
         "error": "CoordinatorNameUnavailable coordinatorId=" + ALICE}, {}, job=bad, status=503)
    expected, _ = freeze(http, good)
    complete(http, good)
    published = []
    assert dispatch_once(api, published.append) == 2
    assert published == [expected]
    assert "Hold update failed; lease will recover" in caplog.text


def test_ac1_dr_claim_auth_failure_escapes_without_publication(api, http):
    """Failure: return 401 from the owner claim endpoint; dispatch raises HTTPStatusError and
    publishes nothing, distinguishing denied access from an empty successful batch (DR8).
    """
    post(http, "claim", {}, {"message": "Internal token required."}, status=401)
    published = []
    with pytest.raises(httpx.HTTPStatusError):
        dispatch_once(api, published.append)
    assert published == []
