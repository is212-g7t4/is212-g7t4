"""
SCRUM-49: Event Change and Modification Notifications

User Story
----------
As an Event Organiser and Event Coordinator, I want to receive notifications
about event changes that affect me, so that I can respond to changes promptly.

Acceptance Criteria
-------------------
AC1: Given an Event Organiser submits a change request, the system sends an
     in-app notification to the Event Coordinator with the event name, proposed
     changes, and a link to review the request.
AC2: Given an approval or rejection of a change request is successfully
     recorded, the Event Organiser receives an in-app notification with the
     event name, decision, and reason if rejected.
AC3: Given an event is cancelled or rejected, the system sends an in-app
     notification to both the Event Coordinator and Event Organiser confirming
     the cancellation or rejection, respectively, with the event name.

Real
----
- The event-workflow notification workers: they claim jobs from the owning
  service's outbox over HTTP, look up current recipients and display facts, ask
  the owner to freeze the envelope, publish the frozen envelope to RabbitMQ and
  mark it published, retrying or holding on failure.
- Assertions are on the envelopes frozen and published, call order, and
  retry/hold decisions.

Doubled
-------
- Owner outbox and lookup HTTP (Event, User, Registration, Venue Availability):
  Stub (respx / monkeypatched httpx fixtures) - canned replies; requests
  inspected.
- RabbitMQ publisher (pika): Mock - publish arguments, confirms and persistence
  inspected.

Not proven
----------
- That the owner freezes the envelope in the same transaction as the change (->
  the owning service's notification tests and integration tests).
- That Notification Service stores and shows the inbox item (->
  notification-service consumer tests and frontend NotificationCenter tests).
"""
import json
from unittest.mock import Mock

import httpx
import pytest

from app.dispatcher import dispatch_once
from tests.unit.factories import (
    CONTEXT, COORDINATOR, EVENT, LEAD, ORGANISER, OTHER_LEAD, OUTBOX, REQUEST,
    change_envelope, change_job,
)


@pytest.mark.parametrize("start,end", [
    ("2030-03-01T09:00:00", "2030-03-01T17:00:00"),
    ("2030-03-01T01:00:00+00:00", "2030-03-01T11:00:00+02:00"),
], ids=["naive-is-singapore", "aware-converted-to-singapore"])
def test_ac1_change_request_alert_shows_proposed_times_in_singapore_time(prepare_change, start, end):
    """
    Summary: dispatch_once on one claimed change-request-submitted job for the
        assigned coordinator, with every proposable field changed, freezes and
        publishes a message "Change requested for Workshop. Proposed changes:
        ..." that lists the fields in display order and shows the start/end
        times in Singapore time (01 Mar 2030, 09:00 SGT / 17:00 SGT) for both
        offset and naive input times.
    AC1: Given an Event Organiser submits a change request, the system sends an
        in-app notification to the Event Coordinator with the event name,
        proposed changes, and a link to review the request.
    Double: Stub (Event notification-context returns coordinator and organiser
        ids; owner freeze returns an owner-revised envelope; published
        accepted; strict respx routes), Mock (broker called once with the
        owner-frozen envelope, after freeze)
    """
    # Arrange (Given)
    # Arrange: reverse input order to check display order, not JSON insertion order.
    changes = dict(accessibilityNeeds="Step-free", equipmentRequirements="Projector",
                   venueRequirements="Quiet room", expectedAttendance="40",
                   preferredEndDate=end, preferredStartDate=start,
                   registrationNeeds="Required", purpose="Learning", description="Hands-on",
                   eventName="New Workshop")
    item = change_job(changeRequestId=REQUEST, proposedChanges=changes)
    api, broker, frozen = prepare_change(item, COORDINATOR,
        "Change requested for Workshop. Proposed changes: Event Name: New Workshop; "
        "Description: Hands-on; Purpose: Learning; Registration Needs: Required; "
        "Start Date/Time: 01 Mar 2030, 09:00 SGT; End Date/Time: 01 Mar 2030, 17:00 SGT; "
        "Expected Attendance: 40; Venue Requirements: Quiet room; "
        "Equipment Requirements: Projector; Accessibility Needs: Step-free.")

    # Act (When)
    # Act
    count = dispatch_once(api, broker)

    # Assert (Then)
    # Assert: includes all envelope metadata, exact message, details and request destination.
    assert count == 1
    assert broker.call_args_list == [((frozen,), {})]


def test_ac1_change_request_alert_lists_only_changed_fields(prepare_change):
    """
    Summary: dispatch_once on one claimed change-request-submitted job whose
        proposed changes contain only expectedAttendance "40" publishes
        "Change requested for Workshop. Proposed changes: Expected Attendance:
        40." and no other field.
    AC1: Given an Event Organiser submits a change request, the system sends an
        in-app notification to the Event Coordinator with the event name,
        proposed changes, and a link to review the request.
    Double: Stub (Event notification-context returns the assigned coordinator;
        owner freeze returns an owner-revised envelope; strict respx routes),
        Mock (broker called once with the owner-frozen envelope)
    """
    # Arrange (Given)
    # Arrange
    item = change_job(changeRequestId=REQUEST, proposedChanges={"expectedAttendance": "40"})
    api, broker, frozen = prepare_change(item, COORDINATOR,
        "Change requested for Workshop. Proposed changes: Expected Attendance: 40.")

    # Act (When)
    # Act
    count = dispatch_once(api, broker)

    # Assert (Then)
    # Assert
    assert count == 1
    assert broker.call_args_list == [((frozen,), {})]


@pytest.mark.parametrize("kind,renamed,reason,message", [
    ("event.change-request-approved", False, None, "Change request for Workshop was approved."),
    ("event.change-request-approved", True, None,
     "Change request for New Workshop (formerly Workshop) was approved."),
    ("event.change-request-rejected", False, "Keep transport.\n交通安排需完善。",
     "Change request for Workshop was rejected: Keep transport.\n交通安排需完善。"),
    ("event.change-request-rejected", True, "Keep transport.",
     "Change request for New Workshop (formerly Workshop) was rejected: Keep transport."),
], ids=["approval-unchanged-name", "approval-renamed", "rejection-verbatim-reason", "rejection-historical-name"])
def test_ac2_change_decision_alert_reaches_current_organiser_with_saved_content(prepare_change, kind, renamed, reason, message):
    """
    Summary: dispatch_once on one claimed approved or rejected change-request
        job, whose saved source names an obsolete recipient, publishes to the
        current organiser from the Event context: "Change request for Workshop
        was approved." (or "... for New Workshop (formerly Workshop) ..." when
        renamed) and, for a rejection, "... was rejected: <reason>" with the
        reason kept verbatim.
    AC2: Given an approval or rejection of a change request is successfully
        recorded, the Event Organiser receives an in-app notification with the
        event name, decision, and reason if rejected.
    Double: Stub (Event notification-context returns the current organiser id;
        owner freeze returns an owner-revised envelope; strict respx routes),
        Mock (broker called once with the owner-frozen envelope)
    """
    # Arrange (Given)
    # Arrange: an obsolete source recipient must not override the current Event context.
    item = change_job(kind, "organiser", changeRequestId=REQUEST,
                      recipientId=OTHER_LEAD, decision="Approved" if reason is None else "Rejected")
    if renamed:
        item["source"].update(eventName="New Workshop", previousEventName="Workshop")
    if reason is not None:
        item["source"]["reason"] = reason
    api, broker, frozen = prepare_change(item, ORGANISER, message)

    # Act (When)
    # Act
    count = dispatch_once(api, broker)

    # Assert (Then)
    # Assert
    assert count == 1
    assert broker.call_args_list == [((frozen,), {})]


@pytest.mark.parametrize("role,recipient", [("coordinator", COORDINATOR), ("organiser", ORGANISER)], ids=["coordinator", "organiser"])
def test_ac3_cancellation_alert_reaches_coordinator_and_organiser(prepare_change, role, recipient):
    """
    Summary: dispatch_once on one claimed event.cancelled job for the
        coordinator role, and one for the organiser role, publishes
        "Workshop was cancelled." to the coordinator and to the organiser
        respectively, taken from the Event context rather than the job's saved
        recipient.
    AC3: Given an event is cancelled or rejected, the system sends an in-app
        notification to both the Event Coordinator and Event Organiser
        confirming the cancellation or rejection, respectively, with the event
        name.
    Double: Stub (Event notification-context returns the coordinator and
        organiser ids; owner freeze returns an owner-revised envelope; strict
        respx routes), Mock (broker called once with the owner-frozen
        envelope)
    """
    # Arrange (Given)
    # Arrange
    item = change_job("event.cancelled", role, recipientId=OTHER_LEAD)
    api, broker, frozen = prepare_change(item, recipient, "Workshop was cancelled.")

    # Act (When)
    # Act
    count = dispatch_once(api, broker)

    # Assert (Then)
    # Assert
    assert count == 1
    assert broker.call_args_list == [((frozen,), {})]


@pytest.mark.parametrize("kind,message", [
    ("event.change-request-submitted", "Change requested for Workshop. Proposed changes: Expected Attendance: 40."),
    ("event.cancelled", "Workshop was cancelled."),
], ids=["change-request", "cancellation"])
def test_ac1_ac3_change_request_alert_without_coordinator_goes_to_the_lead(prepare_change, event_change_http, kind, message):
    """
    Summary: When the Event context has no assigned coordinator,
        dispatch_once on a change-request-submitted job or an event.cancelled
        job looks up the single Event Coordinator Lead in User Service and
        publishes the alert to that Lead; only claim, context, Lead lookup,
        freeze and published calls are made.
    AC1: Given an Event Organiser submits a change request, the system sends an
        in-app notification to the Event Coordinator with the event name,
        proposed changes, and a link to review the request.
    AC3: Given an event is cancelled or rejected, the system sends an in-app
        notification to both the Event Coordinator and Event Organiser
        confirming the cancellation or rejection, respectively, with the event
        name.
    Double: Stub (Event notification-context returns coordinatorId None; User
        Service GET /users?role=Event Coordinator Lead returns exactly one
        Lead; owner freeze returns an owner-revised envelope; strict respx
        routes), Mock (broker called once with the owner-frozen envelope)
    """
    # Arrange (Given)
    # Arrange: User app/__init__.py::users and app/models.py::serialize define this role response.
    _, http = event_change_http
    http.get("http://user.test/users", params={"role": "Event Coordinator Lead"}).respond(200, json={
        "users": [{"user_id": LEAD, "role": "Event Coordinator Lead", "username": "Synthetic Lead",
                   "email": "lead@example.com", "organization": "", "contact_details": ""}],
    })
    item = change_job(kind, changeRequestId=REQUEST, proposedChanges={"expectedAttendance": "40"})
    api, broker, frozen = prepare_change(item, LEAD, message, unassigned=True)

    # Act (When)
    # Act
    count = dispatch_once(api, broker)

    # Assert (Then)
    # Assert: strict HTTP permits only claim, context, Lead GET, freeze and published.
    assert count == 1
    assert broker.call_args_list == [((frozen,), {})]


@pytest.mark.parametrize("users", [
    [],
    [{"user_id": LEAD, "role": "Event Coordinator Lead"},
     {"user_id": OTHER_LEAD, "role": "Event Coordinator Lead"}],
    {},
    [{"user_id": LEAD, "role": "Event Coordinator Lead"},
     {"user_id": OTHER_LEAD, "role": "Event Organiser"}],
    [{"user_id": "not-a-uuid", "role": "Event Coordinator Lead"}],
], ids=["no-lead", "multiple-leads", "non-list", "wrong-role-after-valid-lead", "invalid-lead-id"])
def test_change_request_alert_with_unclear_lead_retries_without_publishing(event_change_http, users):
    """
    Summary: With no assigned coordinator, when User Service returns no Lead,
        several Leads, a non-list body, a non-Lead user after a valid Lead, or
        a Lead with an invalid id, dispatch_once records one retry with
        "ValueError" and makes only claim, context, users and retry calls;
        nothing is frozen or published.
    Supporting design check: an alert whose Lead cannot be identified is
        retried rather than sent to the wrong person
    Double: Stub (Event notification-context returns coordinatorId None; User
        Service GET /users?role=Event Coordinator Lead returns the
        parametrized users; strict respx routes), Mock (broker not called)
    """
    # Arrange (Given)
    # Arrange: intentionally invalid responses at Event notification_context / User users boundaries.
    api, http = event_change_http
    item = change_job("event.cancelled")
    http.post(OUTBOX + "/claim", json={}).respond(200, json={"jobs": [item]})
    http.get(CONTEXT, params={"includeOrganiser": "true"}).respond(200, json={
        "id": EVENT, "eventName": "Workshop", "coordinatorId": None, "organiserId": ORGANISER,
    })
    http.get("http://user.test/users", params={"role": "Event Coordinator Lead"}).respond(200, json={"users": users})
    retry = http.post(f"{OUTBOX}/{item['id']}/retry").respond(200, json={"id": item["id"], "status": "retry"})
    broker = Mock()

    # Act (When)
    # Act
    count = dispatch_once(api, broker)

    # Assert (Then)
    # Assert: no freeze, expand, assignment, hold or completion route is allowed.
    assert count == 1
    broker.assert_not_called()
    assert [call.request.url.path.rsplit("/", 1)[-1] for call in http.calls] == ["claim", "notification-context", "users", "retry"]
    assert json.loads(retry.calls[0].request.content) == {"leaseToken": item["leaseToken"], "error": "ValueError"}


@pytest.mark.parametrize("role,context", [
    ("organiser", {"organiserId": "invalid", "coordinatorId": COORDINATOR}),
    ("coordinator", {"organiserId": ORGANISER, "coordinatorId": "invalid"}),
], ids=["invalid-current-owner", "invalid-assigned-coordinator"])
def test_change_alert_with_invalid_current_recipient_retries(event_change_http, role, context):
    """
    Summary: For an event.cancelled job, when the Event context returns an
        invalid organiser id (organiser role) or an invalid coordinator id
        (coordinator role), dispatch_once records one retry with "ValueError"
        and publishes nothing.
    Supporting design check: an invalid current recipient is retried, not
        delivered to an old or malformed recipient
    Double: Stub (Event notification-context returns the parametrized invalid
        id; the job's saved recipient is another Lead; strict respx routes),
        Mock (broker not called)
    """
    # Arrange (Given)
    # Arrange: Event notification_context response contains an intentionally invalid UUID.
    api, http = event_change_http
    item = change_job("event.cancelled", role, recipientId=OTHER_LEAD)
    http.post(OUTBOX + "/claim", json={}).respond(200, json={"jobs": [item]})
    http.get(CONTEXT, params={"includeOrganiser": "true"}).respond(200, json={"id": EVENT, "eventName": "Workshop", **context})
    retry = http.post(f"{OUTBOX}/{item['id']}/retry").respond(200, json={"id": item["id"], "status": "retry"})
    broker = Mock()

    # Act (When)
    # Act
    count = dispatch_once(api, broker)

    # Assert (Then)
    # Assert
    assert count == 1
    broker.assert_not_called()
    assert json.loads(retry.calls[0].request.content) == {"leaseToken": item["leaseToken"], "error": "ValueError"}


@pytest.mark.parametrize("failure", ["503", "timeout"], ids=["service_unavailable", "timeout"])
def test_change_alert_when_lookup_down_retries_without_freezing(event_change_http, failure):
    """
    Summary: For an event.cancelled job, when the Event context answers 503 or
        times out, dispatch_once records one retry with "HTTPStatusError" or
        "ReadTimeout"; no freeze or published call is made and nothing is
        published.
    Supporting design check: a lookup outage retries without freezing or
        sending anything
    Double: Stub (Event notification-context answers 503 or raises
        ReadTimeout; strict respx routes, so freeze/published routes are not
        registered), Mock (broker not called)
    """
    # Arrange (Given)
    # Arrange: Event app/__init__.py::notification_context is unavailable.
    api, http = event_change_http
    item = change_job("event.cancelled")
    http.post(OUTBOX + "/claim", json={}).respond(200, json={"jobs": [item]})
    context = http.get(CONTEXT, params={"includeOrganiser": "true"})
    if failure == "503":
        context.respond(503, json={"message": "Unavailable"})
    else:
        context.mock(side_effect=httpx.ReadTimeout("Synthetic context timeout"))
    retry = http.post(f"{OUTBOX}/{item['id']}/retry").respond(200, json={"id": item["id"], "status": "retry"})
    broker = Mock()

    # Act (When)
    # Act
    count = dispatch_once(api, broker)

    # Assert (Then)
    # Assert
    assert count == 1
    broker.assert_not_called()
    assert json.loads(retry.calls[0].request.content) == {
        "leaseToken": item["leaseToken"], "error": "HTTPStatusError" if failure == "503" else "ReadTimeout",
    }


# Independent source facts and literal messages for the four SCRUM-49 delivery types.
DELIVERIES = [
    ("event.change-request-submitted", "coordinator", COORDINATOR,
     {"changeRequestId": REQUEST, "proposedChanges": {"eventName": "New Workshop"}},
     "Change requested for Workshop. Proposed changes: Event Name: New Workshop."),
    ("event.change-request-approved", "organiser", ORGANISER,
     {"changeRequestId": REQUEST, "decision": "Approved"}, "Change request for Workshop was approved."),
    ("event.change-request-rejected", "organiser", ORGANISER,
     {"changeRequestId": REQUEST, "decision": "Rejected", "reason": "Keep transport."},
     "Change request for Workshop was rejected: Keep transport."),
    ("event.cancelled", "coordinator", COORDINATOR, {}, "Workshop was cancelled."),
]


@pytest.mark.parametrize("kind,role,recipient,facts,message", DELIVERIES,
                         ids=["submission", "approval", "rejection", "cancellation"])
def test_change_alert_when_freeze_fails_publishes_nothing(event_change_http, kind, role, recipient, facts, message):
    """
    Summary: For a submission, approval, rejection or cancellation job, when
        the owner's freeze call answers 503, dispatch_once sends the expected
        draft envelope to freeze, then records one retry with
        "HTTPStatusError"; the broker is never called and no published call is
        made.
    Supporting design check: if the owner cannot freeze the alert, the local
        draft is never published
    Double: Stub (Event notification-context returns coordinator and organiser;
        owner freeze answers 503; strict respx routes), Mock (broker not
        called; the freeze request body equals the expected envelope)
    """
    # Arrange (Given)
    # Arrange: Event app/outbox.py::operate owns claim/freeze/retry responses.
    api, http = event_change_http
    item = change_job(kind, role, **facts)
    expected = change_envelope(item, recipient, message)
    http.post(OUTBOX + "/claim", json={}).respond(200, json={"jobs": [item]})
    http.get(CONTEXT, params={"includeOrganiser": "true"}).respond(200, json={
        "id": EVENT, "eventName": "Later name", "organiserId": ORGANISER, "coordinatorId": COORDINATOR,
    })
    freeze = http.post(f"{OUTBOX}/{item['id']}/freeze").respond(503, json={"message": "Unavailable"})
    retry = http.post(f"{OUTBOX}/{item['id']}/retry").respond(200, json={"id": item["id"], "status": "retry"})
    broker = Mock()

    # Act (When)
    # Act
    count = dispatch_once(api, broker)

    # Assert (Then)
    # Assert: strict routes forbid a published update after failure.
    assert count == 1
    broker.assert_not_called()
    assert json.loads(freeze.calls[0].request.content) == {"leaseToken": item["leaseToken"], "envelope": expected}
    assert [call.request.url.path.rsplit("/", 1)[-1] for call in http.calls] == ["claim", "notification-context", "freeze", "retry"]
    assert json.loads(retry.calls[0].request.content) == {"leaseToken": item["leaseToken"], "error": "HTTPStatusError"}


@pytest.mark.parametrize("kind,role,recipient,facts,message", DELIVERIES,
                         ids=["submission", "approval", "rejection", "cancellation"])
def test_change_alert_retry_reuses_frozen_envelope(event_change_http, kind, role, recipient, facts, message):
    """
    Summary: For a submission, approval, rejection or cancellation job, the
        first attempt freezes the alert and records a retry when the broker
        raises; the second claim returns the job with the frozen envelope and
        changed source facts, and the same frozen envelope is published and
        marked published without another context lookup or freeze.
    Supporting design check: a retry after a broker failure resends the frozen
        alert without looking up recipients again
    Double: Stub (Event notification-context returns coordinator and organiser;
        owner freeze returns the frozen envelope; strict respx routes), Mock
        (broker raises RuntimeError first then succeeds; claim called twice,
        context and freeze once each, published once with the new lease)
    """
    # Arrange (Given)
    # Arrange: owner wire shapes from Event app/outbox.py::serialize/operate;
    # context from Event app/__init__.py::notification_context.
    api, http = event_change_http
    item = change_job(kind, role, **facts)
    expected = change_envelope(item, recipient, message)
    frozen = {**expected, "ownerRevision": "frozen"}
    current = [item]
    claim = http.post(OUTBOX + "/claim", json={}).mock(
        side_effect=lambda request: httpx.Response(200, json={"jobs": current}))
    context = http.get(CONTEXT, params={"includeOrganiser": "true"}).respond(200, json={
        "id": EVENT, "eventName": "Later name", "organiserId": ORGANISER, "coordinatorId": COORDINATOR,
    })
    freeze = http.post(f"{OUTBOX}/{item['id']}/freeze").respond(200, json={"envelope": frozen})
    retry = http.post(f"{OUTBOX}/{item['id']}/retry").respond(200, json={"id": item["id"], "status": "retry"})
    broker = Mock(side_effect=[RuntimeError("Synthetic broker outage"), None])

    # Act (When)
    # Act: first attempt freezes successfully but cannot publish.
    first = dispatch_once(api, broker)

    # Assert (Then)
    # Assert: recovery has not claimed delivery, and the outgoing freeze uses our literal oracle.
    assert first == 1
    assert [call.request.url.path.rsplit("/", 1)[-1] for call in http.calls] == ["claim", "notification-context", "freeze", "retry"]
    assert json.loads(freeze.calls[0].request.content) == {"leaseToken": item["leaseToken"], "envelope": expected}
    assert json.loads(retry.calls[0].request.content) == {"leaseToken": item["leaseToken"], "error": "RuntimeError"}
    # Arrange / Act: fresh lease, corrupt/missing source facts and moved recipient cannot replace history.
    current[:] = [{**item, "leaseToken": OTHER_LEAD, "envelope": frozen,
                  "source": {"eventName": "Renamed", "recipientId": OTHER_LEAD}}]
    completed = http.post(f"{OUTBOX}/{item['id']}/published").respond(200, json={"id": item["id"], "status": "published"})
    second = dispatch_once(api, broker)
    # Assert: only a second claim/publication/completion; no context, Lead lookup or freeze.
    assert second == 1
    assert (claim.call_count, context.call_count, freeze.call_count, retry.call_count, completed.call_count) == (2, 1, 1, 1, 1)
    assert json.loads(completed.calls[0].request.content) == {"leaseToken": OTHER_LEAD}
    assert broker.call_args_list == [((frozen,), {}), ((frozen,), {})]
