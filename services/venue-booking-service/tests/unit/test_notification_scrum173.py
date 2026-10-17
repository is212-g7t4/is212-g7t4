"""# SCRUM-173 — Receive Venue Disruption Notifications

As an Event Coordinator, I want to receive an in-app notification when a venue booking for an event assigned to me is affected, so that I know that alternative arrangements are required.
AC1: Given a rejection is ready for notification, then the notification is addressed to the coordinator assigned to that event when the notification is created.
AC2: The notification contains the event name, affected venue, closure start/end, rejection reason, and a link to the venue rejection.
AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.

## Layer and scope
# SCRUM-173 MF-02 / AC3: bounded production attempt supervisor.
Hermetic process-adapter seam, not real broker evidence. Whole claim/enrichment/
freeze/publish/cleanup attempt shares one budget below the owner's 60s lease.
Real missing/delayed broker-confirm fault injection is separately recorded.


## AC groups
AC1: current coordinator at preparation; recipient frozen across retries.
AC2: complete frozen content and structured rejection destination.
AC3: eventual delivery without duplicate inbox alerts.
Security, diagnostics, process adapters, fixtures and legacy compatibility are
explicit supporting/cross-ticket checks, not separate direct AC scenarios.
FIRST: unit I/O/clocks are mocked; real integration owns setup/finally teardown.
Historical tests are retrospective evidence, not a blanket test-first claim.


Consolidated story unit tests. Each class preserves an original module scope;
class-local fixtures never leak into another acceptance/supporting group.
"""

# test_notification_deadline.py — original fixture and scenario group
import subprocess
import sys
import runpy
from pathlib import Path
from unittest.mock import patch
import pytest
from app import dispatcher

class TestNotificationDeadline:
    """SCRUM-173 MF-02 / AC3: bounded production attempt supervisor. Hermetic process-adapter seam, not real broker evidence. Whole claim/enrichment/ freeze/publish/cleanup attempt shares one budget below the owner's 60s lease. Real missing/delayed broker-confirm fault injection is separately recorded."""

    def test_attempt_has_one_hard_budget_for_claim_preparation_publish_and_cleanup(self):
        """## AC3
        The supervisor applies one deadline to the entire child attempt, below the owner lease.
        """
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0)) as run:
            assert dispatcher.attempt() == 1
        args, kwargs = run.call_args
        assert args[0] == [sys.executable, '-m', 'app.dispatcher', '--attempt']
        assert kwargs['timeout'] == 50  # starts BEFORE claim, never restarts at publish
        assert kwargs['check'] is True


    def test_missing_confirm_timeout_is_not_reported_as_publication(self):
        """## AC3
        A timed-out attempt returns failure; an unknown broker outcome is never reported as published.
        """
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('worker', .2)):
            with pytest.raises(subprocess.TimeoutExpired):
                dispatcher.attempt(timeout=.2)


    def test_idle_worker_exit_and_real_errors_are_distinct(self):
        """## AC3 supporting process behavior
        Idle and failure child exits produce distinct supervisor outcomes.
        """
        with patch('subprocess.run', side_effect=subprocess.CalledProcessError(3, 'worker')):
            assert dispatcher.attempt() == 0
        with patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'worker')):
            with pytest.raises(subprocess.CalledProcessError):
                dispatcher.attempt()


    @pytest.mark.parametrize('claimed,exit_code', [(False, 3), (True, 0)])
    def test_one_shot_command_exits_after_exactly_one_claim(self, claimed, exit_code, monkeypatch):
        """## Supporting infrastructure
        The internal child command exits after a single attempt with the defined exit code.
        """
        for name in ('VENUE_AVAILABILITY_SERVICE_URL', 'EVENT_SERVICE_URL', 'VENUE_SERVICE_URL'):
            monkeypatch.setenv(name, 'http://owner.invalid')
        monkeypatch.setenv('INTERNAL_SERVICE_TOKEN', 'test-only')
        from unittest.mock import Mock
        response = Mock()
        response.json.side_effect = [
            {'jobs': [{'id': 'one', 'envelope': None, 'source': {}}]} if claimed else {'jobs': []},
            {},
        ]
        with patch('httpx.request', return_value=response), patch('sys.argv', ['dispatcher', '--attempt']):
            with pytest.raises(SystemExit) as exit:
                runpy.run_path(str(Path(dispatcher.__file__)), run_name='__main__')
        assert exit.value.code == exit_code


# test_notification_dispatch.py — original fixture and scenario group
from unittest.mock import Mock
from app.dispatcher import dispatch_once
DISPATCH_JOB = {
    "id": "10000000-0000-0000-0000-000000000001",
    "leaseToken": "20000000-0000-0000-0000-000000000001",
    "createdAt": "2026-10-17T00:00:00+00:00",
    "attempts": 1,
    "source": {
        "eventId": "30000000-0000-0000-0000-000000000001",
        "bookingId": "40000000-0000-0000-0000-000000000001",
        "venueId": "50000000-0000-0000-0000-000000000001",
        "closureId": "60000000-0000-0000-0000-000000000001",
        "startDateTime": "2099-01-01T08:00:00+08:00",
        "endDateTime": "2099-01-02T08:00:00+08:00",
        "reason": "Maintenance",
    },
    "envelope": None,
}

class TestNotificationDispatch:
    """SCRUM-173 AC1/AC2/AC3 — public dispatch-once orchestration seam. Hermetic HTTP/broker adapter doubles; actual messaging is tested separately."""

    def test_frozen_job_retries_without_assignment_lookup(self):
        """## AC1/AC3
        Retry of an already frozen job publishes the original envelope without looking up the newer assignment.
        """
        envelope = {"id": DISPATCH_JOB["id"], "recipientId": "original", "message": "historical"}
        api = Mock()
        api.claim.return_value = [DISPATCH_JOB | {"envelope": envelope}]
        publish = Mock()
        assert dispatch_once(api, publish) == 1
        publish.assert_called_once_with(envelope)
        api.context.assert_not_called()
        api.freeze.assert_not_called()
        api.published.assert_called_once_with(DISPATCH_JOB | {"envelope": envelope})


    def test_failed_publish_keeps_job_retryable(self):
        """## AC3
        Broker publication failure records a retry and never a successful publication.
        """
        api = Mock()
        api.claim.return_value = [DISPATCH_JOB | {"envelope": {"id": DISPATCH_JOB["id"]}}]
        assert dispatch_once(api, Mock(side_effect=RuntimeError("broker down"))) == 1
        api.retry.assert_called_once()
        api.published.assert_not_called()


# test_notification_pipeline.py — original fixture and scenario group
from copy import deepcopy
from pathlib import Path
import runpy
from unittest.mock import Mock, MagicMock, patch
import pytest
import httpx
from app import dispatcher
ID = "10000000-0000-0000-0000-000000000001"
SOURCE = dict(
    eventId=ID,
    bookingId=ID,
    venueId=ID,
    closureId=ID,
    startDateTime="2099-01-01T08:00:00+08:00",
    endDateTime="2099-01-02T08:00:00+08:00",
    reason="Maintenance",
)
JOB = dict(
    id=ID,
    leaseToken=ID,
    createdAt="2026-10-17T00:00:00+00:00",
    attempts=1,
    source=SOURCE,
    envelope=None,
)
def response(data):
    result = Mock()
    result.json.return_value = data
    return result
def handler(event_changes=None, venue_changes=None):
    def call(method, url, **kwargs):
        if url.endswith("/claim"):
            return response({"jobs": [deepcopy(JOB)]})
        if url.endswith("/notification-context"):
            return response(
                dict(id=ID, eventName="Conference", coordinatorId=ID)
                | (event_changes or {})
            )
        if url.endswith("/venues/" + ID):
            return response({"venue": dict(id=ID, name="Hall") | (venue_changes or {})})
        if url.endswith("/freeze"):
            return response({"envelope": kwargs["json"]["envelope"]})
        return response({})

    return call

class TestNotificationPipeline:
    """SCRUM-173 AC1/AC2/AC3 — dispatch entry point with HTTP/broker doubles. Exercises owning HTTP enrichment/freeze, confirmed publication and retry boundaries. Hermetic; real persistence, concurrency and redelivery are in the separate harness."""

    @pytest.fixture(autouse=True)
    def environment(self, monkeypatch):
        for key, value in dict(
            VENUE_AVAILABILITY_SERVICE_URL="http://availability.invalid",
            EVENT_SERVICE_URL="http://event.invalid",
            VENUE_SERVICE_URL="http://venue.invalid",
            INTERNAL_SERVICE_TOKEN="synthetic-token",
            RABBITMQ_URL="amqp://synthetic:synthetic@127.0.0.1:5672/%2F",
        ).items():
            monkeypatch.setenv(key, value)


    def test_complete_dispatch_uses_http_freeze_and_confirmed_persistent_publish(self):
        """## AC1/AC2/AC3
        Preparation reads the current coordinator and complete content via HTTP, freezes once, and confirms a persistent publication.
        """
        connection = MagicMock()
        channel = connection.channel.return_value
        with (
            patch("httpx.request", side_effect=handler()) as http,
            patch("pika.BlockingConnection", return_value=connection),
        ):
            assert dispatcher.dispatch_once(dispatcher.OutboxAPI(), dispatcher.publish) == 1
        published = channel.basic_publish.call_args.kwargs
        assert published["mandatory"] is True
        assert published["properties"].delivery_mode == 2
        assert published["properties"].message_id == ID
        assert b"Conference" in published["body"] and b"Maintenance" in published["body"]
        assert any(call.args[1].endswith("/published") for call in http.call_args_list)
        channel.confirm_delivery.assert_called_once()
        connection.close.assert_called_once()


    @pytest.mark.parametrize(
        "event,venue",
        [
            ({"id": "wrong"}, {}),
            ({}, {"id": "wrong"}),
            ({"coordinatorId": None}, {}),
            ({"eventName": ""}, {}),
            ({}, {"name": None}),
        ],
    )
    def test_bad_or_absent_assignment_is_not_dropped_or_frozen(self, event, venue):
        """## AC1/AC3
        Absent/invalid assignment keeps the intent retryable and unfrozen, without a fallback recipient.
        """
        with patch("httpx.request", side_effect=handler(event, venue)) as http:
            publish = Mock()
            assert dispatcher.dispatch_once(dispatcher.OutboxAPI(), publish) == 1
        publish.assert_not_called()
        paths = [call.args[1] for call in http.call_args_list]
        assert any(path.endswith("/retry") for path in paths)
        assert not any(
            path.endswith("/freeze") or path.endswith("/published") for path in paths
        )


    def test_unknown_publish_and_retry_write_failure_fall_back_to_lease_recovery(self):
        """## AC3
        Uncertain publish and failed retry bookkeeping leave the lease as the recovery path.
        """
        api = Mock()
        api.claim.return_value = [JOB | dict(envelope={"id": ID})]
        api.retry.side_effect = httpx.ConnectError("owner unavailable")
        assert (
            dispatcher.dispatch_once(api, Mock(side_effect=RuntimeError("unknown publish")))
            == 1
        )
        api.published.assert_not_called()


    def test_empty_claim_and_closed_publish_connection(self):
        """## AC3 supporting infrastructure
        An empty claim is idle; a closed publish connection is handled without pretending delivery.
        """
        api = Mock()
        api.claim.return_value = []
        assert dispatcher.dispatch_once(api, Mock()) == 0
        connection = MagicMock()
        connection.is_open = False
        with patch("pika.BlockingConnection", return_value=connection):
            dispatcher.publish(dict(id=ID, type="future.notification"))
        connection.close.assert_not_called()


    def test_dispatcher_command_backoff_then_success_then_idle_then_exit(self):
        """## AC3 supporting process recovery
        Worker failure backs off, then continues through success and idle before clean exit.
        """
        import subprocess
        responses = [
            subprocess.TimeoutExpired("worker", 50),
            subprocess.CompletedProcess([], 0),
            subprocess.CalledProcessError(3, "worker"),
        ]
        with (
            patch("subprocess.run", side_effect=responses),
            patch("time.sleep", side_effect=[None, KeyboardInterrupt()]) as sleep,
            patch("sys.argv", ["dispatcher"]),
        ):
            runpy.run_path(str(Path(dispatcher.__file__)), run_name="__main__")
        assert [call.args[0] for call in sleep.call_args_list] == [1, 1]
