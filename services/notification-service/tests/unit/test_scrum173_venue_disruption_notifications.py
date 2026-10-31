"""SCRUM-173: Receive Venue Disruption Notifications

User Story
----------
As an Event Coordinator, I want to receive an in-app notification when a venue booking for an event assigned to me is affected, so that I know that alternative arrangements are required.

Acceptance Criteria
-------------------
AC1: Given a rejection is ready for notification, then the notification is addressed to the coordinator assigned to that event when the notification is created.
AC2: The notification contains the event name, affected venue, closure start/end, rejection reason, and a link to the venue rejection.
AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.

Real
----
- app.consumer: envelope validation (strict JSON, version, type, message,
  destination, the venue-disruption details contract), process() with ACK only
  after commit, quarantine of malformed bodies, and the consumer command's
  reconnect/back-off loop; app.diagnostics list/replay; the inbox routes (list
  with cursor pagination and unread filter, mark read, unread count) scoped to
  the signed-in user.
- Assertions are on SQL sent, ACK and its order, quarantine contents, retry
  delays and HTTP responses.

Doubled
-------
- psycopg2.connect: Stub - MagicMock connection and cursor (or raising
  OperationalError / ProgrammingError); SQL inspected.
- Broker channel and pika connection: Mock - ACK, close and consume calls
  inspected.
- time.sleep: Stub - skips back-off waits; delays recorded.
- Inbox storage functions: Stub (`setup` fixture) in route tests.

Not proven
----------
- AC1: This consumer receives an already-addressed envelope; assignment-at-creation belongs to Venue Booking, not these inbox doubles.
- AC2: Disruption detail/destination validation and quarantine are checked; actual browser display/navigation is outside this module.
- AC3: Local commit/ACK, failure propagation, recovery/backoff and deduplication SQL are checked. Real broker redelivery and disruption-specific PostgreSQL persistence are UNTESTED here.
- Real PostgreSQL evidence exists only in the maintained SCRUM-45/47/49/166 integration modules; neither their success nor parser acceptance proves all notification types or producer fan-out.
- Broker delivery, other service code and browser navigation are NOT COVERED ANYWHERE in this module.
- Pagination, read/unread controls, legacy rows, quarantine diagnostics, process wiring and future-type compatibility are useful supporting contracts without their own AC. They are preserved and flagged for a Product Owner decision, not relabelled as new acceptance criteria.
- No exact SCRUM-173 AC is claimed by these supporting cases: test_connection_parameters_build_from_url_without_network, test_diagnostics_command_lists_and_replays_quarantined_messages, test_inbox_lists_signed_in_users_notifications_not_query_recipient, test_inbox_pages_filters_unread_and_marks_read, test_inbox_when_storage_down_returns_503_and_reads_legacy_rows, test_inbox_with_bad_page_or_filter_returns_400, test_inbox_without_signed_in_user_returns_401, test_mark_read_with_bad_body_returns_400.
"""

# test_consumer_recovery.py — original fixture and scenario group
import json
import runpy
from pathlib import Path
from app import consumer, diagnostics
from unittest.mock import MagicMock, Mock, patch
import pytest
from app.consumer import process, run, connect
from app.diagnostics import replay, main
from tests.unit.factories import bearer
# Synthetic fixtures local to this story; no cross-module test package imports.
from datetime import datetime, timezone

USER = "10000000-0000-0000-0000-000000000001"
ID = "20000000-0000-0000-0000-000000000001"
EVENT = "30000000-0000-0000-0000-000000000001"
BOOKING = "40000000-0000-0000-0000-000000000001"


def envelope():
    return dict(
        version=1,
        id=ID,
        recipientId=USER,
        type="venue.closure-rejection",
        message="Historical closure notice",
        createdAt="2026-10-17T00:00:00+00:00",
        destination=dict(kind="event-venue-request", eventId=EVENT, bookingId=BOOKING),
        details=dict(
            closureId="50000000-0000-0000-0000-000000000001",
            bookingId=BOOKING, eventId=EVENT,
            venueId="60000000-0000-0000-0000-000000000001",
            eventName="Historical event", venueName="Historical venue",
            startDateTime="2026-10-18T08:00:00+08:00",
            endDateTime="2026-10-19T08:00:00+08:00", reason="Maintenance",
        ),
    )


def row(**changes):
    return dict(
        notification_id=ID,
        event_id=EVENT,
        recipient_id=USER,
        type="venue.closure-rejection",
        payload=envelope(),
        created_at=datetime(2026, 10, 17, tzinfo=timezone.utc),
        read_at=None,
        **changes,
    )


class TestConsumerRecovery:
    """SCRUM-173 AC3 — consumer process/startup and commit/ack seam. Hermetic broker and database adapters, including outage backoff and CLI diagnostics. Real restart/ack redelivery is in the disposable harness, not inferred here."""

    def test_process_alert_acks_only_after_database_commit(self, mocker):
        """Summary: A notification is acknowledged to the broker only after it is safely stored.
AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.
Double: Stub (connection), Mock (commit then ACK order)
"""
        # Arrange (Given)
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        channel = Mock()
        method = Mock(delivery_tag=9)
        order = []
        connection.__exit__.side_effect = lambda *args: order.append("commit")
        channel.basic_ack.side_effect = lambda **kwargs: order.append("ack")

        # Act (When)
        mocker.patch("psycopg2.connect", return_value=connection)
        process("synthetic", channel, method, json.dumps(envelope()).encode())

        # Assert (Then)
        connection.__exit__.assert_called_once()
        channel.basic_ack.assert_called_once_with(delivery_tag=9)
        connection.close.assert_called_once()
        assert order == ["commit", "ack"]


    def test_process_alert_when_commit_fails_leaves_message_for_redelivery(self, mocker):
        """Summary: If storing fails, the message is left on the queue to be delivered later.
AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.
Double: Stub (commit raises), Mock (no ACK)
"""
        # Arrange (Given)
        connection = MagicMock()
        connection.__exit__.side_effect = RuntimeError("commit failed")
        channel = Mock()
        method = Mock(delivery_tag=9)

        # Act (When)
        mocker.patch("psycopg2.connect", return_value=connection)
        with pytest.raises(RuntimeError):
            process("synthetic", channel, method, json.dumps(envelope()).encode())

        # Assert (Then)
        channel.basic_ack.assert_not_called()
        connection.close.assert_called_once()


    def test_process_malformed_alert_quarantines_then_acks(self, mocker):
        # Alias: test_malformed_saved_in_real_quarantine_adapter and
        # test_delivery::test_malformed_is_persisted_before_ack (consolidated).
        """Summary: A malformed message is stored aside first and only then acknowledged.
AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.
Double: Stub (connection), Mock (commit then ACK order)
"""
        # Arrange (Given)
        connection = MagicMock()
        channel = Mock()
        events = []
        connection.__exit__.side_effect = lambda *_: events.append("commit")
        channel.basic_ack.side_effect = lambda **_: events.append("ack")

        # Act (When)
        mocker.patch("psycopg2.connect", return_value=connection)
        process("synthetic", channel, Mock(delivery_tag=7), b"broken")

        # Assert (Then)
        connection.__exit__.assert_called_once()
        connection.close.assert_called_once()
        assert events == ["commit", "ack"]
        channel.basic_ack.assert_called_once_with(delivery_tag=7)


    def test_connection_parameters_build_from_url_without_network(self, mocker):
        """Summary: The broker connection settings can be built from the configured URL without connecting.
Double: Mock (Pika connection constructor captures parameters; real URL parsing and timeout configuration).
"""
        # Act (When)
        connection = mocker.patch("app.consumer.pika.BlockingConnection")
        result = connect("amqp://synthetic:synthetic@127.0.0.1:5672/%2F")

        # Assert (Then)
        assert result is connection.return_value
        params = connection.call_args.args[0]
        assert (params.heartbeat, params.blocked_connection_timeout, params.socket_timeout, params.stack_timeout, params.connection_attempts) == (30, 10, 5, 15, 1)


    def test_consumer_command_after_outage_reconnects_then_stops_cleanly(self, monkeypatch, mocker):
        """Summary: After a broker or database outage the consumer reconnects, and it stops cleanly on interrupt.
AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.
Double: Stub (connect fails then succeeds), Mock (sleep)
"""
        # Arrange (Given)
        monkeypatch.setenv("RABBITMQ_URL", "amqp://synthetic:synthetic@127.0.0.1:5672/%2F")
        monkeypatch.setenv("DATABASE_URL", "synthetic")
        connection = MagicMock()
        channel = connection.channel.return_value

        def consume():
            callback = channel.basic_consume.call_args.kwargs["on_message_callback"]
            callback(channel, Mock(delivery_tag=1), None, b"bad")
            raise KeyboardInterrupt()

        channel.start_consuming.side_effect = consume

        # Act (When)
        mocker.patch(
                "pika.BlockingConnection", side_effect=[RuntimeError("outage"), connection]
            )
        sleep = mocker.patch("time.sleep")
        mocker.patch("app.store.quarantine")
        runpy.run_path(str(Path(consumer.__file__)), run_name="__main__")

        # Assert (Then)
        sleep.assert_called_once_with(1)
        connection.close.assert_called_once()


    def test_consumer_command_when_connection_closes_reconnects(self, monkeypatch, mocker):
        """Summary: A closed broker connection is treated as a reason to reconnect, not to stop.
AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.
Double: Stub (pika raises ConnectionClosed), Mock (sleep)
"""
        # Arrange (Given)
        monkeypatch.setenv("RABBITMQ_URL", "amqp://synthetic:synthetic@127.0.0.1:5672/%2F")
        connection = MagicMock()
        connection.is_open = False

        # Act (When)
        mocker.patch("app.consumer.connect", side_effect=[connection, KeyboardInterrupt()])
        sleep = mocker.patch("time.sleep")
        run()

        # Assert (Then)
        sleep.assert_called_once_with(1)
        connection.close.assert_not_called()


    def test_diagnostics_command_lists_and_replays_quarantined_messages(self, monkeypatch, capsys, mocker):
        """Summary: Quarantined messages can be listed and replayed into delivery.
Double: Stub (storage), Mock (output captured)
"""
        # Arrange (Given)
        monkeypatch.setenv("DATABASE_URL", "synthetic")
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [{"failure_id": ID, "error": "unsupported version"}]
        cursor.fetchone.return_value = {"body": memoryview(json.dumps(envelope()).encode())}

        # Act (When)
        mocker.patch("psycopg2.connect", return_value=connection)
        with patch("sys.argv", ["diagnostics", "list"]):
            runpy.run_path(str(Path(diagnostics.__file__)), run_name="__main__")
        assert ID in capsys.readouterr().out
        with patch("sys.argv", ["diagnostics", "replay", ID]):
            main()

        # Assert (Then)
        assert connection.close.call_count == 4
        cursor.fetchone.return_value = None
        mocker.patch("psycopg2.connect", return_value=connection)
        with pytest.raises(ValueError, match="not found"):
            replay("synthetic", ID)


    def test_consumer_command_when_storage_keeps_failing_backs_off_longer(self, monkeypatch, mocker):
        """Summary: Repeated storage failures wait longer before each retry.
AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.
Double: Stub (storage keeps failing), Mock (sleep durations)
"""
        # Arrange (Given)
        monkeypatch.setenv("RABBITMQ_URL", "amqp://synthetic:synthetic@127.0.0.1:5672/%2F")
        connection = MagicMock()
        connection.channel.return_value.start_consuming.side_effect = [
            RuntimeError("storage down"),
            RuntimeError("still down"),
            KeyboardInterrupt(),
        ]

        # Act (When)
        mocker.patch("app.consumer.connect", return_value=connection)
        sleep = mocker.patch("time.sleep")
        run()

        # Assert (Then)
        assert [call.args[0] for call in sleep.call_args_list] == [1, 2]


    def test_consumer_command_when_close_fails_keeps_recovering(self, monkeypatch, mocker):
        """Summary: An error while closing a broken connection does not stop recovery.
AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.
Double: Stub (close raises), Mock (sleep)
"""
        # Arrange (Given)
        monkeypatch.setenv("RABBITMQ_URL", "amqp://synthetic:synthetic@127.0.0.1:5672/%2F")
        connection = MagicMock()
        connection.channel.return_value.start_consuming.side_effect = [
            RuntimeError("connection failed"),
            KeyboardInterrupt(),
        ]
        connection.close.side_effect = [RuntimeError("close failed"), None]

        # Act (When)
        connect_again = mocker.patch("app.consumer.connect", return_value=connection)
        mocker.patch("time.sleep")
        run()

        # Assert (Then)
        assert connect_again.call_count == 2


# test_delivery.py — original fixture and scenario group
from unittest.mock import Mock, patch
from app.consumer import process

class TestDelivery:
    """SCRUM-173 AC3 — consumer acknowledgement boundary (hermetic). Commit failure must leave delivery unacknowledged; malformed messages are retained."""

    def test_process_alert_when_storage_fails_does_not_ack(self, mocker):
        """Summary: A storage failure leaves the message unacknowledged so it is redelivered.
AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.
Double: Stub (cursor raises), Mock (no ACK)
"""
        # Arrange (Given)
        channel = Mock()
        method = Mock(delivery_tag=7)

        # Act (When)
        mocker.patch("app.consumer.store.quarantine", side_effect=RuntimeError("db down"))
        with pytest.raises(RuntimeError):
            process("synthetic", channel, method, b"broken")

        # Assert (Then)
        channel.basic_ack.assert_not_called()


    @pytest.mark.parametrize(
        "changes",
        [
            {"version": True},
            {"version": 2},
            {"type": ""},
            {"type": "x" * 51},
            {"message": ""},
            {"message": None},
            {"createdAt": "2026-10-17T00:00:00"},
            {"destination": {"kind": "https://untrusted.invalid"}},
            {"destination": []},
            {"id": None},
            {"recipientId": "broken"},
        ],
        ids=["bool_version", "wrong_version", "empty_type", "type_too_long", "empty_message", "null_message", "naive_time", "untrusted_link", "link_not_object", "missing_id", "bad_recipient"],
    )
    def test_process_alert_with_malformed_envelope_quarantines_it(self, changes, mocker):
        """Summary: An envelope with a bad version, type, message, time, link or recipient is kept aside, not delivered.
AC2: The notification contains the event name, affected venue, closure start/end, rejection reason, and a link to the venue rejection.
Double: Stub (connection), Mock (channel ACK)
"""
        import json

        channel = Mock()
        method = Mock(delivery_tag=3)
        deliver = mocker.patch("app.consumer.store.deliver")
        quarantine = mocker.patch("app.consumer.store.quarantine")
        process("synthetic", channel, method, json.dumps(envelope() | changes).encode())
        deliver.assert_not_called()
        quarantine.assert_called_once()
        channel.basic_ack.assert_called_once_with(delivery_tag=3)


    def test_process_alert_with_deeply_nested_json_quarantines_it(self, mocker):
        """Summary: A pathologically nested message is quarantined rather than crashing the consumer.
AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.
Double: Stub (connection), Mock (channel ACK)
"""
        # Arrange (Given)
        channel = Mock()
        method = Mock(delivery_tag=4)
        depth = 100000
        body = b"[" * depth + b"0" + b"]" * depth

        # Act (When)
        quarantine = mocker.patch("app.consumer.store.quarantine")
        process("synthetic", channel, method, body)

        # Assert (Then)
        quarantine.assert_called_once()
        channel.basic_ack.assert_called_once_with(delivery_tag=4)


# test_inbox.py — original fixture and scenario group
from unittest.mock import patch
from app import create_app
INBOX_USER = "10000000-0000-0000-0000-000000000001"

class TestInbox:
    """SCRUM-173 AC1/AC3 — hermetic inbox API ownership seam. No real persistence here; SQL/broker integration is separately exercised."""

    def test_inbox_lists_signed_in_users_notifications_not_query_recipient(self, monkeypatch, mocker):
        """Summary: The inbox shows the signed-in user's own notifications; a recipient in the query is ignored.
Double: Mock (storage records which user is asked about)
"""
        # Arrange (Given)
        monkeypatch.setenv("DATABASE_URL", "synthetic-not-a-real-dsn")
        client = create_app().test_client()

        # Act (When)
        listing = mocker.patch(
            "app.store.list_inbox", return_value={"notifications": [], "nextCursor": None}
        )
        response = client.get(
            "/notifications?recipientId=someone-else",
            headers=bearer(INBOX_USER, "Event Coordinator"),
        )

        # Assert (Then)
        assert response.status_code == 200
        assert listing.call_args.args[1] == INBOX_USER


# test_inbox_behavior.py — original fixture and scenario group
from unittest.mock import MagicMock, patch
import psycopg2
HEADERS = bearer(USER, "Event Coordinator")

class TestInboxBehavior:
    """SCRUM-173 AC1/AC3 — inbox HTTP seam (hermetic database driver). Own listing, keyset pagination, unread filtering, read/unread, CORS and denials. Actual SQL ownership/filter/order/dedup is verified separately in PostgreSQL."""

    @pytest.fixture
    def setup(self, monkeypatch, mocker):
        monkeypatch.setenv("DATABASE_URL", "synthetic")
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [row()]
        cursor.fetchone.return_value = row()
        mocker.patch("psycopg2.connect", return_value=connection)
        yield create_app().test_client(), cursor


    def test_inbox_pages_filters_unread_and_marks_read(self, setup):
        """Summary: The inbox pages through notifications, filters unread ones and marks them read or unread.
Double: Stub (`setup` storage)
"""
        # Arrange (Given)
        client, cursor = setup
        cursor.fetchall.return_value = [row(), row()]

        # Act (When)
        first = client.get("/notifications?limit=1", headers=HEADERS)

        # Assert (Then)
        assert (
            first.status_code == 200
            and len(first.json["notifications"]) == 1
            and first.json["nextCursor"]
        )
        cursor.fetchall.return_value = []
        second = client.get(
            "/notifications?unread=true&cursor=" + first.json["nextCursor"], headers=HEADERS
        )
        assert second.json == dict(notifications=[], nextCursor=None)
        sql, params = cursor.execute.call_args.args
        assert "recipient_id=%s" in sql and "read_at IS NULL" in sql
        assert "(created_at,notification_id)<(%s,%s)" in sql
        assert params == [USER, datetime(2026, 10, 17, tzinfo=timezone.utc), ID, 21]
        for read in (True, False):
            result = client.patch(
                "/notifications/" + ID, json={"read": read}, headers=HEADERS
            )
            assert result.status_code == 200 and result.json["notification"]["id"] == ID
            sql, params = cursor.execute.call_args.args
            assert "WHERE recipient_id=%s AND notification_id=%s" in sql
            assert params == (read, USER, ID)
        cursor.fetchone.return_value = None
        assert (
            client.patch(
                "/notifications/" + ID, json={"read": True}, headers=HEADERS
            ).status_code
            == 404
        )
        cursor.fetchone.return_value = {"count": 5}
        assert client.get("/notifications/unread-count", headers=HEADERS).json == {
            "unreadCount": 5
        }


    @pytest.mark.parametrize(
        "query",
        [
            "limit=0",
            "limit=101",
            "limit=x",
            "unread=yes",
            "cursor=broken",
            "cursor=WyJub3QtYS10aW1lIiwiaWQiXQ==",
            "cursor=WyIyMDI2LTEwLTE3VDAwOjAwOjAwIiwiMjAwMDAwMDAtMDAwMC0wMDAwLTAwMDAtMDAwMDAwMDAwMDAxIl0=",
        ],
        ids=["limit_zero", "limit_above_100", "limit_text", "unread_text", "cursor_broken", "cursor_bad_time", "cursor_bad_id"],
    )
    def test_inbox_with_bad_page_or_filter_returns_400(self, setup, query):
        """Summary: A bad page size, unread filter or cursor is refused.
Double: Stub (`setup` storage)
"""
        # Arrange (Given)
        client, _ = setup

        # Act + Assert (When / Then)
        assert client.get("/notifications?" + query, headers=HEADERS).status_code == 400


    @pytest.mark.parametrize("body", [None, [], {}, {"read": "true"}, {"read": 1}], ids=["no_body", "list_body", "empty_object", "read_as_text", "read_as_number"])
    def test_mark_read_with_bad_body_returns_400(self, setup, body):
        """Summary: Marking read needs a true or false value.
Double: Stub (`setup` storage)
"""
        # Arrange (Given)
        client, _ = setup

        # Act + Assert (When / Then)
        assert (
            client.patch("/notifications/" + ID, json=body, headers=HEADERS).status_code
            == 400
        )


    @pytest.mark.parametrize(
        "headers",
        [{}, {"X-Dev-User-Id": USER, "X-Dev-Role": "Event Coordinator"}, {"X-Internal-Token": "internal-test-token"}],
        ids=["no_headers", "dev_headers", "internal_token"],
    )
    def test_inbox_without_signed_in_user_returns_401(self, setup, headers, monkeypatch):
        """Summary: The inbox needs a signed-in user; old developer headers or the internal token do not count.
Double: None
"""
        # Arrange (Given)
        monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "internal-test-token")
        client, _ = setup

        # Act + Assert (When / Then)
        assert client.get("/notifications", headers=headers).status_code == 401


    def test_inbox_when_storage_down_returns_503_and_reads_legacy_rows(self, setup):
        """Summary: A storage outage is reported as retryable, and older rows with missing fields still display.
Double: Stub (storage raises, then returns a legacy row)
"""
        # Arrange (Given)
        client, cursor = setup
        legacy = row()
        legacy.update(
            event_id=None,
            created_at=None,
            read_at=datetime(2026, 10, 17, tzinfo=timezone.utc),
        )
        cursor.fetchall.return_value = [legacy]

        # Act (When)
        response = client.get("/notifications", headers=HEADERS)

        # Assert (Then)
        assert response.json["notifications"][0]["eventId"] is None
        assert response.json["notifications"][0]["createdAt"] is None
        cursor.execute.side_effect = psycopg2.OperationalError("synthetic outage")
        assert client.get("/notifications", headers=HEADERS).status_code == 503

    # --- Supporting/supplementary design checks ----------------------------------
    # No Jira acceptance criterion covers these. They check design decisions the
    # stories rely on (health check, CORS, configuration and failure handling).

    def test_inbox_when_unconfigured_returns_503_and_health_still_answers(self, setup):
        """Summary: An unconfigured inbox reports itself unavailable while health and browser access still work.
Double: Stub (`setup` storage)
Supporting design check: an unconfigured Notification Service answers 503
"""
        client, _ = setup
        assert client.get("/health").json == {"status": "ok"}
        assert (
            client.options(
                "/notifications", headers={"Origin": "http://127.0.0.1:5174"}
            ).headers["Access-Control-Allow-Origin"]
            == "http://127.0.0.1:5174"
        )
        assert (
            "Access-Control-Allow-Origin"
            not in client.get(
                "/health", headers={"Origin": "https://untrusted.invalid"}
            ).headers
        )
        client.application.config.update(DATABASE_URL=None)
        assert client.get("/notifications", headers=HEADERS).status_code == 503


# test_review_validation.py — original fixture and scenario group
from app import store

class TestReviewValidation:
    """SCRUM-173 review R1/R2: poison retention and known-type contract at consumer seam."""

    @pytest.mark.parametrize("extra", [float("nan"), float("inf"), float("-inf"), "nul\x00text", "\ud800", {"\udfff": "value"}, {"nul\x00key": ["value"]}, [0, {"nested": "\udfff"}]], ids=["nan", "infinity", "negative_infinity", "nul_in_text", "lone_surrogate", "surrogate_key", "nul_in_key", "nested_surrogate"])
    def test_process_alert_with_unstorable_extra_values_quarantines_it(self, extra, mocker):
        """Summary: Values the database cannot store in extra fields send the message to quarantine instead of failing.
AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.
Double: Stub (connection), Mock (channel ACK)
"""
        # Arrange (Given)
        body = json.dumps(envelope() | {"future": extra}).encode()
        ch = Mock()

        # Act (When)
        deliver = mocker.patch("app.consumer.store.deliver")
        quarantine = mocker.patch("app.consumer.store.quarantine")
        process("synthetic", ch, Mock(delivery_tag=1), body)

        # Assert (Then)
        deliver.assert_not_called()
        assert quarantine.call_args.args[1] == body
        ch.basic_ack.assert_called_once_with(delivery_tag=1)


    @pytest.mark.parametrize("body", [b'{"extra":NaN}', b'{"extra":1e999}', b'\xff'], ids=["nan_literal", "overflowing_number", "invalid_bytes"])
    def test_process_alert_with_non_standard_json_quarantines_it(self, body, mocker):
        """Summary: Non-standard JSON (NaN, overflowing numbers, bad bytes) is quarantined.
AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.
Double: Stub (connection), Mock (channel ACK)
"""
        # Arrange (Given): body, from fixtures

        # Act (When)
        quarantine = mocker.patch("app.consumer.store.quarantine")
        process("synthetic", Mock(), Mock(), body)

        # Assert (Then)
        assert quarantine.call_args.args[1] == body


    @pytest.mark.parametrize("error", [psycopg2.OperationalError("outage"), psycopg2.ProgrammingError("missing table")], ids=["outage", "missing_table"])
    def test_process_alert_when_database_fails_retries_instead_of_quarantining(self, error, mocker):
        """Summary: A database failure is retried, never mistaken for a bad message.
AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.
Double: Stub (cursor raises), Mock (no ACK)
"""
        # Arrange (Given)
        ch = Mock()

        # Act (When)
        mocker.patch("app.consumer.store.deliver", side_effect=error)
        quarantine = mocker.patch("app.consumer.store.quarantine")
        with pytest.raises(type(error)):
            process("synthetic", ch, Mock(), json.dumps(envelope()).encode())

        # Assert (Then)
        quarantine.assert_not_called()
        ch.basic_ack.assert_not_called()


    def test_process_disruption_alert_without_event_quarantines_it(self, mocker):
        """Summary: A disruption notice referencing a removed event is quarantined after the database refuses its foreign key.
AC2: The notification contains the event name, affected venue, closure start/end, rejection reason, and a link to the venue rejection.
Double: Stub (connection), Mock (channel ACK)
"""
        body = json.dumps(envelope()).encode()
        ch = Mock()
        error = psycopg2.errors.ForeignKeyViolation("event no longer exists")
        deliver = mocker.patch("app.consumer.store.deliver", side_effect=error)
        quarantine = mocker.patch("app.consumer.store.quarantine")
        process("synthetic", ch, Mock(delivery_tag=31), body)
        deliver.assert_called_once()
        assert quarantine.call_args.args[1] == body
        ch.basic_ack.assert_called_once_with(delivery_tag=31)


    def test_quarantine_keeps_original_bytes_and_sanitises_error_text(self, mocker):
        """Summary: Quarantine keeps the exact message bytes and stores only a sanitised error.
AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.
Double: Stub (connection; insert inspected)
"""
        # Arrange (Given)
        con = MagicMock()
        body = b"original\x00\xff"
        mocker.patch("psycopg2.connect", return_value=con)
        store.quarantine("synthetic", body, ValueError("bad\x00\ud800\nvalue"))
        args = con.cursor.return_value.__enter__.return_value.execute.call_args.args[1]

        # Act + Assert (When / Then)
        assert args[0].adapted == body
        assert args[1] == r"bad\x00\ud800\nvalue"


    @pytest.mark.parametrize("field,bad", [
        (field, None) for field in (
            "closureId", "bookingId", "eventId", "venueId", "eventName",
            "venueName", "startDateTime", "endDateTime", "reason",
        )
    ] + [("eventName", bad) for bad in ("", " ", False, [])])
    def test_process_disruption_alert_missing_any_detail_quarantines_it(self, field, bad, mocker):
        """Summary: A disruption notice missing the event, venue, closure period, reason or ids is kept aside.
AC2: The notification contains the event name, affected venue, closure start/end, rejection reason, and a link to the venue rejection.
Double: Stub (connection), Mock (channel ACK)
"""
        value = envelope()
        value["details"][field] = bad
        ch = Mock()
        deliver = mocker.patch("app.consumer.store.deliver")
        quarantine = mocker.patch("app.consumer.store.quarantine")
        process("synthetic", ch, Mock(), json.dumps(value).encode())
        deliver.assert_not_called()
        quarantine.assert_called_once()
        ch.basic_ack.assert_called_once()


    @pytest.mark.parametrize("details", [None, {}, {"eventId": "broken"}], ids=["null_details", "empty_details", "broken_event_id"])
    def test_process_disruption_alert_with_no_details_is_not_delivered(self, details, mocker):
        """Summary: A disruption notice with no details is not delivered.
AC2: The notification contains the event name, affected venue, closure start/end, rejection reason, and a link to the venue rejection.
Double: Stub (connection), Mock (channel ACK)
"""
        value = envelope()
        value["details"] = details
        deliver = mocker.patch("app.consumer.store.deliver")
        quarantine = mocker.patch("app.consumer.store.quarantine")
        process("synthetic", Mock(), Mock(), json.dumps(value).encode())
        deliver.assert_not_called()
        quarantine.assert_called_once()


    @pytest.mark.parametrize("changes", [
        {"eventId": "70000000-0000-0000-0000-000000000001"},
        {"bookingId": "70000000-0000-0000-0000-000000000001"},
        {"closureId": "broken"}, {"venueId": "broken"},
        {"startDateTime": "2026-10-18T08:00:00"},
        {"endDateTime": "2026-10-19T08:00:00"},
        {"startDateTime": "broken"},
        {"endDateTime": "2026-10-18T08:00:00+08:00"},
        {"endDateTime": "2026-10-17T08:00:00+08:00"},
    ], ids=["other_event", "other_booking", "broken_closure", "broken_venue", "naive_start", "naive_end", "broken_start", "end_equals_start", "end_before_start"])
    def test_process_disruption_alert_with_inconsistent_ids_or_period_quarantines_it(self, changes, mocker):
        """Summary: A disruption notice whose ids, link or closure period disagree is kept aside.
AC2: The notification contains the event name, affected venue, closure start/end, rejection reason, and a link to the venue rejection.
Double: Stub (connection), Mock (channel ACK)
"""
        value = envelope()
        value["details"].update(changes)
        deliver = mocker.patch("app.consumer.store.deliver")
        quarantine = mocker.patch("app.consumer.store.quarantine")
        process("synthetic", Mock(), Mock(), json.dumps(value).encode())
        deliver.assert_not_called()
        quarantine.assert_called_once()


    # --- Supporting/supplementary design checks ----------------------------------
    # No Jira acceptance criterion covers these. They check design decisions the
    # stories rely on (health check, CORS, configuration and failure handling).

    def test_process_unknown_future_type_stores_without_closure_details(self, mocker):
        """Summary: A notification type added later can be delivered without the disruption details.
Double: Stub (connection), Mock (channel ACK)
Supporting design check: new notification types stay deliverable
"""
        value = envelope()
        value["type"] = "future.type"
        del value["details"]
        deliver = mocker.patch("app.consumer.store.deliver")
        quarantine = mocker.patch("app.consumer.store.quarantine")
        process("synthetic", Mock(), Mock(), json.dumps(value).encode())
        deliver.assert_called_once_with("synthetic", value)
        quarantine.assert_not_called()
