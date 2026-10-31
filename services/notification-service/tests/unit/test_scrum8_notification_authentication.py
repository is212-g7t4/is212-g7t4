"""SCRUM-8: User Authentication and Authorization

User Story
----------
As a system user, I want to securely access the system, so that I can use the information and functionality available to me.

Acceptance Criteria
-------------------
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
AC2: Given a system user successfully authenticates, when they access protected information or functionality, then their access is evaluated according to their role and relationship to the relevant event.
AC3: Given a system user's authentication attempt is unsuccessful, when the authentication attempt is completed, then they remain unable to access protected information or functionality.

Real
----
- app.auth.authenticate(): bearer parsing, ES256 signature, expiry, audience
  and subject checks, the internal-token path and the fail-closed paths run for
  real in front of a real create_app(); identity checks prove the caller is
  taken from the token, never from the body or headers.
- Assertions are on the HTTP status and the message the caller sees.

Doubled
-------
- Stub (fixed JWT verification clock at 2030-01-01T00:00:00Z and local ES256 signing-key lookup); signature/claim verification remains real.
- Supabase JWKS: Stub (tests/conftest.py) - signing_key returns a throwaway
  ES256 public key so tokens can be minted locally.
- app storage (count_unread): Stub - returns a canned count so a request that
  passes sign-in gets an answer.
- jwt.PyJWKClient: Mock - verifies the JWKS URL built from SUPABASE_URL.

Not proven
----------
- AC1: Missing-token, developer/internal-header and configuration refusals are checked locally.
- AC2: Token subject scopes unread-count calls; real inbox recipient restrictions are tested in the PostgreSQL tier.
- AC3: Invalid-token refusal is checked; Supabase issuance/sign-in failure is outside this service.
- Real PostgreSQL evidence exists only in the maintained SCRUM-45/47/49/166 integration modules; neither their success nor parser acceptance proves all notification types or producer fan-out.
- Broker delivery, other service code and browser navigation are NOT COVERED ANYWHERE in this module.
- Pagination, read/unread controls, legacy rows, quarantine diagnostics, process wiring and future-type compatibility are useful supporting contracts without their own AC. They are preserved and flagged for a Product Owner decision, not relabelled as new acceptance criteria.
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

    monkeypatch.setenv("DATABASE_URL", "synthetic")
    monkeypatch.setattr("app.store.unread_count", lambda database_url, user: 0)
    return create_app().test_client()


def test_authenticate_with_valid_token_reads_own_unread_count(client, monkeypatch):
    """Summary: A signed-in user gets their own unread count, scoped by their token.
AC2: Given a system user successfully authenticates, when they access protected information or functionality, then their access is evaluated according to their role and relationship to the relevant event.
Double: Mock (count_unread records which user is asked about)
"""
    # Arrange (Given)
    seen = []
    monkeypatch.setattr("app.store.unread_count", lambda database_url, user: seen.append(user) or 3)

    # Act (When)
    response = client.get("/notifications/unread-count", headers=bearer(USER_ID, "Attendee"))

    # Assert (Then)
    assert response.json == {"unreadCount": 3}
    assert seen == [USER_ID]




def test_authenticate_without_token_returns_401_sign_in_message(client):
    """Summary: A request with no sign-in token is turned away with a sign-in prompt.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
Double: None
"""
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get("/notifications/unread-count")

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_authenticate_with_non_bearer_scheme_returns_401(client):
    """Summary: Credentials sent in any form other than a bearer token are refused.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
Double: None
"""
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert client.get("/notifications/unread-count", headers={"Authorization": "Basic abc"}).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(bearer(USER_ID, "Attendee", key=ec.generate_private_key(ec.SECP256R1())), id="forged-signature"),
        pytest.param(bearer(USER_ID, "Attendee", exp=1893456000 - 60), id="expired"),
        pytest.param(bearer(USER_ID, "Attendee", aud="anon"), id="wrong-audience"),
        pytest.param({"Authorization": "Bearer not-a-jwt"}, id="malformed"),
    ],
)
def test_authenticate_with_invalid_token_returns_401_session_expired(client, headers):
    """Summary: Forged, expired, wrong-audience or malformed tokens are all refused.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
Double: Stub (Supabase signing-key lookup trusts the local test public key; token verification remains real).
"""
    # Arrange (Given): client, headers, from fixtures

    # Act (When)
    response = client.get("/notifications/unread-count", headers=headers)

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Your session is invalid or has expired. Sign in again."}


def test_authenticate_with_token_missing_subject_returns_401(client):
    """Summary: A token that names no user is refused.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
Double: Stub (Supabase signing-key lookup trusts the local test public key; token verification remains real).
"""
    # Arrange (Given)
    token = jwt.encode({"aud": "authenticated", "exp": 1893456000 + 60}, TEST_SIGNING_KEY, algorithm="ES256")

    # Act + Assert (When / Then)
    assert client.get("/notifications/unread-count", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_authenticate_with_dev_identity_headers_returns_401(client):
    """Summary: Old developer identity headers cannot be used to impersonate a user.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
Double: None
"""
    # Arrange (Given)
    headers = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Attendee"}

    # Act + Assert (When / Then)
    assert client.get("/notifications/unread-count", headers=headers).status_code == 401


def test_authenticate_with_internal_token_cannot_act_as_a_user(client):
    """Summary: A background worker's internal token cannot perform an action that needs a signed-in user.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
Double: None
"""
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get("/notifications/unread-count", headers={"X-Internal-Token": "internal-test-token"})

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_authenticate_with_bad_user_token_and_internal_token_returns_401(client):
    """Summary: A bad user token is refused even when an internal token is also sent.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
Double: None
"""
    # Arrange (Given)
    headers = {"X-Internal-Token": "internal-test-token", "Authorization": "Bearer not-a-jwt"}

    # Act + Assert (When / Then)
    assert client.get("/notifications/unread-count", headers=headers).status_code == 401


def test_authenticate_with_wrong_internal_token_returns_401(client):
    """Summary: Guessing the internal token does not get a caller in.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
Double: None
"""
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert client.get("/notifications/unread-count", headers={"X-Internal-Token": "guess"}).status_code == 401


def test_authenticate_when_supabase_url_missing_returns_503(client, monkeypatch):
    """Summary: When sign-in checking is not configured, protected endpoints stay closed.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
Double: Stub (Supabase signing-key lookup trusts the local test public key; token verification remains real).
"""
    # Arrange (Given)
    monkeypatch.delenv("SUPABASE_URL")

    # Act + Assert (When / Then)
    assert client.get("/notifications/unread-count", headers=bearer(USER_ID, "Attendee")).status_code == 503


def test_authenticate_when_jwks_unreachable_returns_503(client, monkeypatch):
    """Summary: When Supabase's signing keys cannot be fetched, protected endpoints stay closed.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
Double: Stub (signing_key raises PyJWKClientConnectionError)
"""
    # Arrange (Given)
    def unreachable(token):
        raise jwt.PyJWKClientConnectionError("down")

    monkeypatch.setattr("app.auth.signing_key", unreachable)

    # Act + Assert (When / Then)
    assert client.get("/notifications/unread-count", headers=bearer(USER_ID, "Attendee")).status_code == 503


def test_signing_key_fetches_key_from_supabase_jwks_url(monkeypatch):
    """Summary: Tokens are verified against the Supabase project's published signing keys.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
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


def test_authenticate_with_internal_token_alone_returns_401():
    """Summary: An internal token on its own is not a way into this service.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
Double: None
"""
    from flask import Flask

    from app.auth import authenticate

    with Flask(__name__).test_request_context("/anything", headers={"X-Internal-Token": "internal-test-token"}):
        response, status = authenticate()

    assert status == 401
    assert response.json == {"message": "Sign in to continue."}


def test_authenticate_with_blank_subject_returns_401():
    """Summary: A token naming an empty user is refused, so every handler can rely on a signed-in user.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
Double: Stub (Supabase signing-key lookup trusts the local test public key; token verification remains real).
"""
    from flask import Flask

    from app.auth import authenticate

    with Flask(__name__).test_request_context("/anything", headers=bearer("", "Attendee")):
        response, status = authenticate()

    assert status == 401


@pytest.mark.parametrize("offset, expected_status", [(-1, 401), (0, 401), (1, 200)], ids=["one-second-expired", "exact-expiry", "one-second-valid"])
def test_authenticate_when_token_near_expiry_refuses_at_and_after_deadline(client, offset, expected_status):
    """Summary: A session expires at its exact deadline, not one second before or after it.
    AC2: Given a system user successfully authenticates, when they access protected information or functionality, then their access is evaluated according to their role and relationship to the relevant event.
    AC3: Given a system user's authentication attempt is unsuccessful, when the authentication attempt is completed, then they remain unable to access protected information or functionality.
    Double: Stub (fixed JWT verification clock and local signing-key lookup; route authorization/validation remains real).
    """
    # Arrange (Given): the fixed verification clock is 2030-01-01T00:00:00Z.
    headers = bearer(USER_ID, "Attendee", exp=1893456000 + offset)
    # Act (When)
    response = client.get("/notifications/unread-count", headers=headers)
    # Assert (Then)
    assert response.status_code == expected_status
    if expected_status == 401:
        assert response.json == {"message": "Your session is invalid or has expired. Sign in again."}
