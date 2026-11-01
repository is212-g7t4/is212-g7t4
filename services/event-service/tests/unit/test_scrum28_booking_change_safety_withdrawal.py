"""
SCRUM-28: Venue Booking Request Submission

This file covers only SCRUM-28 AC7, the part Event Service implements: when a
venue booking of a Confirmed event is edited or cancelled, Event Service
withdraws the event's safety approval (and restores it if the booking change
cannot be saved). The other ACs belong to the venue booking services.

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
- AC1 to AC6, and that the booking services call this route when a booking is
  edited or cancelled (-> venue booking service tests).
- What an Attendee sees while the event is back at Approved (->
  test_scrum153_recheck_safety_after_high_impact_changes.py).
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


# --- AC7: withdrawal and restore -----------------------------------------------


def test_ac7_a_booking_change_withdraws_the_safety_approval_and_returns_a_confirmed_event_to_approved(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Approved" with a withdrawnSafetyCheckId and a reason on a 'Confirmed' event answers 200 with status "Approved"; the lookup takes FOR UPDATE and the UPDATE writes status "Approved" with a final history entry naming the withdrawn round, the coordinator and the reason, without opening a new round.
    AC7: Given an event is 'Confirmed' after passing its Operational Safety
        Check, when the Event Coordinator edits or cancels one of its venue
        bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor.fetchone returns the 'Confirmed' event with its approval, then the 'Approved' event),
        Mock (the lookup query contains FOR UPDATE; the UPDATE's status and metadata asserted)
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


@pytest.mark.parametrize("status", ["Approved", "Pending Safety Check", "Safety Changes Requested", "Cancelled"])
def test_ac7_only_a_confirmed_event_has_a_safety_approval_to_withdraw(setup, status):
    """
    Summary: PATCH /events/<id>/safety-status withdrawing the approval of an event that is 'Approved', 'Pending Safety Check', 'Safety Changes Requested' or 'Cancelled' answers 409 INVALID_SAFETY_TRANSITION with the currentStatus, and nothing is written.
    AC7: Given an event is 'Confirmed' after passing its Operational Safety
        Check, when the Event Coordinator edits or cancels one of its venue
        bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor.fetchone returns the event in the parametrised status with an approval in its history),
        Mock (no UPDATE found among the cursor.execute calls)
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


def test_ac7_when_the_booking_change_cannot_be_saved_the_withdrawal_is_undone_and_the_round_is_recorded_again(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Confirmed" with a restoredSafetyCheckId on an 'Approved' event whose history ends with the withdrawal answers 200; the UPDATE writes status "Confirmed" with a final history entry naming the restored round.
    AC7: Given an event is 'Confirmed' after passing its Operational Safety
        Check, when the Event Coordinator edits or cancels one of its venue
        bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor.fetchone returns the 'Approved' event with approval and withdrawal in its history, then the 'Confirmed' event),
        Mock (the UPDATE's status and metadata asserted)
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


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_a_withdrawal_must_name_the_approval_the_event_currently_holds(setup):
    """
    Summary: PATCH /events/<id>/safety-status withdrawing round R on a 'Confirmed' event whose approval is for a different round answers 409 STALE_SAFETY_CHECK and nothing is written.
    Supporting design check: a stale or made-up round cannot withdraw the
        current approval
    Double: Stub (cursor.fetchone returns a 'Confirmed' event approved for another round),
        Mock (no UPDATE found among the cursor.execute calls)
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


def test_a_withdrawal_needs_an_approval_in_the_event_history(setup):
    """
    Summary: PATCH /events/<id>/safety-status withdrawing the approval of a 'Confirmed' event whose history is empty answers 409 and nothing is written.
    Supporting design check: a Confirmed event with no recorded approval has
        nothing to withdraw
    Double: Stub (cursor.fetchone returns a 'Confirmed' event with an empty history),
        Mock (no UPDATE found among the cursor.execute calls)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row("Confirmed", [])

    # Act + Assert (When / Then)
    assert withdraw(client).status_code == 409
    assert written(cursor) is None


def test_a_withdrawal_by_a_coordinator_the_event_is_not_assigned_to_is_refused(setup):
    """
    Summary: PATCH /events/<id>/safety-status withdrawing the approval of a 'Confirmed' event assigned to a different coordinator answers 403 and nothing is written.
    Supporting design check: only the assigned coordinator can change the
        event's venue arrangements
    Double: Stub (cursor.fetchone returns a 'Confirmed' event assigned to another coordinator),
        Mock (no UPDATE found among the cursor.execute calls)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row("Confirmed", [APPROVAL], coordinator_id=OTHER_COORDINATOR_ID)

    # Act + Assert (When / Then)
    assert withdraw(client).status_code == 403
    assert written(cursor) is None


def test_a_withdrawal_without_the_internal_token_is_refused(setup):
    """
    Summary: PATCH /events/<id>/safety-status withdrawing an approval with no X-Internal-Token header answers 403 INTERNAL_ONLY and no query is sent.
    Supporting design check: a browser cannot send an event back to Approved
        directly
    Double: Mock (cursor.execute asserted never called)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = withdraw(client, headers={})

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["code"] == "INTERNAL_ONLY"
    cursor.execute.assert_not_called()


def test_the_approved_status_without_the_withdrawal_marker_is_refused(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Approved" with withdrawnSafetyCheckId null answers 400 "Status must be one of: ..." and no query is sent.
    Supporting design check: plain 'Approved' is not a safety status
    Double: Mock (cursor.execute asserted never called)
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
def test_a_malformed_withdrawal_is_refused_before_any_query(setup, overrides, message):
    """
    Summary: PATCH /events/<id>/safety-status withdrawing an approval with a non-UUID or mismatched withdrawnSafetyCheckId, a blank, missing or 2001-character reason, both a withdrawn and a restored id, or a status other than "Approved" answers 400 with the matching message and no query is sent.
    Supporting design check: a malformed withdrawal is refused before the
        database is read
    Double: Mock (cursor.execute asserted never called; the 400 message compared with the expected one)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = withdraw(client, **overrides)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == message
    cursor.execute.assert_not_called()


def test_a_withdrawal_reason_of_exactly_2000_characters_is_accepted(setup):
    """
    Summary: PATCH /events/<id>/safety-status withdrawing an approval with a 2000-character reason answers 200.
    Supporting design check: the reason limit is 2000 characters
    Double: Stub (cursor.fetchone returns the 'Confirmed' event, then the 'Approved' event); the 200 status is the only assertion
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [event_row("Confirmed", [APPROVAL]), event_row("Approved", [APPROVAL, WITHDRAWAL])]

    # Act + Assert (When / Then)
    assert withdraw(client, reason="x" * 2000).status_code == 200


def test_a_restore_only_undoes_the_latest_action(setup):
    """
    Summary: PATCH /events/<id>/safety-status restoring an approval when a later 'Progress saved.' entry follows the withdrawal answers 409 STALE_SAFETY_CHECK and nothing is written.
    Supporting design check: once anything else has happened to the event, the
        approval cannot be revived
    Double: Stub (cursor.fetchone returns an 'Approved' event whose history has an entry after the withdrawal),
        Mock (no UPDATE found among the cursor.execute calls)
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


def test_a_restore_needs_a_withdrawal_in_the_event_history(setup):
    """
    Summary: PATCH /events/<id>/safety-status restoring an approval on an 'Approved' event with an empty history answers 409 and nothing is written.
    Supporting design check: an Approved event that was never Confirmed cannot
        be restored to it
    Double: Stub (cursor.fetchone returns an 'Approved' event with an empty history),
        Mock (no UPDATE found among the cursor.execute calls)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row("Approved", [])

    # Act + Assert (When / Then)
    assert restore(client).status_code == 409
    assert written(cursor) is None


def test_a_restore_from_a_status_other_than_approved_is_refused(setup):
    """
    Summary: PATCH /events/<id>/safety-status restoring an approval on a 'Pending Safety Check' event answers 409 INVALID_SAFETY_TRANSITION.
    Supporting design check: the restore marker is only valid for the
        Approved to Confirmed undo
    Double: Stub (cursor.fetchone returns a 'Pending Safety Check' event with approval and withdrawal in its history); the 409 status and code are the only assertions
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row("Pending Safety Check", [APPROVAL, WITHDRAWAL])

    # Act (When)
    response = restore(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "INVALID_SAFETY_TRANSITION"


def test_the_restore_marker_is_refused_with_any_status_other_than_confirmed(setup):
    """
    Summary: PATCH /events/<id>/safety-status with a restoredSafetyCheckId and status "Cancelled" answers 400 "restoredSafetyCheckId is only valid with status 'Confirmed'." and no query is sent.
    Supporting design check: the restore marker cannot be used to reach any
        other status
    Double: Mock (cursor.execute asserted never called)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = restore(client, status="Cancelled")

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "restoredSafetyCheckId is only valid with status 'Confirmed'."
    cursor.execute.assert_not_called()


def test_the_venue_change_moves_stay_out_of_the_safety_workflow_and_progress_tables():
    """
    Summary: VENUE_CHANGE_ONLY_MOVES is exactly Confirmed to Approved and Approved to Confirmed; SAFETY_TRANSITIONS lets Confirmed go only to Pending Safety Check and does not let Approved reach Confirmed; ALLOWED_TRANSITIONS keeps Approved and Confirmed where they are.
    Supporting design check: the venue-change moves are separate from the
        safety workflow and progress transition tables
    Double: None; the transition tables are read directly, no route or database is used
    """
    # Act + Assert (When / Then)
    assert VENUE_CHANGE_ONLY_MOVES == {("Confirmed", "Approved"), ("Approved", "Confirmed")}
    assert SAFETY_TRANSITIONS["Confirmed"] == {"Pending Safety Check"}
    assert "Confirmed" not in SAFETY_TRANSITIONS["Approved"]
    assert ALLOWED_TRANSITIONS["Approved"] == {"Approved"}
    assert ALLOWED_TRANSITIONS["Confirmed"] == {"Confirmed"}
