"""# SCRUM-173 — Receive Venue Disruption Notifications

As an Event Coordinator, I want to receive an in-app notification when a venue booking for an event assigned to me is affected, so that I know that alternative arrangements are required.
AC1: Given a rejection is ready for notification, then the notification is addressed to the coordinator assigned to that event when the notification is created.
AC2: The notification contains the event name, affected venue, closure start/end, rejection reason, and a link to the venue rejection.
AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.

## Layer and scope
# SCRUM-173 AC1/AC2/AC3 — owning-service HTTP lease/freeze seam.
Hermetic SQL driver controls responses; no persistence/concurrency claim here.
Real lease fencing, rollback and freeze-once recovery are verified in PostgreSQL.


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

# test_notification_leases.py — original fixture and scenario group
from datetime import datetime, timezone
from copy import deepcopy
from unittest.mock import MagicMock, patch
import pytest
import psycopg2
from app import create_app
ID = "10000000-0000-0000-0000-000000000001"
TOKEN = "20000000-0000-0000-0000-000000000001"
HEADERS = {"X-Internal-Token": "synthetic-token"}
SOURCE = dict(
    eventId=ID,
    bookingId=ID,
    venueId=ID,
    closureId=ID,
    startDateTime="2099-01-01T08:00:00+08:00",
    endDateTime="2099-01-02T08:00:00+08:00",
    reason="Maintenance",
)
STAMP = datetime(2026, 10, 17, tzinfo=timezone.utc)
ENVELOPE = dict(
    version=1,
    id=ID,
    type="venue.closure-rejection",
    recipientId=ID,
    createdAt=STAMP.isoformat(),
    message="Historical notice",
    destination=dict(kind="event-venue-request", eventId=ID, bookingId=ID),
    details=SOURCE | dict(eventName="Conference", venueName="Hall"),
)
def operation(client, action, **data):
    return client.post(
        f"/internal/notification-outbox/{ID}/{action}",
        json={"leaseToken": TOKEN, **data},
        headers=HEADERS,
    )

class TestNotificationLeases:
    """SCRUM-173 AC1/AC2/AC3 — owning-service HTTP lease/freeze seam. Hermetic SQL driver controls responses; no persistence/concurrency claim here. Real lease fencing, rollback and freeze-once recovery are verified in PostgreSQL."""

    @pytest.fixture
    def setup(self, monkeypatch):
        monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "synthetic-token")
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        row = dict(
            source_id=ID,
            lease_valid=True,
            type="venue.closure-rejection",
            lease_token=TOKEN,
            attempts=1,
            source=SOURCE,
            created_at=STAMP,
            envelope=None,
        )
        cursor.fetchone.return_value = row
        cursor.fetchall.return_value = [row]
        with patch("psycopg2.connect", return_value=connection):
            yield create_app({"DATABASE_URL": "synthetic"}).test_client(), cursor, row


    def test_claim_freeze_once_retry_and_publish(self, setup):
        """## AC1/AC2/AC3
        Owning HTTP operations claim, freeze once, retry and publish while fencing stale tokens and retaining the original envelope.
        """
        client, cursor, row = setup
        result = client.post(
            "/internal/notification-outbox/claim", json={}, headers=HEADERS
        )
        assert result.json["jobs"][0]["id"] == ID
        frozen = row | {"envelope": ENVELOPE}
        cursor.fetchone.side_effect = [row, frozen]
        result = operation(client, "freeze", envelope=ENVELOPE)
        assert result.status_code == 200 and result.json["envelope"] == ENVELOPE
        cursor.fetchone.side_effect = None
        cursor.fetchone.return_value = frozen
        result = operation(client, "freeze", envelope={"replacement": "not allowed"})
        assert result.status_code == 200 and result.json["envelope"] == ENVELOPE
        assert operation(client, "published").json == {"id": ID, "status": "published"}
        assert operation(client, "retry", error="temporary outage").json == {
            "id": ID,
            "status": "retry",
        }
        row["attempts"] = 1000
        cursor.fetchone.return_value = row
        assert operation(client, "retry", error="still temporary").status_code == 200
        assert operation(client, "published").status_code == 400
        assert operation(client, "retry", error=None).status_code == 400
        cursor.fetchone.return_value = row | {"lease_valid": False}
        assert operation(client, "freeze", envelope=ENVELOPE).status_code == 409
        cursor.fetchone.return_value = None
        assert operation(client, "freeze", envelope=ENVELOPE).status_code == 409


    @pytest.mark.parametrize(
        "change",
        [
            {"version": 2},
            {"version": True},
            {"id": TOKEN},
            {"type": "other"},
            {"recipientId": "bad"},
            {"createdAt": "changed"},
            {"destination": {"kind": "external-url"}},
            {"message": ""},
            {"details": None},
            {
                "details": SOURCE
                | dict(eventName="Conference", venueName="Hall", eventId=TOKEN)
            },
            {
                "details": SOURCE
                | dict(eventName="Conference", venueName="Hall", bookingId=TOKEN)
            },
            {
                "details": SOURCE
                | dict(eventName="Conference", venueName="Hall", reason="changed")
            },
            {"details": SOURCE | dict(eventName="", venueName="Hall")},
            {"details": SOURCE | dict(eventName="Conference", venueName=123)},
        ],
    )
    def test_freeze_rejects_malformed_or_changed_historical_content(self, setup, change):
        """## AC1/AC2 supporting validation
        Invalid or changed frozen content is rejected rather than silently rewriting recipient/history.
        """
        client, _, _ = setup
        assert (
            operation(client, "freeze", envelope=deepcopy(ENVELOPE) | change).status_code
            == 400
        )


    def test_invalid_operations_missing_database_and_storage_failure(self, setup, monkeypatch):
        """## AC3 supporting recovery/validation
        Malformed internal operations, absent database and driver failures expose explicit failures without false publication.
        """
        client, cursor, _ = setup
        for body in (None, [], {}, {"leaseToken": 123}):
            assert (
                client.post(
                    f"/internal/notification-outbox/{ID}/retry", json=body, headers=HEADERS
                ).status_code
                == 400
            )
        assert operation(client, "unknown").status_code == 404
        cursor.execute.side_effect = psycopg2.OperationalError("outage")
        assert operation(client, "published").status_code == 503
        client.application.config["DATABASE_URL"] = None
        assert (
            client.post(
                "/internal/notification-outbox/claim", json={}, headers=HEADERS
            ).status_code
            == 503
        )
        monkeypatch.delenv("INTERNAL_SERVICE_TOKEN")
        assert (
            client.post(
                "/internal/notification-outbox/claim", json={}, headers=HEADERS
            ).status_code
            == 401
        )


# test_notification_outbox.py — original fixture and scenario group
from app import create_app
from unittest.mock import patch

class TestNotificationOutbox:
    """SCRUM-173 AC3 — authenticated owning-service outbox API (hermetic). Lease/transaction semantics are exercised separately on disposable PostgreSQL."""

    def test_internal_claim_rejects_unconfigured_and_wrong_token(self, monkeypatch):
        """## Supporting security
        Internal claim denies unconfigured or incorrect service tokens before database access.
        """
        monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "synthetic-internal-token")
        client = create_app({"DATABASE_URL": "synthetic"}).test_client()
        assert (
            client.post("/internal/notification-outbox/claim", json={}).status_code == 401
        )
        with patch("app.outbox.claim", return_value=[]):
            response = client.post(
                "/internal/notification-outbox/claim",
                json={},
                headers={"X-Internal-Token": "synthetic-internal-token"},
            )
        assert response.status_code == 200
        assert response.json == {"jobs": []}


    def test_non_ascii_internal_token_is_denied_without_crashing(self, monkeypatch):
        """## Supporting security
        An untrusted non-ASCII token is denied safely rather than causing a comparison exception.
        """
        monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "synthetic-token")
        client = create_app({"DATABASE_URL": "synthetic"}).test_client()
        assert (
            client.post(
                "/internal/notification-outbox/claim", headers={"X-Internal-Token": "é"}
            ).status_code
            == 401
        )


# test_notification_transaction.py — original fixture and scenario group
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import psycopg2
from app import create_app

class TestNotificationTransaction:
    """SCRUM-173 AC3 — closure HTTP transaction seam, hermetic SQL failure. Outbox write failure must surface failure and roll back the same transaction. Real row preservation is verified by the isolated integration harness."""

    def test_outbox_failure_rolls_back_closure_and_rejections(self):
        """## AC3
        An outbox insert error rolls back the closure transaction and returns failure, not a successful lost notification.
        """
        from tests.unit.factories import VENUE_ID, USER_ID, booking_row

        row = booking_row()
        row.update(
            closure_id=VENUE_ID,
            start_date_time=datetime(2099, 1, 1, tzinfo=timezone.utc),
            end_date_time=datetime(2099, 1, 2, tzinfo=timezone.utc),
            reason="Maintenance",
            created_by=USER_ID,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = row
        cursor.fetchall.return_value = [booking_row()]

        def execute(sql, *args):
            if 'INSERT INTO public."VenueNotificationOutbox"' in sql:
                raise psycopg2.OperationalError("injected outbox failure")

        cursor.execute.side_effect = execute
        app = create_app(
            {
                "DATABASE_URL": "synthetic",
                "VENUE_CLOSURE_DEV_MODE": True,
                "CLOSURE_CONFIRMATION_KEY": "synthetic-signing-key-with-32-bytes",
            }
        )
        client = app.test_client()
        headers = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Venue Staff"}
        data = dict(
            venueId=VENUE_ID,
            startDateTime="2099-01-01T08:00:00+08:00",
            endDateTime="2099-01-02T08:00:00+08:00",
            reason="Maintenance",
        )
        with patch("psycopg2.connect", return_value=connection):
            preview = client.post("/venue-closures/preview", json=data, headers=headers)
            response = client.post(
                "/venue-closures",
                json=data
                | dict(confirmed=True, confirmationToken=preview.json["confirmationToken"]),
                headers=headers,
            )
        assert response.status_code == 503
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()
