"""
SCRUM-29: Venue Booking Review and Decision

User Story
----------
As a Venue Staff member, I want to review and decide on a pending venue booking
request, so that I can determine whether the requested venue arrangement can be
accepted and provide the Event Coordinator with the outcome.

Acceptance Criteria
-------------------
AC1: Given a venue booking request is pending review, when Venue Staff open the
     request, then they can view the relevant event timing and venue
     requirements needed to assess the booking.
AC2: Given Venue Staff determine that a pending venue booking request can be
     accepted, when they approve the request, then the booking decision is
     recorded as approved and the outcome is available to the relevant Event
     Coordinator.
AC3: Given Venue Staff determine that a pending venue booking request cannot be
     accepted, when they reject the request, then the booking decision is
     recorded as rejected and the outcome is available to the relevant Event
     Coordinator.
AC4: Given a venue booking request cannot be accepted, when Venue Staff record
     their decision, then they can provide relevant information or a reason
     explaining why the booking cannot be accepted.
AC5: Given Venue Staff have recorded an approval or rejection for a pending
     venue booking request, when the decision is completed, then the request is
     no longer presented as awaiting a booking decision.
AC6: Given a booking request has been rejected and Venue Staff have provided
     relevant information or a reason, when the Event Coordinator views the
     booking decision, then they can view that information so that they can
     continue planning the event.

Real
----
- PATCH /venue-bookings/<id>/approve and .../reject: the reviewer and decision
  time, the reason rules (required on reject, at most 500, never stored on
  approve), the decided/immutable guards and the alert intent run for real, as
  does the serializer.
- Assertions are on the status, codes, stored values and SQL.

Doubled
-------
- psycopg2.connect: Stub (`setup`/`client` fixtures) - fresh MagicMock
  connection; the cursor returns canned VenueBooking / VenueClosure rows (or
  raises); executed SQL, parameters and locks are inspected.

Not proven
----------
- That the overlap SQL, locks and constraints behave the same on real
  PostgreSQL (-> tests/integration/, throwaway postgres:17.6, and the opt-in
  tests/live/test_calendar.py).
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app import create_app
from app import models
from tests.unit.factories import (
    BOOKING_ID, EVENT_ID, USER_ID, VENUE_ID,
    assert_booking_intent, assert_no_booking_intent, bearer, booking_row, signed_in,
)

REASON = "Hall is too small for the stage"
REVIEWER_ID = "00000000-0000-0000-0000-000000000002"


def _update_call(cursor):
    """Return (sql, params) of the decision UPDATE."""
    return next(
        call.args
        for call in cursor.execute.call_args_list
        if call.args[0].lstrip().startswith('UPDATE public."VenueBooking"')
    )


def _decide(client, action, reviewedBy=USER_ID, **body):
    """Decide as the signed-in Venue Staff reviewer (SCRUM-8: the reviewer comes from the token)."""
    return client.patch(
        f"/venue-bookings/{BOOKING_ID}/{action}",
        json=body,
        headers=bearer(reviewedBy, "Venue Staff"),
    )


# AC2 ------------------------------------------------------------------------


def test_approve_booking_records_reviewer_time_and_queues_alert(setup):
    """
    Summary: An approval records who decided and when, and alerts the coordinator who asked.
    AC2: Given Venue Staff determine that a pending venue booking request can
        be accepted, when they approve the request, then the booking decision
        is recorded as approved and the outcome is available to the relevant
        Event Coordinator.
    Double: Stub (cursor returns rows), Mock (outbox insert inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = []
    cursor.fetchone.side_effect = [
        booking_row(),
        booking_row(
            status="Approved",
            reviewed_by=REVIEWER_ID,
            reviewed_at=datetime(2030, 1, 2, 3, 4, tzinfo=timezone.utc),
        ),
    ]

    # Act (When)
    response = _decide(client, "approve", reviewedBy=REVIEWER_ID)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Approved"
    assert response.json["reviewedBy"] == REVIEWER_ID
    assert response.json["reviewedAt"] == "2030-01-02T11:04:00+08:00"
    sql, params = _update_call(cursor)
    assert "reviewed_at = now()" in sql
    assert "rejection_reason = %s" in sql
    assert params == ["Approved", REVIEWER_ID, None, BOOKING_ID]
    assert_booking_intent(cursor, "venue.booking-decision", {
        "bookingId": BOOKING_ID, "eventId": EVENT_ID, "venueId": VENUE_ID,
        "requestedBy": USER_ID, "startDateTime": "2026-10-01T09:00:00+08:00",
        "endDateTime": "2026-10-01T12:00:00+08:00", "decision": "Approved",
    })


def test_approve_booking_with_reason_stores_no_reason(setup):
    """
    Summary: A reason sent with an approval is not stored.
    AC2: Given Venue Staff determine that a pending venue booking request can
        be accepted, when they approve the request, then the booking decision
        is recorded as approved and the outcome is available to the relevant
        Event Coordinator.
    Double: Stub (cursor returns rows; update inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = []
    cursor.fetchone.side_effect = [booking_row(), booking_row(status="Approved")]

    # Act + Assert (When / Then)
    assert _decide(client, "approve", rejectionReason=REASON).status_code == 200
    assert _update_call(cursor)[1][2] is None


def test_review_model_for_approval_stores_null_reason(monkeypatch):
    """
    Summary: The model also stores no reason for an approval.
    AC2: Given Venue Staff determine that a pending venue booking request can
        be accepted, when they approve the request, then the booking decision
        is recorded as approved and the outcome is available to the relevant
        Event Coordinator.
    Double: Stub (cursor; parameters inspected)
    """
    # Arrange (Given)
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    cursor.fetchone.side_effect = [booking_row(), booking_row(status="Approved")]
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: connection)

    # Act (When)
    models.decide_booking("unused", BOOKING_ID, USER_ID, "Approved", 0, 0, REASON)

    # Assert (Then)
    assert _update_call(cursor)[1][2] is None


def test_booking_serializer_returns_decision_time_in_singapore_and_reason():
    """
    Summary: The decision time is shown in Singapore time with the reason.
    AC2: Given Venue Staff determine that a pending venue booking request can
        be accepted, when they approve the request, then the booking decision
        is recorded as approved and the outcome is available to the relevant
        Event Coordinator.
    AC6: Given a booking request has been rejected and Venue Staff have
        provided relevant information or a reason, when the Event Coordinator
        views the booking decision, then they can view that information so that
        they can continue planning the event.
    Double: None
    """
    # Arrange (Given)
    row = booking_row(
        status="Rejected",
        reviewed_at=datetime(2030, 1, 1, 16, 30, tzinfo=timezone.utc),
        rejection_reason=REASON,
    )

    # Act (When)
    result = models.serialize(row)

    # Assert (Then)
    assert result["reviewedAt"] == "2030-01-02T00:30:00+08:00"
    assert result["rejectionReason"] == REASON


@pytest.mark.parametrize("value", ["absent", None], ids=["column_absent", "column_null"])
def test_booking_serializer_without_decision_returns_null_fields(value):
    """
    Summary: Undecided or older bookings show no decision fields.
    AC2: Given Venue Staff determine that a pending venue booking request can
        be accepted, when they approve the request, then the booking decision
        is recorded as approved and the outcome is available to the relevant
        Event Coordinator.
    Double: None
    """
    # Arrange (Given)
    row = booking_row()
    if value != "absent":
        row.update(reviewed_at=value, rejection_reason=value)

    # Act (When)
    result = models.serialize(row)

    # Assert (Then)
    assert result["reviewedAt"] is None
    assert result["rejectionReason"] is None


# AC3 ------------------------------------------------------------------------


def test_reject_booking_records_reason_and_queues_alert(setup):
    """
    Summary: A rejection is recorded with its reason and alerts the coordinator.
    AC3: Given Venue Staff determine that a pending venue booking request
        cannot be accepted, when they reject the request, then the booking
        decision is recorded as rejected and the outcome is available to the
        relevant Event Coordinator.
    AC4: Given a venue booking request cannot be accepted, when Venue Staff
        record their decision, then they can provide relevant information or a
        reason explaining why the booking cannot be accepted.
    Double: Stub (cursor returns rows), Mock (outbox insert inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [
        booking_row(),
        booking_row(status="Rejected", reviewed_by=REVIEWER_ID, rejection_reason=REASON),
    ]

    # Act (When)
    response = _decide(client, "reject", reviewedBy=REVIEWER_ID, rejectionReason=f"  {REASON}\n")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Rejected"
    assert response.json["rejectionReason"] == REASON
    sql, params = _update_call(cursor)
    assert "reviewed_at = now()" in sql
    assert params == ["Rejected", REVIEWER_ID, REASON, BOOKING_ID]
    assert_booking_intent(cursor, "venue.booking-decision", {
        "bookingId": BOOKING_ID, "eventId": EVENT_ID, "venueId": VENUE_ID,
        "requestedBy": USER_ID, "startDateTime": "2026-10-01T09:00:00+08:00",
        "endDateTime": "2026-10-01T12:00:00+08:00", "decision": "Rejected",
    })


@pytest.mark.parametrize("status", ["Rejected", "Cancelled"], ids=["rejected", "cancelled"])
def test_change_rejected_or_cancelled_booking_returns_immutable(setup, status):
    """
    Summary: A rejected or cancelled booking cannot be changed.
    AC5: Given Venue Staff have recorded an approval or rejection for a pending
        venue booking request, when the decision is completed, then the request
        is no longer presented as awaiting a booking decision.
    Double: Stub (cursor returns the closed booking)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = booking_row(status=status)

    # Act (When)
    response = _decide(client, "reject", rejectionReason=REASON)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "BOOKING_IMMUTABLE"
    assert not any("UPDATE public" in c.args[0] for c in cursor.execute.call_args_list)
    assert_no_booking_intent(cursor)


# AC4 ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [{}, {"rejectionReason": ""}, {"rejectionReason": "   "}, {"rejectionReason": 42}],
    ids=["missing", "empty", "blank", "non-string"],
)
def test_reject_booking_without_reason_returns_400_before_database(setup, body):
    """
    Summary: A rejection without a reason never reaches the database.
    AC4: Given a venue booking request cannot be accepted, when Venue Staff
        record their decision, then they can provide relevant information or a
        reason explaining why the booking cannot be accepted.
    Double: Mock (cursor not executed)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = _decide(client, "reject", **body)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["code"] == "REJECTION_REASON_REQUIRED"
    cursor.execute.assert_not_called()


def test_reject_booking_with_500_character_reason_is_accepted(setup):
    """
    Summary: A reason of up to 500 characters is accepted.
    AC4: (boundary: reason length = 500)
    Double: Stub (cursor returns rows)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [booking_row(), booking_row(status="Rejected")]

    # Act + Assert (When / Then)
    assert _decide(client, "reject", rejectionReason="x" * 500).status_code == 200
    assert _update_call(cursor)[1][2] == "x" * 500


def test_reject_booking_with_501_character_reason_returns_400(setup):
    """
    Summary: A reason one character over the limit is refused.
    AC4: (boundary: reason length = 501)
    Double: Mock (cursor not executed)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = _decide(client, "reject", rejectionReason="x" * 501)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["code"] == "REJECTION_REASON_REQUIRED"
    cursor.execute.assert_not_called()


# AC5 ------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["Approved", "On Hold", "Expired"], ids=["approved", "on_hold", "expired"])
@pytest.mark.parametrize("action,body", [("approve", {}), ("reject", {"rejectionReason": REASON})], ids=["approve", "reject"])
def test_decide_booking_not_awaiting_decision_returns_409(setup, status, action, body):
    """
    Summary: A booking that is already decided, on hold or expired cannot be decided.
    AC5: Given Venue Staff have recorded an approval or rejection for a pending
        venue booking request, when the decision is completed, then the request
        is no longer presented as awaiting a booking decision.
    Double: Stub (cursor returns the row)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = booking_row(status=status)

    # Act (When)
    response = _decide(client, action, **body)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "BOOKING_ALREADY_DECIDED"
    assert not any("UPDATE public" in c.args[0] for c in cursor.execute.call_args_list)
    assert_no_booking_intent(cursor)


def test_decide_booking_with_legacy_pending_status_is_allowed(setup):
    """
    Summary: Older bookings marked Pending can still be decided.
    AC5: Given Venue Staff have recorded an approval or rejection for a pending
        venue booking request, when the decision is completed, then the request
        is no longer presented as awaiting a booking decision.
    Double: Stub (cursor returns a Pending row)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = []
    cursor.fetchone.side_effect = [
        booking_row(status="Pending"),
        booking_row(status="Approved", reviewed_by=USER_ID),
    ]

    # Act (When)
    response = _decide(client, "approve")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Approved"


def test_edit_or_safety_reset_clears_previous_decision(setup):
    """
    Summary: A booking sent back to review loses its old decision.
    AC5: Given Venue Staff have recorded an approval or rejection for a pending
        venue booking request, when the decision is completed, then the request
        is no longer presented as awaiting a booking decision.
    Double: Stub (cursor; SQL inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = []
    cursor.fetchone.side_effect = [booking_row(status="Approved"), booking_row()]

    # Act (When)
    edit = client.patch(
        f"/venue-bookings/{BOOKING_ID}",
        json={
            "eventId": EVENT_ID,
            "venueId": VENUE_ID,
            "requestedStartTime": "2030-10-01T09:00",
            "requestedEndTime": "2030-10-01T12:00",
            "requiredCapacity": 80,
            "venueRequirements": "Projector",
        },
    )

    # Assert (Then)
    assert edit.status_code == 200
    assert "reviewed_at = NULL, rejection_reason = NULL" in _update_call(cursor)[0]

    cursor.reset_mock()
    cursor.fetchall.side_effect = [[booking_row(status="Approved")], [booking_row()]]
    client.application.config["INTERNAL_SERVICE_TOKEN"] = "test-token"
    reset = client.post(
        f"/events/{EVENT_ID}/venue-bookings/safety-reset",
        headers={"X-Internal-Service-Token": "test-token", **bearer(USER_ID, "Safety Officer")},
        json={"bookingIds": [BOOKING_ID]},
    )
    assert reset.status_code == 200
    assert "reviewed_at = NULL, rejection_reason = NULL" in _update_call(cursor)[0]


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_reject_booking_when_database_url_missing_returns_503():
    """
    Summary: A valid rejection still needs a configured database.
    Supporting design check: an unconfigured service answers 503
    Double: None
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client())
    assert _decide(client, "reject", rejectionReason=REASON).status_code == 503
