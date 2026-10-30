"""Attendee catalogue: expose only confirmed events for registration discovery."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.models import FIELDS
from tests.unit.factories import signed_in


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client(), role="Attendee"), cursor


def confirmed_row():
    row = {column: "" for column in FIELDS.values()}
    row.update(
        event_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        event_name="Community Workshop",
        description=json.dumps({
            "_connectsphere": "event-submission-v1",
            "description": "A practical workshop",
            "purpose": "Learning",
        }),
        preferred_start_date=datetime(2026, 11, 10, 9),
        preferred_end_date=datetime(2026, 11, 10, 12),
        expected_attendance=30,
        status="Confirmed",
        submission_date=datetime(2026, 10, 1, 8, tzinfo=UTC),
        coordinator_id=None,
        organiser_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    )
    return row


def test_attendee_catalogue_returns_confirmed_events(setup):
    client, cursor = setup
    cursor.fetchall.return_value = [confirmed_row()]

    response = client.get("/events/registration")

    assert response.status_code == 200
    assert response.json["events"][0]["status"] == "Confirmed"
    query = cursor.execute.call_args.args[0]
    assert "status = 'Confirmed'" in query
    assert "coordinator_id" not in query.split("WHERE")[1]


def test_attendee_catalogue_reports_missing_database_configuration():
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client(), role="Attendee")
    assert client.get("/events/registration").status_code == 503
