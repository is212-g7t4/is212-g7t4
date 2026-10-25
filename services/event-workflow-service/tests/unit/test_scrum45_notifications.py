"""SCRUM-45 Event Organiser Status and Update Notifications: event-workflow-service unit tests.

Story: As an Event Organiser, I want to receive an in-app notification when the Lead Coordinator approves or rejects my event request, so that I know the outcome and who is responsible for coordinating my event.
Real: own worker, envelope preparation, HTTP/publisher adapters and runner logic.
Doubled: owner API/HTTP transport, broker connection, process and time boundaries as each scenario states.
Not proven: production authentication, hosted Supabase, cross-service delivery or browser navigation.
Owned: saved-source envelope preparation, name lookup, freeze-before-publish and recovery via Event HTTP. Not covered here: Event persistence, Notification inbox and UI/E2E.
AC = acceptance criterion; DR = supporting design rule, not an extra AC.

AC1 A successfully recorded approval sends an in-app approval notification to the submitting Event Organiser.
  Owned: Approval preparation and publication-adapter calls; Event commit and actual inbox delivery are outside Workflow.
AC2 A successfully recorded rejection sends an in-app rejection notification to the submitting Event Organiser, including the rejection reason.
  Owned: Rejection preparation with saved reason and publication-adapter calls; Event commit and inbox storage are outside Workflow.
AC3 Both decision notifications include event name, decision, and a link to the event request and its decision details.
  Owned: Exact decision envelope and freeze-before-publish ordering; destination access and browser navigation are not proven.
AC4 A successfully recorded initial assignment or reassignment sends the submitting Event Organiser an in-app notification with event name, newly assigned coordinator name, and an event-details link.
  Owned: Saved-ID User lookup, named assignment envelope and frozen retry; Event assignment and inbox storage are outside Workflow.
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

def test_ac1_approval_worker_freezes_saved_facts_before_publish():
    """Normal: dispatch a saved approval using a fake owner API; publish receives the exact
    organiser/content/link and completion is requested, checking message preparation without
    proving broker delivery or call order.
    """
    api, publish = (Mock(), Mock())
    api.claim.return_value = [approval_JOB]
    api.freeze.side_effect = lambda job, envelope: envelope
    assert dispatch_once(api, publish) == 1
    expected = dict(version=1, id=approval_JOB['id'], type='event.approval', recipientId=approval_SOURCE['recipientId'], createdAt=approval_JOB['createdAt'], message='Community Workshop was approved', destination=dict(kind='event-details', eventId=approval_SOURCE['eventId']), details=approval_SOURCE)
    publish.assert_called_once_with(expected)
    api.freeze.assert_called_once_with(approval_JOB, expected)
    api.published.assert_called_once_with(approval_JOB)
    api.retry.assert_not_called()


# AC2 — Rejection and reason

def test_ac2_worker_delivers_rejection_to_saved_submitting_organiser():
    """Normal: dispatch a saved rejection using a fake owner API; publish receives the exact
    reason, organiser and link, and completion is requested, checking the prepared message
    rather than inbox delivery.
    """
    from app.dispatcher import dispatch_once
    api, publish = (Mock(), Mock())
    api.claim.return_value = [rejection_JOB]
    api.freeze.side_effect = lambda job, envelope: envelope
    assert dispatch_once(api, publish) == 1
    envelope = publish.call_args.args[0]
    assert envelope == dict(version=1, id=rejection_JOB['id'], type='event.rejection', recipientId=rejection_SOURCE['recipientId'], createdAt=rejection_JOB['createdAt'], message='Community Workshop was rejected: Missing plan', destination=dict(kind='event-details', eventId=rejection_SOURCE['eventId']), details=rejection_SOURCE)
    api.freeze.assert_called_once_with(rejection_JOB, envelope)
    api.published.assert_called_once_with(rejection_JOB)
    api.retry.assert_not_called()


# AC3 — Decision content and link

@pytest.mark.parametrize('kind', ['event.approval', 'event.rejection', 'event.coordinator-assignment'])
@pytest.mark.parametrize('freeze_fails', [False, True], ids=['frozen-owner-result', 'freeze-outage'])
def test_ac3_dispatch_waits_for_freeze_and_publishes_only_owner_returned_envelope(kind, freeze_fails):
    """Normal/Failure: dispatch each type with ordered recording callbacks; success publishes only
    the owner-returned envelope, while freeze failure publishes nothing and retries, preventing
    an unfrozen local draft from escaping.
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

def test_ac4_worker_resolves_saved_id_using_user_username_and_freezes_before_publish(initial_assignment_api):
    """Normal: dispatch assignment through the HTTP adapter with fake responses; the published
    envelope uses the saved coordinator's username and event link, not an unrelated current
    identity.
    """
    published = []
    with httpx.Client(transport=httpx.MockTransport(initial_assignment_transport)) as client, patch('httpx.request', side_effect=client.request):
        assert dispatch_once(initial_assignment_api, published.append) == 1
    assert len(published) == 1, 'Initial assignment must publish after User lookup'
    assert published[0] == dict(version=1, id=initial_assignment_JOB['id'], type='event.coordinator-assignment', recipientId=initial_assignment_SOURCE['recipientId'], createdAt=initial_assignment_JOB['createdAt'], message='Alice Tan has been assigned to coordinate Community Workshop.', destination=dict(kind='event-details', eventId=initial_assignment_SOURCE['eventId']), details={**initial_assignment_SOURCE, 'coordinatorName': 'Alice Tan'})


# Supporting DR3/DR4/DR6 — retry, frozen history and missing-name recovery

def test_ac1_dr_failed_approval_publication_reuses_frozen_envelope_after_source_changes():
    """Failure: fail approval publication, then reclaim with changed source facts; retry publishes
    the first frozen envelope without another freeze, preserving historical organiser and name
    (DR3/DR4).
    """
    api, publish = (Mock(), Mock(side_effect=RuntimeError('broker unavailable')))
    api.claim.return_value = [approval_JOB]
    api.freeze.side_effect = lambda job, envelope: envelope
    dispatch_once(api, publish)
    frozen = publish.call_args.args[0]
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

def test_ac4_dr_assignment_publish_retry_uses_frozen_name_without_user_lookup(initial_assignment_api):
    """Failure: fail assignment publication, then reclaim its frozen envelope; one User GET and the
    unchanged published name show retry does not resolve a different identity (DR4).
    """
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
    with httpx.Client(transport=httpx.MockTransport(respond)) as client, patch('httpx.request', side_effect=client.request):
        dispatch_once(initial_assignment_api, outage)
        dispatch_once(initial_assignment_api, published.append)
    assert len(looked_up) == 1
    assert published == frozen
    assert published[0]['details']['coordinatorName'] == 'Alice Tan'

def test_ac2_dr_publish_retry_preserves_prepared_notification_content():
    """Failure: fail rejection publication, then reclaim with a renamed source; retry publishes the
    frozen envelope without another freeze, retaining the original decision content (DR3/DR4).
    """
    from app.dispatcher import dispatch_once
    api, publish = (Mock(), Mock(side_effect=RuntimeError('broker down')))
    api.claim.return_value = [rejection_JOB]
    api.freeze.side_effect = lambda job, envelope: envelope
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

def test_ac2_dr_worker_uses_authenticated_event_http_outbox_protocol(monkeypatch):
    """Normal: DR3: mock HTTP transport only; claim/freeze/complete/retry adapters send the owning Event API contract with token, lease and bounded timeouts."""
    import app.dispatcher as worker
    from unittest.mock import patch
    monkeypatch.setenv('EVENT_SERVICE_URL', 'http://event.test/')
    monkeypatch.setenv('INTERNAL_SERVICE_TOKEN', 'test-token')
    with patch('httpx.request') as request:
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

def test_ac2_dr_broker_publish_requires_confirm_and_persistent_message(monkeypatch):
    """Normal: DR3: execute real publication adapter with only broker socket mocked; observe durable queue, publisher confirms, mandatory routing and stable ID."""
    import app.dispatcher as worker
    from unittest.mock import MagicMock, patch
    import json
    monkeypatch.setenv('RABBITMQ_URL', 'amqp://guest:***@localhost/%2F')
    connection = MagicMock()
    with patch('pika.BlockingConnection', return_value=connection):
        worker.publish({'id': rejection_JOB['id'], 'type': 'event.rejection'})
    channel = connection.channel.return_value
    channel.queue_declare.assert_called_once_with(queue='notifications.v1', durable=True)
    channel.confirm_delivery.assert_called_once()
    values = channel.basic_publish.call_args.kwargs
    assert values['routing_key'] == 'notifications.v1' and values['mandatory'] is True
    assert values['properties'].delivery_mode == 2
    assert values['properties'].message_id == rejection_JOB['id']
    assert json.loads(values['body'])['type'] == 'event.rejection'
    connection.close.assert_called_once()

def test_ac2_dr_worker_runner_retries_then_polls_until_stopped():
    """Failure: feed the runner timeouts, child failures, empty work, success and interruption;
    recorded child commands and sleep delays show bounded attempts and reset backoff without
    real waits (DR3).
    """
    import app.dispatcher as worker
    import subprocess
    import sys
    from unittest.mock import call, patch
    outcomes = [subprocess.TimeoutExpired('worker', 50), subprocess.CalledProcessError(1, 'worker'), subprocess.CalledProcessError(3, 'worker'), subprocess.CalledProcessError(1, 'worker'), subprocess.CalledProcessError(1, 'worker'), subprocess.CompletedProcess('worker', 0), subprocess.CalledProcessError(1, 'worker'), KeyboardInterrupt()]
    with patch('subprocess.run', side_effect=outcomes) as run, patch('time.sleep') as sleep:
        worker.run()
        assert run.call_args_list == [call([sys.executable, '-m', 'app.dispatcher', '--attempt'], timeout=50, check=True)] * 8
        assert sleep.call_args_list == [call(1), call(2), call(1), call(1), call(2), call(1)]

def test_ac2_dr_worker_default_cli_stops_cleanly(monkeypatch):
    """Normal: run the default module entry with an interrupted child launch; it returns without
    propagating KeyboardInterrupt, allowing the polling worker to stop cleanly (DR3).
    """
    import runpy
    from pathlib import Path
    from unittest.mock import patch
    monkeypatch.setattr('sys.argv', ['app.dispatcher'])
    with patch('subprocess.run', side_effect=KeyboardInterrupt()):
        runpy.run_path(str(Path(__file__).parents[2] / 'app' / 'dispatcher.py'), run_name='__main__')

def test_ac2_dr_worker_attempt_bounds_io_inside_lease():
    """Boundary: run the attempt adapter with fake child outcomes; it sets a 50-second timeout,
    maps only empty work to zero and propagates timeout, keeping a child attempt inside the
    60-second lease (DR3).
    """
    import app.dispatcher as worker
    import subprocess
    from unittest.mock import patch
    import pytest
    with patch('subprocess.run') as run:
        assert worker.attempt() == 1
        assert run.call_args.kwargs == {'timeout': 50, 'check': True}
        assert run.call_args.args[0][-3:] == ['-m', 'app.dispatcher', '--attempt']
        run.side_effect = subprocess.CalledProcessError(3, 'worker')
        assert worker.attempt() == 0
        run.side_effect = subprocess.TimeoutExpired('worker', 50)
        with pytest.raises(subprocess.TimeoutExpired):
            worker.attempt()

def test_ac2_dr_worker_module_attempt_entry_reports_empty_claim(monkeypatch):
    """Boundary: execute the --attempt module entry with an empty HTTP claim; exit code 3 tells the
    parent to poll rather than misclassify no work as an outage (DR3).
    """
    import runpy
    import pytest
    from unittest.mock import patch
    monkeypatch.setenv('EVENT_SERVICE_URL', 'http://event.test')
    monkeypatch.setenv('INTERNAL_SERVICE_TOKEN', 'test-token')
    monkeypatch.setattr('sys.argv', ['app.dispatcher', '--attempt'])
    with patch('httpx.request') as request:
        request.return_value.json.return_value = {'jobs': []}
        with pytest.raises(SystemExit) as exited:
            from pathlib import Path
            runpy.run_path(str(Path(__file__).parents[2] / 'app' / 'dispatcher.py'), run_name='__main__')
        assert exited.value.code == 3

@pytest.mark.parametrize('status,body', [(404, {'message': 'User not found.'}), (200, {'username': '   '}), (200, {}), (200, {'username': None}), (200, {'username': 23})])
def test_ac4_dr_unusable_user_is_held_for_repair_without_blocking_other_work(initial_assignment_api, status, body):
    """Failure: dispatch a missing or unusably named coordinator beside a valid rejection; HTTP
    records a diagnostic hold and only the rejection publishes, avoiding ID-only messages and
    batch blockage (DR6).
    """
    good = {**initial_assignment_JOB, 'id': '20000000-0000-0000-0000-000000000002', 'type': 'event.rejection', 'source': {**initial_assignment_SOURCE, 'reason': 'Missing plan', 'decision': 'Rejected'}}
    calls, published = ([], [])

    def respond(request):
        calls.append(request)
        if request.method == 'GET':
            return httpx.Response(status, json=body)
        if request.url.path.endswith('claim'):
            return httpx.Response(200, json={'jobs': [initial_assignment_JOB, good]})
        return initial_assignment_transport(request)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client, patch('httpx.request', side_effect=client.request):
        assert dispatch_once(initial_assignment_api, published.append) == 2
    held = [request for request in calls if request.url.path.endswith('/hold')]
    assert len(held) == 1, 'Unusable coordinator name must be held, not endlessly retried'
    import json
    assert json.loads(held[0].content) == {'leaseToken': 'lease', 'error': f'CoordinatorNameUnavailable coordinatorId={initial_assignment_COORDINATOR}'}
    assert len(published) == 1 and published[0]['id'] == good['id']

@pytest.mark.parametrize('outcome', [503, 'timeout'])
def test_ac4_dr_temporary_lookup_failure_retries_same_change_then_delivers(initial_assignment_api, outcome):
    """Failure: fail User lookup with timeout or 503, then restore it; no first-attempt
    freeze/publication and later delivery of the same ID/name preserve retryable assignment work
    (DR3/DR6).
    """
    actions, published = ([], [])
    failed = True

    def respond(request):
        actions.append(request.url.path)
        if request.method == 'GET' and failed:
            if outcome == 'timeout':
                raise httpx.ReadTimeout('temporary', request=request)
            return httpx.Response(503, json={})
        return initial_assignment_transport(request)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client, patch('httpx.request', side_effect=client.request):
        dispatch_once(initial_assignment_api, published.append)
        assert published == []
        assert actions[-1].endswith('/retry')
        assert not any((path.endswith('/freeze') or path.endswith('/hold') for path in actions))
        failed = False
        dispatch_once(initial_assignment_api, published.append)
    assert published[0]['id'] == initial_assignment_JOB['id']
    assert published[0]['details']['coordinatorName'] == 'Alice Tan'

def test_ac4_dr_hold_storage_outage_records_recovery_diagnosis(initial_assignment_api, caplog):
    """Failure: make User lookup missing and the hold write fail; dispatch logs lease-recovery
    warning rather than hiding failed recovery. This one-job case does not prove unrelated
    progress (DR6).
    """
    calls = []

    def respond(request):
        calls.append(request.url.path)
        if request.method == 'GET':
            return httpx.Response(404, json={})
        if request.url.path.endswith('/hold'):
            return httpx.Response(503, json={})
        return initial_assignment_transport(request)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client, patch('httpx.request', side_effect=client.request):
        assert dispatch_once(initial_assignment_api, Mock()) == 1
    assert 'Hold update failed; lease will recover' in caplog.text

def test_ac2_dr_retry_state_outage_does_not_block_unrelated_pending_notification():
    """Failure: fail the first job's publication and retry update; dispatch still marks the second
    job published, so one recovery outage cannot abort the claimed batch (DR3).
    """
    from app.dispatcher import dispatch_once
    api, publish = (Mock(), Mock(side_effect=[RuntimeError(), None]))
    second = {**rejection_JOB, 'id': '20000000-0000-0000-0000-000000000002'}
    api.claim.return_value = [rejection_JOB, second]
    api.freeze.side_effect = lambda job, envelope: envelope
    api.retry.side_effect = RuntimeError('owner unavailable')
    assert dispatch_once(api, publish) == 2
    api.published.assert_called_once_with(second)

def test_ac2_dr_broker_nack_and_closed_connection_propagate_failure(monkeypatch):
    """Failure: make the broker adapter reject publication on an already closed connection; the
    error propagates without a second close, allowing the worker to retry instead of claiming
    delivery (DR3).
    """
    import app.dispatcher as worker
    from unittest.mock import MagicMock, patch
    import pytest
    monkeypatch.setenv('RABBITMQ_URL', 'amqp://guest:guest@localhost/%2F')
    connection = MagicMock(is_open=False)
    connection.channel.return_value.basic_publish.side_effect = RuntimeError('nack')
    with patch('pika.BlockingConnection', return_value=connection), pytest.raises(RuntimeError):
        worker.publish({'id': rejection_JOB['id'], 'type': 'event.rejection'})
    connection.close.assert_not_called()

def test_ac2_dr_worker_attempt_nonempty_child_error_propagates():
    """Failure: make the attempt child exit with an error other than empty work; CalledProcessError
    propagates, preventing a worker outage from being mistaken for a successful empty claim
    (DR3).
    """
    import app.dispatcher as worker
    import subprocess
    import pytest
    from unittest.mock import patch
    with patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'worker')), pytest.raises(subprocess.CalledProcessError):
        worker.attempt()
