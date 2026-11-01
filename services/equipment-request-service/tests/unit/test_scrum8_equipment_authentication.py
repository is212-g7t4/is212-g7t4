"""
SCRUM-8: User Authentication and Authorization

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
- Supabase JWKS: Stub (tests/conftest.py) - signing_key returns a throwaway
  ES256 public key so tokens can be minted locally.
- psycopg2.connect: Stub - a MagicMock connection whose cursor finds no
  request, so a request that passes sign-in gets a 404.
- jwt.PyJWKClient: Mock - verifies the JWKS URL built from SUPABASE_URL.

- Review-access regressions also control the database boundary with stubs and synthetic caller context with a Fake; refusal and caller-token propagation are checked.

Not proven
----------
- That tokens issued by the real Supabase project verify against its live JWKS
  (-> E2E journeys J5/J6, which sign in for real through the UI).
- That the custom_access_token_hook really puts user_role in the token (-> E2E
  journeys J5/J6).
"""

from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.auth import signing_key as real_signing_key
from tests.unit.factories import AUTH_TIMESTAMP, TEST_SIGNING_KEY, bearer

USER_ID = "e7334aa9-eb3a-4c45-84b5-280501b6c109"


@pytest.fixture
def isolated_jwks_cache():
    """Do not retain a test JWKS adapter in the production factory cache."""
    from app.auth import _jwks_client
    _jwks_client.cache_clear()
    try:
        yield
    finally:
        _jwks_client.cache_clear()


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
    """Summary: A signed-in Technical Support user gets past sign-in to the request lookup.
    AC2: Given a system user successfully authenticates, when they access protected information or functionality, then their access is evaluated according to their role and relationship to the relevant event.
    Double: Stub (cursor finds no request); Stub (test JWKS key lookup when a user token is verified)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get(f"/equipment-requests/{REQUEST}", headers=bearer(USER_ID, "Technical Support"))

    # Assert (Then)
    assert response.status_code == 404  # past authentication, into the lookup


def test_authenticate_with_lead_token_reads_like_coordinator(client):
    """Summary: The Event Coordinator Lead can read equipment requests with their own token.
    AC2: Given a system user successfully authenticates, when they access protected information or functionality, then their access is evaluated according to their role and relationship to the relevant event.
    Double: Stub (cursor finds no request); Stub (test JWKS key lookup when a user token is verified)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get(f"/equipment-requests/{REQUEST}", headers=bearer(USER_ID, "Event Coordinator Lead"))

    # Assert (Then)
    assert response.status_code == 404


def test_authenticate_with_dev_role_header_uses_token_role_instead(client):
    """Summary: A retired developer role header cannot raise an attendee to Technical Support.
    AC2: Given a system user successfully authenticates, when they access protected information or functionality, then their access is evaluated according to their role and relationship to the relevant event.
    Double: Stub (cursor finds no request); Stub (test JWKS key lookup when a user token is verified)
    """
    # Arrange (Given)
    headers = {**bearer(USER_ID, "Attendee"), "X-Dev-Role": "Technical Support"}

    # Act + Assert (When / Then)
    assert client.get(f"/equipment-requests/{REQUEST}", headers=headers).status_code == 403




def test_authenticate_without_token_returns_401_sign_in_message(client):
    """Summary: A request with no sign-in token is turned away with a sign-in prompt.
    AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
    Double: None reached on public/pre-validation paths; installed JWKS/database stubs remain unused
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000")

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_authenticate_with_non_bearer_scheme_returns_401(client):
    """Summary: Credentials sent in any form other than a bearer token are refused.
    AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
    Double: None reached on public/pre-validation paths; installed JWKS/database stubs remain unused
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000", headers={"Authorization": "Basic abc"}).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(bearer(USER_ID, "Technical Support", key=ec.generate_private_key(ec.SECP256R1())), id="forged-signature"),
        pytest.param(bearer(USER_ID, "Technical Support", exp=AUTH_TIMESTAMP - 60), id="expired"),
        pytest.param(bearer(USER_ID, "Technical Support", aud="anon"), id="wrong-audience"),
        pytest.param({"Authorization": "Bearer not-a-jwt"}, id="malformed"),
    ],
)
def test_authenticate_with_invalid_token_returns_401_session_expired(client, headers):
    """Summary: Forged, expired, wrong-audience or malformed tokens are all refused.
    AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
    Double: Stub (test JWKS public key; database adapter remains unused)
    """
    # Arrange (Given): client, headers, from fixtures

    # Act (When)
    response = client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000", headers=headers)

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Your session is invalid or has expired. Sign in again."}


def test_authenticate_with_token_missing_subject_returns_401(client):
    """Summary: A token that names no user is refused.
    AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
    Double: Stub (test JWKS public key; database adapter remains unused)
    """
    # Arrange (Given)
    token = jwt.encode({"aud": "authenticated", "exp": AUTH_TIMESTAMP + 60}, TEST_SIGNING_KEY, algorithm="ES256")

    # Act + Assert (When / Then)
    assert client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_authenticate_with_dev_identity_headers_returns_401(client):
    """Summary: Old developer identity headers cannot be used to impersonate a user.
    AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
    Double: None reached on public/pre-validation paths; installed JWKS/database stubs remain unused
    """
    # Arrange (Given)
    headers = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Technical Support"}

    # Act + Assert (When / Then)
    assert client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000", headers=headers).status_code == 401


def test_authenticate_with_internal_token_cannot_act_as_a_user(client):
    """Summary: A background worker's internal token cannot perform an action that needs a signed-in user.
    AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
    Double: None reached on public/pre-validation paths; installed JWKS/database stubs remain unused
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000", headers={"X-Internal-Token": "internal-test-token"})

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_authenticate_with_bad_user_token_and_internal_token_returns_401(client):
    """Summary: A bad user token is refused even when an internal token is also sent.
    AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
    Double: Stub (test JWKS public key; database adapter remains unused)
    """
    # Arrange (Given)
    headers = {"X-Internal-Token": "internal-test-token", "Authorization": "Bearer not-a-jwt"}

    # Act + Assert (When / Then)
    assert client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000", headers=headers).status_code == 401


def test_authenticate_with_wrong_internal_token_returns_401(client):
    """Summary: Guessing the internal token does not get a caller in.
    AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
    Double: None reached on public/pre-validation paths; installed JWKS/database stubs remain unused
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000", headers={"X-Internal-Token": "guess"}).status_code == 401


def test_authenticate_when_supabase_url_missing_returns_503(client, monkeypatch):
    """Summary: When sign-in checking is not configured, protected endpoints stay closed.
    AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
    Double: None reached on public/pre-validation paths; installed JWKS/database stubs remain unused
    """
    # Arrange (Given)
    monkeypatch.delenv("SUPABASE_URL")

    # Act + Assert (When / Then)
    assert client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000", headers=bearer(USER_ID, "Technical Support")).status_code == 503


def test_authenticate_when_jwks_unreachable_returns_503(client, monkeypatch):
    """Summary: When Supabase's signing keys cannot be fetched, protected endpoints stay closed.
    AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
    Double: Stub (signing_key raises PyJWKClientConnectionError); Stub (test JWKS key lookup when a user token is verified)
    """
    # Arrange (Given)
    def unreachable(token):
        raise jwt.PyJWKClientConnectionError("down")

    monkeypatch.setattr("app.auth.signing_key", unreachable)

    # Act + Assert (When / Then)
    assert client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000", headers=bearer(USER_ID, "Technical Support")).status_code == 503


def test_authenticate_when_token_key_not_in_jwks_returns_401(client, monkeypatch):
    """Summary: GET /equipment-requests/<id> with a token whose key id is not in Supabase's published keys is answered 401 "Your session is invalid or has expired. Sign in again.", not 500 or 503.
    AC3: Given a system user's authentication attempt is unsuccessful, when the authentication attempt is completed, then they remain unable to access protected information or functionality. (a token signed by an unknown key is a failed sign-in, unlike an unreachable JWKS, which is a 503)
    Double: Stub (the conftest signing-key stub is switched back to the real auth.signing_key; auth._jwks_client is replaced so its get_signing_key_from_jwt raises PyJWKClientError("Unable to find a signing key that matches"); the `client` fixture's database cursor finds no request, never reached)
    """
    # Arrange (Given)
    unknown_key = MagicMock()
    unknown_key.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientError("Unable to find a signing key that matches")
    monkeypatch.setattr("app.auth.signing_key", real_signing_key)
    monkeypatch.setattr("app.auth._jwks_client", lambda url: unknown_key)

    # Act (When)
    response = client.get("/equipment-requests/2a1bfb57-a3c0-4450-897e-cc5c73690000", headers=bearer(USER_ID, "Technical Support"))

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Your session is invalid or has expired. Sign in again."}


def test_signing_key_fetches_key_from_supabase_jwks_url(monkeypatch, isolated_jwks_cache):
    """Summary: The verifier asks the configured Supabase JWKS adapter for the token’s signing key.
    AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
    Double: Mock (jwt.PyJWKClient records the JWKS URL and returns a key)
    """
    # Arrange (Given)
    jwks = MagicMock()
    created = []
    monkeypatch.setattr("app.auth.jwt.PyJWKClient", lambda url: created.append(url) or jwks)
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test/")

    # Act (When)
    key = real_signing_key("token")

    # Assert (Then)
    assert created == ["https://project.supabase.test/auth/v1/.well-known/jwks.json"]
    jwks.get_signing_key_from_jwt.assert_called_once_with("token")
    assert key is jwks.get_signing_key_from_jwt.return_value.key


import psycopg2


from tests.unit.factories import EVENT_ID, MIC, REQUEST_ID, TABLE, USER_ID, bearer, db_row, item, approval_context

TS = bearer(USER_ID, "Technical Support")

COORDINATOR = bearer(USER_ID, "Event Coordinator")

SAFETY_OFFICER = bearer(USER_ID, "Safety Officer")



def test_get_request_when_missing_malformed_or_anonymous_is_refused(setup):
    """Summary: Opening a missing or malformed request, or one without signing in, is refused.
    AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
    AC2: Given a system user successfully authenticates, when they access protected information or functionality, then their access is evaluated according to their role and relationship to the relevant event.
    Double: Stub (canned database results/errors); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchone.return_value = None

    # Act + Assert (When / Then)
    assert client.get(f"/equipment-requests/{REQUEST_ID}", headers=TS).status_code == 404
    assert client.get("/equipment-requests/not-a-uuid", headers=TS).status_code == 400
    assert client.get(f"/equipment-requests/{REQUEST_ID}", headers={}).status_code == 401


@pytest.mark.parametrize(
    "headers,code",
    [({}, 401), ({"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Technical Support"}, 401), (bearer(USER_ID, "Attendee"), 403)],
    ids=["no_token", "dev_headers", "attendee"],
)
def test_list_requests_without_reader_role_is_refused_before_database(setup, headers, code):
    """Summary: Requests are not shown to anonymous callers, retired developer headers or attendees.
    AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
    AC2: Given a system user successfully authenticates, when they access protected information or functionality, then their access is evaluated according to their role and relationship to the relevant event.
    Double: Stub (canned database results/errors); Mock (database interactions inspected); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    """
    # Arrange (Given)
    # Review AC1/AC3 (access): require a signed-in user (SCRUM-8) with a permitted reader role.
    # Arrange (Given): test data and external adapters from fixtures.
    client, _, connect = setup

    # Act + Assert (When / Then)
    assert client.get("/equipment-requests", headers=headers).status_code == code
    connect.assert_not_called()


@pytest.mark.parametrize("headers,code", [({}, 401), (TS, 403), (bearer(USER_ID, "Attendee"), 403)], ids=["no_token", "technical_support", "attendee"])
def test_create_request_when_not_a_coordinator_is_refused_before_database(setup, headers, code):
    """Summary: Only a signed-in Event Coordinator or Lead can record equipment needs.
    AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
    AC2: Given a system user successfully authenticates, when they access protected information or functionality, then their access is evaluated according to their role and relationship to the relevant event.
    Double: Stub (canned database results/errors); Mock (database interactions inspected); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    """
    # Arrange (Given)
    client, _, connect = setup

    # Act + Assert (When / Then)
    assert client.post(f"/events/{EVENT_ID}/equipment-requests", headers=headers, json={"items": [item()]}).status_code == code
    connect.assert_not_called()
