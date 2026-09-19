import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from app import create_app
from app.models import FIELDS

EVENT_ID = "00000000-0000-0000-0000-000000000001"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"


def event_row(**overrides):
    row = {column: "Current value" for column in FIELDS.values()}
    row.update(
        event_id=EVENT_ID,
        status="Submitted",
        submission_date=datetime(2026, 9, 15, 1, 30),
        preferred_start_date=datetime(2026, 10, 1, 9),
        preferred_end_date=datetime(2026, 10, 1, 17),
        expected_attendance=25,
        coordinator_id=COORDINATOR_ID,
    )
    row["description"] = json.dumps(
        {
            "_connectsphere": "event-submission-v1",
            "description": "Current description",
            "purpose": "Current purpose",
        }
    )
    row.update(overrides)
    return row


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    return connection, cursor


def test_low_impact_update_is_saved_without_conflict_check(setup):
    connection, cursor = setup
    cursor.fetchone.side_effect = [
        event_row(),
        event_row(
            description=json.dumps(
                {
                    "_connectsphere": "event-submission-v1",
                    "description": "Updated description",
                    "purpose": "Current purpose",
                }
            )
        ),
    ]
    conflict_checker = MagicMock(return_value=["should not be called"])
    client = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": "unused-test-url",
            "ARRANGEMENT_CONFLICT_CHECKER": conflict_checker,
        }
    ).test_client()

    response = client.patch(
        f"/events/{EVENT_ID}/update",
        json={"coordinatorId": COORDINATOR_ID, "description": "Updated description"},
    )

    assert response.status_code == 200
    assert response.json["description"] == "Updated description"
    conflict_checker.assert_not_called()
    assert "SET event_name = %s" in cursor.execute.call_args_list[-1].args[0]
    connection.commit.assert_called()


def test_high_impact_conflict_blocks_update(setup):
    _, cursor = setup
    cursor.fetchone.return_value = event_row()
    conflict_checker = MagicMock(
        return_value=["Confirmed venue booking cannot support the new time."]
    )
    client = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": "unused-test-url",
            "ARRANGEMENT_CONFLICT_CHECKER": conflict_checker,
        }
    ).test_client()

    response = client.patch(
        f"/events/{EVENT_ID}/update",
        json={
            "coordinatorId": COORDINATOR_ID,
            "preferredStartDate": "2026-10-02T09:00",
            "preferredEndDate": "2026-10-02T17:00",
        },
    )

    assert response.status_code == 409
    assert response.json["conflicts"] == [
        "Confirmed venue booking cannot support the new time."
    ]
    assert cursor.execute.call_count == 1
    conflict_checker.assert_called_once()


def test_high_impact_update_without_conflict_is_saved(setup):
    _, cursor = setup
    updated = event_row(preferred_start_date=datetime(2026, 10, 2, 9))
    cursor.fetchone.side_effect = [event_row(), updated]
    conflict_checker = MagicMock(return_value=[])
    client = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": "unused-test-url",
            "ARRANGEMENT_CONFLICT_CHECKER": conflict_checker,
        }
    ).test_client()

    response = client.patch(
        f"/events/{EVENT_ID}/update",
        json={
            "coordinatorId": COORDINATOR_ID,
            "preferredStartDate": "2026-10-02T09:00",
        },
    )

    assert response.status_code == 200
    conflict_checker.assert_called_once()
    assert response.json["preferredStartDate"] == "2026-10-02T09:00:00"


def test_update_requires_assigned_coordinator(setup):
    _, cursor = setup
    cursor.fetchone.return_value = event_row(
        coordinator_id="22222222-2222-4222-8222-222222222222"
    )
    client = create_app(
        {"TESTING": True, "DATABASE_URL": "unused-test-url"}
    ).test_client()

    response = client.patch(
        f"/events/{EVENT_ID}/update",
        json={"coordinatorId": COORDINATOR_ID, "eventName": "New name"},
    )

    assert response.status_code == 403
