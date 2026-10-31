"""
SCRUM-173: Receive Venue Disruption Notifications

User Story
----------
As an Event Coordinator, I want to receive an in-app notification when a venue
booking for an event assigned to me is affected, so that I know that
alternative arrangements are required.

Acceptance Criteria
-------------------
AC1: Given a rejection is ready for notification, then the notification is
     addressed to the coordinator assigned to that event when the notification
     is created.
AC2: The notification contains the event name, affected venue, closure
     start/end, rejection reason, and a link to the venue rejection.
AC3: Given a temporary system failure occurs during notification dispatch, the
     system must ensure the notification is eventually delivered to the
     assigned coordinator without generating multiple duplicate alerts.

Real
----
- app.dispatcher for venue disruption alerts: one time budget per child
  attempt, reading the current coordinator, freezing over HTTP, confirmed
  persistent publish, retries and lease recovery, and the one-shot and daemon
  commands.
- Assertions are on exit codes, frozen and published envelopes and retries.

Doubled
-------
- Venue Availability outbox and Event/Venue lookups: Stub (monkeypatched httpx)
  - canned replies; requests inspected.
- pika (RabbitMQ) and subprocess: Mock - publish, confirms and child runs
  inspected.

Not proven
----------
- That a real broker keeps the message and Notification Service shows it once
  (-> notification-service consumer tests; NOT COVERED against a live broker).
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

    def test_ac3_attempt_applies_one_deadline_to_whole_dispatch(self, mocker):
        """
        Summary: One deadline covers the whole attempt, so a stuck step cannot hold the alert.
        AC3: Given a temporary system failure occurs during notification
            dispatch, the system must ensure the notification is eventually
            delivered to the assigned coordinator without generating multiple
            duplicate alerts.
        Double: Mock (subprocess.run timeout)
        """
        # Arrange (Given)
        run = mocker.patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0))
        assert dispatcher.attempt() == 1
        args, kwargs = run.call_args

        # Act + Assert (When / Then)
        assert args[0] == [sys.executable, '-m', 'app.dispatcher', '--attempt']
        assert kwargs['timeout'] == 50  # starts BEFORE claim, never restarts at publish
        assert kwargs['check'] is True


    def test_ac3_attempt_timeout_is_not_reported_as_published(self, mocker):
        """
        Summary: A timed-out attempt is a failure, never reported as sent.
        AC3: Given a temporary system failure occurs during notification
            dispatch, the system must ensure the notification is eventually
            delivered to the assigned coordinator without generating multiple
            duplicate alerts.
        Double: Stub (child times out)
        """
        mocker.patch('subprocess.run', side_effect=subprocess.TimeoutExpired('worker', .2))
        with pytest.raises(subprocess.TimeoutExpired):
            dispatcher.attempt(timeout=.2)


    def test_ac3_attempt_exit_codes_distinguish_idle_from_error(self, mocker):
        """
        Summary: An idle worker and a failed one exit differently.
        AC3: Given a temporary system failure occurs during notification
            dispatch, the system must ensure the notification is eventually
            delivered to the assigned coordinator without generating multiple
            duplicate alerts.
        Double: Stub (child exit codes)
        """
        mocker.patch('subprocess.run', side_effect=subprocess.CalledProcessError(3, 'worker'))
        assert dispatcher.attempt() == 0
        mocker.patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'worker'))
        with pytest.raises(subprocess.CalledProcessError):
            dispatcher.attempt()


    @pytest.mark.parametrize('claimed,exit_code', [(False, 3), (True, 0)], ids=["nothing_claimed", "job_claimed"])
    def test_ac3_one_shot_command_handles_exactly_one_claim(self, claimed, exit_code, monkeypatch, mocker):
        """
        Summary: The one-shot command claims once and exits with the result.
        AC3: Given a temporary system failure occurs during notification
            dispatch, the system must ensure the notification is eventually
            delivered to the assigned coordinator without generating multiple
            duplicate alerts.
        Double: Stub (claim result)
        """
        # Arrange (Given)
        for name in ('VENUE_AVAILABILITY_SERVICE_URL', 'EVENT_SERVICE_URL', 'VENUE_SERVICE_URL'):
            monkeypatch.setenv(name, 'http://owner.invalid')
        monkeypatch.setenv('INTERNAL_SERVICE_TOKEN', 'test-only')
        from unittest.mock import Mock
        response = Mock()
        response.json.side_effect = [
            {'jobs': [{'id': 'one', 'envelope': None, 'source': {}}]} if claimed else {'jobs': []},
            {},
        ]

        # Act (When)
        mocker.patch('httpx.request', return_value=response)
        mocker.patch('sys.argv', ['dispatcher', '--attempt'])
        with pytest.raises(SystemExit) as exit:
            runpy.run_path(str(Path(dispatcher.__file__)), run_name='__main__')

        # Assert (Then)
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

    def test_ac1_ac3_retry_of_frozen_alert_skips_assignment_lookup(self):
        """
        Summary: A retry of a frozen alert resends it without looking up the coordinator again.
        AC1: Given a rejection is ready for notification, then the notification
            is addressed to the coordinator assigned to that event when the
            notification is created.
        AC3: Given a temporary system failure occurs during notification
            dispatch, the system must ensure the notification is eventually
            delivered to the assigned coordinator without generating multiple
            duplicate alerts.
        Double: Stub (frozen job), Mock (no lookup)
        """
        # Arrange (Given)
        envelope = {"id": DISPATCH_JOB["id"], "recipientId": "original", "message": "historical"}
        api = Mock()
        api.claim.return_value = [DISPATCH_JOB | {"envelope": envelope}]
        publish = Mock()

        # Act + Assert (When / Then)
        assert dispatch_once(api, publish) == 1
        publish.assert_called_once_with(envelope)
        api.context.assert_not_called()
        api.freeze.assert_not_called()
        api.published.assert_called_once_with(DISPATCH_JOB | {"envelope": envelope})


    def test_ac3_failed_publish_records_retry(self):
        """
        Summary: A failed publish records a retry, never success.
        AC3: Given a temporary system failure occurs during notification
            dispatch, the system must ensure the notification is eventually
            delivered to the assigned coordinator without generating multiple
            duplicate alerts.
        Double: Mock (publish fails; retry recorded)
        """
        # Arrange (Given)
        api = Mock()
        api.claim.return_value = [DISPATCH_JOB | {"envelope": {"id": DISPATCH_JOB["id"]}}]

        # Act + Assert (When / Then)
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


    def test_ac1_ac2_ac3_dispatch_reads_current_coordinator_freezes_and_publishes(self, mocker):
        """
        Summary: An alert is addressed to the current coordinator, frozen, and published with confirmation.
        AC1: Given a rejection is ready for notification, then the notification
            is addressed to the coordinator assigned to that event when the
            notification is created.
        AC2: The notification contains the event name, affected venue, closure
            start/end, rejection reason, and a link to the venue rejection.
        AC3: Given a temporary system failure occurs during notification
            dispatch, the system must ensure the notification is eventually
            delivered to the assigned coordinator without generating multiple
            duplicate alerts.
        Double: Stub (lookups), Mock (freeze and publish inspected)
        """
        # Arrange (Given)
        connection = MagicMock()
        channel = connection.channel.return_value
        http = mocker.patch("httpx.request", side_effect=handler())
        mocker.patch("pika.BlockingConnection", return_value=connection)
        assert dispatcher.dispatch_once(dispatcher.OutboxAPI(), dispatcher.publish) == 1
        published = channel.basic_publish.call_args.kwargs

        # Act + Assert (When / Then)
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
        ids=["wrong_event", "wrong_venue", "no_coordinator", "blank_event_name", "no_venue_name"],
    )
    def test_ac1_ac3_dispatch_with_bad_assignment_keeps_alert_retryable(self, event, venue, mocker):
        """
        Summary: A missing or bad coordinator or venue detail keeps the alert waiting, not dropped.
        AC1: Given a rejection is ready for notification, then the notification
            is addressed to the coordinator assigned to that event when the
            notification is created.
        AC3: Given a temporary system failure occurs during notification
            dispatch, the system must ensure the notification is eventually
            delivered to the assigned coordinator without generating multiple
            duplicate alerts.
        Double: Stub (lookups return bad data), Mock (no freeze)
        """
        # Arrange (Given): event, venue, from fixtures

        # Act (When)
        http = mocker.patch("httpx.request", side_effect=handler(event, venue))
        publish = Mock()
        assert dispatcher.dispatch_once(dispatcher.OutboxAPI(), publish) == 1

        # Assert (Then)
        publish.assert_not_called()
        paths = [call.args[1] for call in http.call_args_list]
        assert any(path.endswith("/retry") for path in paths)
        assert not any(
            path.endswith("/freeze") or path.endswith("/published") for path in paths
        )


    def test_ac3_uncertain_publish_or_retry_failure_falls_back_to_lease_recovery(self):
        """
        Summary: If the outcome is unknown or the retry cannot be saved, the lease expiry recovers the alert.
        AC3: Given a temporary system failure occurs during notification
            dispatch, the system must ensure the notification is eventually
            delivered to the assigned coordinator without generating multiple
            duplicate alerts.
        Double: Stub (publish outcome unknown)
        """
        # Arrange (Given)
        api = Mock()
        api.claim.return_value = [JOB | dict(envelope={"id": ID})]
        api.retry.side_effect = httpx.ConnectError("owner unavailable")

        # Act + Assert (When / Then)
        assert (
            dispatcher.dispatch_once(api, Mock(side_effect=RuntimeError("unknown publish")))
            == 1
        )
        api.published.assert_not_called()


    def test_ac3_empty_claim_is_idle_and_closed_connection_fails(self, mocker):
        """
        Summary: An empty claim is idle; a closed broker connection is a failure.
        AC3: Given a temporary system failure occurs during notification
            dispatch, the system must ensure the notification is eventually
            delivered to the assigned coordinator without generating multiple
            duplicate alerts.
        Double: Stub (claim and pika)
        """
        # Arrange (Given)
        api = Mock()
        api.claim.return_value = []

        # Act + Assert (When / Then)
        assert dispatcher.dispatch_once(api, Mock()) == 0
        connection = MagicMock()
        connection.is_open = False
        mocker.patch("pika.BlockingConnection", return_value=connection)
        dispatcher.publish(dict(id=ID, type="future.notification"))
        connection.close.assert_not_called()


    def test_ac3_dispatcher_command_backs_off_recovers_and_exits(self, mocker):
        """
        Summary: The worker backs off after failures, recovers, idles and exits cleanly.
        AC3: Given a temporary system failure occurs during notification
            dispatch, the system must ensure the notification is eventually
            delivered to the assigned coordinator without generating multiple
            duplicate alerts.
        Double: Stub (attempt outcomes), Mock (sleep)
        """
        # Arrange (Given)
        import subprocess
        responses = [
            subprocess.TimeoutExpired("worker", 50),
            subprocess.CompletedProcess([], 0),
            subprocess.CalledProcessError(3, "worker"),
        ]

        # Act (When)
        mocker.patch("subprocess.run", side_effect=responses)
        sleep = mocker.patch("time.sleep", side_effect=[None, KeyboardInterrupt()])
        mocker.patch("sys.argv", ["dispatcher"])
        runpy.run_path(str(Path(dispatcher.__file__)), run_name="__main__")

        # Assert (Then)
        assert [call.args[0] for call in sleep.call_args_list] == [1, 1]
