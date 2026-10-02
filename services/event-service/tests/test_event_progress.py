"""Update Event Status AC3-AC4: assigned coordinators update status and action details.

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
    metadata = {
        "_connectsphere": "event-submission-v1",
        "description": "A practical workshop",
        "purpose": "Learning",
        "decision": None,
        "decisionHistory": [],
        "actionDetails": action_details,
        "actionHistory": [],
    }
    row["description"] = json.dumps(metadata)
    return row


def test_assigned_coordinator_updates_status_and_records_action(setup):
    client, connection, cursor = setup
    updated = event_row("Approved", action_details="Venue and equipment confirmed.")
    updated_metadata = json.loads(updated["description"])
    updated_metadata["decision"] = {
        "status": "Approved",
        "coordinatorId": COORDINATOR_ID,
        "decidedAt": "2026-10-02T02:00:00+00:00",
        "reason": None,
    }
    updated_metadata["decisionHistory"] = [updated_metadata["decision"]]
    updated_metadata["actionHistory"] = [{
        "status": "Approved",
        "details": "Venue and equipment confirmed.",
        "coordinatorId": COORDINATOR_ID,
        "recordedAt": "2026-10-02T02:00:00+00:00",
    }]
    updated["description"] = json.dumps(updated_metadata)
    cursor.fetchone.side_effect = [event_row(), updated]

    response = client.patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": "Approved",
            "actionDetails": "  Venue and equipment confirmed.  ",
        },
    )

    assert response.status_code == 200
    assert response.json["status"] == "Approved"
    assert response.json["actionDetails"] == "Venue and equipment confirmed."
    assert response.json["actionHistory"][0]["coordinatorId"] == COORDINATOR_ID
    assert response.json["decision"]["status"] == "Approved"
    assert cursor.execute.call_count == 2
    select_query = cursor.execute.call_args_list[0].args[0]
    assert "FOR UPDATE" in select_query
    update_query, parameters = cursor.execute.call_args_list[1].args
    assert "SET status = %s, description = %s" in update_query
    assert parameters[0] == "Approved"
    stored = json.loads(parameters[1])
    assert stored["actionDetails"] == "Venue and equipment confirmed."
    assert stored["actionHistory"][0]["status"] == "Approved"
    assert parameters[2] == EVENT_ID
    connection.__exit__.assert_called_once()


def test_same_status_updates_action_details_without_duplicate_decision(setup):
    client, _, cursor = setup
    current = event_row("Approved", action_details="Venue confirmed.")
    current_metadata = json.loads(current["description"])
    current_metadata["decision"] = {
        "status": "Approved",
        "coordinatorId": COORDINATOR_ID,
        "decidedAt": "2026-10-01T02:00:00+00:00",
        "reason": None,
    }
    current_metadata["decisionHistory"] = [current_metadata["decision"]]
    current["description"] = json.dumps(current_metadata)
    updated = event_row("Approved", action_details="Equipment confirmed too.")
    cursor.fetchone.side_effect = [current, updated]

    response = client.patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": "Approved",
            "actionDetails": "Equipment confirmed too.",
        },
    )

    assert response.status_code == 200
    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    assert stored["decisionHistory"] == current_metadata["decisionHistory"]
    assert stored["actionHistory"][-1]["details"] == "Equipment confirmed too."


@pytest.mark.parametrize(
    ("current_status", "requested_status"),
    [("Approved", "Submitted"), ("Approved", "Rejected"),
     ("Rejected", "Submitted"), ("Rejected", "Approved")],
)
def test_final_status_cannot_transition(current_status, requested_status, setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(current_status)

    response = client.patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": requested_status,
            "actionDetails": "Attempted status change.",
        },
    )

    assert response.status_code == 409
    assert response.json["message"] == (
        "Approved and rejected events have a final status that cannot be changed."
    )
    assert cursor.execute.call_count == 1


def test_progress_update_is_forbidden_for_another_coordinators_event(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=OTHER_COORDINATOR_ID)

    response = client.patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": "Approved",
            "actionDetails": "Reviewed.",
        },
    )

    assert response.status_code == 403
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("status", ["", "Pending", "approved", None])
def test_progress_update_requires_supported_status(status, setup):
    response = setup[0].patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": status,
            "actionDetails": "Reviewed.",
        },
    )
    assert response.status_code == 400
    setup[2].execute.assert_not_called()


@pytest.mark.parametrize("details", ["", "   ", None, [], "x" * 1001])
def test_progress_update_requires_valid_action_details(details, setup):
    response = setup[0].patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": "Submitted",
            "actionDetails": details,
        },
    )
    assert response.status_code == 400
    setup[2].execute.assert_not_called()


@pytest.mark.parametrize("body", [{}, None, {"coordinatorId": "not-a-uuid"}])
def test_progress_update_requires_valid_coordinator(body, setup):
    response = setup[0].patch(f"/events/{EVENT_ID}/progress", json=body)
    assert response.status_code == 400
    setup[2].execute.assert_not_called()


def test_progress_update_returns_not_found(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = None
    response = client.patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": "Submitted",
            "actionDetails": "Reviewed.",
        },
    )
    assert response.status_code == 404


def test_progress_update_requires_database_configuration():
    client = create_app({"TESTING": True, "DATABASE_URL": None}).test_client()
    response = client.patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": "Submitted",
            "actionDetails": "Reviewed.",
        },
    )
    assert response.status_code == 503
