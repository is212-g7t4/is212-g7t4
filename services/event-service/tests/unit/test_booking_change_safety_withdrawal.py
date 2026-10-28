"""SCRUM-28 Part B: the event-side half of "a venue booking change withdraws the approval".

Decided by Clarice on 25 Oct: editing or cancelling a venue booking of a
'Confirmed' event withdraws its safety approval and moves the event back to
'Approved' (Venue Staff re-review the booking, then the coordinator
resubmits through SCRUM-149). `Approved -> Confirmed` exists only to undo
that when the booking change then fails.

Both moves are in VENUE_CHANGE_ONLY_MOVES, not SAFETY_TRANSITIONS, so
`PATCH /events/<id>/safety-status` makes them only when the body names the
round (`withdrawnSafetyCheckId` / `restoredSafetyCheckId`) and refuses them
otherwise. Safety Check Service is the only caller. Database calls are mocked.
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

EVENT_ID = "00000000-0000-0000-0000-000000000001"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OTHER_COORDINATOR_ID = "22222222-2222-4222-8222-222222222222"
OFFICER_ID = "33333333-3333-4333-8333-333333333333"
ROUND_ID = "55555555-5555-4555-8555-555555555555"
OTHER_ROUND_ID = "66666666-6666-4666-8666-666666666666"
INTERNAL_TOKEN = "test-internal-token"
INTERNAL_HEADERS = {"X-Internal-Service-Token": INTERNAL_TOKEN}
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
    return app.test_client(), cursor


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
    """Normal: the approval the event holds is withdrawn and the reason is in its history."""
    client, cursor = setup
    cursor.fetchone.side_effect = [event_row("Confirmed", [APPROVAL]), event_row("Approved", [APPROVAL, WITHDRAWAL])]

    response = withdraw(client)

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
    """Conflict: a stale or made-up round can't withdraw the current approval."""
    client, cursor = setup
    cursor.fetchone.return_value = event_row("Confirmed", [{**APPROVAL, "safetyCheckId": OTHER_ROUND_ID}])

    response = withdraw(client)

    assert response.status_code == 409
    assert response.json["code"] == "STALE_SAFETY_CHECK"
    assert written(cursor) is None


def test_withdrawal_needs_an_approval_in_the_history(setup):
    """Conflict: a Confirmed event with no recorded approval has nothing to withdraw."""
    client, cursor = setup
    cursor.fetchone.return_value = event_row("Confirmed", [])

    assert withdraw(client).status_code == 409
    assert written(cursor) is None


@pytest.mark.parametrize("status", ["Approved", "Pending Safety Check", "Safety Changes Requested", "Cancelled"])
def test_withdrawal_only_leaves_confirmed(setup, status):
    """Conflict: only a Confirmed event has a safety approval to withdraw."""
    client, cursor = setup
    cursor.fetchone.return_value = event_row(status, [APPROVAL])

    response = withdraw(client)

    assert response.status_code == 409
    assert response.json["code"] == "INVALID_SAFETY_TRANSITION"
    assert response.json["currentStatus"] == status
    assert written(cursor) is None


def test_withdrawal_by_an_unassigned_coordinator_is_refused(setup):
    """Failure: only the event's assigned coordinator can change its venue arrangements."""
    client, cursor = setup
    cursor.fetchone.return_value = event_row("Confirmed", [APPROVAL], coordinator_id=OTHER_COORDINATOR_ID)

    assert withdraw(client).status_code == 403
    assert written(cursor) is None


def test_withdrawal_needs_the_internal_token(setup):
    """Failure: a browser can't send an event back to Approved directly."""
    client, cursor = setup

    response = withdraw(client, headers={})

    assert response.status_code == 403
    assert response.json["code"] == "INTERNAL_ONLY"
    cursor.execute.assert_not_called()


def test_approved_without_the_withdrawal_marker_is_still_refused(setup):
    """Regression (SCRUM-149/152): plain 'Approved' is not a safety status."""
    client, cursor = setup

    response = withdraw(client, withdrawnSafetyCheckId=None)

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
        ({"coordinatorId": "nope"}, "A valid coordinator ID is required."),
        ({"restoredSafetyCheckId": ROUND_ID}, "Send withdrawnSafetyCheckId or restoredSafetyCheckId, not both."),
        ({"status": "Pending Safety Check"}, "withdrawnSafetyCheckId is only valid with status 'Approved'."),
    ],
)
def test_withdrawal_body_is_validated(setup, overrides, message):
    """Failure: a malformed withdrawal is refused before the database is read."""
    client, cursor = setup

    response = withdraw(client, **overrides)

    assert response.status_code == 400
    assert response.json["message"] == message
    cursor.execute.assert_not_called()


def test_a_reason_at_the_limit_is_accepted(setup):
    """Boundary: a 2000-character reason is within the limit."""
    client, cursor = setup
    cursor.fetchone.side_effect = [event_row("Confirmed", [APPROVAL]), event_row("Approved", [APPROVAL, WITHDRAWAL])]

    assert withdraw(client, reason="x" * 2000).status_code == 200


# --- Restore: Approved -> Confirmed (compensation only) ----------------------


def test_restore_undoes_the_withdrawal_and_records_the_round_again(setup):
    """Normal: the event is Confirmed again and its history names the approval in force."""
    client, cursor = setup
    cursor.fetchone.side_effect = [event_row("Approved", [APPROVAL, WITHDRAWAL]), event_row("Confirmed", [APPROVAL])]

    response = restore(client)

    assert response.status_code == 200
    status, metadata = written(cursor)
    assert status == "Confirmed"
    entry = metadata["actionHistory"][-1]
    assert entry["status"] == "Confirmed"
    assert entry["safetyCheckId"] == ROUND_ID
    assert entry["restoredSafetyCheckId"] == ROUND_ID


def test_restore_only_undoes_the_latest_action(setup):
    """Conflict: once anything else has happened to the event, the approval can't be revived."""
    client, cursor = setup
    later = {"status": "Approved", "details": "Progress saved.", "recordedAt": "2026-11-04T00:00:00+00:00"}
    cursor.fetchone.return_value = event_row("Approved", [APPROVAL, WITHDRAWAL, later])

    response = restore(client)

    assert response.status_code == 409
    assert response.json["code"] == "STALE_SAFETY_CHECK"
    assert written(cursor) is None


def test_restore_needs_a_withdrawal_in_the_history(setup):
    """Conflict: an Approved event that was never Confirmed can't be restored to it."""
    client, cursor = setup
    cursor.fetchone.return_value = event_row("Approved", [])

    assert restore(client).status_code == 409
    assert written(cursor) is None


def test_restore_from_another_status_is_refused(setup):
    """Conflict: the marker is only valid for the Approved -> Confirmed undo."""
    client, cursor = setup
    cursor.fetchone.return_value = event_row("Pending Safety Check", [APPROVAL, WITHDRAWAL])

    response = restore(client)

    assert response.status_code == 409
    assert response.json["code"] == "INVALID_SAFETY_TRANSITION"


def test_restore_marker_requires_status_confirmed(setup):
    """Failure: restoredSafetyCheckId can't be used to reach any other status."""
    client, cursor = setup

    response = restore(client, status="Cancelled")

    assert response.status_code == 400
    assert response.json["message"] == "restoredSafetyCheckId is only valid with status 'Confirmed'."
    cursor.execute.assert_not_called()


def test_approved_cannot_be_confirmed_by_a_decision(setup):
    """Regression (SCRUM-150/152): without the restore marker, Approved never reaches Confirmed."""
    client, cursor = setup
    cursor.fetchone.return_value = event_row("Approved", [APPROVAL, WITHDRAWAL])

    response = client.patch(
        f"/events/{EVENT_ID}/safety-status",
        json={"status": "Confirmed", "decidedBy": OFFICER_ID, "safetyCheckId": ROUND_ID, "roundNumber": 1},
        headers=INTERNAL_HEADERS,
    )

    assert response.status_code == 409
    assert response.json["code"] == "INVALID_SAFETY_TRANSITION"
    assert written(cursor) is None


def test_the_venue_change_moves_stay_out_of_the_workflow_tables():
    """Regression (SCRUM-150/152/153): the safety workflow and /progress tables are unchanged."""
    assert VENUE_CHANGE_ONLY_MOVES == {("Confirmed", "Approved"), ("Approved", "Confirmed")}
    assert SAFETY_TRANSITIONS["Confirmed"] == {"Pending Safety Check"}
    assert "Confirmed" not in SAFETY_TRANSITIONS["Approved"]
    assert ALLOWED_TRANSITIONS["Approved"] == {"Approved"}
    assert ALLOWED_TRANSITIONS["Confirmed"] == {"Confirmed"}
