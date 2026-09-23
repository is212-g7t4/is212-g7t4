"""Registration lookups: list every registration row for a given event.

Database calls are mocked; no live database writes.
"""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app import create_app

EVENT_ID = "25c9fe40-c44d-4d79-8d5d-de66d40c1678"


def registration_row(**overrides):
    row = {
        "registration_id": "9f725c7a-ac3d-4d4a-937a-84db7906be71",
        "event_id": EVENT_ID,
        "attendee_id": None,
        "registration_date": datetime(2026, 9, 13, 9, 15),
        "status": "Confirmed",
        "attendee_name": "Lena Ho",
        "attendee_email": "lena.ho@example.com",
        "attendee_organization": "Acme Studio",
    }
    row.update(overrides)
    return row


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), connection, cursor


def test_list_registrations_returns_all_rows_for_event(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = [
        registration_row(),
        registration_row(registration_id="1eec36d7-3c51-4981-8f80-ae62f7f99b7f", status="Withdrawn", attendee_organization=""),
    ]

    response = client.get(f"/registrations?eventId={EVENT_ID}")

    assert response.status_code == 200
    assert len(response.json["registrations"]) == 2
    assert response.json["registrations"][0]["status"] == "Confirmed"
    assert response.json["registrations"][1]["status"] == "Withdrawn"
    query, params = cursor.execute.call_args.args
    assert "WHERE event_id = %s" in query
    assert params == [EVENT_ID]


def test_list_registrations_returns_empty_list_when_none_exist(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = []

    response = client.get(f"/registrations?eventId={EVENT_ID}")

    assert response.status_code == 200
    assert response.json == {"registrations": []}


def test_registration_date_serializes_to_isoformat(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = [registration_row()]

    response = client.get(f"/registrations?eventId={EVENT_ID}")

    assert response.json["registrations"][0]["registration_date"] == "2026-09-13T09:15:00"


def test_null_registration_date_serializes_to_none(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = [registration_row(registration_date=None)]

    response = client.get(f"/registrations?eventId={EVENT_ID}")

    assert response.json["registrations"][0]["registration_date"] is None


@pytest.mark.parametrize("query_string", ["", "?eventId=", "?eventId=not-a-uuid"])
def test_requires_valid_event_id(query_string, setup):
    client, _, cursor = setup
    response = client.get(f"/registrations{query_string}")
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_missing_database_configuration():
    client = create_app({"TESTING": True, "DATABASE_URL": None}).test_client()
    response = client.get(f"/registrations?eventId={EVENT_ID}")
    assert response.status_code == 503


def test_health_and_browser_cors(setup):
    client = setup[0]
    assert client.get("/health").json == {"status": "ok"}
    response = client.options("/registrations", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert (
        "Access-Control-Allow-Origin"
        not in client.options("/registrations", headers={"Origin": "https://other.example"}).headers
    )
