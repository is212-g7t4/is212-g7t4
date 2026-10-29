"""SCRUM-8: signing in with email and password through Supabase Auth.

Supabase and the database are mocked; nothing leaves the process.
"""

from unittest.mock import MagicMock

import httpx
import pytest

from app import create_app

USER_ID = "e7334aa9-eb3a-4c45-84b5-280501b6c109"
CREDENTIALS = {"email": "alice.tan@connectsphere.example", "password": "correct-horse"}
CONFIG = {
    "TESTING": True,
    "DATABASE_URL": "unused-test-url",
    "SUPABASE_URL": "https://project.supabase.test/",
    "SUPABASE_ANON_KEY": "anon-key",
}


def supabase_reply(status, body=None):
    return httpx.Response(status, json=body or {}, request=httpx.Request("POST", "https://project.supabase.test"))


@pytest.fixture
def setup(monkeypatch):
    calls = []
    reply = {"response": supabase_reply(200, {"access_token": "jwt", "expires_at": 1893456000, "user": {"id": USER_ID}})}

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if isinstance(reply["response"], Exception):
            raise reply["response"]
        return reply["response"]

    monkeypatch.setattr("app.httpx.post", post)
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = {
        "user_id": USER_ID,
        "username": "Alice Tan",
        "email": CREDENTIALS["email"],
        "role": "Event Coordinator Lead",
        "organization": "ConnectSphere",
        "contact_details": "+65 8111 1111",
    }
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    return create_app(CONFIG).test_client(), calls, reply, cursor


def test_valid_credentials_return_a_token_and_the_users_profile(setup):
    client, calls, _, cursor = setup

    response = client.post("/auth/login", json=CREDENTIALS)

    assert response.status_code == 200
    assert response.json["accessToken"] == "jwt"
    assert response.json["expiresAt"] == 1893456000
    assert response.json["user"]["user_id"] == USER_ID
    assert response.json["user"]["role"] == "Event Coordinator Lead"
    url, kwargs = calls[0]
    assert url == "https://project.supabase.test/auth/v1/token"
    assert kwargs["params"] == {"grant_type": "password"}
    assert kwargs["json"] == CREDENTIALS
    assert kwargs["headers"] == {"apikey": "anon-key"}
    assert cursor.execute.call_args.args[1] == [USER_ID]


def test_email_is_trimmed(setup):
    client, calls, _, _ = setup

    client.post("/auth/login", json={**CREDENTIALS, "email": "  alice.tan@connectsphere.example "})

    assert calls[0][1]["json"]["email"] == CREDENTIALS["email"]


@pytest.mark.parametrize("status", [400, 401])
def test_wrong_credentials_are_rejected_without_a_token(setup, status):
    """AC3: an unsuccessful attempt yields no token, so protected endpoints stay closed."""
    client, _, reply, _ = setup
    reply["response"] = supabase_reply(status, {"error_code": "invalid_credentials"})

    response = client.post("/auth/login", json=CREDENTIALS)

    assert response.status_code == 401
    assert response.json == {"message": "Incorrect email or password."}
    assert client.get("/users").status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {"password": "x"},
        {"email": "  ", "password": "x"},
        {"email": "a@b.c"},
        {"email": "a@b.c", "password": ""},
        {"email": 1, "password": "x"},
    ],
)
def test_missing_credentials_are_rejected_before_calling_supabase(setup, body):
    client, calls, _, _ = setup

    response = client.post("/auth/login", json=body)

    assert response.status_code == 400
    assert response.json == {"message": "Email and password are required."}
    assert calls == []


@pytest.mark.parametrize("missing", ["SUPABASE_URL", "SUPABASE_ANON_KEY", "DATABASE_URL"])
def test_unconfigured_sign_in_is_unavailable(monkeypatch, missing):
    client = create_app({**CONFIG, missing: None}).test_client()

    assert client.post("/auth/login", json=CREDENTIALS).status_code == 503


def test_unreachable_supabase_is_unavailable(setup):
    client, _, reply, _ = setup
    reply["response"] = httpx.ConnectError("down")

    response = client.post("/auth/login", json=CREDENTIALS)

    assert response.status_code == 503
    assert "accessToken" not in response.json


def test_supabase_failure_is_unavailable(setup):
    client, _, reply, _ = setup
    reply["response"] = supabase_reply(500)

    assert client.post("/auth/login", json=CREDENTIALS).status_code == 503


def test_account_without_a_profile_is_refused(setup):
    client, _, _, cursor = setup
    cursor.fetchone.return_value = None

    response = client.post("/auth/login", json=CREDENTIALS)

    assert response.status_code == 403
    assert "accessToken" not in response.json
