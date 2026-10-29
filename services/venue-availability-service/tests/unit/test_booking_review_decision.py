"""SCRUM-29 Venue Booking Review and Decision — Venue Availability unit tests.

As a Venue Staff member, I want to review and decide on a pending venue
booking request, so that I can determine whether the requested venue
arrangement can be accepted and provide the Event Coordinator with the outcome.

This atomic owns the stored decision: who decided, when, the rejection reason,
and the rule that only an undecided booking can be decided. AC1 (opening the
request with the event's details) and the role/event-status gates live in
Venue Booking Service and are tested there.


SCRUM-47 Venue booking notification and decision alerts (additional assertions only).
Story: As an Event Coordinator and Venue Staff, I want to receive notifications
about venue booking requests and decisions, so that I can coordinate venue
arrangements efficiently.
AC1 Given an Event Coordinator submits a venue booking request, system sends
an in-app notification to Venue Staff with event name, requested venue,
date/time and link to review.
AC2 Given booking approved/rejected, sends an in-app notification to Event
Coordinator with event name, venue, decision.
AC means acceptance criterion; DR means supporting design rule. Original story
AC numbering below is unchanged; SCRUM-47 has only AC1 and AC2.
Real: Flask routes, validation and model transaction/SQL construction.
Doubled: psycopg2 connection/cursor; SQL ordering is not durable-commit proof.
SCRUM-47 AC2: approval/rejection retain the original requestedBy and decision.
SCRUM-47 AC1: submission intent is verified in test_booking_request_submission.py.
Not proven here: all-staff fanout, display text, links or inbox delivery; the
three Venue Booking dispatcher unit cases cover content/recipients/links, not delivery.
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


def test_ac2_approval_stamps_reviewer_and_decision_time(setup):
    """Normal: approval records its reviewer/time and queues the original submitter's alert."""
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

    response = _decide(client, "approve", reviewedBy=REVIEWER_ID)

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


def test_ac2_reason_sent_with_an_approval_is_not_stored(setup):
    """Boundary: an approval never carries a rejection reason."""
    client, cursor = setup
    cursor.fetchall.return_value = []
    cursor.fetchone.side_effect = [booking_row(), booking_row(status="Approved")]

    assert _decide(client, "approve", rejectionReason=REASON).status_code == 200
    assert _update_call(cursor)[1][2] is None


def test_ac2_model_ignores_reason_passed_with_an_approval(monkeypatch):
    """Boundary: the model, too, stores NULL for an approval's reason."""
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    cursor.fetchone.side_effect = [booking_row(), booking_row(status="Approved")]
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: connection)
    models.decide_booking("unused", BOOKING_ID, USER_ID, "Approved", 0, 0, REASON)
    assert _update_call(cursor)[1][2] is None


def test_ac2_serialise_includes_decision_time_in_singapore_and_reason():
    """Normal: a UTC decision time is returned in Singapore time with the reason."""
    row = booking_row(
        status="Rejected",
        reviewed_at=datetime(2030, 1, 1, 16, 30, tzinfo=timezone.utc),
        rejection_reason=REASON,
    )
    result = models.serialize(row)
    assert result["reviewedAt"] == "2030-01-02T00:30:00+08:00"
    assert result["rejectionReason"] == REASON


@pytest.mark.parametrize("value", ["absent", None])
def test_ac2_undecided_or_legacy_row_serialises_decision_fields_as_null(value):
    """Boundary: rows without a decision (or the columns) serialise as None."""
    row = booking_row()
    if value != "absent":
        row.update(reviewed_at=value, rejection_reason=value)
    result = models.serialize(row)
    assert result["reviewedAt"] is None
    assert result["rejectionReason"] is None


# AC3 ------------------------------------------------------------------------


def test_ac3_rejection_is_recorded_with_its_reason(setup):
    """Normal: rejection records the decision and queues the original submitter's alert."""
    client, cursor = setup
    cursor.fetchone.side_effect = [
        booking_row(),
        booking_row(status="Rejected", reviewed_by=REVIEWER_ID, rejection_reason=REASON),
    ]

    response = _decide(client, "reject", reviewedBy=REVIEWER_ID, rejectionReason=f"  {REASON}\n")

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


@pytest.mark.parametrize("status", ["Rejected", "Cancelled"])
def test_ac3_rejected_or_cancelled_booking_stays_immutable(setup, status):
    """Conflict: rejected and cancelled bookings keep their BOOKING_IMMUTABLE code."""
    client, cursor = setup
    cursor.fetchone.return_value = booking_row(status=status)

    response = _decide(client, "reject", rejectionReason=REASON)

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
def test_ac4_reject_without_reason_is_refused(setup, body):
    """Failure: a rejection with no usable reason never reaches the database."""
    client, cursor = setup

    response = _decide(client, "reject", **body)

    assert response.status_code == 400
    assert response.json["code"] == "REJECTION_REASON_REQUIRED"
    cursor.execute.assert_not_called()


def test_ac4_reason_of_exactly_500_characters_is_accepted(setup):
    """Boundary: 500 characters is the longest reason accepted."""
    client, cursor = setup
    cursor.fetchone.side_effect = [booking_row(), booking_row(status="Rejected")]

    assert _decide(client, "reject", rejectionReason="x" * 500).status_code == 200
    assert _update_call(cursor)[1][2] == "x" * 500


def test_ac4_reason_of_501_characters_is_refused(setup):
    """Boundary: one character over the limit is refused before any SQL."""
    client, cursor = setup

    response = _decide(client, "reject", rejectionReason="x" * 501)

    assert response.status_code == 400
    assert response.json["code"] == "REJECTION_REASON_REQUIRED"
    cursor.execute.assert_not_called()


# AC5 ------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["Approved", "On Hold", "Expired"])
@pytest.mark.parametrize("action,body", [("approve", {}), ("reject", {"rejectionReason": REASON})])
def test_ac5_already_approved_booking_cannot_be_decided_again(setup, status, action, body):
    """Conflict: a decided (or non-request) row is refused and left untouched."""
    client, cursor = setup
    cursor.fetchone.return_value = booking_row(status=status)

    response = _decide(client, action, **body)

    assert response.status_code == 409
    assert response.json["code"] == "BOOKING_ALREADY_DECIDED"
    assert not any("UPDATE public" in c.args[0] for c in cursor.execute.call_args_list)
    assert_no_booking_intent(cursor)


def test_ac5_legacy_pending_spelling_can_still_be_decided(setup):
    """Normal: legacy 'Pending' rows count as awaiting a decision."""
    client, cursor = setup
    cursor.fetchall.return_value = []
    cursor.fetchone.side_effect = [
        booking_row(status="Pending"),
        booking_row(status="Approved", reviewed_by=USER_ID),
    ]

    response = _decide(client, "approve")

    assert response.status_code == 200
    assert response.json["status"] == "Approved"


def test_ac5_edit_or_safety_reset_clears_previous_decision(setup):
    """Normal: a booking sent back to review drops the old decision fields."""
    client, cursor = setup
    cursor.fetchall.return_value = []
    cursor.fetchone.side_effect = [booking_row(status="Approved"), booking_row()]

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
    assert edit.status_code == 200
    assert "reviewed_at = NULL, rejection_reason = NULL" in _update_call(cursor)[0]

    cursor.reset_mock()
    cursor.fetchall.side_effect = [[booking_row(status="Approved")], [booking_row()]]
    client.application.config["INTERNAL_SERVICE_TOKEN"] = "test-token"
    reset = client.post(
        f"/events/{EVENT_ID}/venue-bookings/safety-reset",
        headers={"X-Internal-Service-Token": "test-token"},
        json={"bookingIds": [BOOKING_ID]},
    )
    assert reset.status_code == 200
    assert "reviewed_at = NULL, rejection_reason = NULL" in _update_call(cursor)[0]


def test_decision_requires_configured_database_after_validation():
    """Failure: a valid rejection still needs the database to be configured."""
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client())
    assert _decide(client, "reject", rejectionReason=REASON).status_code == 503
