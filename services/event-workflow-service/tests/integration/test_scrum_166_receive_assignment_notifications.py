"""SCRUM-166 — Receive assignment notifications.

As an Event Coordinator, I want to receive in-app notifications when I am assigned to or removed from an event, so that I know which events I am responsible for.

- **AC1:** Given the Lead Coordinator successfully assigns an Event Coordinator to an event that previously had no assigned coordinator, the assigned coordinator receives an in-app assignment notification.
- **AC2:** Given the Lead Coordinator successfully reassigns an event from one coordinator to a different coordinator:
  - The new coordinator receives an in-app notification that they have been assigned.
  - The previous coordinator receives an in-app notification that they have been removed.
- **AC3:** Assignment notifications include the event name, Event Organiser name, proposed event date/time, and a link to view the newly assigned event.
- **AC4:** Removal notifications include the event name, Event Organiser name, proposed event date/time, and a clear statement that the recipient is no longer assigned to the event.
- **AC5:** Saving an assignment without changing the assigned coordinator does not create new assignment or removal notifications.

AC = acceptance criterion; DR = supporting design rule.
AC1/AC2: not covered here as business triggers or committed inboxes; Event and
Notification integration story modules own those persistence boundaries.
AC3/AC4: covered here at HTTP preparation/freeze/publication adapter boundaries;
frontend components cover presentation, not a live linked-event journey.
AC5: not covered here because Event suppresses unchanged saves before dispatch;
Event unit and integration story modules verify that rule.

Real: dispatcher and HTTPX adapter. Doubled: strict HTTP owner/User stubs and recording publisher.
Not proven: live owner persistence, real broker, inbox or UI. No database or service starts.
"""

import json
import httpx
import pytest
from app.dispatcher import dispatch_once
from tests.integration.factories import (
    EVENT, ORGANISER, ALICE, BOB, make_received_job, received_envelope,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


# Owner contracts: services/event-service/app/outbox.py operate(), serialize(),
# mutate(): POST claim -> {jobs: [serialized row]}, freeze -> {envelope, ...},
# published/retry -> {id, status}. Callers ignore unused response fields.
def post(http, job, action, expected, result=None, status=200, before=None):
    url = "https://event.test/internal/notification-outbox/" + (
        "claim" if action == "claim" else job["id"] + "/" + action)
    def respond(request):
        assert request.headers["X-Internal-Token"] == "scrum45-test-token"
        assert json.loads(request.content) == expected
        if before:
            before()
        return httpx.Response(status, json=result if result is not None else dict(id=job["id"], status=action))
    return http.post(url).mock(side_effect=respond)


def prepare(http, job, published):
    post(http, job, "claim", {}, {"jobs": [job]})
    # GET shape: services/user-service/app/__init__.py user_details() returns
    # services/user-service/app/models.py serialize() directly (no wrapper).
    http.get(f"https://user.test/users/{ORGANISER}").respond(200, json={
        "user_id": ORGANISER, "username": "Synthetic Organiser", "email": "organiser@example.com",
        "role": "Event Organiser", "organization": "", "contact_details": "",
    })
    expected = received_envelope(job)
    # A prior successful preparation can win the owner's first-write freeze.
    # Keep the returned envelope valid but distinguishable from this attempt's draft.
    owner_frozen = {**expected,
                    "details": {**expected["details"], "organiserName": "Previously Frozen Organiser"},
                    "message": expected["message"].replace("Synthetic Organiser", "Previously Frozen Organiser")}
    def unpublished():
        assert published == [], "Publication must follow owner freeze"
    frozen = post(http, job, "freeze", {"leaseToken": job["leaseToken"], "envelope": expected},
                  {**job, "envelope": owner_frozen}, before=unpublished)
    assert owner_frozen != expected
    return owner_frozen, frozen


# AC3 — HTTP assignment contract

def test_ac3_assignment_adapter_freezes_before_publish_and_completes(api, http):
    """Dispatch assignment through the actual HTTP client with strict owner/User stubs.
    Exact captured content/link freezes before publication, then the owner completes.
    """
    job = make_received_job()
    published = []
    expected, frozen = prepare(http, job, published)
    def published_first():
        assert published == [expected]
    done = post(http, job, "published", {"leaseToken": job["leaseToken"]}, before=published_first)
    assert dispatch_once(api, published.append) == 1
    assert published == [expected]
    assert frozen.call_count == done.call_count == 1


# AC4 — HTTP removal contract

def test_ac4_removal_adapter_uses_previous_recipient_and_no_destination(api, http):
    """Dispatch a removal whose historical schedule was absent.
    The old recipient gets explicit removal and Not provided, with null navigation.
    """
    job = make_received_job("removed", ALICE, scheduled=False)
    published = []
    expected, frozen = prepare(http, job, published)
    post(http, job, "published", {"leaseToken": job["leaseToken"]})
    assert dispatch_once(api, published.append) == 1
    assert published == [expected]
    assert published[0]["recipientId"] == ALICE
    assert published[0]["destination"] is None
    assert frozen.call_count == 1


# Supporting design rule — ambiguous publication/completion recovery

def test_dr_completion_failure_replays_frozen_content_without_enrichment(api, http):
    """Publish successfully, fail completion, then reclaim the frozen assignment.
    The retry publishes the same content and ID without another lookup or freeze.
    """
    job = make_received_job()
    published = []
    expected, frozen = prepare(http, job, published)
    done = post(http, job, "published", {"leaseToken": job["leaseToken"]}, status=503)
    retry = post(http, job, "retry", {"leaseToken": job["leaseToken"], "error": "HTTPStatusError"})
    assert dispatch_once(api, published.append) == 1
    assert done.call_count == retry.call_count == 1
    reclaim = {**job, "leaseToken": "replacement-lease", "envelope": expected,
               "source": {**job["source"], "eventName": "Later event"}}
    post(http, reclaim, "claim", {}, {"jobs": [reclaim]})
    complete = post(http, reclaim, "published", {"leaseToken": "replacement-lease"})
    assert dispatch_once(api, published.append) == 1
    assert published == [expected, expected]
    assert frozen.call_count == 1
    # respx retains route history on replacement: first 503 + one successful retry,
    # not two successful completions.
    assert complete.call_count == 2
    assert http.calls.call_count == 7


# Supporting design rule — organiser lookup failures hold or retry safely

@pytest.mark.parametrize("kind", ["assigned", "removed"], ids=["assignment", "removal"])
@pytest.mark.parametrize("lookup", ["not-found", "unusable-name"], ids=["user-404", "user-200-blank-name"])
def test_dr_unavailable_organiser_holds_without_freeze_or_publication(api, http, kind, lookup):
    """A missing or nameless organiser holds the intent without freezing or publishing."""
    job, published = make_received_job(kind), []
    post(http, job, "claim", {}, {"jobs": [job]})
    # User user_details()/serialize(): direct user object, or 404 message object.
    body = ({"message": "User not found."} if lookup == "not-found" else {
        "user_id": ORGANISER, "username": " ", "email": "organiser@example.com",
        "role": "Event Organiser", "organization": "", "contact_details": ""})
    user = http.get(f"https://user.test/users/{ORGANISER}").respond(
        404 if lookup == "not-found" else 200, json=body)
    held = post(http, job, "hold", {"leaseToken": job["leaseToken"],
                "error": f"OrganiserNameUnavailable organiserId={ORGANISER}"})

    assert dispatch_once(api, published.append) == 1
    assert published == []
    assert user.call_count == held.call_count == 1
    assert [call.request.url.path for call in http.calls] == [
        "/internal/notification-outbox/claim", f"/users/{ORGANISER}",
        f"/internal/notification-outbox/{job['id']}/hold"]


@pytest.mark.parametrize("kind", ["assigned", "removed"], ids=["assignment", "removal"])
@pytest.mark.parametrize("failure", ["503", "timeout"], ids=["user-503", "user-read-timeout"])
def test_dr_transient_organiser_failure_retries_same_identity_after_recovery(api, http, kind, failure):
    """A transient lookup retries unfrozen work; recovery publishes the original identity."""
    job, published = make_received_job(kind), []
    post(http, job, "claim", {}, {"jobs": [job]})
    user = http.get(f"https://user.test/users/{ORGANISER}")
    if failure == "503":
        user.respond(503, json={"message": "Temporarily unavailable."})
    else:
        user.mock(side_effect=httpx.ReadTimeout("Synthetic lookup timeout"))
    retry = post(http, job, "retry", {"leaseToken": job["leaseToken"],
                 "error": "HTTPStatusError" if failure == "503" else "ReadTimeout"})

    # First attempt must not freeze, complete, or publish anything.
    assert dispatch_once(api, published.append) == 1
    assert published == []
    assert retry.call_count == 1
    assert [call.request.url.path for call in http.calls] == [
        "/internal/notification-outbox/claim", f"/users/{ORGANISER}",
        f"/internal/notification-outbox/{job['id']}/retry"]

    # Reclaim the same obligation with a fresh lease after the lookup recovers.
    recovered = {**job, "leaseToken": "recovered-lease", "attempts": 2}
    expected, frozen = prepare(http, recovered, published)
    complete = post(http, recovered, "published", {"leaseToken": "recovered-lease"})
    assert dispatch_once(api, published.append) == 1
    assert published == [expected]
    assert published[0]["id"] == job["id"]
    assert published[0]["recipientId"] == job["source"]["recipientId"]
    assert published[0]["details"] == expected["details"]
    assert frozen.call_count == complete.call_count == 1
    assert retry.call_count == 1
    assert user.call_count == 2  # Failed lookup plus recovered lookup, not two successes.


# AC3/AC4 — Proposed Singapore period across midnight and equivalent offsets

@pytest.mark.parametrize("kind", ["assigned", "removed"], ids=["assignment", "removal"])
@pytest.mark.parametrize("start,end", [
    ("2030-03-01T15:59:00+00:00", "2030-03-01T16:00:00+00:00"),
    ("2030-03-01T10:59:00-05:00", "2030-03-02T01:00:00+09:00"),
], ids=["utc-singapore-midnight", "equivalent-mixed-offsets"])
def test_ac3_ac4_adapter_freezes_singapore_midnight_period(api, http, kind, start, end):
    """Equivalent offset intervals produce the same two-date Singapore midnight message."""
    job, published = make_received_job(kind), []
    job["source"].update(startDateTime=start, endDateTime=end)
    expected = received_envelope(job)
    action = "You are no longer assigned to" if kind == "removed" else "You have been assigned to"
    expected["message"] = (f"{action} Community Workshop. Event Organiser: Synthetic Organiser. "
        "Proposed: 01 Mar 2030, 23:59 SGT – 02 Mar 2030, 00:00 SGT.")
    post(http, job, "claim", {}, {"jobs": [job]})
    # User user_details()/serialize() returns the complete direct account object.
    http.get(f"https://user.test/users/{ORGANISER}").respond(200, json={
        "user_id": ORGANISER, "username": "Synthetic Organiser", "email": "organiser@example.com",
        "role": "Event Organiser", "organization": "", "contact_details": ""})
    def not_published():
        assert published == []
    frozen = post(http, job, "freeze", {"leaseToken": job["leaseToken"], "envelope": expected},
                  {**job, "envelope": expected}, before=not_published)
    complete = post(http, job, "published", {"leaseToken": job["leaseToken"]})

    assert dispatch_once(api, published.append) == 1
    assert published == [expected]
    assert frozen.call_count == complete.call_count == 1
