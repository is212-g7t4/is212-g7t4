"""SCRUM-48: Equipment Request Notification and Decision Alerts

User Story
----------
As an Event Coordinator and Technical Support Staff, I want to receive notifications about equipment requests and decisions, so that I can coordinate equipment arrangements efficiently.

Acceptance Criteria
-------------------
AC1: Given an Event Coordinator submits an equipment request, the system sends an in-app notification to Technical Support Staff with the event name, requested equipment list, and a link to review the request.
AC2: Given Technical Support Staff approves or rejects an Equipment Request, the system sends an in-app notification to the Event Coordinator assigned to that event with the event name, the equipment covered by the decision, and the decision status (Approved or Rejected).
AC3: Given a Technical Support Staff rejects the equipment request, the system sends an in-app notification to the Event Coordinator with the rejection message, event name, equipment request and link to the equipment request.

Real
----
- Purpose: check background notification delivery attempts and safe retries,
  keeping the frozen alert unchanged across transport failures.
- app.dispatcher: the owner outbox HTTP adapter, the single dispatch cycle
  (publish before marking published, retry on failure), the RabbitMQ publisher,
  the bounded child attempt, the back-off loop and both CLI entry points run
  for real.
- Assertions are on call order, the exact envelope published, retry arguments
  and exit codes.

Doubled
-------
- httpx (owner outbox): Stub (`transport`) - canned claim/published/retry
  replies; requests inspected.
- pika (RabbitMQ): Mock (`broker`) - asserts durable queue, confirms and
  persistent mandatory publish.
- subprocess.run, time.sleep: Stub - simulate child outcomes and skip waits.

Not proven
----------
- AC3 "rejection message" means a statement that the Equipment Request was rejected, not that the whole event was rejected and not the private rejectionReason/why. Existing reason-exclusion assertions are intentional; the private reason remains in the review workflow.
- Supporting transport, retry/backoff, authentication configuration, broker flags and CLI/process regressions have no explicit Jira AC for their exact contracts; Product Owner ownership/acceptance remains pending. The synthetic job contains an Approved decision, not a rejection or submission.
- An outbox is saved work awaiting publication; a lease is a temporary worker claim. Doubled HTTP, RabbitMQ and subprocess results prove local calls/order only, not actual broker durability, child termination, inbox delivery or exactly-once sending. No AC is claimed complete.
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


def test_outbox_api_calls_owner_with_internal_token_and_same_lease(transport, job):
    """Summary: Delivery calls to the owner keep the internal token and the claimed alert's lease.
    Double: Stub (owner replies), Mock (requests inspected)
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
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


def test_outbox_api_when_owner_refuses_raises_http_error(transport, job):
    """Summary: A refused finalisation is raised, not reported as delivered.
    Double: Stub (owner answers 409)
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
    """
    transport.return_value = httpx.Response(409, json={"message": "Lease lost."},
        request=httpx.Request("POST", "http://owner.invalid/published"))
    with pytest.raises(httpx.HTTPStatusError):
        dispatcher.OutboxAPI().published(job)


def test_dispatch_once_publishes_before_marking_published(job):
    """Summary: An alert is published before it is marked delivered, exactly as the owner froze it.
    Double: Mock (api and publisher call order)
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
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


@pytest.mark.parametrize("failure", ["publish", "published-response-lost", "missing-envelope"], ids=["publish_fails", "published_response_lost", "missing_envelope"])
@pytest.mark.parametrize("retry_fails", [False, True], ids=["retry-recorded", "retry-response-lost"])
def test_dispatch_once_when_delivery_fails_retries_same_alert_without_secrets(job, failure, retry_fails, caplog):
    """Summary: A failed delivery is retried with the same alert and lease, without leaking exception text.
    Double: Stub (publish or mark fails), Mock (retry arguments inspected)
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
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


def test_dispatch_after_lost_response_republishes_identical_alert(job):
    """Summary: When the outcome of a send is unknown, the retry sends the identical alert again.
    Double: Stub (claim returns the job twice), Mock (published payloads compared)
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
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


def test_dispatch_once_when_nothing_waiting_does_nothing():
    """Summary: An idle cycle sends and changes nothing.
    Double: Mock (no publish, retry or mark)
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
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


def test_publish_sends_durable_confirmed_message_and_closes(broker, job):
    """Summary: Alerts go to the durable notifications queue with broker confirmation, and the connection is closed.
    Double: Mock (pika channel calls inspected)
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
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


@pytest.mark.parametrize("stage", ["channel", "queue_declare", "confirm_delivery", "basic_publish"], ids=["channel", "queue_declare", "confirm_delivery", "basic_publish"])
@pytest.mark.parametrize("still_open", [True, False], ids=["owned-open-connection", "already-closed-connection"])
def test_publish_when_broker_fails_raises_and_closes_open_connection(broker, job, stage, still_open):
    """Summary: A broker failure at any step is raised and the connection it opened is closed.
    Double: Stub (one pika step raises), Mock (close inspected)
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
    """
    failure = RuntimeError("broker failed")
    target = broker.connection.channel if stage == "channel" else getattr(broker.channel, stage)
    target.side_effect = failure
    broker.connection.is_open = still_open
    with pytest.raises(RuntimeError, match="broker failed") as error:
        dispatcher.publish(job["envelope"])
    assert error.value is failure
    assert broker.connection.close.call_count == int(still_open)


@pytest.mark.parametrize("outcome,expected", [(None, 1), (3, 0), (2, None), ("timeout", None)], ids=["sent", "idle", "failed", "timed_out"])
def test_attempt_in_child_when_run_reports_sent_idle_failed_or_timed_out(monkeypatch, outcome, expected):
    """Summary: Each bounded attempt reports whether it sent, found nothing, failed or timed out.
    Double: Stub (subprocess.run returns or times out)
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
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


def test_worker_loop_when_outages_repeat_caps_backoff_then_resets(monkeypatch):
    """Summary: Repeated outages back off up to a cap, recovery resets the wait, and an interrupt stops the worker.
    Double: Stub (attempt outcomes, sleep), Mock (sleep durations inspected)
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
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
def test_one_shot_cli_runs_a_single_cycle_and_exits_with_result(monkeypatch, transport, broker, job, has_job):
    """Summary: The one-shot command runs one cycle and exits with a code saying whether it sent anything.
    Double: Stub (owner and broker replies)
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
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


def test_daemon_cli_enters_loop_and_stops_on_interrupt(monkeypatch, transport):
    """Summary: The default command runs the worker loop and stops cleanly on interrupt.
    Double: Stub (attempt raises KeyboardInterrupt)
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
    """
    monkeypatch.delitem(sys.modules, "app.dispatcher", raising=False)
    monkeypatch.setattr(sys, "argv", ["app.dispatcher"])
    runner = MagicMock(side_effect=KeyboardInterrupt())
    monkeypatch.setattr(subprocess, "run", runner)
    runpy.run_module("app.dispatcher", run_name="__main__")
    runner.assert_called_once_with([sys.executable, "-m", "app.dispatcher", "--attempt"], timeout=50, check=True)
    transport.assert_not_called()
