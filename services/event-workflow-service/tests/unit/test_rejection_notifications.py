"""User story (SCRUM-45): As an Event Organiser, I want in-app notification
when the Lead Coordinator rejects my event request, so I know the outcome
and who coordinates it. AC2/AC3: rejection reason, event name and details link.
DR2/DR3/DR4/DR5: atomic intent, retry identity, frozen facts and legacy diagnosis.
"""

from unittest.mock import Mock

SOURCE = dict(eventId="30000000-0000-0000-0000-000000000001",
              recipientId="10000000-0000-0000-0000-000000000001",
              eventName="Community Workshop", decision="Rejected", reason="Missing plan")
JOB = dict(id="20000000-0000-0000-0000-000000000001", source=SOURCE,
           envelope=None, createdAt="2026-10-21T00:00:00+00:00", leaseToken="lease")


def test_worker_delivers_rejection_to_saved_submitting_organiser():
    """AC2/AC3/DR4: worker public boundary prepares saved facts, freezes via
    Event API before broker I/O, then marks published only after acceptance.
    """
    from app.dispatcher import dispatch_once
    api, publish = Mock(), Mock()
    api.claim.return_value = [JOB]
    api.freeze.side_effect = lambda job, envelope: envelope
    assert dispatch_once(api, publish) == 1
    envelope = publish.call_args.args[0]
    assert envelope == dict(version=1, id=JOB["id"], type="event.rejection",
                           recipientId=SOURCE["recipientId"], createdAt=JOB["createdAt"],
                           message="Community Workshop was rejected: Missing plan",
                           destination=dict(kind="event-details", eventId=SOURCE["eventId"]),
                           details=SOURCE)
    api.freeze.assert_called_once_with(JOB, envelope)
    api.published.assert_called_once_with(JOB)
    api.retry.assert_not_called()

def test_publish_retry_preserves_prepared_notification_content():
    """DR3/DR4: broker outage reports retry, then reclaim publishes the owner's
    frozen content unchanged even if mutable source fields differ; no blocking.
    """
    from app.dispatcher import dispatch_once
    api, publish = Mock(), Mock(side_effect=RuntimeError("broker down"))
    api.claim.return_value = [JOB]
    api.freeze.side_effect = lambda job, envelope: envelope
    assert dispatch_once(api, publish) == 1
    api.retry.assert_called_once_with(JOB, "RuntimeError")
    api.published.assert_not_called()
    frozen = publish.call_args.args[0]
    retry_job = {**JOB, "source": {**SOURCE, "eventName": "Renamed"}, "envelope": frozen}
    api.reset_mock()
    api.claim.return_value = [retry_job]
    publish = Mock()
    assert dispatch_once(api, publish) == 1
    publish.assert_called_once_with(frozen)
    api.freeze.assert_not_called()
    api.published.assert_called_once_with(retry_job)

def test_worker_uses_authenticated_event_http_outbox_protocol(monkeypatch):
    """DR3: mock HTTP transport only; claim/freeze/complete/retry adapters send
    the owning Event API contract with token, lease and bounded timeouts.
    """
    import app.dispatcher as worker
    from unittest.mock import patch
    monkeypatch.setenv("EVENT_SERVICE_URL", "http://event.test/")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "test-token")
    with patch("httpx.request") as request:
        request.return_value.json.side_effect = [{"jobs": [JOB]}, {"envelope": {"frozen": True}}, {}, {}]
        api = worker.OutboxAPI()
        assert api.claim() == [JOB]
        assert api.freeze(JOB, {"draft": True}) == {"frozen": True}
        api.published(JOB)
        api.retry(JOB, "BrokerUnavailable")
        calls = request.call_args_list
        assert [call.args for call in calls] == [
            ("POST", "http://event.test/internal/notification-outbox/claim"),
            ("POST", f"http://event.test/internal/notification-outbox/{JOB['id']}/freeze"),
            ("POST", f"http://event.test/internal/notification-outbox/{JOB['id']}/published"),
            ("POST", f"http://event.test/internal/notification-outbox/{JOB['id']}/retry")]
        assert calls[1].kwargs["json"] == {"leaseToken": "lease", "envelope": {"draft": True}}
        assert calls[3].kwargs["json"] == {"leaseToken": "lease", "error": "BrokerUnavailable"}
        assert all(call.kwargs["headers"] == {"X-Internal-Token": "test-token"}
                   and call.kwargs["timeout"] == 5 for call in calls)

def test_broker_publish_requires_confirm_and_persistent_message(monkeypatch):
    """DR3: execute real publication adapter with only broker socket mocked;
    observe durable queue, publisher confirms, mandatory routing and stable ID.
    """
    import app.dispatcher as worker
    from unittest.mock import MagicMock, patch
    import json
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:***@localhost/%2F")
    connection = MagicMock()
    with patch("pika.BlockingConnection", return_value=connection):
        worker.publish({"id": JOB["id"], "type": "event.rejection"})
    channel = connection.channel.return_value
    channel.queue_declare.assert_called_once_with(queue="notifications.v1", durable=True)
    channel.confirm_delivery.assert_called_once()
    values = channel.basic_publish.call_args.kwargs
    assert values["routing_key"] == "notifications.v1" and values["mandatory"] is True
    assert values["properties"].delivery_mode == 2
    assert values["properties"].message_id == JOB["id"]
    assert json.loads(values["body"])["type"] == "event.rejection"
    connection.close.assert_called_once()

def test_worker_attempt_bounds_io_inside_lease():
    """DR3: execute worker process adapter with only subprocess mocked;
    child claims inside its 50-second budget, less than Event's 60-second lease.
    """
    import app.dispatcher as worker
    import subprocess
    from unittest.mock import patch
    import pytest
    with patch("subprocess.run") as run:
        assert worker.attempt() == 1
        assert run.call_args.kwargs == {"timeout": 50, "check": True}
        assert run.call_args.args[0][-3:] == ["-m", "app.dispatcher", "--attempt"]
        run.side_effect = subprocess.CalledProcessError(3, "worker")
        assert worker.attempt() == 0
        run.side_effect = subprocess.TimeoutExpired("worker", 50)
        with pytest.raises(subprocess.TimeoutExpired):
            worker.attempt()

def test_retry_state_outage_does_not_block_unrelated_pending_notification():
    """DR3: failed broker/retry I/O for one job must leave lease recovery to
    Event and still deliver another job returned by the public claim boundary.
    """
    from app.dispatcher import dispatch_once
    api, publish = Mock(), Mock(side_effect=[RuntimeError(), None])
    second = {**JOB, "id": "20000000-0000-0000-0000-000000000002"}
    api.claim.return_value = [JOB, second]
    api.freeze.side_effect = lambda job, envelope: envelope
    api.retry.side_effect = RuntimeError("owner unavailable")
    assert dispatch_once(api, publish) == 2
    api.published.assert_called_once_with(second)

def test_worker_runner_retries_then_polls_until_stopped():
    """DR3: exercise public long-running worker entry with process/time mocked;
    timeout/child failure back off, empty work polls, success resets backoff
    without sleeping, and keyboard interrupt exits through the real attempt.
    """
    import app.dispatcher as worker
    import subprocess
    import sys
    from unittest.mock import call, patch
    outcomes = [
        subprocess.TimeoutExpired("worker", 50),
        subprocess.CalledProcessError(1, "worker"),
        subprocess.CalledProcessError(3, "worker"),
        subprocess.CalledProcessError(1, "worker"),
        subprocess.CalledProcessError(1, "worker"),
        subprocess.CompletedProcess("worker", 0),
        subprocess.CalledProcessError(1, "worker"),
        KeyboardInterrupt(),
    ]
    with patch("subprocess.run", side_effect=outcomes) as run, patch("time.sleep") as sleep:
        worker.run()
        assert run.call_args_list == [call(
            [sys.executable, "-m", "app.dispatcher", "--attempt"],
            timeout=50, check=True,
        )] * 8
        assert sleep.call_args_list == [call(1), call(2), call(1), call(1), call(2), call(1)]

def test_worker_module_attempt_entry_reports_empty_claim(monkeypatch):
    """DR3: launch module entry in process context with HTTP mocked; empty
    claim returns exit code 3 so parent polls rather than treating outage.
    """
    import runpy
    import pytest
    from unittest.mock import patch
    monkeypatch.setenv("EVENT_SERVICE_URL", "http://event.test")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "test-token")
    monkeypatch.setattr("sys.argv", ["app.dispatcher", "--attempt"])
    with patch("httpx.request") as request:
        request.return_value.json.return_value = {"jobs": []}
        with pytest.raises(SystemExit) as exited:
            from pathlib import Path
            runpy.run_path(str(Path(__file__).parents[2] / "app" / "dispatcher.py"), run_name="__main__")
        assert exited.value.code == 3

def test_broker_nack_and_closed_connection_propagate_failure(monkeypatch):
    """DR3: broker NACK propagates so pending work retries; a broker-closed
    connection is not closed again (external transport only mocked).
    """
    import app.dispatcher as worker
    from unittest.mock import MagicMock, patch
    import pytest
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@localhost/%2F")
    connection = MagicMock(is_open=False)
    connection.channel.return_value.basic_publish.side_effect = RuntimeError("nack")
    with patch("pika.BlockingConnection", return_value=connection), pytest.raises(RuntimeError):
        worker.publish({"id": JOB["id"], "type": "event.rejection"})
    connection.close.assert_not_called()


def test_worker_attempt_nonempty_child_error_propagates():
    """DR3: nonempty child failure is not mistaken for an empty claim."""
    import app.dispatcher as worker
    import subprocess
    import pytest
    from unittest.mock import patch
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "worker")), pytest.raises(subprocess.CalledProcessError):
        worker.attempt()


def test_worker_default_cli_stops_cleanly(monkeypatch):
    """DR3: default module entry starts bounded polling and can stop cleanly."""
    import runpy
    from pathlib import Path
    from unittest.mock import patch
    monkeypatch.setattr("sys.argv", ["app.dispatcher"])
    with patch("subprocess.run", side_effect=KeyboardInterrupt()):
        runpy.run_path(str(Path(__file__).parents[2] / "app" / "dispatcher.py"), run_name="__main__")
