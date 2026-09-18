"""Event details AC1: view the full set of recorded information for a single event.

Database calls are mocked; no live database writes.
"""
import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.models import FIELDS

VALID = {
    "eventName": "Community Workshop", "description": "A workshop", "purpose": "Learning",
    "preferredStartDate": "2026-10-01T09:00", "preferredEndDate": "2026-10-01T17:00",
    "expectedAttendance": "25",
}

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


def saved_row():
    row = {column: VALID.get(key, "") for key, column in FIELDS.items()}
    row.update(event_id=EVENT_ID, status="Submitted",
               submission_date=datetime(2026, 9, 15, 1, 30),
               preferred_start_date=datetime(2026, 10, 1, 9),
               preferred_end_date=datetime(2026, 10, 1, 17), expected_attendance=25,
               coordinator_id=None)
    row["description"] = json.dumps({"_connectsphere": "event-submission-v1",
                                     "description": VALID["description"], "purpose": VALID["purpose"]})
    return row


def test_ac1_returns_full_event_details_for_assigned_coordinator(setup):
    client, _, cursor = setup
    assigned = saved_row()
    assigned["coordinator_id"] = COORDINATOR_ID
    cursor.fetchone.return_value = assigned

    response = client.get(f"/events/{EVENT_ID}?coordinatorId={COORDINATOR_ID}")

    assert response.status_code == 200
    body = response.json
    for key in FIELDS:
        assert key in body
    assert body["id"] == EVENT_ID
    assert body["status"] == "Submitted"
    assert body["purpose"] == "Learning"
    assert body["description"] == "A workshop"
    assert body["submittedAt"] == "2026-09-15T01:30:00+00:00"
    assert body["coordinatorId"] == COORDINATOR_ID
    query, parameters = cursor.execute.call_args.args
    assert "SELECT event_id" in query
    assert "FROM public.event_service" in query
    assert "FOR UPDATE" not in query
    assert parameters == [EVENT_ID]


def test_ac1_not_found_for_unknown_event(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = None
    response = client.get(f"/events/{EVENT_ID}?coordinatorId={COORDINATOR_ID}")
    assert response.status_code == 404


def test_ac1_forbidden_when_not_assigned_to_caller(setup):
    client, _, cursor = setup
    assigned = saved_row()
    assigned["coordinator_id"] = OTHER_COORDINATOR_ID
    cursor.fetchone.return_value = assigned

    response = client.get(f"/events/{EVENT_ID}?coordinatorId={COORDINATOR_ID}")

    assert response.status_code == 403


def test_ac1_forbidden_when_event_has_no_coordinator_assigned(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = saved_row()

    response = client.get(f"/events/{EVENT_ID}?coordinatorId={COORDINATOR_ID}")

    assert response.status_code == 403


@pytest.mark.parametrize("query_string", ["", "?coordinatorId=", "?coordinatorId=not-a-uuid"])
def test_ac1_requires_valid_coordinator_id(query_string, setup):
    client, _, cursor = setup
    response = client.get(f"/events/{EVENT_ID}{query_string}")
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_ac1_missing_database_configuration():
    client = create_app({"TESTING": True, "DATABASE_URL": None}).test_client()
    response = client.get(f"/events/{EVENT_ID}?coordinatorId={COORDINATOR_ID}")
    assert response.status_code == 503
