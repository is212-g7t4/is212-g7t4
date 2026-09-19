"""Event list AC2/AC3: filter the coordinator's own event list.

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

COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), connection, cursor


def saved_row(**overrides):
    row = {column: VALID.get(key, "") for key, column in FIELDS.items()}
    row.update(event_id="00000000-0000-0000-0000-000000000001", status="Submitted",
               submission_date=datetime(2026, 9, 15, 1, 30),
               preferred_start_date=datetime(2026, 10, 1, 9),
               preferred_end_date=datetime(2026, 10, 1, 17), expected_attendance=25,
               coordinator_id=COORDINATOR_ID)
    row["description"] = json.dumps({"_connectsphere": "event-submission-v1",
                                     "description": VALID["description"], "purpose": VALID["purpose"]})
    row.update(overrides)
    return row


def test_ac2_returns_only_events_assigned_to_caller(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = [saved_row(), saved_row(event_id="00000000-0000-0000-0000-000000000002")]

    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}")

    assert response.status_code == 200
    assert len(response.json["events"]) == 2
    query, params = cursor.execute.call_args.args
    assert "coordinator_id = %s" in query
    assert params[0] == COORDINATOR_ID
    assert params == [COORDINATOR_ID]


def test_ac2_filters_by_status(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = [saved_row()]

    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}&status=Approved")

    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert "status = %s" in query
    assert params == [COORDINATOR_ID, "Approved"]


def test_ac2_filters_by_venue_substring(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = [saved_row()]

    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}&venue=Main+Hall")

    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert "venue_requirements ILIKE %s ESCAPE '\\'" in query
    assert params == [COORDINATOR_ID, "%Main Hall%"]


def test_ac2_venue_filter_escapes_percent_and_underscore(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = []

    response = client.get("/events", query_string={"coordinatorId": COORDINATOR_ID, "venue": "Room 50% A_B"})

    assert response.status_code == 200
    _, params = cursor.execute.call_args.args
    assert params == [COORDINATOR_ID, "%Room 50\\% A\\_B%"]


def test_ac2_filters_by_date_range(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = [saved_row()]

    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}&dateFrom=2026-09-01&dateTo=2026-10-31")

    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert "preferred_start_date <= %s" in query
    assert "preferred_end_date >= %s" in query
    assert params[0] == COORDINATOR_ID
    assert params[1] == datetime(2026, 10, 31, 23, 59, 59, 999999)
    assert params[2] == datetime(2026, 9, 1)


def test_ac2_date_range_is_inclusive_of_end_date(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = []

    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}&dateTo=2026-10-31")

    assert response.status_code == 200
    _, params = cursor.execute.call_args.args
    assert params == [COORDINATOR_ID, datetime(2026, 10, 31, 23, 59, 59, 999999)]


def test_ac2_combined_filters(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = []

    response = client.get(
        f"/events?coordinatorId={COORDINATOR_ID}&status=Submitted&venue=Hall&dateFrom=2026-01-01"
    )

    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert "coordinator_id = %s" in query
    assert "status = %s" in query
    assert "venue_requirements ILIKE" in query
    assert "preferred_end_date >= %s" in query
    assert params == [COORDINATOR_ID, "Submitted", "%Hall%", datetime(2026, 1, 1)]


def test_ac3_no_filters_still_requires_and_scopes_by_coordinator(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = []

    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}")

    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert query.strip().count("%s") == 1
    assert params == [COORDINATOR_ID]


@pytest.mark.parametrize("query_string", ["", "?coordinatorId=", "?coordinatorId=not-a-uuid"])
def test_ac3_requires_valid_coordinator_id(query_string, setup):
    client, _, cursor = setup
    response = client.get(f"/events{query_string}")
    assert response.status_code == 400
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("query_string", [
    "dateFrom=not-a-date",
    "dateTo=not-a-date",
    "dateFrom=2026-10-01T09:00",
    "dateTo=2026-10-01T09:00",
    "dateFrom=2026-10-31&dateTo=2026-10-01",
])
def test_ac2_rejects_invalid_date_range(query_string, setup):
    client, _, cursor = setup
    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}&{query_string}")
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_ac2_missing_database_configuration():
    client = create_app({"TESTING": True, "DATABASE_URL": None}).test_client()
    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}")
    assert response.status_code == 503
