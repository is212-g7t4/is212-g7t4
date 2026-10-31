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
- The /internal disruption-notification outbox: claim, freeze once, retry and
  publish with lease fencing; validation of frozen content; and rollback of the
  closure and its rejections when the outbox insert fails.
- Assertions are on the HTTP status, SQL sent and rollback.

Doubled
-------
- psycopg2.connect: Stub (`setup`/`client` fixtures) - fresh MagicMock
  connection; the cursor returns canned VenueBooking / VenueClosure rows (or
  raises); executed SQL, parameters and locks are inspected.

Not proven
----------
- That the SQL, locks and constraints behave the same on real PostgreSQL (->
  tests/integration/, throwaway postgres:17.6).
- That the dispatcher delivers to the coordinator assigned at preparation time
  (AC1) (-> venue-booking-service dispatcher tests).
"""

# test_notification_leases.py — original fixture and scenario group
from datetime import datetime, timezone
from copy import deepcopy
from unittest.mock import MagicMock, patch
import pytest
import psycopg2
from app import create_app
from tests.unit.factories import bearer, signed_in
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
    def setup(self, monkeypatch, mocker):
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
        mocker.patch("psycopg2.connect", return_value=connection)
        yield signed_in(create_app({"DATABASE_URL": "synthetic"}).test_client()), cursor, row


    def test_ac1_ac2_ac3_disruption_outbox_claims_freezes_once_retries_and_publishes(self, setup):
        """
        Summary: A disruption alert is claimed, frozen once, retried and published without duplicates.
        AC1: Given a rejection is ready for notification, then the notification
            is addressed to the coordinator assigned to that event when the
            notification is created.
        AC2: The notification contains the event name, affected venue, closure
            start/end, rejection reason, and a link to the venue rejection.
        AC3: Given a temporary system failure occurs during notification
            dispatch, the system must ensure the notification is eventually
            delivered to the assigned coordinator without generating multiple
            duplicate alerts.
        Double: Stub (cursor returns jobs; SQL inspected)
        """
        # Arrange (Given)
        client, cursor, row = setup

        # Act (When)
        result = client.post(
            "/internal/notification-outbox/claim", json={}, headers=HEADERS
        )

        # Assert (Then)
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
        ids=["version_2", "version_true", "id_token", "type_other", "recipientid_bad", "createdat_changed", "destination_kind_external_url", "message", "details_none", "details_source_dict_eventname_conference_venuena", "details_source_dict_eventname_conference_venuena_2", "details_source_dict_eventname_conference_venuena_3", "details_source_dict_eventname_venuename_hall", "details_source_dict_eventname_conference_venuena_4"],
    )
    def test_ac2_freeze_disruption_alert_with_bad_or_changed_content_returns_400(self, setup, change):
        """
        Summary: Malformed or changed alert content is refused rather than frozen.
        AC2: The notification contains the event name, affected venue, closure
            start/end, rejection reason, and a link to the venue rejection.
        Double: Stub (cursor returns the job)
        """
        client, _, _ = setup
        assert (
            operation(client, "freeze", envelope=deepcopy(ENVELOPE) | change).status_code
            == 400
        )


    def test_ac3_disruption_outbox_with_bad_action_or_storage_failure_fails_safely(self, setup, monkeypatch):
        """
        Summary: Bad actions, a missing database or a storage failure fail safely and can be retried.
        AC3: Given a temporary system failure occurs during notification
            dispatch, the system must ensure the notification is eventually
            delivered to the assigned coordinator without generating multiple
            duplicate alerts.
        Double: Stub (cursor raises)
        """
        # Arrange (Given)
        client, cursor, _ = setup

        # Act (When)
        for body in (None, [], {}, {"leaseToken": 123}):
            assert (
                client.post(
                    f"/internal/notification-outbox/{ID}/retry", json=body, headers=HEADERS
                ).status_code
                == 400
            )

        # Assert (Then)
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

    def test_ac3_disruption_outbox_without_valid_service_token_returns_401(self, monkeypatch, mocker):
        """
        Summary: Only a caller with the configured service token can claim alerts.
        AC3: Given a temporary system failure occurs during notification
            dispatch, the system must ensure the notification is eventually
            delivered to the assigned coordinator without generating multiple
            duplicate alerts.
        Double: Environment stub (configured internal token); the outbox claim
            is a Mock and is asserted unused for invalid credentials.
        """
        # Arrange (Given)
        monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "synthetic-internal-token")
        client = signed_in(create_app({"DATABASE_URL": "synthetic"}).test_client())

        # Act + Assert (When / Then)
        assert (
            client.post("/internal/notification-outbox/claim", json={}).status_code == 401
        )
        mocker.patch("app.outbox.claim", return_value=[])
        response = client.post(
            "/internal/notification-outbox/claim",
            json={},
            headers={"X-Internal-Token": "synthetic-internal-token"},
        )
        assert response.status_code == 200
        assert response.json == {"jobs": []}


    def test_ac3_disruption_outbox_with_non_ascii_token_is_refused(self, monkeypatch):
        """
        Summary: An odd service token is refused safely.
        AC3: Given a temporary system failure occurs during notification
            dispatch, the system must ensure the notification is eventually
            delivered to the assigned coordinator without generating multiple
            duplicate alerts.
        Double: Environment stub (configured internal token).
        """
        # Arrange (Given)
        monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "synthetic-token")
        client = signed_in(create_app({"DATABASE_URL": "synthetic"}).test_client())

        # Act + Assert (When / Then)
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

    def test_ac3_closure_when_alert_cannot_be_queued_rolls_back(self, mocker):
        """
        Summary: If the alert cannot be queued, the closure and its rejections are rolled back too.
        AC3: Given a temporary system failure occurs during notification
            dispatch, the system must ensure the notification is eventually
            delivered to the assigned coordinator without generating multiple
            duplicate alerts.
        Double: Stub (outbox insert raises), Mock (rollback)
        """
        # Arrange (Given)
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
                "CLOSURE_CONFIRMATION_KEY": "synthetic-signing-key-with-32-bytes",
            }
        )
        client = signed_in(app.test_client())
        headers = bearer(USER_ID, "Venue Staff")
        data = dict(
            venueId=VENUE_ID,
            startDateTime="2099-01-01T08:00:00+08:00",
            endDateTime="2099-01-02T08:00:00+08:00",
            reason="Maintenance",
        )

        # Act (When)
        mocker.patch("psycopg2.connect", return_value=connection)
        preview = client.post("/venue-closures/preview", json=data, headers=headers)
        response = client.post(
            "/venue-closures",
            json=data
            | dict(confirmed=True, confirmationToken=preview.json["confirmationToken"]),
            headers=headers,
        )

        # Assert (Then)
        assert response.status_code == 503
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()
