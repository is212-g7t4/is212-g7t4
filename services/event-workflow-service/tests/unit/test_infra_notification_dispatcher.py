"""
SUPPORTING DESIGN CHECKS: Notification dispatcher worker (app/dispatcher.py)

User Story
----------
Supporting/supplementary design checks. No story or acceptance
criterion describes the behaviour these tests check; it is plumbing
that every notification story of this service relies on (SCRUM-44, 45, 46, 49,
166 and 168 all deliver through the same worker).

Real
----
- app.dispatcher: the outbox HTTP adapter (URLs, token, timeout), the RabbitMQ
  publish call, the one-shot attempt child process, the retry/backoff loop and
  the command line entry run for real.
- Assertions are on the requests made, the publish arguments, the exit codes
  and which jobs are still processed after a failure.

Doubled
-------
- Event Service outbox HTTP (httpx.request): Stub / Mock - canned replies;
  requests inspected.
- RabbitMQ (pika.BlockingConnection): Mock - declared queue, confirms and
  message properties inspected.
- subprocess.run and time.sleep: Stub / Mock - child outcomes are scripted and
  sleeps recorded, so nothing is spawned and nothing waits.

Not proven
----------
- That a real RabbitMQ broker accepts and persists the message (-> integration
  tests).
- That a stuck publish really loses its lease after 60 seconds (NOT COVERED
  ANYWHERE).
"""
from unittest.mock import Mock

from app.dispatcher import dispatch_once

rejection_SOURCE = dict(eventId='30000000-0000-0000-0000-000000000001', recipientId='10000000-0000-0000-0000-000000000001', eventName='Community Workshop', decision='Rejected', reason='Missing plan')

rejection_JOB = dict(id='20000000-0000-0000-0000-000000000001', source=rejection_SOURCE, envelope=None, createdAt='2026-10-21T00:00:00+00:00', leaseToken='lease')


def test_worker_calls_event_outbox_with_internal_token(monkeypatch, mocker):
    """
    Summary: OutboxAPI.claim, freeze, published and retry each POST to
        http://event.test/internal/notification-outbox/ (claim, <id>/freeze,
        <id>/published, <id>/retry), sending the lease token (and envelope or
        error), header X-Internal-Token "test-token" and a 5 second timeout;
        claim returns the jobs and freeze returns the frozen envelope.
    Supporting design check: the worker calls Event Service's outbox as a
        trusted service
    Double: Stub (httpx.request returns {"jobs": [job]}, {"envelope":
        {"frozen": true}}, {}, {}; EVENT_SERVICE_URL and INTERNAL_SERVICE_TOKEN
        set with monkeypatch), Mock (the four recorded requests are asserted)
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
    Summary: publish() declares the durable queue notifications.v1, enables
        delivery confirms, publishes with routing key notifications.v1,
        mandatory=True, delivery_mode 2 and message_id equal to the envelope
        id, sends the envelope as the JSON body, and closes the connection.
    Supporting design check: alerts are published with broker confirmation and
        as persistent messages
    Double: Mock (pika.BlockingConnection returns a MagicMock connection whose
        channel calls are asserted; RABBITMQ_URL set with monkeypatch)
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
    Summary: worker.run() runs 8 attempts: it sleeps 1 then 2 seconds after
        consecutive failures, resets the delay to 1 after an empty claim or a
        success, sleeps 1 second after an empty claim, and returns when
        KeyboardInterrupt is raised.
    Supporting design check: the worker backs off after failures and keeps
        polling until stopped
    Double: Stub (subprocess.run raises TimeoutExpired, CalledProcessError
        1 / 3 / 1 / 1, returns success, raises CalledProcessError 1, then
        KeyboardInterrupt), Mock (time.sleep call arguments and the child
        command are asserted)
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
    Summary: Running app/dispatcher.py as a script with no arguments enters the
        worker loop and returns without raising when the first attempt is
        interrupted with KeyboardInterrupt.
    Supporting design check: the worker command stops cleanly on interrupt
    Double: Stub (subprocess.run raises KeyboardInterrupt; sys.argv set to
        ["app.dispatcher"] with monkeypatch)
    """
    import runpy
    from pathlib import Path
    from unittest.mock import patch
    monkeypatch.setattr('sys.argv', ['app.dispatcher'])
    mocker.patch('subprocess.run', side_effect=KeyboardInterrupt())
    runpy.run_path(str(Path(__file__).parents[2] / 'app' / 'dispatcher.py'), run_name='__main__')

def test_worker_attempt_runs_io_inside_bounded_child(mocker):
    """
    Summary: worker.attempt() runs `python -m app.dispatcher --attempt` with
        timeout=50 and check=True and returns 1; it returns 0 when the child
        exits with code 3 (empty claim); it lets TimeoutExpired propagate.
    Supporting design check: each attempt runs inside a time-bounded child so
        a stuck call cannot hold the lease
    Double: Mock (subprocess.run succeeds, then raises CalledProcessError 3,
        then TimeoutExpired; the call arguments are asserted)
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
    Summary: Running app/dispatcher.py as a script with --attempt exits with
        code 3 when the outbox claim returns no jobs.
    Supporting design check: a one-off attempt reports when there was nothing
        to send
    Double: Stub (httpx.request returns {"jobs": []}; EVENT_SERVICE_URL,
        INTERNAL_SERVICE_TOKEN and sys.argv set with monkeypatch)
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

def test_worker_when_retry_state_unavailable_still_sends_other_alerts():
    """
    Summary: dispatch_once with two claimed jobs returns 2 and still publishes
        and marks the second job published after the first job's publish raised
        and recording its retry also raised.
    Supporting design check: a failure recording one retry does not block other
        waiting alerts
    Double: Stub (claim returns two jobs; freeze echoes the draft; the first
        publish raises RuntimeError; retry raises RuntimeError), Mock (published
        called once, with the second job)
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
    Summary: publish() raises RuntimeError when basic_publish raises (a broker
        nack) and does not call close() on a connection that is already closed.
    Supporting design check: a broker rejection or closed connection is
        reported as a failure
    Double: Mock (pika.BlockingConnection returns a MagicMock connection with
        is_open False whose basic_publish raises RuntimeError("nack");
        RABBITMQ_URL set with monkeypatch; close not called is asserted)
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
    Summary: worker.attempt() raises CalledProcessError when the child exits
        with code 1.
    Supporting design check: a failed attempt in the child process is reported
    Double: Stub (subprocess.run raises CalledProcessError with return code 1)
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
