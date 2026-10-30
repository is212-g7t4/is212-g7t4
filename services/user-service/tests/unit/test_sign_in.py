"""
SCRUM-8: User Authentication and Authorization

User Story
----------
As a system user, I want to securely access the system, so that I can use the
information and functionality available to me.

Acceptance Criteria
-------------------
AC1: Given a system user has not been successfully authenticated, when they
     attempt to access protected information or functionality, then access is
     denied.
AC2: Given a system user successfully authenticates, when they access protected
     information or functionality, then their access is evaluated according to
     their role and relationship to the relevant event.
AC3: Given a system user's authentication attempt is unsuccessful, when the
     authentication attempt is completed, then they remain unable to access
     protected information or functionality.

Real
----
- POST /auth/login: input validation, the Supabase password-grant request it
  builds, response mapping and the profile lookup run for real.
- Assertions are on the status, the returned token and profile, and the exact
  request sent to Supabase.

Doubled
-------
- httpx.post (Supabase Auth): Stub that also records calls - returns a canned
  token reply, an error status, or raises ConnectError; the recorded call is
  asserted on to prove what is sent to Supabase.
- psycopg2.connect: Stub - the cursor returns a canned User row (or None).

Not proven
----------
- That the real Supabase Auth accepts the request shape and returns these
  fields (-> E2E journeys J5/J6, which sign in for real).
- That the UI stores the token and shows the error message (-> frontend
  LoginPage.test.tsx and e2e/role-switching.spec.ts).
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


def test_login_with_valid_credentials_returns_token_and_profile(setup):
    """
    Summary: Correct credentials return an access token together with the user's profile and role.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event.
    Double: Stub (Supabase returns a token; cursor returns the profile), Mock
        (records the Supabase request)
    """
    # Arrange (Given)
    client, calls, _, cursor = setup

    # Act (When)
    response = client.post("/auth/login", json=CREDENTIALS)

    # Assert (Then)
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


def test_login_with_padded_email_sends_trimmed_email(setup):
    """
    Summary: Stray spaces around the email do not stop a user signing in.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event.
    Double: Mock (records the Supabase request)
    """
    # Arrange (Given)
    client, calls, _, _ = setup

    # Act (When)
    client.post("/auth/login", json={**CREDENTIALS, "email": "  alice.tan@connectsphere.example "})

    # Assert (Then)
    assert calls[0][1]["json"]["email"] == CREDENTIALS["email"]


@pytest.mark.parametrize("status", [400, 401], ids=["supabase_400", "supabase_401"])
def test_login_with_wrong_credentials_returns_401_and_no_token(setup, status):
    """
    Summary: A wrong email or password gives no token, so protected endpoints stay closed.
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality.
    Double: Stub (Supabase answers 400 or 401)
    """
    # Arrange (Given)
    client, _, reply, _ = setup
    reply["response"] = supabase_reply(status, {"error_code": "invalid_credentials"})

    # Act (When)
    response = client.post("/auth/login", json=CREDENTIALS)

    # Assert (Then)
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
    ids=["no_body", "list_body", "missing_email", "blank_email", "missing_password", "empty_password", "non_string_email"],
)
def test_login_with_missing_credentials_returns_400_without_calling_supabase(setup, body):
    """
    Summary: A sign-in with a missing or blank email or password is refused before Supabase is asked.
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality.
    Double: Mock (asserts Supabase is never called)
    """
    # Arrange (Given)
    client, calls, _, _ = setup

    # Act (When)
    response = client.post("/auth/login", json=body)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json == {"message": "Email and password are required."}
    assert calls == []


@pytest.mark.parametrize("missing", ["SUPABASE_URL", "SUPABASE_ANON_KEY", "DATABASE_URL"], ids=["no_supabase_url", "no_anon_key", "no_database_url"])
def test_login_when_service_unconfigured_returns_503(monkeypatch, missing):
    """
    Summary: Sign-in reports itself unavailable when Supabase or the database is not configured.
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality.
    Double: None
    """
    # Arrange (Given)
    client = create_app({**CONFIG, missing: None}).test_client()

    # Act + Assert (When / Then)
    assert client.post("/auth/login", json=CREDENTIALS).status_code == 503


def test_login_when_supabase_unreachable_returns_503_and_no_token(setup):
    """
    Summary: When Supabase cannot be reached, the user gets no token and a try-again message.
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality.
    Double: Stub (httpx.post raises ConnectError)
    """
    # Arrange (Given)
    client, _, reply, _ = setup
    reply["response"] = httpx.ConnectError("down")

    # Act (When)
    response = client.post("/auth/login", json=CREDENTIALS)

    # Assert (Then)
    assert response.status_code == 503
    assert "accessToken" not in response.json


def test_login_when_supabase_errors_returns_503(setup):
    """
    Summary: A Supabase server error is reported as unavailable rather than as wrong credentials.
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality.
    Double: Stub (Supabase answers 500)
    """
    # Arrange (Given)
    client, _, reply, _ = setup
    reply["response"] = supabase_reply(500)

    # Act + Assert (When / Then)
    assert client.post("/auth/login", json=CREDENTIALS).status_code == 503


def test_login_when_account_has_no_profile_returns_403_and_no_token(setup):
    """
    Summary: An account with no ConnectSphere profile cannot sign in.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event.
    Double: Stub (cursor returns no profile row)
    """
    # Arrange (Given)
    client, _, _, cursor = setup
    cursor.fetchone.return_value = None

    # Act (When)
    response = client.post("/auth/login", json=CREDENTIALS)

    # Assert (Then)
    assert response.status_code == 403
    assert "accessToken" not in response.json
