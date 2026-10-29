"""SCRUM-151: the event-side half of "request changes" / "reject".

AC2 Given changes are requested, then the event status changes to 'Safety
    Changes Requested' ... and its existing arrangements are preserved.
AC4 Given I confirm a rejection, then the event status changes to
    'Cancelled', and the event cannot be resubmitted for a safety check or
    moved to any further stage.
AC6 Given either decision, then the safety check is recorded with ...
    identity, timestamp and reason (plus the selected areas for a change
    request), and the original event information is retained.
AC7 Given an event is not 'Pending Safety Check', then these actions are not
    available and an API call is rejected without changing the event.

`PATCH /events/<id>/safety-status` is the only way into a safety status, and
only Safety Check Service calls it. This endpoint owns the lifecycle move,
and re-checks the round under a row lock so a stale or made-up round can't
move the event (AC7).

Database calls are mocked; no live database writes.
"""
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.models import FIELDS
from tests.unit.factories import signed_in

EVENT_ID = "00000000-0000-0000-0000-000000000001"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OFFICER_ID = "33333333-3333-4333-8333-333333333333"
SAFETY_CHECK_ID = "55555555-5555-4555-8555-555555555555"
OTHER_SAFETY_CHECK_ID = "66666666-6666-4666-8666-666666666666"
INTERNAL_TOKEN = "test-internal-token"
INTERNAL_HEADERS = {"X-Internal-Service-Token": INTERNAL_TOKEN}

# Every status an event can hold that isn't 'Pending Safety Check'; none of
# them may move to 'Safety Changes Requested' or 'Cancelled' through this
# endpoint (AC7).
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
    return signed_in(app.test_client()), connection, cursor


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


def request_changes(client, headers=INTERNAL_HEADERS, **overrides):
    body = {
        "status": "Safety Changes Requested",
        "decidedBy": OFFICER_ID,
        "safetyCheckId": SAFETY_CHECK_ID,
        "roundNumber": 1,
        "remarks": "Needs another look.",
        "areas": ["venue arrangement", "event details"],
        **overrides,
    }
    return client.patch(f"/events/{EVENT_ID}/safety-status", json=body, headers=headers)


def reject(client, headers=INTERNAL_HEADERS, **overrides):
    body = {
        "status": "Cancelled",
        "decidedBy": OFFICER_ID,
        "safetyCheckId": SAFETY_CHECK_ID,
        "roundNumber": 1,
        "remarks": "Unsafe egress plan.",
        **overrides,
    }
    return client.patch(f"/events/{EVENT_ID}/safety-status", json=body, headers=headers)


# --- AC2/AC6: request changes -------------------------------------------------


def test_pending_safety_check_moves_to_safety_changes_requested(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Safety Changes Requested"),
    ]

    response = request_changes(client)

    assert response.status_code == 200
    assert response.json["status"] == "Safety Changes Requested"
    assert cursor.execute.call_args_list[1].args[1][0] == "Safety Changes Requested"


def test_changes_requested_history_entry_has_areas_and_remarks(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Safety Changes Requested"),
    ]

    request_changes(client)

    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    action = stored["actionHistory"][-1]
    assert action["status"] == "Safety Changes Requested"
    assert action["decidedBy"] == OFFICER_ID
    assert action["safetyCheckId"] == SAFETY_CHECK_ID
    assert action["remarks"] == "Needs another look."
    assert action["areas"] == ["venue arrangement", "event details"]
    assert action["recordedAt"].endswith("+00:00")
    assert "venue arrangement, event details" in action["details"]
    # The earlier submit entry is kept, not replaced.
    assert stored["actionHistory"][0]["status"] == "Pending Safety Check"


def test_changes_requested_preserves_everything_else(setup):
    """AC2: "existing arrangements are preserved" — only status/history change."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Safety Changes Requested"),
    ]

    request_changes(client)

    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    assert stored["decision"]["status"] == "Approved"
    assert stored["actionDetails"] == "Venue booked."


def test_changes_requested_requires_remarks(setup):
    client, _, cursor = setup

    response = request_changes(client, remarks=None)

    assert response.status_code == 400
    assert response.json["message"] == "remarks is required."
    cursor.execute.assert_not_called()


def test_changes_requested_rejects_blank_remarks(setup):
    client, _, cursor = setup

    response = request_changes(client, remarks="   ")

    assert response.status_code == 400
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    "areas",
    [
        None,
        [],
        "venue arrangement",
        ["not a real area"],
        ["venue arrangement", "venue arrangement"],
    ],
)
def test_changes_requested_rejects_bad_areas(areas, setup):
    client, _, cursor = setup

    response = request_changes(client, areas=areas)

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_changes_requested_runs_under_a_row_lock(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Safety Changes Requested"),
    ]

    request_changes(client)

    assert "FOR UPDATE" in cursor.execute.call_args_list[0].args[0]


def test_no_coordinator_check_on_request_changes(setup):
    """The Safety Officer deciding need not be the assigned coordinator."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check", coordinator_id=COORDINATOR_ID),
        event_row("Safety Changes Requested"),
    ]

    response = request_changes(client, decidedBy=OFFICER_ID)

    assert response.status_code == 200


# --- AC4/AC6: reject -----------------------------------------------------------


def test_pending_safety_check_moves_to_cancelled(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Cancelled"),
    ]

    response = reject(client)

    assert response.status_code == 200
    assert response.json["status"] == "Cancelled"
    assert cursor.execute.call_args_list[1].args[1][0] == "Cancelled"


def test_rejected_history_entry_has_remarks_and_no_areas(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Cancelled"),
    ]

    reject(client)

    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    action = stored["actionHistory"][-1]
    assert action["status"] == "Cancelled"
    assert action["decidedBy"] == OFFICER_ID
    assert action["remarks"] == "Unsafe egress plan."
    assert "areas" not in action
    assert "cancelled" in action["details"].lower()


def test_rejected_requires_remarks(setup):
    client, _, cursor = setup

    response = reject(client, remarks=None)

    assert response.status_code == 400
    assert response.json["message"] == "remarks is required."
    cursor.execute.assert_not_called()


def test_no_coordinator_check_on_reject(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check", coordinator_id=COORDINATOR_ID),
        event_row("Cancelled"),
    ]

    response = reject(client, decidedBy=OFFICER_ID)

    assert response.status_code == 200


# --- AC7: only 'Pending Safety Check' may move, and only with its own round --


@pytest.mark.parametrize("current_status", NON_PENDING_STATUSES)
def test_only_pending_safety_check_can_move_to_changes_requested(current_status, setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(current_status)

    response = request_changes(client)

    assert response.status_code == 409
    assert response.json["code"] == "INVALID_SAFETY_TRANSITION"
    assert response.json["currentStatus"] == current_status
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("current_status", NON_PENDING_STATUSES)
def test_only_pending_safety_check_can_be_rejected(current_status, setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(current_status)

    response = reject(client)

    assert response.status_code == 409
    assert response.json["code"] == "INVALID_SAFETY_TRANSITION"
    assert response.json["currentStatus"] == current_status
    assert cursor.execute.call_count == 1


def test_stale_safety_check_id_is_refused_for_changes_requested(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Pending Safety Check")

    response = request_changes(client, safetyCheckId=OTHER_SAFETY_CHECK_ID)

    assert response.status_code == 409
    assert response.json["code"] == "STALE_SAFETY_CHECK"
    assert cursor.execute.call_count == 1


def test_stale_safety_check_id_is_refused_for_reject(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Pending Safety Check")

    response = reject(client, safetyCheckId=OTHER_SAFETY_CHECK_ID)

    assert response.status_code == 409
    assert response.json["code"] == "STALE_SAFETY_CHECK"
    assert cursor.execute.call_count == 1


def test_missing_event_is_404(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = reject(client)

    assert response.status_code == 404
    assert response.json["message"] == "Event request not found."


# --- AC4: nothing leaves 'Cancelled' -------------------------------------------


@pytest.mark.parametrize("target", ["Pending Safety Check", "Confirmed"])
def test_cancelled_event_cannot_move_through_safety_status(target, setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Cancelled")

    if target == "Pending Safety Check":
        response = client.patch(
            f"/events/{EVENT_ID}/safety-status",
            json={
                "status": "Pending Safety Check",
                "coordinatorId": COORDINATOR_ID,
                "safetyCheckId": SAFETY_CHECK_ID,
                "roundNumber": 1,
            },
            headers=INTERNAL_HEADERS,
        )
    else:
        response = client.patch(
            f"/events/{EVENT_ID}/safety-status",
            json={
                "status": "Confirmed",
                "decidedBy": OFFICER_ID,
                "safetyCheckId": SAFETY_CHECK_ID,
                "roundNumber": 1,
            },
            headers=INTERNAL_HEADERS,
        )

    assert response.status_code == 409
    assert response.json["code"] == "INVALID_SAFETY_TRANSITION"
    assert cursor.execute.call_count == 1


def test_cancelled_event_progress_self_save_still_works(setup):
    """`/progress`'s Cancelled -> Cancelled notes save is untouched by this story."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Cancelled"),
        event_row("Cancelled", action_history=[]),
    ]

    response = client.patch(
        f"/events/{EVENT_ID}/progress",
        json={"coordinatorId": COORDINATOR_ID, "status": "Cancelled", "actionDetails": "Noted."},
    )

    assert response.status_code == 200
    assert response.json["status"] == "Cancelled"
