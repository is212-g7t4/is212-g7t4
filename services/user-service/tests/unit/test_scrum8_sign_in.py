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
- Signing in with email and password: checking the input, asking Supabase,
  turning its answer into a sign-in result, and loading the user's profile.
- We check the result the user gets (token and profile, or a message) and
  exactly what was sent to Supabase.

Doubled
-------
- Supabase sign-in: accepts or rejects the credentials, fails, or cannot be
  reached, as each test needs [Stub]; we check what was sent to it [Mock].
- User records (database): hold the user's profile, or none [Stub].

Not proven
----------
- That the real Supabase accepts this request and replies in this shape (-> E2E
  journeys J5/J6, which sign in for real).
- That the sign-in page stores the token and shows these messages (-> frontend
  LoginPage.test.tsx).
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
    Summary: Correct credentials sign the user in and return their profile, including the role that decides what they may do.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event.
    Double: Supabase accepts the credentials and issues a token, and the user
        records hold Alice's profile [Stub]; we check exactly what was sent to
        Supabase [Mock].
    """
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


def test_login_with_padded_email_sends_trimmed_email(setup):
    """
    Summary: Stray spaces around the email do not stop a user signing in.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event.
    Double: Supabase accepts the credentials [Stub]; we check the email sent
        to it has no surrounding spaces [Mock].
    """
    client, calls, _, _ = setup

    response = client.post("/auth/login", json={**CREDENTIALS, "email": "  alice.tan@connectsphere.example "})

    assert response.status_code == 200
    assert calls[0][1]["json"]["email"] == CREDENTIALS["email"]


@pytest.mark.parametrize("status", [400, 401], ids=["supabase_400", "supabase_401"])
def test_login_with_wrong_credentials_returns_401_and_no_token(setup, status):
    """
    Summary: A wrong email or password gives no token, and the user still cannot reach protected pages.
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality.
    Double: Supabase rejects the credentials [Stub].
    """
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
    ids=["no_body", "list_body", "missing_email", "blank_email", "missing_password", "empty_password", "non_string_email"],
)
def test_login_with_missing_credentials_returns_400_without_calling_supabase(setup, body):
    """
    Summary: A sign-in with a missing or blank email or password is refused before Supabase is asked.
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality.
    Double: We check Supabase is never contacted [Mock].
    """
    client, calls, _, _ = setup

    response = client.post("/auth/login", json=body)

    assert response.status_code == 400
    assert response.json == {"message": "Email and password are required."}
    assert calls == []


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError("down"), supabase_reply(500)],
    ids=["unreachable", "server_error"],
)
def test_login_when_supabase_unavailable_returns_503_and_no_token(setup, failure):
    """
    Summary: When Supabase cannot be reached or fails, the user gets no token and a try-again message, not "wrong password".
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality.
    Double: Supabase cannot be reached, or answers with a server error [Stub].
    """
    client, _, reply, _ = setup
    reply["response"] = failure

    response = client.post("/auth/login", json=CREDENTIALS)

    assert response.status_code == 503
    assert response.json == {"message": "Unable to reach the sign-in service. Please try again."}


def test_login_when_account_has_no_profile_returns_403_and_no_token(setup):
    """
    Summary: A Supabase account with no ConnectSphere profile is not signed in, so it cannot reach protected pages.
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality.
    Double: Supabase accepts the credentials, but the user records have no
        profile for that account [Stub].
    """
    client, _, _, cursor = setup
    cursor.fetchone.return_value = None

    response = client.post("/auth/login", json=CREDENTIALS)

    assert response.status_code == 403
    assert response.json == {"message": "This account has no ConnectSphere profile."}


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


@pytest.mark.parametrize("missing", ["SUPABASE_URL", "SUPABASE_ANON_KEY", "DATABASE_URL"], ids=["no_supabase_url", "no_anon_key", "no_database_url"])
def test_login_when_service_unconfigured_returns_503(missing):
    """
    Summary: Sign-in reports itself unavailable when Supabase or the user records are not configured.
    Supporting design check: an unconfigured sign-in answers 503 instead of
        failing in an unclear way
    Double: None
    """
    client = create_app({**CONFIG, missing: None}).test_client()

    response = client.post("/auth/login", json=CREDENTIALS)

    assert response.status_code == 503
    assert response.json == {"message": "Sign-in is not configured for User Service."}
