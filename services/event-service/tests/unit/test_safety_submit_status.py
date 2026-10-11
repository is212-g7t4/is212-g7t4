"""SCRUM-149: the event-side half of "submit for safety check".

AC1 Given an event ... has every arrangement approved, when the Event
    Coordinator submits it for a safety check, then its status changes to
    'Pending Safety Check' and the submission time is recorded.
AC4 Given the event is already 'Pending Safety Check', when the Event
    Coordinator submits it again, then no duplicate safety check is created.
AC5 Given the Event Coordinator is not the assigned coordinator, then ... an
    API call is rejected.

`PATCH /events/<id>/safety-status` is the only way into a safety status, and
only Safety Check Service calls it — the arrangements check (AC2) lives there.
This endpoint owns the lifecycle move and re-checks the coordinator and the
current status under a row lock.

Database calls are mocked; no live database writes.
"""
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.models import FIELDS

EVENT_ID = "00000000-0000-0000-0000-000000000001"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OTHER_COORDINATOR_ID = "22222222-2222-4222-8222-222222222222"
SAFETY_CHECK_ID = "55555555-5555-4555-8555-555555555555"

# Every status an event can hold that must not reach 'Pending Safety Check'.
# Only 'Approved' may (SAFETY_TRANSITIONS).
NON_APPROVED_STATUSES = [
    "Submitted",
    "Under Review",
    "Rejected",
    "Confirmed",
    "Safety Changes Requested",
    "Cancelled",
]


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), connection, cursor


def event_row(status="Approved", coordinator_id=COORDINATOR_ID, action_history=None):
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
    row["description"] = json.dumps(
        {
            "_connectsphere": "event-submission-v1",
            "description": "A practical workshop",
            "purpose": "Learning",
            "decision": {
                "status": "Approved",
                "coordinatorId": COORDINATOR_ID,
                "decidedAt": "2026-10-02T01:00:00+00:00",
                "reason": None,
            },
            "decisionHistory": [],
            "actionDetails": "Venue booked.",
            "actionHistory": action_history or [],
        }
    )
    return row


def patch_safety_status(client, **overrides):
    body = {
        "status": "Pending Safety Check",
        "coordinatorId": COORDINATOR_ID,
        "safetyCheckId": SAFETY_CHECK_ID,
        "roundNumber": 1,
        **overrides,
    }
    return client.patch(f"/events/{EVENT_ID}/safety-status", json=body)


# --- AC1: the move and the submission time ----------------------------------


def test_approved_event_moves_to_pending_safety_check(setup):
    """AC1: 'Approved' -> 'Pending Safety Check' for the assigned coordinator."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Approved"),
        event_row("Pending Safety Check"),
    ]

    response = patch_safety_status(client)

    assert response.status_code == 200
    assert response.json["status"] == "Pending Safety Check"
    assert cursor.execute.call_count == 2
    assert cursor.execute.call_args_list[1].args[1][0] == "Pending Safety Check"


def test_submission_is_recorded_in_the_action_history(setup):
    """AC1 "the submission time is recorded": the event keeps its own note of it.

    SafetyCheck.submitted_at stays the authoritative time; this is what the
    event detail page reads to say when it was submitted.
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Approved", action_history=[{"status": "Approved"}]),
        event_row("Pending Safety Check"),
    ]

    patch_safety_status(client, roundNumber=2)

    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    action = stored["actionHistory"][-1]
    assert action["status"] == "Pending Safety Check"
    assert action["details"] == (
        "Submitted for Operational Safety Check (round 2)."
    )
    assert action["coordinatorId"] == COORDINATOR_ID
    assert action["safetyCheckId"] == SAFETY_CHECK_ID
    assert action["recordedAt"].endswith("+00:00")
    # The earlier history is kept, not replaced.
    assert stored["actionHistory"][0] == {"status": "Approved"}


def test_coordinator_decision_is_left_alone(setup):
    """A safety submission is not a coordinator decision: `decision` is untouched."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Approved"),
        event_row("Pending Safety Check"),
    ]

    patch_safety_status(client)

    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    assert stored["decision"]["status"] == "Approved"
    assert stored["actionDetails"] == "Venue booked."


def test_move_runs_under_a_row_lock(setup):
    """The composite's earlier read can be stale, so the checks repeat in the lock."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Approved"),
        event_row("Pending Safety Check"),
    ]

    patch_safety_status(client)

    assert "FOR UPDATE" in cursor.execute.call_args_list[0].args[0]


# --- AC5: only the assigned coordinator -------------------------------------


def test_another_coordinator_is_refused(setup):
    """AC5: an API call from anyone but the assigned coordinator is rejected."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(
        "Approved", coordinator_id=OTHER_COORDINATOR_ID
    )

    response = patch_safety_status(client)

    assert response.status_code == 403
    assert response.json["message"] == (
        "This event request is not assigned to the current coordinator."
    )
    # Only the SELECT ran: the event was never updated.
    assert cursor.execute.call_count == 1


def test_unassigned_event_is_refused(setup):
    """AC5 boundary: an event with no coordinator has no assigned coordinator."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Approved", coordinator_id=None)

    response = patch_safety_status(client)

    assert response.status_code == 403
    assert cursor.execute.call_count == 1


def test_another_coordinator_on_a_pending_event_gets_403_not_409(setup):
    """AC5 before AC4: a stranger learns nothing about the event's stage."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(
        "Pending Safety Check", coordinator_id=OTHER_COORDINATOR_ID
    )

    response = patch_safety_status(client)

    assert response.status_code == 403
    assert "code" not in response.json


# --- AC4 and the lifecycle guard --------------------------------------------


def test_already_pending_event_is_a_conflict(setup):
    """AC4's backstop: a second submission can't re-enter 'Pending Safety Check'."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Pending Safety Check")

    response = patch_safety_status(client)

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_PENDING"
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("current_status", NON_APPROVED_STATUSES)
def test_only_an_approved_event_can_be_submitted(current_status, setup):
    """Only 'Approved' is in SAFETY_TRANSITIONS, so every other status is refused."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(current_status)

    response = patch_safety_status(client)

    assert response.status_code == 409
    assert response.json["code"] == "INVALID_SAFETY_TRANSITION"
    assert response.json["currentStatus"] == current_status
    assert response.json["message"] == (
        f"This event can't move to 'Pending Safety Check' from '{current_status}'."
    )
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize(
    "status", ["Confirmed", "Safety Changes Requested", "Cancelled"]
)
def test_statuses_for_later_stories_are_not_reachable_yet(status, setup):
    """SCRUM-150/151 add their own moves to SAFETY_TRANSITIONS; until then, no."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Approved")

    response = patch_safety_status(client, status=status)

    assert response.status_code == 409
    assert response.json["code"] == "INVALID_SAFETY_TRANSITION"


def test_missing_event_is_404(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = patch_safety_status(client)

    assert response.status_code == 404
    assert response.json["message"] == "Event request not found."


# --- Input and configuration -------------------------------------------------


@pytest.mark.parametrize("status", ["Approved", "Submitted", "Under Review", "Rejected"])
def test_pre_safety_statuses_are_not_accepted(status, setup):
    """This endpoint only sets safety statuses; the rest is PATCH /progress."""
    client, _, cursor = setup

    response = patch_safety_status(client, status=status)

    assert response.status_code == 400
    assert response.json["message"].startswith("Status must be one of: ")
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    "overrides",
    [
        {"coordinatorId": "not-a-uuid"},
        {"coordinatorId": ""},
        {"safetyCheckId": "not-a-uuid"},
        {"safetyCheckId": None},
    ],
)
def test_bad_identifiers_are_rejected(overrides, setup):
    client, _, cursor = setup

    response = patch_safety_status(client, **overrides)

    assert response.status_code == 400
    assert response.json["message"] == (
        "A valid coordinator ID and safety check ID are required."
    )
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("round_number", [0, -1, 1.5, "1", True, None])
def test_bad_round_number_is_rejected(round_number, setup):
    client, _, cursor = setup

    response = patch_safety_status(client, roundNumber=round_number)

    assert response.status_code == 400
    assert response.json["message"] == "roundNumber must be a positive whole number."
    cursor.execute.assert_not_called()


def test_non_object_body_is_rejected(setup):
    client, _, cursor = setup

    response = client.patch(f"/events/{EVENT_ID}/safety-status", json=["nope"])

    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    cursor.execute.assert_not_called()


def test_without_database_url():
    client = create_app({"TESTING": True, "DATABASE_URL": None}).test_client()

    response = patch_safety_status(client)

    assert response.status_code == 503
    assert "DATABASE_URL" in response.json["message"]


# --- Regression: PATCH /progress is still shut out (SCRUM-152) ---------------


def test_progress_endpoint_still_cannot_set_pending_safety_check(setup):
    """SCRUM-152 must keep holding: the coordinator's own endpoint can't do this."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Approved")

    response = client.patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": "Pending Safety Check",
            "actionDetails": "Trying the back door.",
        },
    )

    assert response.status_code == 409
    assert response.json["message"] == (
        "This status change is not allowed for the event's current stage."
    )
    assert cursor.execute.call_count == 1
