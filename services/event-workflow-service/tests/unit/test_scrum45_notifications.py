"""
SCRUM-45: Event Organiser Status and Update Notifications

User Story
----------
As an Event Organiser, I want to receive an in-app notification when the Lead
Coordinator approves or rejects my event request, so that I know the outcome
and and who is responsible for coordinating my event.

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
"""
from unittest.mock import Mock

from app.dispatcher import dispatch_once

approval_SOURCE = dict(eventId='30000000-0000-0000-0000-000000000001', recipientId='10000000-0000-0000-0000-000000000001', eventName='Community Workshop', decision='Approved')

approval_JOB = dict(id='20000000-0000-0000-0000-000000000001', source=approval_SOURCE, envelope=None, createdAt='2026-10-21T00:00:00+00:00', leaseToken='lease')

import pytest

from unittest.mock import Mock, patch

import httpx

from app.dispatcher import OutboxAPI, dispatch_once

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
        import json
        return httpx.Response(200, json=dict(envelope=json.loads(request.content)['envelope']))
    return httpx.Response(200, json={})

rejection_SOURCE = dict(eventId='30000000-0000-0000-0000-000000000001', recipientId='10000000-0000-0000-0000-000000000001', eventName='Community Workshop', decision='Rejected', reason='Missing plan')

rejection_JOB = dict(id='20000000-0000-0000-0000-000000000001', source=rejection_SOURCE, envelope=None, createdAt='2026-10-21T00:00:00+00:00', leaseToken='lease')


# AC1 — Approval

def test_approval_alert_freezes_saved_facts_before_publish():
    """
    Summary: An approval alert is frozen with the saved facts before it is sent.
    AC1: Given the Lead Coordinator successfully records an approval of an
        event request, the Event Organiser who submitted it receives an in-app
        notification confirming the approval.
    AC3: Both decision notifications include the event name, the decision, and
        a link to view the event request and its decision details.
    Double: Stub (owner outbox), Mock (freeze then publish)
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

def test_rejection_alert_reaches_submitting_organiser():
    """
    Summary: A rejection alert reaches the organiser who submitted the request.
    AC2: Given the Lead Coordinator successfully records a rejection of an
        event request, the Event Organiser who submitted it receives an in-app
        notification confirming the rejection and stating the rejection reason.
    Double: Stub (owner outbox), Mock (publish)
    """
    # Arrange (Given)
    from app.dispatcher import dispatch_once
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


# AC3 — Decision content and link

@pytest.mark.parametrize('kind', ['event.approval', 'event.rejection', 'event.coordinator-assignment'], ids=["approval", "rejection", "coordinator_assignment"])
@pytest.mark.parametrize('freeze_fails', [False, True], ids=['frozen-owner-result', 'freeze-outage'])
def test_decision_alert_publishes_only_owner_frozen_envelope(kind, freeze_fails):
    """
    Summary: Only the envelope the owner froze is sent, and nothing if freezing fails.
    AC3: Both decision notifications include the event name, the decision, and
        a link to view the event request and its decision details.
    Double: Stub (freeze succeeds or fails), Mock (publish)
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


# AC4 — Initial assignment and reassignment

def test_assignment_alert_names_coordinator_from_user_service(initial_assignment_api, mocker):
    """
    Summary: An assignment alert names the new coordinator, looked up before freezing.
    AC4: Given an initial coordinator assignment or reassignment is
        successfully recorded, the Event Organiser receives an in-app
        notification with the event name, the newly assigned coordinator’s
        name, and a link to view the event details.
    Double: Stub (user lookup), Mock (freeze then publish)
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


# Supporting DR3/DR4/DR6 — retry, frozen history and missing-name recovery

def test_approval_alert_retry_reuses_frozen_envelope():
    """
    Summary: A retried approval alert resends the frozen alert even if the event changed.
    AC1: Given the Lead Coordinator successfully records an approval of an
        event request, the Event Organiser who submitted it receives an in-app
        notification confirming the approval.
    Double: Stub (frozen envelope), Mock (publish)
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
    Summary: A retried assignment alert keeps the frozen coordinator name.
    AC4: Given an initial coordinator assignment or reassignment is
        successfully recorded, the Event Organiser receives an in-app
        notification with the event name, the newly assigned coordinator’s
        name, and a link to view the event details.
    Double: Stub (frozen envelope), Mock (no user lookup)
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
    Summary: A retried rejection alert keeps its prepared content.
    AC2: Given the Lead Coordinator successfully records a rejection of an
        event request, the Event Organiser who submitted it receives an in-app
        notification confirming the rejection and stating the rejection reason.
    Double: Stub (frozen envelope), Mock (publish)
    """
    # Arrange (Given)
    from app.dispatcher import dispatch_once
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

def test_worker_calls_event_outbox_with_internal_token(monkeypatch, mocker):
    """
    Summary: The worker calls Event Service's outbox as a trusted service.
    AC2: (delivery)
    Double: Stub (httpx), Mock (requests inspected)
    """
    import app.dispatcher as worker
    from unittest.mock import patch
    monkeypatch.setenv('EVENT_SERVICE_URL', 'http://event.test/')
    monkeypatch.setenv('INTERNAL_SERVICE_TOKEN', 'test-token')
    request = mocker.patch('httpx.request')
    request.return_value.json.side_effect = [{'jobs': [rejection_JOB]}, {'envelope': {'frozen': True}}, {}, {}]
    api = worker.OutboxAPI()
    assert api.claim() == [rejection_JOB]
    assert api.freeze(rejection_JOB, {'draft': True}) == {'frozen': True}
    api.published(rejection_JOB)
    api.retry(rejection_JOB, 'BrokerUnavailable')
    calls = request.call_args_list
    assert [call.args for call in calls] == [('POST', 'http://event.test/internal/notification-outbox/claim'), ('POST', f"http://event.test/internal/notification-outbox/{rejection_JOB['id']}/freeze"), ('POST', f"http://event.test/internal/notification-outbox/{rejection_JOB['id']}/published"), ('POST', f"http://event.test/internal/notification-outbox/{rejection_JOB['id']}/retry")]
    assert calls[1].kwargs['json'] == {'leaseToken': 'lease', 'envelope': {'draft': True}}
    assert calls[3].kwargs['json'] == {'leaseToken': 'lease', 'error': 'BrokerUnavailable'}
    assert all((call.kwargs['headers'] == {'X-Internal-Token': 'test-token'} and call.kwargs['timeout'] == 5 for call in calls))

def test_publish_uses_confirms_and_persistent_messages(monkeypatch, mocker):
    """
    Summary: Alerts are published with broker confirmation and as persistent messages.
    AC2: (delivery)
    Double: Mock (pika channel)
    """
    # Arrange (Given)
    import app.dispatcher as worker
    from unittest.mock import MagicMock, patch
    import json
    monkeypatch.setenv('RABBITMQ_URL', 'amqp://guest:***@localhost/%2F')
    connection = MagicMock()
    mocker.patch('pika.BlockingConnection', return_value=connection)
    worker.publish({'id': rejection_JOB['id'], 'type': 'event.rejection'})
    channel = connection.channel.return_value

    # Act + Assert (When / Then)
    channel.queue_declare.assert_called_once_with(queue='notifications.v1', durable=True)
    channel.confirm_delivery.assert_called_once()
    values = channel.basic_publish.call_args.kwargs
    assert values['routing_key'] == 'notifications.v1' and values['mandatory'] is True
    assert values['properties'].delivery_mode == 2
    assert values['properties'].message_id == rejection_JOB['id']
    assert json.loads(values['body'])['type'] == 'event.rejection'
    connection.close.assert_called_once()

def test_worker_loop_retries_then_polls_until_stopped(mocker):
    """
    Summary: The worker retries after failures and keeps polling until stopped.
    AC2: (delivery)
    Double: Stub (attempt outcomes), Mock (sleep)
    """
    import app.dispatcher as worker
    import subprocess
    import sys
    from unittest.mock import call, patch
    outcomes = [subprocess.TimeoutExpired('worker', 50), subprocess.CalledProcessError(1, 'worker'), subprocess.CalledProcessError(3, 'worker'), subprocess.CalledProcessError(1, 'worker'), subprocess.CalledProcessError(1, 'worker'), subprocess.CompletedProcess('worker', 0), subprocess.CalledProcessError(1, 'worker'), KeyboardInterrupt()]
    run = mocker.patch('subprocess.run', side_effect=outcomes)
    sleep = mocker.patch('time.sleep')
    worker.run()
    assert run.call_args_list == [call([sys.executable, '-m', 'app.dispatcher', '--attempt'], timeout=50, check=True)] * 8
    assert sleep.call_args_list == [call(1), call(2), call(1), call(1), call(2), call(1)]

def test_worker_cli_stops_cleanly(monkeypatch, mocker):
    """
    Summary: The worker command stops cleanly.
    AC2: (delivery)
    Double: Stub (interrupt)
    """
    import runpy
    from pathlib import Path
    from unittest.mock import patch
    monkeypatch.setattr('sys.argv', ['app.dispatcher'])
    mocker.patch('subprocess.run', side_effect=KeyboardInterrupt())
    runpy.run_path(str(Path(__file__).parents[2] / 'app' / 'dispatcher.py'), run_name='__main__')

def test_worker_attempt_runs_io_inside_bounded_child(mocker):
    """
    Summary: Each attempt runs inside a time-bounded child so a stuck call cannot hold the lease.
    AC2: (delivery)
    Double: Mock (subprocess.run)
    """
    import app.dispatcher as worker
    import subprocess
    from unittest.mock import patch
    import pytest
    run = mocker.patch('subprocess.run')
    assert worker.attempt() == 1
    assert run.call_args.kwargs == {'timeout': 50, 'check': True}
    assert run.call_args.args[0][-3:] == ['-m', 'app.dispatcher', '--attempt']
    run.side_effect = subprocess.CalledProcessError(3, 'worker')
    assert worker.attempt() == 0
    run.side_effect = subprocess.TimeoutExpired('worker', 50)
    with pytest.raises(subprocess.TimeoutExpired):
        worker.attempt()

def test_worker_attempt_entry_reports_empty_claim(monkeypatch, mocker):
    """
    Summary: A one-off attempt reports when there was nothing to send.
    AC2: (delivery)
    Double: Stub (empty claim)
    """
    import runpy
    import pytest
    from unittest.mock import patch
    monkeypatch.setenv('EVENT_SERVICE_URL', 'http://event.test')
    monkeypatch.setenv('INTERNAL_SERVICE_TOKEN', 'test-token')
    monkeypatch.setattr('sys.argv', ['app.dispatcher', '--attempt'])
    request = mocker.patch('httpx.request')
    request.return_value.json.return_value = {'jobs': []}
    with pytest.raises(SystemExit) as exited:
        from pathlib import Path
        runpy.run_path(str(Path(__file__).parents[2] / 'app' / 'dispatcher.py'), run_name='__main__')
    assert exited.value.code == 3

@pytest.mark.parametrize('status,body', [(404, {'message': 'User not found.'}), (200, {'username': '   '}), (200, {}), (200, {'username': None}), (200, {'username': 23})], ids=["not_found", "blank_name", "no_name", "null_name", "numeric_name"])
def test_assignment_alert_with_unusable_user_is_held_without_blocking(initial_assignment_api, status, body, mocker):
    """
    Summary: An assignment alert whose coordinator cannot be named is held for repair without blocking others.
    AC4: Given an initial coordinator assignment or reassignment is
        successfully recorded, the Event Organiser receives an in-app
        notification with the event name, the newly assigned coordinator’s
        name, and a link to view the event details.
    Double: Stub (user lookup returns unusable data), Mock (hold)
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
    import json
    assert json.loads(held[0].content) == {'leaseToken': 'lease', 'error': f'CoordinatorNameUnavailable coordinatorId={initial_assignment_COORDINATOR}'}
    assert len(published) == 1 and published[0]['id'] == good['id']

@pytest.mark.parametrize('outcome', [503, 'timeout'], ids=["service_unavailable", "timeout"])
def test_assignment_alert_after_temporary_lookup_failure_retries_then_delivers(initial_assignment_api, outcome, mocker):
    """
    Summary: A temporary lookup failure is retried for the same change and then delivered.
    AC4: Given an initial coordinator assignment or reassignment is
        successfully recorded, the Event Organiser receives an in-app
        notification with the event name, the newly assigned coordinator’s
        name, and a link to view the event details.
    Double: Stub (lookup fails once), Mock (publish)
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
    Summary: If a hold cannot be recorded, a recovery diagnosis is logged.
    AC4: Given an initial coordinator assignment or reassignment is
        successfully recorded, the Event Organiser receives an in-app
        notification with the event name, the newly assigned coordinator’s
        name, and a link to view the event details.
    Double: Stub (hold storage fails)
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

def test_worker_when_retry_state_unavailable_still_sends_other_alerts():
    """
    Summary: A failure recording one retry does not block other waiting alerts.
    AC2: (delivery)
    Double: Stub (retry call fails), Mock (publish other job)
    """
    # Arrange (Given)
    from app.dispatcher import dispatch_once
    api, publish = (Mock(), Mock(side_effect=[RuntimeError(), None]))
    second = {**rejection_JOB, 'id': '20000000-0000-0000-0000-000000000002'}
    api.claim.return_value = [rejection_JOB, second]
    api.freeze.side_effect = lambda job, envelope: envelope
    api.retry.side_effect = RuntimeError('owner unavailable')

    # Act + Assert (When / Then)
    assert dispatch_once(api, publish) == 2
    api.published.assert_called_once_with(second)

def test_publish_when_broker_rejects_or_closes_raises(monkeypatch, mocker):
    """
    Summary: A broker rejection or closed connection is reported as a failure.
    AC2: (delivery)
    Double: Mock (pika nacks or closes)
    """
    # Arrange (Given)
    import app.dispatcher as worker
    from unittest.mock import MagicMock, patch
    import pytest
    monkeypatch.setenv('RABBITMQ_URL', 'amqp://guest:guest@localhost/%2F')
    connection = MagicMock(is_open=False)
    connection.channel.return_value.basic_publish.side_effect = RuntimeError('nack')

    # Act + Assert (When / Then)
    mocker.patch('pika.BlockingConnection', return_value=connection)
    with pytest.raises(RuntimeError):
        worker.publish({'id': rejection_JOB['id'], 'type': 'event.rejection'})

    # Assert (Then)
    connection.close.assert_not_called()

def test_worker_attempt_when_child_fails_reports_error(mocker):
    """
    Summary: A failed attempt in the child process is reported.
    AC2: (delivery)
    Double: Mock (subprocess.run returns an error)
    """
    # Arrange (Given)
    import app.dispatcher as worker
    import subprocess
    import pytest
    from unittest.mock import patch

    # Act + Assert (When / Then)
    mocker.patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'worker'))
    with pytest.raises(subprocess.CalledProcessError):
        worker.attempt()
