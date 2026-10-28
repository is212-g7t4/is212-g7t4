"""SCRUM-49 Event Change and Modification Notifications: Event Workflow unit tests.

Story: As an Event Organiser and Event Coordinator, I want to receive notifications about event changes that affect me, so that I can respond to changes promptly.
Real: dispatcher, OutboxAPI and HTTPX request serialization.
Doubled: Event/User HTTP APIs via strict respx and recording publisher; sockets blocked.
Not proven: cross-service E2E, live broker delivery, authentication or browser navigation.
AC = acceptance criterion; DR = supporting design rule, not an extra AC.

AC1 Given an Event Organiser submits a change request, the system sends an in-app notification to the Event Coordinator with the event name, proposed changes, and a link to review the request.
AC2 Given an approval or rejection of a change request is successfully recorded, the Event Organiser receives an in-app notification with the event name, decision, and reason if rejected.
AC3 Given an event is cancelled or rejected, the system sends an in-app notification to both the Event Coordinator and Event Organiser confirming the cancellation or rejection respectively with the event name.
Coverage: AC1-3 preparation/formatting/publication only; mutations and SQL/inbox are covered in Event/Notification owner suites.
DR cases cover recipient lookup, freeze failure and frozen retry, not additional ACs.
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


# AC1 ---- complete proposed changes and the exact request review destination
@pytest.mark.parametrize("start,end", [
    ("2030-03-01T09:00:00", "2030-03-01T17:00:00"),
    ("2030-03-01T01:00:00+00:00", "2030-03-01T11:00:00+02:00"),
], ids=["naive-is-singapore", "aware-converted-to-singapore"])
def test_ac1_all_proposed_fields_are_readable_in_singapore_time(prepare_change, start, end):
    """Boundary: every supported field is named; naive and offset dates display in SGT."""
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
    # Act
    count = dispatch_once(api, broker)
    # Assert: includes all envelope metadata, exact message, details and request destination.
    assert count == 1
    assert broker.call_args_list == [((frozen,), {})]


def test_ac1_partial_change_does_not_invent_unchanged_fields(prepare_change):
    """Normal: a single changed attendance value yields only that field in the review message."""
    # Arrange
    item = change_job(changeRequestId=REQUEST, proposedChanges={"expectedAttendance": "40"})
    api, broker, frozen = prepare_change(item, COORDINATOR,
        "Change requested for Workshop. Proposed changes: Expected Attendance: 40.")
    # Act
    count = dispatch_once(api, broker)
    # Assert
    assert count == 1
    assert broker.call_args_list == [((frozen,), {})]


# AC2 ---- current organiser, decision, renamed event and verbatim rejection reason
@pytest.mark.parametrize("kind,renamed,reason,message", [
    ("event.change-request-approved", False, None, "Change request for Workshop was approved."),
    ("event.change-request-approved", True, None,
     "Change request for New Workshop (formerly Workshop) was approved."),
    ("event.change-request-rejected", False, "Keep transport.\n交通安排需完善。",
     "Change request for Workshop was rejected: Keep transport.\n交通安排需完善。"),
    ("event.change-request-rejected", True, "Keep transport.",
     "Change request for New Workshop (formerly Workshop) was rejected: Keep transport."),
], ids=["approval-unchanged-name", "approval-renamed", "rejection-verbatim-reason", "rejection-historical-name"])
def test_ac2_decision_reaches_current_organiser_with_saved_event_content(prepare_change, kind, renamed, reason, message):
    """Normal: current ownership controls delivery while saved name, decision and reason stay intact."""
    # Arrange: an obsolete source recipient must not override the current Event context.
    item = change_job(kind, "organiser", changeRequestId=REQUEST,
                      recipientId=OTHER_LEAD, decision="Approved" if reason is None else "Rejected")
    if renamed:
        item["source"].update(eventName="New Workshop", previousEventName="Workshop")
    if reason is not None:
        item["source"]["reason"] = reason
    api, broker, frozen = prepare_change(item, ORGANISER, message)
    # Act
    count = dispatch_once(api, broker)
    # Assert
    assert count == 1
    assert broker.call_args_list == [((frozen,), {})]


# AC3 ---- coordinator and organiser cancellation notifications
@pytest.mark.parametrize("role,recipient", [("coordinator", COORDINATOR), ("organiser", ORGANISER)])
def test_ac3_cancellation_delivers_each_role_the_event_name_and_details(prepare_change, role, recipient):
    """Normal: separate cancellation intents reach each current role with the original event name."""
    # Arrange
    item = change_job("event.cancelled", role, recipientId=OTHER_LEAD)
    api, broker, frozen = prepare_change(item, recipient, "Workshop was cancelled.")
    # Act
    count = dispatch_once(api, broker)
    # Assert
    assert count == 1
    assert broker.call_args_list == [((frozen,), {})]


# DR ---- current recipient selection, sole-Lead fallback and technical recovery
@pytest.mark.parametrize("kind,message", [
    ("event.change-request-submitted", "Change requested for Workshop. Proposed changes: Expected Attendance: 40."),
    ("event.cancelled", "Workshop was cancelled."),
], ids=["change-request", "cancellation"])
def test_dr_unassigned_coordinator_delivery_uses_sole_lead_without_assignment(prepare_change, event_change_http, kind, message):
    """Boundary: an unassigned event immediately notifies the sole Lead without any assignment write."""
    # Arrange: User app/__init__.py::users and app/models.py::serialize define this role response.
    _, http = event_change_http
    http.get("http://user.test/users", params={"role": "Event Coordinator Lead"}).respond(200, json={
        "users": [{"user_id": LEAD, "role": "Event Coordinator Lead", "username": "Synthetic Lead",
                   "email": "lead@example.com", "organization": "", "contact_details": ""}],
    })
    item = change_job(kind, changeRequestId=REQUEST, proposedChanges={"expectedAttendance": "40"})
    api, broker, frozen = prepare_change(item, LEAD, message, unassigned=True)
    # Act
    count = dispatch_once(api, broker)
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
def test_dr_ambiguous_or_invalid_lead_data_retries_without_publishing(event_change_http, users):
    """Failure: missing, ambiguous or malformed Lead data never causes partial or misaddressed delivery."""
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
    # Act
    count = dispatch_once(api, broker)
    # Assert: no freeze, expand, assignment, hold or completion route is allowed.
    assert count == 1
    broker.assert_not_called()
    assert [call.request.url.path.rsplit("/", 1)[-1] for call in http.calls] == ["claim", "notification-context", "users", "retry"]
    assert json.loads(retry.calls[0].request.content) == {"leaseToken": item["leaseToken"], "error": "ValueError"}


@pytest.mark.parametrize("role,context", [
    ("organiser", {"organiserId": "invalid", "coordinatorId": COORDINATOR}),
    ("coordinator", {"organiserId": ORGANISER, "coordinatorId": "invalid"}),
], ids=["invalid-current-owner", "invalid-assigned-coordinator"])
def test_dr_invalid_current_recipient_retries_instead_of_using_saved_recipient(event_change_http, role, context):
    """Failure: an invalid current recipient does not fall back to a stale source recipient or Lead."""
    # Arrange: Event notification_context response contains an intentionally invalid UUID.
    api, http = event_change_http
    item = change_job("event.cancelled", role, recipientId=OTHER_LEAD)
    http.post(OUTBOX + "/claim", json={}).respond(200, json={"jobs": [item]})
    http.get(CONTEXT, params={"includeOrganiser": "true"}).respond(200, json={"id": EVENT, "eventName": "Workshop", **context})
    retry = http.post(f"{OUTBOX}/{item['id']}/retry").respond(200, json={"id": item["id"], "status": "retry"})
    broker = Mock()
    # Act
    count = dispatch_once(api, broker)
    # Assert
    assert count == 1
    broker.assert_not_called()
    assert json.loads(retry.calls[0].request.content) == {"leaseToken": item["leaseToken"], "error": "ValueError"}


@pytest.mark.parametrize("failure", ["503", "timeout"])
def test_dr_context_outage_retries_without_freeze_or_broker_publication(event_change_http, failure):
    """Failure: transient owner-context outages retry the saved intent without guessing a recipient."""
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
    # Act
    count = dispatch_once(api, broker)
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
def test_dr_freeze_failure_prevents_publication_of_local_draft(event_change_http, kind, role, recipient, facts, message):
    """Failure: an owner freeze outage leaves each change notification unpublished and retryable."""
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
    # Act
    count = dispatch_once(api, broker)
    # Assert: strict routes forbid a published update after failure.
    assert count == 1
    broker.assert_not_called()
    assert json.loads(freeze.calls[0].request.content) == {"leaseToken": item["leaseToken"], "envelope": expected}
    assert [call.request.url.path.rsplit("/", 1)[-1] for call in http.calls] == ["claim", "notification-context", "freeze", "retry"]
    assert json.loads(retry.calls[0].request.content) == {"leaseToken": item["leaseToken"], "error": "HTTPStatusError"}


@pytest.mark.parametrize("kind,role,recipient,facts,message", DELIVERIES,
                         ids=["submission", "approval", "rejection", "cancellation"])
def test_dr_broker_retry_reuses_owner_frozen_envelope_without_recipient_lookup(event_change_http, kind, role, recipient, facts, message):
    """Failure: after a broker outage, reclaim publishes the identical frozen content without relookup."""
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
    # Act: first attempt freezes successfully but cannot publish.
    first = dispatch_once(api, broker)
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
