"""
SCRUM-47: Venue Booking Notification and Decision Alerts

User Story
----------
As an Event Coordinator and Venue Staff, I want to receive notifications about
venue booking requests and decisions, so that I can coordinate venue
arrangements efficiently.

Acceptance Criteria
-------------------
AC1: Given an Event Coordinator submits a venue booking request, the system
     sends an in-app notification to Venue Staff with the event name, requested
     venue, date/time, and a link to review the request.
AC2: Given a venue booking request is approved or rejected, the system sends an
     in-app notification to the Event Coordinator with the event name, venue,
     and decision.

Real
----
- The booking notification outbox: Venue Staff fan-out (one child per distinct
  staff member), freezing each outcome's exact recipient, content and link, and
  rollback of the business change when the intent cannot be saved.
- Assertions are on the SQL sent, the frozen envelope and the rollback.

Doubled
-------
- psycopg2.connect: Stub (`setup`/`client` fixtures) - fresh MagicMock
  connection; the cursor returns canned VenueBooking / VenueClosure rows (or
  raises); executed SQL, parameters and locks are inspected.

Not proven
----------
- That the SQL, locks and constraints behave the same on real PostgreSQL (->
  tests/integration/, throwaway postgres:17.6).
"""
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import MagicMock

import psycopg2
import pytest

from app import create_app
from tests.unit.factories import bearer, BOOKING_ID, EVENT_ID, USER_ID, VENUE_ID, booking_row, signed_in

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
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": "synthetic"}).test_client())
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


def test_submission_alert_fans_out_once_per_staff_member(owner):
    """
    Summary: A submission alert goes to each Venue Staff member once, even if they are listed twice.
    AC1: Given an Event Coordinator submits a venue booking request, the system
        sends an in-app notification to Venue Staff with the event name,
        requested venue, date/time, and a link to review the request.
    Double: Stub (staff lookup with duplicates; inserts inspected)
    """
    # Arrange (Given)
    # Arrange: isolate the driver while retaining the real route and owner logic.
    client, cursor, row, connection = owner

    # Act (When)
    # Act: enter through the public HTTP boundary.
    result = operate(client, "expand", **EXPANSION)

    # Assert (Then)
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
def test_submission_alert_with_bad_staff_list_stays_retryable(owner, kind, change):
    """
    Summary: A bad staff list creates no alerts and leaves the job to retry.
    AC1: Given an Event Coordinator submits a venue booking request, the system
        sends an in-app notification to Venue Staff with the event name,
        requested venue, date/time, and a link to review the request.
    Double: Stub (invalid staff lookup), Mock (no inserts)
    """
    # Arrange (Given)
    client, cursor, row, connection = owner
    row["type"] = kind

    # Act (When)
    result = operate(client, "expand", **(EXPANSION | change))

    # Assert (Then)
    assert result.status_code == 400
    assert result.json == {"message": "Invalid outbox input."}
    assert len(cursor.execute.call_args_list) == 1
    assert "SELECT" in cursor.execute.call_args.args[0]
    assert connection.__exit__.call_args.args[0] in (ValueError, TypeError, AttributeError)


@pytest.mark.parametrize("outcome", ["submission", "Approved", "Rejected"], ids=["submission", "approved", "rejected"])
def test_booking_alert_freezes_exact_recipient_content_and_link(owner, outcome):
    """
    Summary: Each booking alert is frozen with its exact recipient, content and link.
    AC1: Given an Event Coordinator submits a venue booking request, the system
        sends an in-app notification to Venue Staff with the event name,
        requested venue, date/time, and a link to review the request.
    AC2: Given a venue booking request is approved or rejected, the system
        sends an in-app notification to the Event Coordinator with the event
        name, venue, and decision.
    Double: Stub (cursor returns the job; update inspected)
    """
    # Arrange (Given)
    # Arrange: isolate the driver while retaining the real route and owner logic.
    client, cursor, row, connection = owner
    envelope = booking_envelope(outcome)
    row.update(type=envelope["type"], source=deepcopy(envelope["details"]))
    cursor.fetchone.side_effect = [row, {**row, "envelope": deepcopy(envelope)}]

    # Act (When)
    # Act: enter through the public HTTP boundary.
    result = operate(client, "freeze", envelope=envelope)

    # Assert (Then)
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
def test_booking_alert_with_changed_recipient_or_decision_is_not_frozen(owner, outcome, recipient, decision):
    """
    Summary: An alert whose recipient or decision changed is never frozen.
    AC1: Given an Event Coordinator submits a venue booking request, the system
        sends an in-app notification to Venue Staff with the event name,
        requested venue, date/time, and a link to review the request.
    AC2: Given a venue booking request is approved or rejected, the system
        sends an in-app notification to the Event Coordinator with the event
        name, venue, and decision.
    Double: Stub (cursor returns the job)
    """
    # Arrange (Given)
    client, cursor, row, connection = owner
    envelope = booking_envelope(outcome)
    if decision is not None:
        envelope["details"]["decision"] = decision
    row.update(type=envelope["type"], source=deepcopy(envelope["details"]))
    envelope["recipientId"] = recipient

    # Act (When)
    result = operate(client, "freeze", envelope=envelope)

    # Assert (Then)
    assert result.status_code == 400
    assert result.json == {"message": "Invalid outbox input."}
    assert len(cursor.execute.call_args_list) == 1
    assert connection.__exit__.call_args.args[0] is ValueError


@pytest.mark.parametrize("action", ["submit", "approve", "reject"], ids=["submit", "approve", "reject"])
def test_booking_change_when_alert_cannot_be_queued_rolls_back(setup, action):
    """
    Summary: If the alert cannot be queued, the submission or decision is rolled back too.
    AC1: Given an Event Coordinator submits a venue booking request, the system
        sends an in-app notification to Venue Staff with the event name,
        requested venue, date/time, and a link to review the request.
    AC2: Given a venue booking request is approved or rejected, the system
        sends an in-app notification to the Event Coordinator with the event
        name, venue, and decision.
    Double: Stub (outbox insert raises), Mock (rollback)
    """
    # Arrange (Given)
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

    # Act (When)
    # Act: enter through the public HTTP boundary.
    if action == "submit":
        result = client.post("/venue-bookings", json=dict(
            eventId=EVENT_ID, venueId=VENUE_ID, requestedBy=USER_ID,
            requestedStartTime="2099-01-01T09:00", requestedEndTime="2099-01-01T11:00",
            requiredCapacity=80, venueRequirements="Projector"))
    else:
        # Rejection input only satisfies the upstream decision workflow, not a SCRUM-47 assertion.
        result = client.patch(f"/venue-bookings/{BOOKING_ID}/{action}",
                              json={"reviewedBy": STAFF, "rejectionReason": "Fixture input"},
                              headers=bearer(USER_ID, "Venue Staff"))

    # Assert (Then)
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
