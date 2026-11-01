"""
SCRUM-45: Event Organiser Status and Update Notifications

User Story
----------
As an Event Organiser, I want to receive an in-app notification when the Lead
Coordinator approves or rejects my event request, so that I know the outcome
and who is responsible for coordinating my event.

Acceptance Criteria
-------------------
AC1: Given the Lead Coordinator successfully records an approval of an event
     request, the Event Organiser who submitted it receives an in-app
     notification confirming the approval.
AC2: Given the Lead Coordinator successfully records a rejection of an event
     request, the Event Organiser who submitted it receives an in-app
     notification confirming the rejection and stating the rejection reason.
AC3: Both decision notifications include the event name, the decision, and a
     link to view the event request and its decision details.
AC4: Given an initial coordinator assignment or reassignment is successfully
     recorded, the Event Organiser receives an in-app notification with the
     event name, the newly assigned coordinator’s name, and a link to view the
     event details.

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
- The shared worker plumbing (outbox URLs, broker publish, retry loop) is
  covered in test_infra_notification_dispatcher.py.
"""
import json
from unittest.mock import Mock

import httpx
import pytest

from app.dispatcher import OutboxAPI, dispatch_once

approval_SOURCE = dict(eventId='30000000-0000-0000-0000-000000000001', recipientId='10000000-0000-0000-0000-000000000001', eventName='Community Workshop', decision='Approved')

approval_JOB = dict(id='20000000-0000-0000-0000-000000000001', source=approval_SOURCE, envelope=None, createdAt='2026-10-21T00:00:00+00:00', leaseToken='lease')

initial_assignment_COORDINATOR = '10000000-0000-0000-0000-000000000002'

initial_assignment_SOURCE = dict(eventId='30000000-0000-0000-0000-000000000001', recipientId='10000000-0000-0000-0000-000000000001', eventName='Community Workshop', coordinatorId=initial_assignment_COORDINATOR)

initial_assignment_JOB = dict(id='20000000-0000-0000-0000-000000000001', source=initial_assignment_SOURCE, type='event.coordinator-assignment', envelope=None, createdAt='2026-10-21T00:00:00+00:00', leaseToken='lease')

@pytest.fixture
def initial_assignment_api(monkeypatch):
    """Return the real outbox HTTP adapter configured for synthetic Event/User URLs and a test
    token.
    """
    monkeypatch.setenv('EVENT_SERVICE_URL', 'http://event.test')
    monkeypatch.setenv('USER_SERVICE_URL', 'http://user.test/')
    monkeypatch.setenv('INTERNAL_SERVICE_TOKEN', 'test-token')
    return OutboxAPI()

def initial_assignment_transport(request):
    """Answer synthetic claim, saved-ID User lookup and freeze requests; no service or broker runs."""
    if request.method == 'GET':
        assert str(request.url) == f'http://user.test/users/{initial_assignment_COORDINATOR}'
        return httpx.Response(200, json=dict(user_id=initial_assignment_COORDINATOR, username='Alice Tan'))
    if request.url.path.endswith('claim'):
        return httpx.Response(200, json=dict(jobs=[initial_assignment_JOB]))
    if request.url.path.endswith('freeze'):
        return httpx.Response(200, json=dict(envelope=json.loads(request.content)['envelope']))
    return httpx.Response(200, json={})

rejection_SOURCE = dict(eventId='30000000-0000-0000-0000-000000000001', recipientId='10000000-0000-0000-0000-000000000001', eventName='Community Workshop', decision='Rejected', reason='Missing plan')

rejection_JOB = dict(id='20000000-0000-0000-0000-000000000001', source=rejection_SOURCE, envelope=None, createdAt='2026-10-21T00:00:00+00:00', leaseToken='lease')


# AC1 — Approval

def test_ac1_ac3_approval_alert_freezes_saved_facts_before_publish():
    """
    Summary: dispatch_once on one claimed approval job builds the envelope
        {type event.approval, message "Community Workshop was approved",
        destination event-details link, details = the saved facts}, freezes it
        with the owner, publishes exactly that envelope, marks the job
        published and records no retry.
    AC1: Given the Lead Coordinator successfully records an approval of an
        event request, the Event Organiser who submitted it receives an in-app
        notification confirming the approval.
    AC3: Both decision notifications include the event name, the decision, and
        a link to view the event request and its decision details.
    Double: Stub (api.claim returns the approval job; api.freeze returns the
        draft envelope unchanged), Mock (publish called once with the envelope;
        freeze called with the job and envelope; published called once; retry
        not called)
    """
    # Arrange (Given)
    api, publish = (Mock(), Mock())
    api.claim.return_value = [approval_JOB]
    api.freeze.side_effect = lambda job, envelope: envelope

    # Act + Assert (When / Then)
    assert dispatch_once(api, publish) == 1
    expected = dict(version=1, id=approval_JOB['id'], type='event.approval', recipientId=approval_SOURCE['recipientId'], createdAt=approval_JOB['createdAt'], message='Community Workshop was approved', destination=dict(kind='event-details', eventId=approval_SOURCE['eventId']), details=approval_SOURCE)
    publish.assert_called_once_with(expected)
    api.freeze.assert_called_once_with(approval_JOB, expected)
    api.published.assert_called_once_with(approval_JOB)
    api.retry.assert_not_called()


# AC2 — Rejection and reason

def test_ac2_ac3_rejection_alert_reaches_submitting_organiser():
    """
    Summary: dispatch_once on one claimed rejection job builds the envelope
        {type event.rejection, recipient = the submitting organiser, message
        "Community Workshop was rejected: Missing plan", destination
        event-details link, details = the saved facts}, freezes and publishes
        it, marks the job published and records no retry.
    AC2: Given the Lead Coordinator successfully records a rejection of an
        event request, the Event Organiser who submitted it receives an in-app
        notification confirming the rejection and stating the rejection reason.
    AC3: Both decision notifications include the event name, the decision, and
        a link to view the event request and its decision details.
    Double: Stub (api.claim returns the rejection job; api.freeze returns the
        draft envelope unchanged), Mock (publish called once; freeze called
        with the job and the published envelope; published called once; retry
        not called)
    """
    # Arrange (Given)
    api, publish = (Mock(), Mock())
    api.claim.return_value = [rejection_JOB]
    api.freeze.side_effect = lambda job, envelope: envelope

    # Act + Assert (When / Then)
    assert dispatch_once(api, publish) == 1
    envelope = publish.call_args.args[0]
    assert envelope == dict(version=1, id=rejection_JOB['id'], type='event.rejection', recipientId=rejection_SOURCE['recipientId'], createdAt=rejection_JOB['createdAt'], message='Community Workshop was rejected: Missing plan', destination=dict(kind='event-details', eventId=rejection_SOURCE['eventId']), details=rejection_SOURCE)
    api.freeze.assert_called_once_with(rejection_JOB, envelope)
    api.published.assert_called_once_with(rejection_JOB)
    api.retry.assert_not_called()


# AC4 — Initial assignment and reassignment

def test_ac4_assignment_alert_names_coordinator_from_user_service(initial_assignment_api, mocker):
    """
    Summary: dispatch_once on one claimed coordinator-assignment job looks the
        coordinator up in User Service by the saved id, then freezes and
        publishes an envelope with message "Alice Tan has been assigned to
        coordinate Community Workshop.", an event-details link and
        coordinatorName "Alice Tan" in its details.
    AC4: Given an initial coordinator assignment or reassignment is
        successfully recorded, the Event Organiser receives an in-app
        notification with the event name, the newly assigned coordinator’s
        name, and a link to view the event details.
    Double: Stub (httpx.request routed to an in-memory transport: claim returns
        the assignment job, GET /users/<id> returns username "Alice Tan",
        freeze echoes the envelope), Mock (the published envelope is
        collected and asserted)
    """
    # Arrange (Given)
    published = []

    # Act (When)
    with httpx.Client(transport=httpx.MockTransport(initial_assignment_transport)) as client:
        mocker.patch('httpx.request', side_effect=client.request)
        assert dispatch_once(initial_assignment_api, published.append) == 1

    # Assert (Then)
    assert len(published) == 1, 'Initial assignment must publish after User lookup'
    assert published[0] == dict(version=1, id=initial_assignment_JOB['id'], type='event.coordinator-assignment', recipientId=initial_assignment_SOURCE['recipientId'], createdAt=initial_assignment_JOB['createdAt'], message='Alice Tan has been assigned to coordinate Community Workshop.', destination=dict(kind='event-details', eventId=initial_assignment_SOURCE['eventId']), details={**initial_assignment_SOURCE, 'coordinatorName': 'Alice Tan'})


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers freezing, retry, hold or recovery; they
# check design decisions the stories rely on.

@pytest.mark.parametrize('kind', ['event.approval', 'event.rejection', 'event.coordinator-assignment'], ids=["approval", "rejection", "coordinator_assignment"])
@pytest.mark.parametrize('freeze_fails', [False, True], ids=['frozen-owner-result', 'freeze-outage'])
def test_decision_alert_publishes_only_owner_frozen_envelope(kind, freeze_fails):
    """
    Summary: For an approval, rejection or coordinator-assignment job, nothing
        is published before the owner's freeze call; when freeze succeeds only
        the owner's returned envelope is published and the job is marked
        published; when freeze raises, nothing is published and a retry is
        recorded with "RuntimeError".
    Supporting design check: only the owner-frozen envelope is ever published
    Double: Stub (api.claim returns one job of the given kind; api.freeze
        returns an owner envelope or raises RuntimeError("Event
        unavailable")), Mock (publish asserts freeze already happened; the
        published and retry calls are asserted)
    """
    source = dict(eventId='event', recipientId='organiser', eventName='Community Workshop', decision='Approved' if kind == 'event.approval' else 'Rejected', reason='Missing plan', coordinatorId='alice')
    job = dict(id='change', type=kind, source=source, envelope=None, createdAt='2026-10-21T00:00:00+00:00', leaseToken='lease')
    api = Mock()
    api.claim.return_value = [job]
    api.coordinator_name.return_value = 'Alice Tan'
    effects = []
    owner_result = {'owner': 'authoritative frozen result'}

    def freeze(received_job, draft):
        assert received_job == job
        assert effects == [], 'Nothing may publish before Event confirms freeze'
        assert draft['type'] == kind
        effects.append('freeze')
        if freeze_fails:
            raise RuntimeError('Event unavailable')
        return owner_result

    def publish(envelope):
        assert effects == ['freeze'], 'Freeze must finish before broker I/O'
        assert envelope == owner_result, 'Publish owner result, not mutable local draft'
        effects.append('publish')

    def completed(received_job):
        assert received_job == job
        assert effects == ['freeze', 'publish']
        effects.append('published')
    api.published.side_effect = completed
    api.freeze.side_effect = freeze
    broker = Mock(side_effect=publish)
    assert dispatch_once(api, broker) == 1
    api.freeze.assert_called_once()
    if freeze_fails:
        broker.assert_not_called()
        api.published.assert_not_called()
        api.retry.assert_called_once_with(job, 'RuntimeError')
    else:
        assert effects == ['freeze', 'publish', 'published']
        broker.assert_called_once_with(owner_result)
        api.published.assert_called_once_with(job)
        api.retry.assert_not_called()

def test_approval_alert_retry_reuses_frozen_envelope():
    """
    Summary: When the first publish of an approval alert raises, a retry is
        recorded with "RuntimeError"; on the next claim the job carries the
        frozen envelope although the event was renamed and the recipient
        changed, and that same envelope is published without a new freeze.
    Supporting design check: a retried alert resends its frozen envelope, not
        newer event facts
    Double: Stub (api.claim returns the approval job, then the same job with
        the frozen envelope and changed source facts; api.freeze echoes the
        draft), Mock (first publish raises RuntimeError("broker unavailable");
        second publish called once with the frozen envelope; freeze not called
        again; published called with the retry job)
    """
    # Arrange (Given)
    api, publish = (Mock(), Mock(side_effect=RuntimeError('broker unavailable')))
    api.claim.return_value = [approval_JOB]
    api.freeze.side_effect = lambda job, envelope: envelope
    dispatch_once(api, publish)
    frozen = publish.call_args.args[0]

    # Act + Assert (When / Then)
    api.published.assert_not_called()
    api.retry.assert_called_once_with(approval_JOB, 'RuntimeError')
    api.reset_mock()
    retry = {**approval_JOB, 'envelope': frozen, 'source': {**approval_SOURCE, 'eventName': 'Renamed', 'recipientId': 'changed'}}
    api.claim.return_value = [retry]
    publish = Mock()
    dispatch_once(api, publish)
    publish.assert_called_once_with(frozen)
    api.freeze.assert_not_called()
    api.published.assert_called_once_with(retry)

def test_assignment_alert_retry_uses_frozen_name(initial_assignment_api, mocker):
    """
    Summary: After the first publish of a coordinator-assignment alert raises
        a broker outage, the retry publishes the same frozen envelope, with
        coordinatorName "Alice Tan", and User Service was looked up only once.
    Supporting design check: a retried assignment alert keeps its frozen
        coordinator name and does not look the coordinator up again
    Double: Stub (httpx.request routed to an in-memory transport: claim returns
        the job, and on the retry the same job with the frozen envelope; GET
        /users/<id> returns "Alice Tan"; the first publish raises
        RuntimeError("broker outage")), Mock (the number of User Service
        lookups and the published envelopes are asserted)
    """
    # Arrange (Given)
    frozen, looked_up = ([], [])

    def respond(request):
        if request.method == 'GET':
            looked_up.append(request.url.path)
        if request.url.path.endswith('claim') and frozen:
            return httpx.Response(200, json={'jobs': [{**initial_assignment_JOB, 'envelope': frozen[0]}]})
        return initial_assignment_transport(request)

    def outage(envelope):
        frozen.append(envelope)
        raise RuntimeError('broker outage')
    published = []

    # Act (When)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        mocker.patch('httpx.request', side_effect=client.request)
        dispatch_once(initial_assignment_api, outage)
        dispatch_once(initial_assignment_api, published.append)

    # Assert (Then)
    assert len(looked_up) == 1
    assert published == frozen
    assert published[0]['details']['coordinatorName'] == 'Alice Tan'

def test_rejection_alert_retry_keeps_prepared_content():
    """
    Summary: When the first publish of a rejection alert raises, a retry is
        recorded with "RuntimeError"; on the next claim the job carries the
        frozen envelope although the event was renamed, and that same envelope
        is published without a new freeze.
    Supporting design check: a retried alert resends its frozen envelope, not
        newer event facts
    Double: Stub (api.claim returns the rejection job, then the same job with
        the frozen envelope and a renamed event; api.freeze echoes the draft),
        Mock (first publish raises RuntimeError("broker down"); second publish
        called once with the frozen envelope; freeze not called again;
        published called with the retry job)
    """
    # Arrange (Given)
    api, publish = (Mock(), Mock(side_effect=RuntimeError('broker down')))
    api.claim.return_value = [rejection_JOB]
    api.freeze.side_effect = lambda job, envelope: envelope

    # Act + Assert (When / Then)
    assert dispatch_once(api, publish) == 1
    api.retry.assert_called_once_with(rejection_JOB, 'RuntimeError')
    api.published.assert_not_called()
    frozen = publish.call_args.args[0]
    retry_job = {**rejection_JOB, 'source': {**rejection_SOURCE, 'eventName': 'Renamed'}, 'envelope': frozen}
    api.reset_mock()
    api.claim.return_value = [retry_job]
    publish = Mock()
    assert dispatch_once(api, publish) == 1
    publish.assert_called_once_with(frozen)
    api.freeze.assert_not_called()
    api.published.assert_called_once_with(retry_job)

@pytest.mark.parametrize('status,body', [(404, {'message': 'User not found.'}), (200, {'username': '   '}), (200, {}), (200, {'username': None}), (200, {'username': 23})], ids=["not_found", "blank_name", "no_name", "null_name", "numeric_name"])
def test_assignment_alert_with_unusable_user_is_held_without_blocking(initial_assignment_api, status, body, mocker):
    """
    Summary: When User Service answers 404, or 200 with a blank, missing, null
        or numeric username, the assignment alert is held (one hold call with
        error "CoordinatorNameUnavailable coordinatorId=<id>"), nothing is
        published for it, and a second claimed rejection job is still
        published (dispatch_once returns 2).
    Supporting design check: an assignment alert whose coordinator cannot be
        named is held for repair without blocking other alerts
    Double: Stub (httpx.request routed to an in-memory transport: claim
        returns an assignment job and a rejection job; GET /users/<id> returns
        the parametrized status and body), Mock (the recorded hold request body
        and the published envelopes are asserted)
    """
    # Arrange (Given)
    good = {**initial_assignment_JOB, 'id': '20000000-0000-0000-0000-000000000002', 'type': 'event.rejection', 'source': {**initial_assignment_SOURCE, 'reason': 'Missing plan', 'decision': 'Rejected'}}
    calls, published = ([], [])

    def respond(request):
        calls.append(request)
        if request.method == 'GET':
            return httpx.Response(status, json=body)
        if request.url.path.endswith('claim'):
            return httpx.Response(200, json={'jobs': [initial_assignment_JOB, good]})
        return initial_assignment_transport(request)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        mocker.patch('httpx.request', side_effect=client.request)
        assert dispatch_once(initial_assignment_api, published.append) == 2

    # Act (When)
    held = [request for request in calls if request.url.path.endswith('/hold')]

    # Assert (Then)
    assert len(held) == 1, 'Unusable coordinator name must be held, not endlessly retried'
    assert json.loads(held[0].content) == {'leaseToken': 'lease', 'error': f'CoordinatorNameUnavailable coordinatorId={initial_assignment_COORDINATOR}'}
    assert len(published) == 1 and published[0]['id'] == good['id']

@pytest.mark.parametrize('outcome', [503, 'timeout'], ids=["service_unavailable", "timeout"])
def test_assignment_alert_after_temporary_lookup_failure_retries_then_delivers(initial_assignment_api, outcome, mocker):
    """
    Summary: When User Service answers 503 or times out on the first attempt,
        nothing is published, the job is retried (last call is /retry, with no
        freeze or hold); on the next attempt the lookup succeeds and the alert
        is published with coordinatorName "Alice Tan".
    Supporting design check: a temporary lookup failure is retried for the
        same change and then delivered
    Double: Stub (httpx.request routed to an in-memory transport: GET
        /users/<id> fails once with 503 or ReadTimeout, then returns "Alice
        Tan"; claim returns the assignment job), Mock (the recorded request
        paths and the published envelopes are asserted)
    """
    # Arrange (Given)
    actions, published = ([], [])
    failed = True

    def respond(request):
        actions.append(request.url.path)
        if request.method == 'GET' and failed:
            if outcome == 'timeout':
                raise httpx.ReadTimeout('temporary', request=request)
            return httpx.Response(503, json={})
        return initial_assignment_transport(request)

    # Act (When)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        mocker.patch('httpx.request', side_effect=client.request)
        dispatch_once(initial_assignment_api, published.append)
        assert published == []
        assert actions[-1].endswith('/retry')
        assert not any((path.endswith('/freeze') or path.endswith('/hold') for path in actions))
        failed = False
        dispatch_once(initial_assignment_api, published.append)

    # Assert (Then)
    assert published[0]['id'] == initial_assignment_JOB['id']
    assert published[0]['details']['coordinatorName'] == 'Alice Tan'

def test_assignment_alert_when_hold_cannot_be_saved_logs_diagnosis(initial_assignment_api, caplog, mocker):
    """
    Summary: When User Service answers 404 for the coordinator and the hold
        call is answered 503, dispatch_once still returns 1 and logs "Hold
        update failed; lease will recover".
    Supporting design check: if a hold cannot be recorded, a recovery diagnosis
        is logged
    Double: Stub (httpx.request routed to an in-memory transport: GET
        /users/<id> returns 404, POST /hold returns 503, claim returns the
        assignment job; the publish function is a Mock that is not expected to
        be called)
    """
    # Arrange (Given)
    calls = []

    def respond(request):
        calls.append(request.url.path)
        if request.method == 'GET':
            return httpx.Response(404, json={})
        if request.url.path.endswith('/hold'):
            return httpx.Response(503, json={})
        return initial_assignment_transport(request)

    # Act (When)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        mocker.patch('httpx.request', side_effect=client.request)
        assert dispatch_once(initial_assignment_api, Mock()) == 1

    # Assert (Then)
    assert 'Hold update failed; lease will recover' in caplog.text
