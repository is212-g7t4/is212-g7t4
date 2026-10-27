"""SCRUM-47 Venue booking notification and decision alerts: owner unit tests.

Story: As an Event Coordinator and Venue Staff, I want to receive notifications
about venue booking requests and decisions, so that I can coordinate venue
arrangements efficiently.
AC1 Given an Event Coordinator submits a venue booking request, system sends
an in-app notification to Venue Staff with event name, requested venue,
date/time and link to review.
AC2 Given booking approved/rejected, sends an in-app notification to Event
Coordinator with event name, venue, decision.

AC = acceptance criterion; DR = supporting design rule, not an extra AC.
Real: Flask/authentication, owner expansion/freeze validation, mutation routes/models.
Doubled: native psycopg2 connection/cursor, including transaction-exit protocol.
AC1: owner fans out a captured submission; AC2: owner freezes original-recipient
approval/rejection history. Dispatcher tests own enriched content/SGT/link building;
Notification tests own consumption. Existing mutation successes/refusals stay in
submission/review modules. DR: invalid input cannot write, failed intent rolls back.
Not proven: PostgreSQL persistence/rollback, concurrent leases, user lookup, broker
or inbox delivery; these require the separate integration/E2E tiers.
"""
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import MagicMock

import psycopg2
import pytest

from app import create_app
from tests.unit.factories import BOOKING_ID, EVENT_ID, USER_ID, VENUE_ID, booking_row

JOB = "10000000-0000-0000-0000-000000000004"
TOKEN = "10000000-0000-0000-0000-000000000005"
STAFF = "20000000-0000-0000-0000-000000000001"
OTHER_STAFF = "20000000-0000-0000-0000-000000000002"
STAMP = datetime(2026, 10, 27, tzinfo=timezone.utc)
SOURCE = dict(bookingId=BOOKING_ID, eventId=EVENT_ID, venueId=VENUE_ID,
              requestedBy=USER_ID, startDateTime="2099-01-01T01:00:00+00:00",
              endDateTime="2099-01-01T03:00:00+00:00")
EXPANSION = dict(recipientIds=[OTHER_STAFF, STAFF, OTHER_STAFF],
                 eventName="Community Fair", venueName="Grand Hall")


@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "synthetic")
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("psycopg2.connect", lambda *args, **kwargs: connection)
    client = create_app({"TESTING": True, "DATABASE_URL": "synthetic"}).test_client()
    row = dict(source_id=JOB, type="venue.booking-submission-fanout", booking_id=BOOKING_ID,
               source=deepcopy(SOURCE), envelope=None, lease_token=TOKEN, attempts=1,
               created_at=STAMP, lease_valid=True)
    cursor.fetchone.return_value = row
    return client, cursor, row, connection


def operate(client, action, **data):
    return client.post(f"/internal/notification-outbox/{JOB}/{action}",
                       headers={"X-Internal-Token": "synthetic"},
                       json={"leaseToken": TOKEN, **data})


def booking_envelope(outcome) -> dict:
    submission = outcome == "submission"
    source = {**SOURCE, "eventName": "Community Fair", "venueName": "Grand Hall"}
    source.update({"recipientId": STAFF} if submission else {"decision": outcome})
    return dict(version=1, id=JOB,
                type="venue.booking-submission" if submission else "venue.booking-decision",
                recipientId=STAFF if submission else USER_ID, createdAt=STAMP.isoformat(),
                message="Community Fair venue booking update",
                destination={"kind": "venue-requests"} if submission else
                    {"kind": "event-venue-request", "eventId": EVENT_ID, "bookingId": BOOKING_ID},
                details=source)


# AC1 — expansion; DR: stable child identities and captured historical source.
def test_ac1_duplicate_staff_expand_to_one_historical_child_each(owner):
    """Normal: two distinct staff receive stable children while duplicate lookup rows collapse."""
    # Arrange: isolate the driver while retaining the real route and owner logic.
    client, cursor, row, connection = owner

    # Act: enter through the public HTTP boundary.
    result = operate(client, "expand", **EXPANSION)

    # Assert: response and write/transaction outcomes, not just executed lines.
    assert result.status_code == 200
    assert result.json == {"id": JOB, "status": "expanded", "recipients": 2}
    calls = [call.args for call in cursor.execute.call_args_list]
    assert len(calls) == 4  # Lease read, two inserts, then parent completion.
    expected_children = [
        ("e7f37869-6703-5d89-bdd2-188e488fe4f1", STAFF),
        ("5b68146b-950c-5a69-a638-24e22fc0cbbc", OTHER_STAFF),
    ]  # Fixed UUIDv5 examples, not recomputed with the production algorithm.
    for (sql, params), (child, recipient) in zip(calls[1:3], expected_children, strict=True):
        assert 'INSERT INTO public."VenueNotificationOutbox"' in sql
        assert "(source_id,type,booking_id,source,created_at)" in sql
        assert params[:3] == (child, "venue.booking-submission", BOOKING_ID)
        assert params[3].adapted == {**SOURCE, "recipientId": recipient,
                                   "eventName": "Community Fair", "venueName": "Grand Hall"}
        assert params[4] == STAMP
    sql, params = calls[-1]
    assert 'UPDATE public."VenueNotificationOutbox" SET published_at=now()' in sql
    assert "lease_until=NULL,lease_token=NULL,last_error=NULL" in sql
    assert params == (JOB,)
    assert row["source"] == SOURCE
    connection.__exit__.assert_called_once_with(None, None, None)


@pytest.mark.parametrize("kind,change", [
    pytest.param("venue.booking-decision", {}, id="wrong-parent-kind"),
    pytest.param("venue.booking-submission-fanout", {"recipientIds": STAFF}, id="recipients-not-list"),
    pytest.param("venue.booking-submission-fanout", {"recipientIds": []}, id="no-staff"),
    pytest.param("venue.booking-submission-fanout", {"recipientIds": ["not-a-uuid"]}, id="invalid-staff-id"),
    pytest.param("venue.booking-submission-fanout", {"eventName": 42}, id="invalid-event-name"),
    pytest.param("venue.booking-submission-fanout", {"venueName": " "}, id="blank-venue-name"),
])
def test_ac1_invalid_expansion_never_creates_children_or_completes_parent(owner, kind, change):
    """Failure: invalid fanout inputs leave the parent retryable without any child/completion write."""
    client, cursor, row, connection = owner
    row["type"] = kind

    result = operate(client, "expand", **(EXPANSION | change))

    assert result.status_code == 400
    assert result.json == {"message": "Invalid outbox input."}
    assert len(cursor.execute.call_args_list) == 1
    assert "SELECT" in cursor.execute.call_args.args[0]
    assert connection.__exit__.call_args.args[0] in (ValueError, TypeError, AttributeError)


# AC1/AC2 — freeze; DR: retain recipient and original decision, not current ownership.
@pytest.mark.parametrize("outcome", ["submission", "Approved", "Rejected"])
def test_ac1_ac2_valid_booking_history_is_frozen_and_returned_exactly(owner, outcome):
    """Normal: each supported booking outcome freezes the exact recipient, content and destination."""
    # Arrange: isolate the driver while retaining the real route and owner logic.
    client, cursor, row, connection = owner
    envelope = booking_envelope(outcome)
    row.update(type=envelope["type"], source=deepcopy(envelope["details"]))
    cursor.fetchone.side_effect = [row, {**row, "envelope": deepcopy(envelope)}]

    # Act: enter through the public HTTP boundary.
    result = operate(client, "freeze", envelope=envelope)

    # Assert: response and write/transaction outcomes, not just executed lines.
    assert result.status_code == 200
    assert result.json == dict(id=JOB, type=envelope["type"], source=envelope["details"],
                               envelope=envelope, leaseToken=TOKEN, attempts=1,
                               createdAt="2026-10-27T00:00:00+00:00")
    assert len(cursor.execute.call_args_list) == 2
    sql, (saved, identifier) = cursor.execute.call_args.args
    assert "SET envelope=%s" in sql and "RETURNING *" in sql
    assert saved.adapted == envelope and identifier == JOB
    connection.__exit__.assert_called_once_with(None, None, None)


@pytest.mark.parametrize("outcome,recipient,decision", [
    pytest.param("submission", OTHER_STAFF, None, id="submission-recipient-mismatch"),
    pytest.param("Approved", STAFF, None, id="decision-recipient-mismatch"),
    pytest.param("Approved", USER_ID, "Pending Review", id="unsupported-decision"),
])
def test_ac1_ac2_inconsistent_booking_contract_is_never_frozen(owner, outcome, recipient, decision):
    """Failure: changing the captured recipient or using an unsupported decision cannot freeze history."""
    client, cursor, row, connection = owner
    envelope = booking_envelope(outcome)
    if decision is not None:
        envelope["details"]["decision"] = decision
    row.update(type=envelope["type"], source=deepcopy(envelope["details"]))
    envelope["recipientId"] = recipient

    result = operate(client, "freeze", envelope=envelope)

    assert result.status_code == 400
    assert result.json == {"message": "Invalid outbox input."}
    assert len(cursor.execute.call_args_list) == 1
    assert connection.__exit__.call_args.args[0] is ValueError


# DR supporting AC1/AC2 — mutation and intent share the failing transaction.
@pytest.mark.parametrize("action", ["submit", "approve", "reject"])
def test_ac1_ac2_failed_intent_rolls_back_the_business_transaction(setup, action):
    """Failure: intent insertion failure refuses submission or decision and requests rollback, never commit."""
    # Arrange: isolate the driver while retaining the real route and owner logic.
    client, cursor = setup
    connection = cursor.connection
    cursor.fetchall.return_value = []
    cursor.fetchone.side_effect = ([booking_row()] if action == "submit" else
                                  [booking_row(), booking_row(status="Approved" if action == "approve" else "Rejected")])
    failure = psycopg2.OperationalError("synthetic intent write failure")

    def execute(sql, *args):
        if 'INSERT INTO public."VenueNotificationOutbox"' in sql:
            raise failure

    def finish_transaction(error_type, error, traceback):
        # Model psycopg2's external transaction protocol; this is not a durable rollback.
        if error_type is None:
            connection.commit()
        else:
            connection.rollback()
        return False

    cursor.execute.side_effect = execute
    connection.__exit__.side_effect = finish_transaction

    # Act: enter through the public HTTP boundary.
    if action == "submit":
        result = client.post("/venue-bookings", json=dict(
            eventId=EVENT_ID, venueId=VENUE_ID, requestedBy=USER_ID,
            requestedStartTime="2099-01-01T09:00", requestedEndTime="2099-01-01T11:00",
            requiredCapacity=80, venueRequirements="Projector"))
    else:
        # Rejection input only satisfies the upstream decision workflow, not a SCRUM-47 assertion.
        result = client.patch(f"/venue-bookings/{BOOKING_ID}/{action}",
                              json={"reviewedBy": STAFF, "rejectionReason": "Fixture input"})

    # Assert: response and write/transaction outcomes, not just executed lines.
    assert result.status_code == 503
    connection.__exit__.assert_called_once()
    error_type, error, traceback = connection.__exit__.call_args.args
    assert error_type is psycopg2.OperationalError and error is failure and traceback is not None
    connection.rollback.assert_called_once()
    connection.commit.assert_not_called()
    connection.close.assert_called_once()
    writes = [call.args[0] for call in cursor.execute.call_args_list]
    assert any('INSERT INTO public."VenueBooking"' in sql or
               'UPDATE public."VenueBooking"' in sql for sql in writes[:-1])
    assert 'INSERT INTO public."VenueNotificationOutbox"' in writes[-1]
