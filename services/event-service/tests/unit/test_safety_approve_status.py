"""SCRUM-150: the event-side half of "approve the Operational Safety Check".

AC1 Given an event is 'Pending Safety Check', when I approve it, then its
    status changes to 'Confirmed'.
AC2 Given I approve an event, then the safety check is recorded with the
    status 'Safety Approved', together with my identity, the approval
    timestamp and any optional remarks, in the event's history — the
    event-side half of that history lives here (`actionHistory`); the
    `SafetyCheck` row, decided by Safety Check Record Service, is the
    authoritative record.
AC3 Given an event is not 'Pending Safety Check', then the approve action is
    not available and an API call is rejected without changing the event.

`PATCH /events/<id>/safety-status` is the only way into a safety status, and
only Safety Check Service calls it — the caller's role check (Safety Officer)
lives there. This endpoint owns the lifecycle move, and re-checks the round
under a row lock so a stale or made-up round can't confirm the event (AC3).

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
OFFICER_ID = "33333333-3333-4333-8333-333333333333"
SAFETY_CHECK_ID = "55555555-5555-4555-8555-555555555555"
OTHER_SAFETY_CHECK_ID = "66666666-6666-4666-8666-666666666666"
INTERNAL_TOKEN = "test-internal-token"
INTERNAL_HEADERS = {"X-Internal-Service-Token": INTERNAL_TOKEN}

# Every status an event can hold that isn't 'Pending Safety Check'; none of
# them may move to 'Confirmed' through this endpoint (AC3).
NON_PENDING_STATUSES = [
    "Submitted",
    "Under Review",
    "Approved",
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
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": "unused-test-url",
            "INTERNAL_SERVICE_TOKEN": INTERNAL_TOKEN,
        }
    )
    return app.test_client(), connection, cursor


def event_row(
    status="Pending Safety Check",
    coordinator_id=COORDINATOR_ID,
    action_history=None,
):
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
    if action_history is None:
        action_history = [
            {
                "status": "Pending Safety Check",
                "details": "Submitted for Operational Safety Check (round 1).",
                "coordinatorId": COORDINATOR_ID,
                "safetyCheckId": SAFETY_CHECK_ID,
                "recordedAt": "2026-11-01T02:30:00+00:00",
            }
        ]
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
            "actionHistory": action_history,
        }
    )
    return row


def patch_safety_status(client, headers=INTERNAL_HEADERS, **overrides):
    body = {
        "status": "Confirmed",
        "decidedBy": OFFICER_ID,
        "safetyCheckId": SAFETY_CHECK_ID,
        "roundNumber": 1,
        **overrides,
    }
    return client.patch(f"/events/{EVENT_ID}/safety-status", json=body, headers=headers)


# --- AC1/AC2: the move and the history entry ---------------------------------


def test_pending_safety_check_moves_to_confirmed(setup):
    """AC1: 'Pending Safety Check' -> 'Confirmed' with the open round's id."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Confirmed"),
    ]

    response = patch_safety_status(client)

    assert response.status_code == 200
    assert response.json["status"] == "Confirmed"
    assert cursor.execute.call_args_list[1].args[1][0] == "Confirmed"


def test_history_entry_has_decided_by_safety_check_id_remarks_and_time(setup):
    """AC2: the event-side history entry carries the officer's decision."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Confirmed"),
    ]

    patch_safety_status(client, remarks="Looks safe.")

    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    action = stored["actionHistory"][-1]
    assert action["status"] == "Confirmed"
    assert action["decidedBy"] == OFFICER_ID
    assert action["safetyCheckId"] == SAFETY_CHECK_ID
    assert action["remarks"] == "Looks safe."
    assert action["recordedAt"].endswith("+00:00")
    assert action["details"] == "Operational Safety Check approved (round 1)."
    # The earlier submit entry is kept, not replaced.
    assert stored["actionHistory"][0]["status"] == "Pending Safety Check"


def test_remarks_are_optional(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Confirmed"),
    ]

    response = patch_safety_status(client, remarks=None)

    assert response.status_code == 200
    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    assert stored["actionHistory"][-1]["remarks"] is None


def test_no_coordinator_check_on_approve(setup):
    """AC1: the Safety Officer deciding need not be the assigned coordinator."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check", coordinator_id=COORDINATOR_ID),
        event_row("Confirmed"),
    ]

    response = patch_safety_status(client, decidedBy=OFFICER_ID)

    assert response.status_code == 200


def test_coordinator_decision_is_left_alone(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Confirmed"),
    ]

    patch_safety_status(client)

    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    assert stored["decision"]["status"] == "Approved"
    assert stored["actionDetails"] == "Venue booked."


def test_move_runs_under_a_row_lock(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Confirmed"),
    ]

    patch_safety_status(client)

    assert "FOR UPDATE" in cursor.execute.call_args_list[0].args[0]


# --- AC3: only 'Pending Safety Check' may move, and only with its own round -


@pytest.mark.parametrize("current_status", NON_PENDING_STATUSES)
def test_only_pending_safety_check_can_be_confirmed(current_status, setup):
    """AC3: every other status is refused, and the event is not touched."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(current_status)

    response = patch_safety_status(client)

    assert response.status_code == 409
    assert response.json["code"] == "INVALID_SAFETY_TRANSITION"
    assert response.json["currentStatus"] == current_status
    # Only the SELECT ran: nothing was updated.
    assert cursor.execute.call_count == 1


def test_stale_safety_check_id_is_refused(setup):
    """AC3: a round that isn't the one this event has open can't confirm it."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Pending Safety Check")

    response = patch_safety_status(client, safetyCheckId=OTHER_SAFETY_CHECK_ID)

    assert response.status_code == 409
    assert response.json["code"] == "STALE_SAFETY_CHECK"
    # Only the SELECT ran: nothing was updated.
    assert cursor.execute.call_count == 1


def test_missing_pending_entry_is_refused(setup):
    """No 'Pending Safety Check' action at all means there is no round to match."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Pending Safety Check", action_history=[])

    response = patch_safety_status(client)

    assert response.status_code == 409
    assert response.json["code"] == "STALE_SAFETY_CHECK"


def test_missing_event_is_404(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = patch_safety_status(client)

    assert response.status_code == 404
    assert response.json["message"] == "Event request not found."


# --- Input validation ---------------------------------------------------------


def test_missing_decided_by_is_rejected(setup):
    client, _, cursor = setup

    response = patch_safety_status(client, decidedBy="")

    assert response.status_code == 400
    assert response.json["message"] == "A valid decidedBy ID is required."
    cursor.execute.assert_not_called()


def test_remarks_over_the_limit_are_rejected(setup):
    client, _, cursor = setup

    response = patch_safety_status(client, remarks="x" * 2001)

    assert response.status_code == 400
    assert response.json["message"] == "remarks must be 2000 characters or fewer."
    cursor.execute.assert_not_called()


def test_non_text_remarks_are_rejected(setup):
    client, _, cursor = setup

    response = patch_safety_status(client, remarks={"nested": "object"})

    assert response.status_code == 400
    assert response.json["message"] == "remarks must be text."
    cursor.execute.assert_not_called()


def test_bad_safety_check_id_is_rejected(setup):
    client, _, cursor = setup

    response = patch_safety_status(client, safetyCheckId="not-a-uuid")

    assert response.status_code == 400
    assert response.json["message"] == "A valid safety check ID is required."
    cursor.execute.assert_not_called()
