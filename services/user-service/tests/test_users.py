"""User lookups: list (optionally filtered by role) and get by id.

Database calls are mocked; no live database writes.
"""
from unittest.mock import MagicMock

import pytest

from app import create_app

ALICE_ID = "e7334aa9-eb3a-4c45-84b5-280501b6c109"
MARCUS_ID = "7912075d-46f5-405b-9af3-05502f42f173"


def user_row(**overrides):
    row = {
        "user_id": ALICE_ID,
        "username": "Alice Tan",
        "email": "alice.tan@connectsphere.example",
        "role": "Event Coordinator",
        "organization": "ConnectSphere",
        "contact_details": "+65 8111 1111",
        "manager_id": None,
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


def test_list_users_returns_all_users(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = [
        user_row(),
        user_row(user_id=MARCUS_ID, username="Marcus Lim", manager_id=ALICE_ID),
    ]

    response = client.get("/users")

    assert response.status_code == 200
    assert len(response.json["users"]) == 2
    assert response.json["users"][1]["manager_id"] == ALICE_ID
    query, params = cursor.execute.call_args.args
    assert "WHERE" not in query
    assert params == []


def test_list_users_filters_by_role(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = [user_row()]

    response = client.get("/users?role=Event+Coordinator")

    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert "role = %s" in query
    assert params == ["Event Coordinator"]


def test_get_user_returns_manager_with_null_manager_id(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = user_row()

    response = client.get(f"/users/{ALICE_ID}")

    assert response.status_code == 200
    assert response.json["manager_id"] is None
    assert response.json["role"] == "Event Coordinator"


def test_get_user_returns_404_when_not_found(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = client.get(f"/users/{ALICE_ID}")

    assert response.status_code == 404


def test_get_user_rejects_invalid_uuid(setup):
    client, _, cursor = setup

    response = client.get("/users/not-a-uuid")

    assert response.status_code == 404
    cursor.execute.assert_not_called()


def test_missing_database_configuration():
    client = create_app({"TESTING": True, "DATABASE_URL": None}).test_client()
    response = client.get("/users")
    assert response.status_code == 503


def test_get_user_missing_database_configuration():
    client = create_app({"TESTING": True, "DATABASE_URL": None}).test_client()
    response = client.get(f"/users/{ALICE_ID}")
    assert response.status_code == 503


def test_health_and_browser_cors(setup):
    client = setup[0]
    assert client.get("/health").json == {"status": "ok"}
    response = client.options("/users", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert (
        "Access-Control-Allow-Origin"
        not in client.options("/users", headers={"Origin": "https://other.example"}).headers
    )
