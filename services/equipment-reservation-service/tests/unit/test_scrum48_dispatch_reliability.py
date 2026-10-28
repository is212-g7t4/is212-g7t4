"""SCRUM-48: reliable delivery of equipment submission/decision notifications.

Story: Technical Support Staff and Event Coordinators receive in-app equipment
alerts so they can coordinate arrangements. AC1 is submission; AC2 is approval;
AC3 is rejection without its workflow reason. All cases here are supporting
reliability/transport design rules (DR), NOT new acceptance criteria.

Public seams: dispatcher single-cycle/loop/CLI, owner HTTP adapter and publisher.
HTTP, broker and subprocess boundaries are fresh doubles. These tests prove
ordering, identity preservation and requested delivery settings, not durable
inbox uniqueness, real broker confirmations, OS child reaping or live workers.
"""
from copy import deepcopy
import json
import runpy
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import httpx
import pytest

from app import dispatcher

SOURCE = "10000000-0000-4000-8000-000000000010"
LEASE = "10000000-0000-4000-8000-000000000011"
RECIPIENT = "10000000-0000-4000-8000-000000000005"


@pytest.fixture
def job():
    """A fresh frozen owner response: transport never enriches or regenerates it."""
    return dict(id=SOURCE, leaseToken=LEASE, attempts=1,
        envelope=dict(id=SOURCE, type="equipment.request-decision", recipientId=RECIPIENT,
            message="Community Fair: equipment request for Microphone x5 approved.",
            details={"eventName": "Community Fair"}))


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setenv("EQUIPMENT_REQUEST_SERVICE_URL", "http://owner.invalid/")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "synthetic")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@broker.invalid/")
    request = MagicMock()
    monkeypatch.setattr(httpx, "request", request)
    request.return_value = httpx.Response(200, json={"jobs": []},
        request=httpx.Request("POST", "http://owner.invalid/claim"))
    return request


def test_owner_adapter_preserves_token_and_frozen_job_identity(transport, job):
    """DR HTTP: Arrange owner responses; claim/published/retry; assert exact
    internal-only requests with same source/lease, bounded timeout and error.

    Why: Worker HTTP calls must retain the credentials and lease of the claimed job.
    """
    transport.return_value = httpx.Response(200, json={"jobs": [job]},
        request=httpx.Request("POST", "http://owner.invalid/claim"))
    api = dispatcher.OutboxAPI()
    assert api.claim() == [job]
    api.published(job)
    api.retry(job, "TimeoutError")
    assert transport.call_args_list == [
        call("POST", "http://owner.invalid/internal/notification-outbox/claim",
             headers={"X-Internal-Token": "synthetic"}, timeout=5, json={}),
        call("POST", f"http://owner.invalid/internal/notification-outbox/{SOURCE}/published",
             headers={"X-Internal-Token": "synthetic"}, timeout=5, json={"leaseToken": LEASE}),
        call("POST", f"http://owner.invalid/internal/notification-outbox/{SOURCE}/retry",
             headers={"X-Internal-Token": "synthetic"}, timeout=5,
             json={"leaseToken": LEASE, "error": "TimeoutError"})]


def test_owner_adapter_does_not_hide_http_failure(transport, job):
    """DR failure: Arrange owner 409; finalize; assert the HTTP status raises
    rather than pretending the stale worker successfully finalized its lease.

    Why: A rejected lease must not be reported as a completed publication.
    """
    transport.return_value = httpx.Response(409, json={"message": "Lease lost."},
        request=httpx.Request("POST", "http://owner.invalid/published"))
    with pytest.raises(httpx.HTTPStatusError):
        dispatcher.OutboxAPI().published(job)


def test_single_cycle_publishes_owner_envelope_before_marking_published(job):
    """DR order: Arrange a frozen job; dispatch; assert publish occurs before
    published and receives the exact owner object, not a regenerated draft.

    Why: Marking first could permanently lose an undelivered alert.
    """
    api = MagicMock()
    api.claim.return_value = [job]
    observed = []
    def publish(envelope):
        assert envelope is job["envelope"]
        observed.append(("publish", deepcopy(envelope)))
    api.published.side_effect = lambda received: observed.append(("published", received["id"]))
    assert dispatcher.dispatch_once(api, publish) == 1
    assert observed == [("publish", job["envelope"]), ("published", SOURCE)]
    api.retry.assert_not_called()


@pytest.mark.parametrize("failure", ["publish", "published-response-lost", "missing-envelope"])
@pytest.mark.parametrize("retry_fails", [False, True], ids=["retry-recorded", "retry-response-lost"])
def test_failed_delivery_retries_original_job_without_exposing_exception_text(job, failure, retry_fails, caplog):
    """DR recovery: Arrange failure before/after broker acceptance or absent
    envelope; dispatch; assert retry uses original source/lease and error class,
    never exception secrets, and retry failure is left for lease recovery.

    Why: Recovery must preserve the source identity without leaking sensitive errors.
    """
    api = MagicMock()
    api.claim.return_value = [job]
    publisher = MagicMock()
    if failure == "publish":
        publisher.side_effect = TimeoutError("private broker credentials")
    elif failure == "published-response-lost":
        api.published.side_effect = httpx.ReadError("private owner credentials")
    else:
        job["envelope"] = None
    if retry_fails:
        api.retry.side_effect = ConnectionError("private retry credentials")
    assert dispatcher.dispatch_once(api, publisher) == 1
    expected_error = {"publish": "TimeoutError", "published-response-lost": "ReadError", "missing-envelope": "ValueError"}[failure]
    api.retry.assert_called_once_with(job, expected_error)
    if failure == "missing-envelope":
        publisher.assert_not_called()
    else:
        publisher.assert_called_once_with(job["envelope"])
    if failure == "published-response-lost":
        api.published.assert_called_once_with(job)
    else:
        api.published.assert_not_called()
    assert "private" not in caplog.text
    assert ("lease will recover" in caplog.text) is retry_fails


def test_reclaim_after_unknown_publication_reuses_frozen_payload_and_source(job):
    """DR at-least-once: Arrange broker accepted but owner response lost; retry
    with a new lease; assert byte-equivalent payload/source on both attempts.
    This proves producer identity only, not durable inbox dedup/read-state.

    Why: A new source on retry would defeat downstream deduplication.
    """
    api = MagicMock()
    api.claim.side_effect = [[deepcopy(job)], [{**deepcopy(job), "leaseToken": RECIPIENT}]]
    api.published.side_effect = [httpx.ReadError("response lost"), None]
    sent = []
    publisher = lambda envelope: sent.append(json.dumps(envelope, sort_keys=True).encode())
    dispatcher.dispatch_once(api, publisher)
    dispatcher.dispatch_once(api, publisher)
    assert sent == [json.dumps(job["envelope"], sort_keys=True).encode()] * 2
    assert [c.args[0]["id"] for c in api.published.call_args_list] == [SOURCE, SOURCE]
    assert [c.args[0]["leaseToken"] for c in api.published.call_args_list] == [LEASE, RECIPIENT]
    assert api.retry.call_count == 1


def test_empty_claim_has_no_publication_or_mutation():
    """DR no-op: Arrange no work; dispatch once; assert no publish/retry/mark.

    Why: An idle cycle must not fabricate work or alter unrelated jobs.
    """
    api, publisher = MagicMock(), MagicMock()
    api.claim.return_value = []
    assert dispatcher.dispatch_once(api, publisher) == 0
    publisher.assert_not_called()
    api.published.assert_not_called()
    api.retry.assert_not_called()


@pytest.fixture
def broker(monkeypatch, transport):
    """Double only the AMQP boundary; the publisher implementation stays real."""
    connection = MagicMock()
    connection.is_open = True
    factory = MagicMock(return_value=connection)
    monkeypatch.setattr(dispatcher.pika, "BlockingConnection", factory)
    return SimpleNamespace(connection=connection, factory=factory,
                           channel=connection.channel.return_value)


def test_publisher_requests_confirmed_durable_mandatory_json_and_closes(broker, job):
    """DR broker contract: Arrange channel; publish; assert durable queue,
    confirms BEFORE persistent mandatory publish and exact message identity.

    Why: Losing delivery flags or confirms would weaken the delivery contract.
    """
    dispatcher.publish(job["envelope"])
    assert broker.channel.method_calls[:2] == [call.queue_declare(queue="notifications.v1", durable=True), call.confirm_delivery()]
    _, kwargs = broker.channel.basic_publish.call_args
    assert kwargs["exchange"] == "" and kwargs["routing_key"] == "notifications.v1"
    assert kwargs["mandatory"] is True
    assert json.loads(kwargs["body"]) == job["envelope"]
    properties = kwargs["properties"]
    assert (properties.message_id, properties.type, properties.delivery_mode, properties.content_type) == (
        SOURCE, "equipment.request-decision", 2, "application/json")
    params = broker.factory.call_args.args[0]
    assert (params.heartbeat, params.blocked_connection_timeout, params.socket_timeout,
            params.stack_timeout, params.connection_attempts) == (30, 10, 5, 15, 1)
    broker.connection.close.assert_called_once()


@pytest.mark.parametrize("stage", ["channel", "queue_declare", "confirm_delivery", "basic_publish"])
@pytest.mark.parametrize("still_open", [True, False], ids=["owned-open-connection", "already-closed-connection"])
def test_publisher_propagates_broker_failure_and_closes_only_open_connection(broker, job, stage, still_open):
    """DR failure cleanup: Arrange channel/declaration/confirm/publish error;
    publish; assert original error propagates and owned open connection closes.
    No test opens a real broker connection.

    Why: Silent publication failure would prevent recovery; leaked connections would accumulate.
    """
    failure = RuntimeError("broker failed")
    target = broker.connection.channel if stage == "channel" else getattr(broker.channel, stage)
    target.side_effect = failure
    broker.connection.is_open = still_open
    with pytest.raises(RuntimeError, match="broker failed") as error:
        dispatcher.publish(job["envelope"])
    assert error.value is failure
    assert broker.connection.close.call_count == int(still_open)


@pytest.mark.parametrize("outcome,expected", [(None, 1), (3, 0), (2, None), ("timeout", None)])
def test_bounded_attempt_distinguishes_empty_work_from_failure(monkeypatch, outcome, expected):
    """DR process boundary: Arrange subprocess success/empty/failure/timeout;
    attempt; assert claim is INSIDE the bounded child and timeout is propagated.
    subprocess.run itself owns kill/reap; this unit test does not prove OS cleanup.

    Why: Idle work and failed work need different retry behavior.
    """
    runner = MagicMock()
    monkeypatch.setattr(subprocess, "run", runner)
    expected_exception = subprocess.CalledProcessError
    if outcome == "timeout":
        runner.side_effect = subprocess.TimeoutExpired("worker", 7)
        expected_exception = subprocess.TimeoutExpired
    elif outcome:
        runner.side_effect = subprocess.CalledProcessError(outcome, "worker")
        expected_exception = subprocess.CalledProcessError
    if expected is None:
        with pytest.raises(expected_exception):
            dispatcher.attempt(timeout=7)
    else:
        assert dispatcher.attempt(timeout=7) == expected
    runner.assert_called_once_with([sys.executable, "-m", "app.dispatcher", "--attempt"], timeout=7, check=True)


def test_worker_loop_caps_backoff_then_resets_after_success_and_stops(monkeypatch):
    """DR loop: Arrange repeated outages, success, another outage and interrupt;
    run; assert exponential cap, reset to one, idle wait and clean shutdown.

    Why: Outages must not spin, and recovery must not retain an excessive delay.
    """
    outcomes = [RuntimeError("offline")] * 8 + [1, RuntimeError("again"), 0, KeyboardInterrupt()]
    attempt = MagicMock(side_effect=outcomes)
    sleeps = MagicMock()
    monkeypatch.setattr(dispatcher, "attempt", attempt)
    monkeypatch.setattr(dispatcher.time, "sleep", sleeps)
    assert dispatcher.run() is None
    assert [c.args[0] for c in sleeps.call_args_list] == [1, 2, 4, 8, 16, 32, 60, 60, 1, 1]
    assert attempt.call_count == 12


@pytest.mark.parametrize("has_job", [False, True], ids=["empty-exit-3", "processed-exit-0"])
def test_one_shot_cli_claims_only_one_cycle_with_doubled_io(monkeypatch, transport, broker, job, has_job):
    """DR CLI: Arrange one-shot argv and owner job/empty response; execute real
    module entrypoint; assert process exit contract with no live subprocess/I/O.

    Why: The one-shot command must not unexpectedly become a long-running worker.
    """
    monkeypatch.delitem(sys.modules, "app.dispatcher", raising=False)
    monkeypatch.setattr(sys, "argv", ["app.dispatcher", "--attempt"])
    transport.return_value = httpx.Response(200, json={"jobs": [job] if has_job else []},
        request=httpx.Request("POST", "http://owner.invalid/claim"))
    with pytest.raises(SystemExit) as error:
        runpy.run_module("app.dispatcher", run_name="__main__")
    assert error.value.code == (0 if has_job else 3)
    assert transport.call_count == (2 if has_job else 1)
    assert broker.channel.basic_publish.call_count == int(has_job)


def test_daemon_cli_enters_loop_and_honours_interrupt_without_real_worker(monkeypatch, transport):
    """DR CLI: Arrange default argv and a child-run interrupt double; execute
    real daemon entrypoint; assert clean return, without starting a worker.

    Why: The daemon entrypoint must remain stoppable through its normal interrupt path.
    """
    monkeypatch.delitem(sys.modules, "app.dispatcher", raising=False)
    monkeypatch.setattr(sys, "argv", ["app.dispatcher"])
    runner = MagicMock(side_effect=KeyboardInterrupt())
    monkeypatch.setattr(subprocess, "run", runner)
    runpy.run_module("app.dispatcher", run_name="__main__")
    runner.assert_called_once_with([sys.executable, "-m", "app.dispatcher", "--attempt"], timeout=50, check=True)
    transport.assert_not_called()
