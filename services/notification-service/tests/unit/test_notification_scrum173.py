"""SCRUM-173: venue disruptions tell the assigned coordinator to rearrange bookings.

Story: As an Event Coordinator, I want an in-app notification when a venue booking
for my assigned event is affected, so I know alternative arrangements are needed.
AC1: notify the coordinator assigned when the notification is prepared.
AC2: include event, venue, closure interval, reason and rejection destination.
AC3: recover from temporary dispatch failure without duplicate alerts.
AC = acceptance criterion; DR = design rule (supporting behaviour, not an extra AC).

Real: consumer validation, storage adapters, Flask routes and command-loop logic.
Mocked: database/broker I/O, time delays and selected route storage calls.
Identity: DEV headers exercise caller scoping, not JWT login or production auth.
Not proven: durable database writes, broker restart/redelivery, producer recipient
selection, deployed authentication or browser navigation; isolated suites cover
those boundaries separately. Quarantine means the mocked SQL write was requested.

Classes group recovery, inbox access and validation. Security, diagnostics and
legacy compatibility support the story; they are not additional acceptance criteria.
Historical checks are regression evidence, not a claim of test-first chronology."""

# test_consumer_recovery.py — original fixture and scenario group
import json
import runpy
from pathlib import Path
from app import consumer, diagnostics
from unittest.mock import MagicMock, Mock, patch
import pytest
from app.consumer import process, run, connect
from app.diagnostics import replay, main
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

    def test_delivered_only_after_database_commit(self):
        """AC3: processing exits the mocked transaction, closes it and requests ACK.
        Checks expected calls, not a real commit or their relative call order."""
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        channel = Mock()
        method = Mock(delivery_tag=9)
        with patch("psycopg2.connect", return_value=connection):
            process("synthetic", channel, method, json.dumps(envelope()).encode())
        connection.__exit__.assert_called_once()
        channel.basic_ack.assert_called_once_with(delivery_tag=9)
        connection.close.assert_called_once()


    def test_database_commit_failure_leaves_delivery_unacknowledged(self):
        """## AC3
        A database commit failure propagates without acknowledging; redelivery remains possible.
        """
        connection = MagicMock()
        connection.__exit__.side_effect = RuntimeError("commit failed")
        channel = Mock()
        method = Mock(delivery_tag=9)
        with patch("psycopg2.connect", return_value=connection):
            with pytest.raises(RuntimeError):
                process("synthetic", channel, method, json.dumps(envelope()).encode())
        channel.basic_ack.assert_not_called()
        connection.close.assert_called_once()


    def test_malformed_quarantine_commits_before_ack_with_mocked_database(self):
        # Alias: test_malformed_saved_in_real_quarantine_adapter and
        # test_delivery::test_malformed_is_persisted_before_ack (consolidated).
        """## AC3 supporting poison recovery
        Malformed bytes commit to quarantine before ACK; the mocked adapter is not real persistence evidence.
        """
        connection = MagicMock()
        channel = Mock()
        events = []
        connection.__exit__.side_effect = lambda *_: events.append("commit")
        channel.basic_ack.side_effect = lambda **_: events.append("ack")
        with patch("psycopg2.connect", return_value=connection):
            process("synthetic", channel, Mock(delivery_tag=7), b"broken")
        connection.__exit__.assert_called_once()
        connection.close.assert_called_once()
        assert events == ["commit", "ack"]
        channel.basic_ack.assert_called_once_with(delivery_tag=7)


    def test_connection_parameters_are_usable_without_network(self):
        """## Supporting infrastructure
        Broker connection parameters construct a connection through a mocked transport, with no real network.
        """
        with patch("app.consumer.pika.BlockingConnection") as connection:
            result = connect("amqp://synthetic:synthetic@127.0.0.1:5672/%2F")
        assert result is connection.return_value


    def test_consumer_command_recovers_outage_then_stops_cleanly(self, monkeypatch):
        """## AC3 supporting process recovery
        A startup connection outage backs off, then consumes through the recovered channel and closes cleanly.
        """
        monkeypatch.setenv("RABBITMQ_URL", "amqp://synthetic:synthetic@127.0.0.1:5672/%2F")
        monkeypatch.setenv("DATABASE_URL", "synthetic")
        connection = MagicMock()
        channel = connection.channel.return_value

        def consume():
            callback = channel.basic_consume.call_args.kwargs["on_message_callback"]
            callback(channel, Mock(delivery_tag=1), None, b"bad")
            raise KeyboardInterrupt()

        channel.start_consuming.side_effect = consume
        with (
            patch(
                "pika.BlockingConnection", side_effect=[RuntimeError("outage"), connection]
            ),
            patch("time.sleep") as sleep,
            patch("app.store.quarantine"),
        ):
            runpy.run_path(str(Path(consumer.__file__)), run_name="__main__")
        sleep.assert_called_once_with(1)
        connection.close.assert_called_once()


    def test_consumer_handles_closed_connection_and_normal_return(self, monkeypatch):
        """## AC3 supporting process recovery
        A closed broker connection and normal return back off safely without closing twice.
        """
        monkeypatch.setenv("RABBITMQ_URL", "amqp://synthetic:synthetic@127.0.0.1:5672/%2F")
        connection = MagicMock()
        connection.is_open = False
        with (
            patch("app.consumer.connect", side_effect=[connection, KeyboardInterrupt()]),
            patch("time.sleep") as sleep,
        ):
            run()
        sleep.assert_called_once_with(1)
        connection.close.assert_not_called()


    def test_diagnostic_list_and_replay_command(self, monkeypatch, capsys):
        """## Supporting diagnostics
        CLI listing exposes retained failure IDs; replay reads saved bytes; an absent failure is explicit.
        """
        monkeypatch.setenv("DATABASE_URL", "synthetic")
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [{"failure_id": ID, "error": "unsupported version"}]
        cursor.fetchone.return_value = {"body": memoryview(json.dumps(envelope()).encode())}
        with patch("psycopg2.connect", return_value=connection):
            with patch("sys.argv", ["diagnostics", "list"]):
                runpy.run_path(str(Path(diagnostics.__file__)), run_name="__main__")
            assert ID in capsys.readouterr().out
            with patch("sys.argv", ["diagnostics", "replay", ID]):
                main()
        assert connection.close.call_count == 4
        cursor.fetchone.return_value = None
        with patch("psycopg2.connect", return_value=connection):
            with pytest.raises(ValueError, match="not found"):
                replay("synthetic", ID)


    def test_repeated_storage_failure_increases_reconnect_delay(self, monkeypatch):
        """## AC3
        Repeated storage outages increase reconnect delay instead of busy-looping or dropping delivery.
        """
        monkeypatch.setenv("RABBITMQ_URL", "amqp://synthetic:synthetic@127.0.0.1:5672/%2F")
        connection = MagicMock()
        connection.channel.return_value.start_consuming.side_effect = [
            RuntimeError("storage down"),
            RuntimeError("still down"),
            KeyboardInterrupt(),
        ]
        with (
            patch("app.consumer.connect", return_value=connection),
            patch("time.sleep") as sleep,
        ):
            run()
        assert [call.args[0] for call in sleep.call_args_list] == [1, 2]


    def test_connection_close_failure_does_not_kill_recovery_loop(self, monkeypatch):
        """## AC3
        A failed connection close does not prevent the following reconnect attempt.
        """
        monkeypatch.setenv("RABBITMQ_URL", "amqp://synthetic:synthetic@127.0.0.1:5672/%2F")
        connection = MagicMock()
        connection.channel.return_value.start_consuming.side_effect = [
            RuntimeError("connection failed"),
            KeyboardInterrupt(),
        ]
        connection.close.side_effect = [RuntimeError("close failed"), None]
        with (
            patch("app.consumer.connect", return_value=connection) as connect_again,
            patch("time.sleep"),
        ):
            run()
        assert connect_again.call_count == 2


# test_delivery.py — original fixture and scenario group
from unittest.mock import Mock, patch
import pytest
from app.consumer import process

class TestDelivery:
    """SCRUM-173 AC3 — consumer acknowledgement boundary (hermetic). Commit failure must leave delivery unacknowledged; malformed messages are retained."""

    def test_storage_failure_does_not_ack(self):
        """## AC3 supporting poison recovery
        Quarantine failure leaves malformed delivery unacknowledged, retaining the broker recovery path.
        """
        channel = Mock()
        method = Mock(delivery_tag=7)
        with patch("app.consumer.store.quarantine", side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError):
                process("synthetic", channel, method, b"broken")
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
    )
    def test_malformed_envelopes_are_retained_instead_of_delivered(self, changes):
        """## AC3 supporting validation
        Each distinct invalid envelope contract is retained and ACKed, never inserted into the inbox.
        """
        import json

        channel = Mock()
        method = Mock(delivery_tag=3)
        with (
            patch("app.consumer.store.deliver") as deliver,
            patch("app.consumer.store.quarantine") as quarantine,
        ):
            process("synthetic", channel, method, json.dumps(envelope() | changes).encode())
        deliver.assert_not_called()
        quarantine.assert_called_once()
        channel.basic_ack.assert_called_once_with(delivery_tag=3)


    def test_excessively_nested_malformed_json_is_durably_quarantined(self):
        """AC3 supporting poison recovery: excessive JSON nesting requests quarantine
        and ACK instead of crashing. Mocked SQL is not durable storage evidence."""
        channel = Mock()
        method = Mock(delivery_tag=4)
        depth = 100000
        body = b"[" * depth + b"0" + b"]" * depth
        with patch("app.consumer.store.quarantine") as quarantine:
            process("synthetic", channel, method, body)
        quarantine.assert_called_once()
        channel.basic_ack.assert_called_once_with(delivery_tag=4)


# test_inbox.py — original fixture and scenario group
from unittest.mock import patch
from app import create_app
INBOX_USER = "10000000-0000-0000-0000-000000000001"

class TestInbox:
    """SCRUM-173 AC1/AC3 — hermetic inbox API ownership seam. No real persistence here; SQL/broker integration is separately exercised."""

    def test_inbox_uses_authenticated_identity_not_query_recipient(self, monkeypatch):
        """## AC1 supporting ownership
        The DEV caller identity, not an attacker-supplied recipient query, scopes inbox access.
        """
        monkeypatch.setenv("NOTIFICATION_DEV_MODE", "true")
        monkeypatch.setenv("DATABASE_URL", "synthetic-not-a-real-dsn")
        client = create_app().test_client()
        with patch(
            "app.store.list_inbox", return_value={"notifications": [], "nextCursor": None}
        ) as listing:
            response = client.get(
                "/notifications?recipientId=someone-else",
                headers={"X-Dev-User-Id": INBOX_USER, "X-Dev-Role": "Event Coordinator"},
            )
        assert response.status_code == 200
        assert listing.call_args.args[1] == INBOX_USER


# test_inbox_behavior.py — original fixture and scenario group
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest
import psycopg2
from app import create_app
HEADERS = {"X-Dev-User-Id": USER, "X-Dev-Role": "Event Coordinator"}

class TestInboxBehavior:
    """SCRUM-173 AC1/AC3 — inbox HTTP seam (hermetic database driver). Own listing, keyset pagination, unread filtering, read/unread, CORS and denials. Actual SQL ownership/filter/order/dedup is verified separately in PostgreSQL."""

    @pytest.fixture
    def setup(self, monkeypatch):
        monkeypatch.setenv("NOTIFICATION_DEV_MODE", "true")
        monkeypatch.setenv("DATABASE_URL", "synthetic")
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [row()]
        cursor.fetchone.return_value = row()
        with patch("psycopg2.connect", return_value=connection):
            yield create_app().test_client(), cursor


    def test_pagination_filter_read_and_unread(self, setup):
        """## Supporting inbox UI contract
        Keyset pagination/filtering, individual read/unread, absent-row response and unread count have explicit HTTP outcomes.
        """
        client, cursor = setup
        cursor.fetchall.return_value = [row(), row()]
        first = client.get("/notifications?limit=1", headers=HEADERS)
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
        for read in (True, False):
            result = client.patch(
                "/notifications/" + ID, json={"read": read}, headers=HEADERS
            )
            assert result.status_code == 200 and result.json["notification"]["id"] == ID
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
    )
    def test_bad_query_is_client_error(self, setup, query):
        """## Supporting API validation
        Invalid limits, unread values and cursors return 400 rather than silently changing the inbox window.
        """
        client, _ = setup
        assert client.get("/notifications?" + query, headers=HEADERS).status_code == 400


    @pytest.mark.parametrize("body", [None, [], {}, {"read": "true"}, {"read": 1}])
    def test_bad_read_input_is_client_error(self, setup, body):
        """## Supporting API validation
        Malformed read bodies return 400, never coercing strings or numbers into a read mutation.
        """
        client, _ = setup
        assert (
            client.patch("/notifications/" + ID, json=body, headers=HEADERS).status_code
            == 400
        )


    @pytest.mark.parametrize(
        "headers", [{}, {"X-Dev-User-Id": "bad"}, {"X-Dev-User-Id": USER}]
    )
    def test_identity_required(self, setup, headers):
        """## AC1 supporting ownership
        Missing/malformed DEV identity is denied before any recipient-scoped read.
        """
        client, _ = setup
        assert client.get("/notifications", headers=headers).status_code == 401


    def test_disabled_missing_database_cors_and_health(self, setup):
        """## Supporting infrastructure/security
        Disabled mode and missing storage fail closed; trusted CORS and process-health semantics remain explicit.
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
        client.application.config["NOTIFICATION_DEV_MODE"] = False
        assert client.get("/notifications", headers=HEADERS).status_code == 503
        client.application.config.update(NOTIFICATION_DEV_MODE=True, DATABASE_URL=None)
        assert client.get("/notifications", headers=HEADERS).status_code == 503


    def test_storage_outage_is_retryable_and_nullable_legacy_row_survives(self, setup):
        """## AC3 + cross-ticket legacy compatibility
        Legacy nullable fields serialize unchanged; storage outage yields retryable 503, not an empty successful inbox.
        """
        client, cursor = setup
        legacy = row()
        legacy.update(
            event_id=None,
            created_at=None,
            read_at=datetime(2026, 10, 17, tzinfo=timezone.utc),
        )
        cursor.fetchall.return_value = [legacy]
        response = client.get("/notifications", headers=HEADERS)
        assert response.json["notifications"][0]["eventId"] is None
        assert response.json["notifications"][0]["createdAt"] is None
        cursor.execute.side_effect = psycopg2.OperationalError("synthetic outage")
        assert client.get("/notifications", headers=HEADERS).status_code == 503


# test_review_validation.py — original fixture and scenario group
import json
from unittest.mock import MagicMock, Mock, patch
import psycopg2
import pytest
from app.consumer import process
from app import store

class TestReviewValidation:
    """SCRUM-173 review R1/R2: poison retention and known-type contract at consumer seam."""

    @pytest.mark.parametrize("extra", [float("nan"), float("inf"), float("-inf"), "nul\x00text", "\ud800", {"\udfff": "value"}, {"nul\x00key": ["value"]}, [0, {"nested": "\udfff"}]])
    def test_r1_jsonb_poison_in_unknown_fields_is_retained_before_ack(self, extra):
        """## AC3 supporting JSONB safety
        Nonfinite numbers and NUL/surrogate text at nested values/keys retain original bytes and cannot poison inbox persistence.
        """
        body = json.dumps(envelope() | {"future": extra}).encode()
        ch = Mock()
        with patch("app.consumer.store.deliver") as deliver, patch("app.consumer.store.quarantine") as quarantine:
            process("synthetic", ch, Mock(delivery_tag=1), body)
        deliver.assert_not_called()
        assert quarantine.call_args.args[1] == body
        ch.basic_ack.assert_called_once_with(delivery_tag=1)


    @pytest.mark.parametrize("body", [b'{"extra":NaN}', b'{"extra":1e999}', b'\xff'])
    def test_r1_strict_wire_json_is_quarantined(self, body):
        """## AC3 supporting JSON safety
        Nonstandard constants, overflowing numbers and invalid UTF-8 retain exact input bytes.
        """
        with patch("app.consumer.store.quarantine") as quarantine:
            process("synthetic", Mock(), Mock(), body)
        assert quarantine.call_args.args[1] == body


    @pytest.mark.parametrize("error", [psycopg2.OperationalError("outage"), psycopg2.ProgrammingError("missing table")])
    def test_r1_database_failures_are_not_misclassified_as_poison(self, error):
        """## AC3
        Real driver error classes propagate without quarantine or ACK; temporary infrastructure failure remains retryable.
        """
        ch = Mock()
        with patch("app.consumer.store.deliver", side_effect=error), patch("app.consumer.store.quarantine") as quarantine:
            with pytest.raises(type(error)):
                process("synthetic", ch, Mock(), json.dumps(envelope()).encode())
        quarantine.assert_not_called()
        ch.basic_ack.assert_not_called()


    def test_r1_quarantine_keeps_bytes_and_sanitizes_untrusted_error_text(self):
        """## Supporting diagnostics/security
        Quarantine keeps original binary bytes while escaping unsafe diagnostic text.
        """
        con = MagicMock()
        body = b"original\x00\xff"
        with patch("psycopg2.connect", return_value=con):
            store.quarantine("synthetic", body, ValueError("bad\x00\ud800\nvalue"))
        args = con.cursor.return_value.__enter__.return_value.execute.call_args.args[1]
        assert args[0].adapted == body
        assert args[1] == r"bad\x00\ud800\nvalue"


    @pytest.mark.parametrize("field,bad", [
        (field, None) for field in (
            "closureId", "bookingId", "eventId", "venueId", "eventName",
            "venueName", "startDateTime", "endDateTime", "reason",
        )
    ] + [("eventName", bad) for bad in ("", " ", False, [])])
    def test_r2_known_contract_requires_complete_details(self, field, bad):
        """## AC2 supporting validation
        Each required detail rejects absence; representative shared-text invalid types/blank values are rejected without redundant cross-products.
        """
        value = envelope()
        value["details"][field] = bad
        ch = Mock()
        with patch("app.consumer.store.deliver") as deliver, patch("app.consumer.store.quarantine") as quarantine:
            process("synthetic", ch, Mock(), json.dumps(value).encode())
        deliver.assert_not_called()
        quarantine.assert_called_once()
        ch.basic_ack.assert_called_once()


    @pytest.mark.parametrize("details", [None, {}, {"eventId": "broken"}])
    def test_r2_minimal_known_message_is_not_delivered(self, details):
        """## AC2 supporting validation
        Known closure notifications reject missing/non-object/incomplete details rather than delivering misleading content.
        """
        value = envelope()
        value["details"] = details
        with patch("app.consumer.store.deliver") as deliver, patch("app.consumer.store.quarantine") as quarantine:
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
    ])
    def test_r2_details_interval_and_destination_references_are_consistent(self, changes):
        """## AC2
        Invalid identifiers, mismatched destinations and invalid/reversed intervals are quarantined, not delivered.
        """
        value = envelope()
        value["details"].update(changes)
        with patch("app.consumer.store.deliver") as deliver, patch("app.consumer.store.quarantine") as quarantine:
            process("synthetic", Mock(), Mock(), json.dumps(value).encode())
        deliver.assert_not_called()
        quarantine.assert_called_once()


    def test_r2_future_type_remains_extensible_without_closure_details(self):
        """## Supporting extensibility
        A future notification type can use the common envelope without closure-specific details.
        """
        value = envelope()
        value["type"] = "future.type"
        del value["details"]
        with patch("app.consumer.store.deliver") as deliver, patch("app.consumer.store.quarantine") as quarantine:
            process("synthetic", Mock(), Mock(), json.dumps(value).encode())
        deliver.assert_called_once_with("synthetic", value)
        quarantine.assert_not_called()
