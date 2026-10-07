"""SCRUM-152 AC1-AC2: an event can't progress to 'Confirmed' without a safety pass.

'Confirmed' is the preparation stage — an event that has passed its Operational
Safety Check is the one that may proceed. There is no separate 'In Preparation'
status. Setting 'Confirmed' belongs to the safety workflow (SCRUM-150); this
story only stops anything else from doing it.

AC1 Given an event's status is not 'Confirmed', when the assigned Event
    Coordinator tries to move it to 'Confirmed' (the preparation stage) through
    either the UI or the API, then the change is blocked and the reason is shown.
AC2 Given an event has not yet reached the safety check, then the existing
    status transitions (SCRUM-19) continue to work unchanged.

Database calls are mocked; no live database writes.
"""
import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.models import FIELDS

EVENT_ID = "00000000-0000-0000-0000-000000000001"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OTHER_COORDINATOR_ID = "22222222-2222-4222-8222-222222222222"

# Every status that isn't 'Confirmed' — the gate must block all of them.
UNCONFIRMED_STATUSES = [
    "Submitted",
    "Under Review",
    "Approved",
    "Rejected",
    "Pending Safety Check",
    "Safety Changes Requested",
    "Cancelled",
]


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), connection, cursor


def event_row(status="Submitted", coordinator_id=COORDINATOR_ID, action_details=""):
    row = {column: "" for column in FIELDS.values()}
    row.update(
        event_id=EVENT_ID,
        event_name="Community Workshop",
        status=status,
        coordinator_id=coordinator_id,
        submission_date=datetime(2026, 10, 1, 8),
        preferred_start_date=datetime(2026, 10, 10, 9),
        preferred_end_date=datetime(2026, 10, 10, 12),
        expected_attendance=30,
        venue_id=None,
    )
    row["description"] = json.dumps({
        "_connectsphere": "event-submission-v1",
        "description": "A practical workshop",
        "purpose": "Learning",
        "decision": None,
        "decisionHistory": [],
        "actionDetails": action_details,
        "actionHistory": [],
    })
    return row


def patch_progress(client, status, action_details="Recording progress."):
    return client.patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": status,
            "actionDetails": action_details,
        },
    )


@pytest.mark.parametrize("current_status", UNCONFIRMED_STATUSES)
def test_coordinator_cannot_confirm_event(current_status, setup):
    """AC1 / SCRUM-153 AC2: only the safety workflow sets 'Confirmed'."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(current_status)

    response = patch_progress(client, "Confirmed", "All arrangements done.")

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_APPROVAL_REQUIRED"
    assert response.json["currentStatus"] == current_status
    assert response.json["requiredStatus"] == "Confirmed"
    # Only the SELECT ran — the event was never updated.
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize(
    ("current_status", "message"),
    [
        (
            "Approved",
            "Submit this event for safety check for it to progress to Confirmed.",
        ),
        (
            "Submitted",
            "This event must be approved and pass its Operational Safety Check "
            "before it can progress to Confirmed.",
        ),
        (
            "Under Review",
            "This event must be approved and pass its Operational Safety Check "
            "before it can progress to Confirmed.",
        ),
        ("Rejected", "This event was rejected, so it can't progress to Confirmed."),
        (
            "Pending Safety Check",
            "This event is waiting for the Safety Officer's decision.",
        ),
        (
            "Safety Changes Requested",
            "The Safety Officer has requested changes that must be made and resubmitted.",
        ),
        (
            "Cancelled",
            "This event was cancelled after its safety check, so it can't progress to Confirmed.",
        ),
    ],
)
def test_block_message_names_the_reason(current_status, message, setup):
    """AC1 "the reason is shown": the 409 message explains why, per status."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(current_status)

    response = patch_progress(client, "Confirmed")

    assert response.status_code == 409
    assert response.json["message"] == message


def test_approved_event_tells_the_coordinator_to_submit_for_safety_check(setup):
    """AC1: the actionable case — an approved event's next step is SCRUM-149."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Approved")

    response = patch_progress(client, "Confirmed")

    assert response.status_code == 409
    assert response.json["message"] == (
        "Submit this event for safety check for it to progress to Confirmed."
    )


def test_cancelled_event_cannot_progress(setup):
    """AC1, and SCRUM-151 AC4: a safety rejection ends the lifecycle."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Cancelled")

    response = patch_progress(client, "Confirmed")

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_APPROVAL_REQUIRED"
    assert cursor.execute.call_count == 1


def test_gate_checks_assignment_first(setup):
    """AC1 is about the *assigned* coordinator: others get 403, not the reason."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Approved", coordinator_id=OTHER_COORDINATOR_ID)

    response = patch_progress(client, "Confirmed")

    assert response.status_code == 403
    assert "code" not in response.json
    assert cursor.execute.call_count == 1


def test_confirmed_event_stays_confirmed_and_records_progress(setup):
    """Boundary: the gate must not over-block. An event already at 'Confirmed'
    has passed its safety check, so recording progress against it still works."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Confirmed"),
        event_row("Confirmed", action_details="Preparation under way."),
    ]

    response = patch_progress(client, "Confirmed", "Preparation under way.")

    assert response.status_code == 200
    assert response.json["status"] == "Confirmed"
    assert response.json["actionDetails"] == "Preparation under way."
    assert cursor.execute.call_count == 2
    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    assert stored["actionHistory"][-1]["status"] == "Confirmed"


@pytest.mark.parametrize(
    "status", ["Pending Safety Check", "Safety Changes Requested", "Cancelled"]
)
def test_coordinator_cannot_set_other_safety_status(status, setup):
    """Guards the safety workflow: only it writes the safety statuses."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Approved")

    response = patch_progress(client, status)

    assert response.status_code == 409
    assert response.json["message"] == (
        "This status change is not allowed for the event's current stage."
    )
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize(
    "status",
    ["Pending Safety Check", "Confirmed", "Safety Changes Requested", "Cancelled"],
)
def test_self_save_on_safety_status_keeps_working(status, setup):
    """AC2 spirit: recording action details never changes the status, so it's allowed."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row(status),
        event_row(status, action_details="Logged the latest progress."),
    ]

    response = patch_progress(client, status, "Logged the latest progress.")

    assert response.status_code == 200
    assert response.json["status"] == status
    assert response.json["actionDetails"] == "Logged the latest progress."


@pytest.mark.parametrize("status", ["In Preparation", "Preparing", "SafetyApproved"])
def test_unknown_status_is_400(status, setup):
    """Input validation: only the documented lifecycle statuses are accepted.

    'In Preparation' is deliberately not a status — 'Confirmed' is the
    preparation stage.
    """
    client, _, cursor = setup

    response = patch_progress(client, status)

    assert response.status_code == 400
    assert response.json["message"].startswith("Status must be one of: ")
    cursor.execute.assert_not_called()


def test_gate_runs_under_row_lock(setup):
    """A concurrent safety decision can't make the gate act on a stale status."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Approved")

    patch_progress(client, "Confirmed")

    assert "FOR UPDATE" in cursor.execute.call_args_list[0].args[0]
