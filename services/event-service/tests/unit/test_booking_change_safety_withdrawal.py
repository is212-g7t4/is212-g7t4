"""
SCRUM-153: Re-check Safety After High-Impact Changes

User Story
----------
As an Event Coordinator, I want a safety approval to be withdrawn when a
high-impact detail changes afterwards, so that the event is never prepared on
the basis of an outdated safety review.

Acceptance Criteria
-------------------
AC1: Given an event is 'Confirmed', when its date/time, expected attendance,
     venue requirements, equipment requirements or accessibility needs change,
     then its status returns to 'Pending Safety Check' and the coordinator is
     told why.
AC2: Given only a low-impact field changes (name, description, purpose,
     registration needs), then the event stays 'Confirmed'.
AC3: Given a safety approval is withdrawn, then it stays visible in the event's
     safety history.
AC4: Given a high-impact change to a 'Confirmed' event is waiting for its new
     safety check, when a registered Attendee views the event, then they still
     see the previously approved details, and the changed details are shown to
     them only after the Safety Officer approves the new safety check.
AC5: Given the new safety check ends without approval (changes requested or the
     event is cancelled), then registered Attendees are never shown the
     unapproved change, and they continue to see the last approved details or
     the cancellation.

SCRUM-28: Venue Booking Request Submission

User Story
----------
As an Event Coordinator, I want to submit a venue booking request for an event,
so that Venue Staff can assess whether the requested venue arrangement can be
accepted.

Acceptance Criteria
-------------------
AC1: Given an Event Coordinator is preparing a venue booking request for an
     event, when they enter the booking information, then they can provide the
     relevant event timing and venue requirements needed for Venue Staff to
     assess the booking.
AC2: Given the relevant event timing and venue requirements have been provided,
     when the Event Coordinator submits the venue booking request, then the
     request is recorded and made available to Venue Staff for review.
AC3: Given a venue booking request has been submitted, when Venue Staff access
     the request, then they can view the event to which the request relates
     together with the relevant event timing and venue requirements.
AC4: Given a venue booking request has been submitted and has not yet received
     a booking decision, when Venue Staff view requests requiring action, then
     the request can be identified as awaiting Venue Staff review.
AC5: Given an Event Coordinator submits a venue booking request for an event,
     when the request is recorded, then it remains associated with that event
     so that the booking can be assessed in the context of the corresponding
     event requirements.
AC6: Given an Event Coordinator submits a venue booking request for a venue and
     time slot, when the same venue has already been requested or booked for
     another event, and the requested event timing does not overlap with that
     other event's timing, then the request is accepted for Venue Staff review
     as normal, so the same venue can be booked for multiple events across
     non-overlapping time slots.
AC7: Given an event is 'Confirmed' after passing its Operational Safety Check,
     when the Event Coordinator edits or cancels one of its venue bookings,
     then the event's safety approval is withdrawn without opening a new safety
     check round, the event returns to 'Approved', and an edited booking
     returns to awaiting Venue Staff review, so the event must be submitted for
     a safety check again. If the booking change cannot be saved, the safety
     approval is restored and the event stays 'Confirmed'. While the event is
     'Pending Safety Check', its venue bookings cannot be edited or cancelled.

Real
----
- The Event Service routes in app/__init__.py and the rules in app/models.py,
  run through a real create_app(): request validation, the caller's role and
  ownership checks from the signed token, the status rules, and the SQL and
  parameters sent to the database (including notification outbox rows).
- Assertions are on the HTTP status, the response body and the queries and
  parameters the cursor received.

Doubled
-------
- psycopg2.connect: Stub (fixture) - a MagicMock connection whose cursor
  returns canned rows; Mock - its execute calls are asserted to prove what was
  (or was not) written.
- Supabase JWKS: Stub (tests/conftest.py) - tokens are signed with a throwaway
  ES256 key.

Not proven
----------
- That the SQL runs against the real Postgres schema, constraints and row locks
  (-> tests/integration/ against a throwaway postgres:17.6).
- That the notification outbox rows are delivered (-> Notification Service
  tests and the E2E journeys).
"""
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.models import (
    ALLOWED_TRANSITIONS,
    FIELDS,
    SAFETY_TRANSITIONS,
    VENUE_CHANGE_ONLY_MOVES,
)
from tests.unit.factories import signed_in

EVENT_ID = "00000000-0000-0000-0000-000000000001"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OTHER_COORDINATOR_ID = "22222222-2222-4222-8222-222222222222"
OFFICER_ID = "33333333-3333-4333-8333-333333333333"
ROUND_ID = "55555555-5555-4555-8555-555555555555"
OTHER_ROUND_ID = "66666666-6666-4666-8666-666666666666"
INTERNAL_TOKEN = "test-internal-token"
INTERNAL_HEADERS = {"X-Internal-Token": INTERNAL_TOKEN}
REASON = "The Grand Hall booking changed after safety approval."

APPROVAL = {
    "status": "Confirmed",
    "details": "Operational Safety Check approved (round 1).",
    "decidedBy": OFFICER_ID,
    "safetyCheckId": ROUND_ID,
    "remarks": None,
    "recordedAt": "2026-11-02T02:30:00+00:00",
}
WITHDRAWAL = {
    "status": "Approved",
    "details": "Safety approval withdrawn (round 1): ...",
    "coordinatorId": COORDINATOR_ID,
    "withdrawnSafetyCheckId": ROUND_ID,
    "recordedAt": "2026-11-03T02:30:00+00:00",
}


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url", "INTERNAL_SERVICE_TOKEN": INTERNAL_TOKEN})
    return signed_in(app.test_client()), cursor


def event_row(status, action_history, coordinator_id=COORDINATOR_ID):
    row = {column: "" for column in FIELDS.values()}
    row.update(
        event_id=EVENT_ID,
        event_name="Community Workshop",
        status=status,
        coordinator_id=coordinator_id,
        organiser_id=None,
        submission_date=datetime(2026, 10, 1, 8, tzinfo=UTC),
        preferred_start_date=datetime(2026, 11, 12, 9),
        preferred_end_date=datetime(2026, 11, 12, 17),
        expected_attendance=120,
    )
    row["description"] = json.dumps({
        "_connectsphere": "event-submission-v1",
        "description": "A practical workshop",
        "purpose": "Learning",
        "decision": {"status": "Approved", "coordinatorId": COORDINATOR_ID,
                     "decidedAt": "2026-10-02T01:00:00+00:00", "reason": None},
        "decisionHistory": [],
        "actionDetails": "Venue booked.",
        "actionHistory": action_history,
    })
    return row


def withdraw(client, headers=INTERNAL_HEADERS, **overrides):
    body = {
        "status": "Approved",
        "safetyCheckId": ROUND_ID,
        "roundNumber": 1,
        "coordinatorId": COORDINATOR_ID,
        "withdrawnSafetyCheckId": ROUND_ID,
        "reason": REASON,
        # SCRUM-46 baseline input, not an extra venue-lookup simulation.
        "venueBefore": "Grand Hall",
        **overrides,
    }
    return client.patch(f"/events/{EVENT_ID}/safety-status", json=body, headers=headers)


def restore(client, **overrides):
    body = {
        "status": "Confirmed",
        "safetyCheckId": ROUND_ID,
        "roundNumber": 1,
        "coordinatorId": COORDINATOR_ID,
        "restoredSafetyCheckId": ROUND_ID,
        **overrides,
    }
    return client.patch(f"/events/{EVENT_ID}/safety-status", json=body, headers=INTERNAL_HEADERS)


def written(cursor):
    """The (status, stored metadata) of the UPDATE, or None if nothing was written."""
    updates = [call.args for call in cursor.execute.call_args_list if call.args[0].lstrip().startswith("UPDATE")]
    if not updates:
        return None
    status, description, _ = updates[0][1]
    return status, json.loads(description)


# --- Withdrawal: Confirmed -> Approved ---------------------------------------


def test_withdrawal_moves_a_confirmed_event_back_to_approved(setup):
    """
    Summary: The approval the event holds is withdrawn and the reason is in its history.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [event_row("Confirmed", [APPROVAL]), event_row("Approved", [APPROVAL, WITHDRAWAL])]

    # Act (When)
    response = withdraw(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Approved"
    status, metadata = written(cursor)
    assert status == "Approved"
    entry = metadata["actionHistory"][-1]
    assert entry["status"] == "Approved"
    assert entry["withdrawnSafetyCheckId"] == ROUND_ID
    assert entry["coordinatorId"] == COORDINATOR_ID
    assert REASON in entry["details"]
    assert "FOR UPDATE" in cursor.execute.call_args_list[0].args[0]


def test_withdrawal_must_name_the_approval_the_event_holds(setup):
    """
    Summary: A stale or made-up round can't withdraw the current approval.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row("Confirmed", [{**APPROVAL, "safetyCheckId": OTHER_ROUND_ID}])

    # Act (When)
    response = withdraw(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "STALE_SAFETY_CHECK"
    assert written(cursor) is None


def test_withdrawal_needs_an_approval_in_the_history(setup):
    """
    Summary: A Confirmed event with no recorded approval has nothing to withdraw.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row("Confirmed", [])

    # Act + Assert (When / Then)
    assert withdraw(client).status_code == 409
    assert written(cursor) is None


@pytest.mark.parametrize("status", ["Approved", "Pending Safety Check", "Safety Changes Requested", "Cancelled"])
def test_withdrawal_only_leaves_confirmed(setup, status):
    """
    Summary: Only a Confirmed event has a safety approval to withdraw.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(status, [APPROVAL])

    # Act (When)
    response = withdraw(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "INVALID_SAFETY_TRANSITION"
    assert response.json["currentStatus"] == status
    assert written(cursor) is None


def test_withdrawal_by_an_unassigned_coordinator_is_refused(setup):
    """
    Summary: Only the event's assigned coordinator can change its venue arrangements.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row("Confirmed", [APPROVAL], coordinator_id=OTHER_COORDINATOR_ID)

    # Act + Assert (When / Then)
    assert withdraw(client).status_code == 403
    assert written(cursor) is None


def test_withdrawal_needs_the_internal_token(setup):
    """
    Summary: A browser can't send an event back to Approved directly.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = withdraw(client, headers={})

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["code"] == "INTERNAL_ONLY"
    cursor.execute.assert_not_called()


def test_approved_without_the_withdrawal_marker_is_still_refused(setup):
    """
    Summary: Plain 'Approved' is not a safety status.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = withdraw(client, withdrawnSafetyCheckId=None)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"].startswith("Status must be one of: ")
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"withdrawnSafetyCheckId": "nope"}, "withdrawnSafetyCheckId must be a valid UUID."),
        ({"withdrawnSafetyCheckId": OTHER_ROUND_ID}, "withdrawnSafetyCheckId must match safetyCheckId."),
        ({"reason": "  "}, "reason is required."),
        ({"reason": None}, "reason is required."),
        ({"reason": "x" * 2001}, "reason must be 2000 characters or fewer."),
        ({"restoredSafetyCheckId": ROUND_ID}, "Send withdrawnSafetyCheckId or restoredSafetyCheckId, not both."),
        ({"status": "Pending Safety Check"}, "withdrawnSafetyCheckId is only valid with status 'Approved'."),
    ],
    ids=["withdrawnsafetycheckid_nope_withdrawnsafetycheck", "withdrawnsafetycheckid_other_round_id_withdrawns", "reason_reason_is_required", "reason_none_reason_is_required", "reason_x_2001_reason_must_be_2000_characters_or", "restoredsafetycheckid_round_id_send_withdrawnsaf", "status_pending_safety_check_withdrawnsafetycheck"],
)
def test_withdrawal_body_is_validated(setup, overrides, message):
    """
    Summary: A malformed withdrawal is refused before the database is read.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = withdraw(client, **overrides)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == message
    cursor.execute.assert_not_called()


def test_a_reason_at_the_limit_is_accepted(setup):
    """
    Summary: A 2000-character reason is within the limit.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [event_row("Confirmed", [APPROVAL]), event_row("Approved", [APPROVAL, WITHDRAWAL])]

    # Act + Assert (When / Then)
    assert withdraw(client, reason="x" * 2000).status_code == 200


# --- Restore: Approved -> Confirmed (compensation only) ----------------------


def test_restore_undoes_the_withdrawal_and_records_the_round_again(setup):
    """
    Summary: The event is Confirmed again and its history names the approval in force.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [event_row("Approved", [APPROVAL, WITHDRAWAL]), event_row("Confirmed", [APPROVAL])]

    # Act (When)
    response = restore(client)

    # Assert (Then)
    assert response.status_code == 200
    status, metadata = written(cursor)
    assert status == "Confirmed"
    entry = metadata["actionHistory"][-1]
    assert entry["status"] == "Confirmed"
    assert entry["safetyCheckId"] == ROUND_ID
    assert entry["restoredSafetyCheckId"] == ROUND_ID


def test_restore_only_undoes_the_latest_action(setup):
    """
    Summary: Once anything else has happened to the event, the approval can't be revived.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup
    later = {"status": "Approved", "details": "Progress saved.", "recordedAt": "2026-11-04T00:00:00+00:00"}
    cursor.fetchone.return_value = event_row("Approved", [APPROVAL, WITHDRAWAL, later])

    # Act (When)
    response = restore(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "STALE_SAFETY_CHECK"
    assert written(cursor) is None


def test_restore_needs_a_withdrawal_in_the_history(setup):
    """
    Summary: An Approved event that was never Confirmed can't be restored to it.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row("Approved", [])

    # Act + Assert (When / Then)
    assert restore(client).status_code == 409
    assert written(cursor) is None


def test_restore_from_another_status_is_refused(setup):
    """
    Summary: The marker is only valid for the Approved -> Confirmed undo.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row("Pending Safety Check", [APPROVAL, WITHDRAWAL])

    # Act (When)
    response = restore(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "INVALID_SAFETY_TRANSITION"


def test_restore_marker_requires_status_confirmed(setup):
    """
    Summary: RestoredSafetyCheckId can't be used to reach any other status.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = restore(client, status="Cancelled")

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "restoredSafetyCheckId is only valid with status 'Confirmed'."
    cursor.execute.assert_not_called()


def test_approved_cannot_be_confirmed_by_a_decision(setup):
    """
    Summary: Without the restore marker, Approved never reaches Confirmed.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row("Approved", [APPROVAL, WITHDRAWAL])

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/safety-status",
        json={"status": "Confirmed", "decidedBy": OFFICER_ID, "safetyCheckId": ROUND_ID, "roundNumber": 1},
        headers=INTERNAL_HEADERS,
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "INVALID_SAFETY_TRANSITION"
    assert written(cursor) is None


def test_the_venue_change_moves_stay_out_of_the_workflow_tables():
    """
    Summary: The safety workflow and /progress tables are unchanged.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Act + Assert (When / Then)
    assert VENUE_CHANGE_ONLY_MOVES == {("Confirmed", "Approved"), ("Approved", "Confirmed")}
    assert SAFETY_TRANSITIONS["Confirmed"] == {"Pending Safety Check"}
    assert "Confirmed" not in SAFETY_TRANSITIONS["Approved"]
    assert ALLOWED_TRANSITIONS["Approved"] == {"Approved"}
    assert ALLOWED_TRANSITIONS["Confirmed"] == {"Confirmed"}
