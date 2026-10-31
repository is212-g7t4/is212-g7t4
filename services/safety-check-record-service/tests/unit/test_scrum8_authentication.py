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
- Safety Check Record Service's sign-in check in front of every protected
  request: the token's signature, expiry, audience and user, refusing the
  internal service token for any action on a round, and staying closed when
  checking is impossible.
- We check whether the caller gets in, and the message they see.

Doubled
-------
- Supabase's signing keys: a test key stands in, so tokens can be made locally
  (tests/unit/conftest.py) [Stub].
- Safety records (database): empty, so a request that gets in needs no database
  [Stub].

Not proven
----------
- That tokens issued by the real Supabase project pass this check (-> E2E
  journeys, which sign in for real).
"""

import time
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.auth import signing_key as real_signing_key
from tests.unit.factories import TEST_SIGNING_KEY, bearer

USER_ID = "e7334aa9-eb3a-4c45-84b5-280501b6c109"


@pytest.fixture(autouse=True)
def internal_service_token(monkeypatch):
    """The token background workers present as X-Internal-Token."""
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "internal-test-token")


EVENT = "22222222-2222-4222-8222-222222222222"
RECORD = "33333333-3333-4333-8333-333333333333"
INTERNAL = {"X-Internal-Token": "internal-test-token"}


@pytest.fixture
def client(monkeypatch):
    from app import create_app

    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value.fetchall.return_value = []
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    return create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"}).test_client()


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/safety-check-records", {"eventId": EVENT}),
        ("patch", f"/safety-check-records/{RECORD}/decision", {"status": "Safety Approved"}),
        ("post", f"/safety-check-records/{RECORD}/withdraw", {"reason": "Venue moved"}),
    ],
    ids=["open_round", "decide_round", "withdraw_round"],
)
def test_internal_token_when_round_action_requested_returns_401(client, method, path, body):
    """
    Summary: A background worker's internal service token cannot open, decide or withdraw a safety round.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    response = getattr(client, method)(path, json=body, headers=INTERNAL)

    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_authenticate_without_token_returns_401_sign_in_message(client):
    """
    Summary: A user who has not signed in is turned away and asked to sign in.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    response = client.get("/safety-check-records?eventId=22222222-2222-4222-8222-222222222222")

    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_authenticate_with_non_bearer_scheme_returns_401(client):
    """
    Summary: Credentials sent in any form other than a sign-in token are refused.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    assert client.get("/safety-check-records?eventId=22222222-2222-4222-8222-222222222222", headers={"Authorization": "Basic abc"}).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(bearer(USER_ID, "Event Coordinator", key=ec.generate_private_key(ec.SECP256R1())), id="forged-signature"),
        pytest.param(bearer(USER_ID, "Event Coordinator", exp=int(time.time()) - 60), id="expired"),
        pytest.param(bearer(USER_ID, "Event Coordinator", aud="anon"), id="wrong-audience"),
        pytest.param({"Authorization": "Bearer not-a-jwt"}, id="malformed"),
    ],
)
def test_authenticate_with_invalid_token_returns_401_session_expired(client, headers):
    """
    Summary: Forged, expired, wrong-audience or malformed sign-in tokens are all refused.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    response = client.get("/safety-check-records?eventId=22222222-2222-4222-8222-222222222222", headers=headers)

    assert response.status_code == 401
    assert response.json == {"message": "Your session is invalid or has expired. Sign in again."}


def test_authenticate_with_token_missing_subject_returns_401(client):
    """
    Summary: A sign-in token that names no user is refused.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    token = jwt.encode({"aud": "authenticated", "exp": int(time.time()) + 60}, TEST_SIGNING_KEY, algorithm="ES256")

    assert client.get("/safety-check-records?eventId=22222222-2222-4222-8222-222222222222", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_authenticate_with_dev_identity_headers_returns_401(client):
    """
    Summary: The old developer identity headers cannot be used to pose as another user.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    headers = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Event Coordinator"}

    assert client.get("/safety-check-records?eventId=22222222-2222-4222-8222-222222222222", headers=headers).status_code == 401


def test_authenticate_with_internal_token_alone_returns_401():
    """
    Summary: The internal service token on its own is not a way into this service.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    from flask import Flask

    from app.auth import authenticate

    with Flask(__name__).test_request_context("/anything", headers={"X-Internal-Token": "internal-test-token"}):
        response, status = authenticate()

    assert status == 401
    assert response.json == {"message": "Sign in to continue."}


def test_authenticate_with_bad_user_token_and_internal_token_returns_401(client):
    """
    Summary: A bad sign-in token is refused even when the internal service token is also sent.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    headers = {"X-Internal-Token": "internal-test-token", "Authorization": "Bearer not-a-jwt"}

    assert client.get("/safety-check-records?eventId=22222222-2222-4222-8222-222222222222", headers=headers).status_code == 401


def test_authenticate_with_wrong_internal_token_returns_401(client):
    """
    Summary: Guessing the internal service token does not get a caller in.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    assert client.get("/safety-check-records?eventId=22222222-2222-4222-8222-222222222222", headers={"X-Internal-Token": "guess"}).status_code == 401


def test_authenticate_when_supabase_url_missing_returns_503(client, monkeypatch):
    """
    Summary: When sign-in checking is not configured, protected pages stay closed rather than open.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    monkeypatch.delenv("SUPABASE_URL")

    assert client.get("/safety-check-records?eventId=22222222-2222-4222-8222-222222222222", headers=bearer(USER_ID, "Event Coordinator")).status_code == 503


def test_authenticate_when_jwks_unreachable_returns_503(client, monkeypatch):
    """
    Summary: When Supabase's signing keys cannot be fetched, protected pages stay closed rather than open.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Supabase's signing keys cannot be fetched [Stub].
    """
    def unreachable(token):
        raise jwt.PyJWKClientConnectionError("down")

    monkeypatch.setattr("app.auth.signing_key", unreachable)

    assert client.get("/safety-check-records?eventId=22222222-2222-4222-8222-222222222222", headers=bearer(USER_ID, "Event Coordinator")).status_code == 503


def test_signing_key_fetches_key_from_supabase_jwks_url(monkeypatch):
    """
    Summary: Tokens are verified against the Supabase project's published signing keys.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: We check the keys are fetched from this project's Supabase address
        [Mock].
    """
    jwks = MagicMock()
    created = []
    monkeypatch.setattr("app.auth.jwt.PyJWKClient", lambda url: created.append(url) or jwks)
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test/")

    key = real_signing_key("token")

    assert created == ["https://project.supabase.test/auth/v1/.well-known/jwks.json"]
    jwks.get_signing_key_from_jwt.assert_called_once_with("token")
    assert key is jwks.get_signing_key_from_jwt.return_value.key


def test_authenticate_with_blank_subject_returns_401():
    """
    Summary: A sign-in token naming an empty user is refused.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    from flask import Flask

    from app.auth import authenticate

    with Flask(__name__).test_request_context("/anything", headers=bearer("", "Attendee")):
        response, status = authenticate()

    assert status == 401


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_health_and_preflight_without_token_are_answered(client):
    """
    Summary: Health checks and browser preflights need no sign-in.
    Supporting design check: /health and CORS preflight answer without a token
    Double: None
    """
    assert client.get("/health").status_code == 200
    assert client.options("/safety-check-records?eventId=22222222-2222-4222-8222-222222222222").status_code == 200
