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
- app.auth.authenticate(): bearer parsing, ES256 signature, expiry, audience
  and subject checks, the internal-token path and the fail-closed paths run for
  real in front of a real create_app(); identity checks prove the caller is
  taken from the token, never from the body or headers.
- Assertions are on the HTTP status and the message the caller sees.

Doubled
-------
- Supabase JWKS: Stub (tests/conftest.py) - signing_key returns a throwaway
  ES256 public key so tokens can be minted locally.
- psycopg2.connect: Stub - a MagicMock connection whose cursor finds no
  request, so a request that passes sign-in gets a 404.
- jwt.PyJWKClient: Mock - verifies the JWKS URL built from SUPABASE_URL.

Not proven
----------
- That tokens issued by the real Supabase project verify against its live JWKS
  (-> E2E journeys J5/J6, which sign in for real through the UI).
- That the custom_access_token_hook really puts user_role in the token (-> E2E
  journeys J5/J6).
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


@pytest.fixture
def client(monkeypatch):
    from app import create_app

    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    return create_app({"DATABASE_URL": "postgresql://x"}).test_client()


REQUEST = "2a1bfb57-a3c0-4450-897e-cc5c73690000"


def test_authenticate_with_technical_support_token_reaches_lookup(client):
    """
    Summary: A signed-in Technical Support user gets past sign-in to the request lookup.
    AC2: successfully authenticated users reach protected functionality
    Double: Stub (cursor finds no request)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get(f"/equipment-requests/{REQUEST}", headers=bearer(USER_ID, "Technical Support"))

    # Assert (Then)
    assert response.status_code == 404  # past authentication, into the lookup


def test_authenticate_with_lead_token_reads_like_coordinator(client):
    """
    Summary: The Event Coordinator Lead can read equipment requests with their own token.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event.
    Double: Stub (cursor finds no request)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get(f"/equipment-requests/{REQUEST}", headers=bearer(USER_ID, "Event Coordinator Lead"))

    # Assert (Then)
    assert response.status_code == 404


def test_authenticate_with_dev_role_header_uses_token_role_instead(client):
    """
    Summary: A retired developer role header cannot raise an attendee to Technical Support.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event.
    Double: Stub (cursor finds no request)
    """
    # Arrange (Given)
    headers = {**bearer(USER_ID, "Attendee"), "X-Dev-Role": "Technical Support"}

    # Act + Assert (When / Then)
    assert client.get(f"/equipment-requests/{REQUEST}", headers=headers).status_code == 403




def test_authenticate_without_token_returns_401_sign_in_message(client):
    """
    Summary: A request with no sign-in token is turned away with a sign-in prompt.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000")

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_authenticate_with_non_bearer_scheme_returns_401(client):
    """
    Summary: Credentials sent in any form other than a bearer token are refused.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000", headers={"Authorization": "Basic abc"}).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(bearer(USER_ID, "Technical Support", key=ec.generate_private_key(ec.SECP256R1())), id="forged-signature"),
        pytest.param(bearer(USER_ID, "Technical Support", exp=int(time.time()) - 60), id="expired"),
        pytest.param(bearer(USER_ID, "Technical Support", aud="anon"), id="wrong-audience"),
        pytest.param({"Authorization": "Bearer not-a-jwt"}, id="malformed"),
    ],
)
def test_authenticate_with_invalid_token_returns_401_session_expired(client, headers):
    """
    Summary: Forged, expired, wrong-audience or malformed tokens are all refused.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    # Arrange (Given): client, headers, from fixtures

    # Act (When)
    response = client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000", headers=headers)

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Your session is invalid or has expired. Sign in again."}


def test_authenticate_with_token_missing_subject_returns_401(client):
    """
    Summary: A token that names no user is refused.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    # Arrange (Given)
    token = jwt.encode({"aud": "authenticated", "exp": int(time.time()) + 60}, TEST_SIGNING_KEY, algorithm="ES256")

    # Act + Assert (When / Then)
    assert client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_authenticate_with_dev_identity_headers_returns_401(client):
    """
    Summary: Old developer identity headers cannot be used to impersonate a user.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    # Arrange (Given)
    headers = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Technical Support"}

    # Act + Assert (When / Then)
    assert client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000", headers=headers).status_code == 401


def test_authenticate_with_internal_token_cannot_act_as_a_user(client):
    """
    Summary: A background worker's internal token cannot perform an action that needs a signed-in user.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000", headers={"X-Internal-Token": "internal-test-token"})

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_authenticate_with_bad_user_token_and_internal_token_returns_401(client):
    """
    Summary: A bad user token is refused even when an internal token is also sent.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    # Arrange (Given)
    headers = {"X-Internal-Token": "internal-test-token", "Authorization": "Bearer not-a-jwt"}

    # Act + Assert (When / Then)
    assert client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000", headers=headers).status_code == 401


def test_authenticate_with_wrong_internal_token_returns_401(client):
    """
    Summary: Guessing the internal token does not get a caller in.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000", headers={"X-Internal-Token": "guess"}).status_code == 401


def test_authenticate_when_supabase_url_missing_returns_503(client, monkeypatch):
    """
    Summary: When sign-in checking is not configured, protected endpoints stay closed.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    # Arrange (Given)
    monkeypatch.delenv("SUPABASE_URL")

    # Act + Assert (When / Then)
    assert client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000", headers=bearer(USER_ID, "Technical Support")).status_code == 503


def test_authenticate_when_jwks_unreachable_returns_503(client, monkeypatch):
    """
    Summary: When Supabase's signing keys cannot be fetched, protected endpoints stay closed.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Stub (signing_key raises PyJWKClientConnectionError)
    """
    # Arrange (Given)
    def unreachable(token):
        raise jwt.PyJWKClientConnectionError("down")

    monkeypatch.setattr("app.auth.signing_key", unreachable)

    # Act + Assert (When / Then)
    assert client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000", headers=bearer(USER_ID, "Technical Support")).status_code == 503


def test_signing_key_fetches_key_from_supabase_jwks_url(monkeypatch):
    """
    Summary: Tokens are verified against the Supabase project's published signing keys.
    AC1: tokens are checked against Supabase's keys before access is granted
    Double: Mock (jwt.PyJWKClient records the JWKS URL and returns a key)
    """
    jwks = MagicMock()
    created = []
    monkeypatch.setattr("app.auth.jwt.PyJWKClient", lambda url: created.append(url) or jwks)
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test/")

    key = real_signing_key("token")

    assert created == ["https://project.supabase.test/auth/v1/.well-known/jwks.json"]
    jwks.get_signing_key_from_jwt.assert_called_once_with("token")
    assert key is jwks.get_signing_key_from_jwt.return_value.key
