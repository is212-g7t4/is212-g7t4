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
- psycopg2.connect: Stub - a MagicMock connection whose cursor returns no rows,
  so a request that passes sign-in gets an answer.
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


EVENT = "22222222-2222-4222-8222-222222222222"
REGISTRATION = "33333333-3333-4333-8333-333333333333"
OTHER = "44444444-4444-4444-8444-444444444444"


@pytest.fixture
def client(monkeypatch):
    from app import create_app

    monkeypatch.setattr("app.list_registrations", lambda *args: [])
    return create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"}).test_client()


def test_register_with_attendee_id_in_body_registers_token_user_instead(client, monkeypatch):
    """
    Summary: A registration is always for the signed-in attendee; an attendee id in the body is ignored.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event.
    Double: Mock (create_registration records its arguments)
    """
    # Arrange (Given)
    calls = []
    monkeypatch.setattr("app.create_registration", lambda *args, **kwargs: calls.append(args) or {})

    # Act (When)
    response = client.post(
        "/registrations", json={"eventId": EVENT, "attendeeId": OTHER, "capacity": 5}, headers=bearer(USER_ID, "Attendee")
    )

    # Assert (Then)
    assert response.status_code == 201
    assert calls == [("unused-test-url", EVENT, USER_ID, 5)]


def test_withdraw_with_attendee_id_in_body_withdraws_for_token_user_instead(client, monkeypatch):
    """
    Summary: A withdrawal is always made by the signed-in attendee; an attendee id in the body is ignored.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event.
    Double: Mock (withdraw_registration records its arguments)
    """
    # Arrange (Given)
    calls = []
    monkeypatch.setattr("app.withdraw_registration", lambda *args, **kwargs: calls.append(args) or {})

    # Act (When)
    response = client.patch(
        f"/registrations/{REGISTRATION}/withdraw", json={"attendeeId": OTHER}, headers=bearer(USER_ID, "Attendee")
    )

    # Assert (Then)
    assert response.status_code == 200
    assert calls == [("unused-test-url", REGISTRATION, USER_ID)]


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/registrations", {"eventId": EVENT, "capacity": 5}),
        ("patch", f"/registrations/{REGISTRATION}/withdraw", {}),
    ],
    ids=["register", "withdraw"],
)
def test_internal_token_when_attendee_action_requested_returns_401(client, method, path, body):
    """
    Summary: A background worker's internal token cannot register or withdraw on anyone's behalf.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    # Arrange (Given): client, method, path, body, from fixtures

    # Act (When)
    response = getattr(client, method)(path, json=body, headers={"X-Internal-Token": "internal-test-token"})

    # Assert (Then)
    assert response.status_code == 401


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
    response = client.get("/registrations?eventId=22222222-2222-4222-8222-222222222222")

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
    assert client.get("/registrations?eventId=22222222-2222-4222-8222-222222222222", headers={"Authorization": "Basic abc"}).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(bearer(USER_ID, "Attendee", key=ec.generate_private_key(ec.SECP256R1())), id="forged-signature"),
        pytest.param(bearer(USER_ID, "Attendee", exp=int(time.time()) - 60), id="expired"),
        pytest.param(bearer(USER_ID, "Attendee", aud="anon"), id="wrong-audience"),
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
    response = client.get("/registrations?eventId=22222222-2222-4222-8222-222222222222", headers=headers)

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
    assert client.get("/registrations?eventId=22222222-2222-4222-8222-222222222222", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_authenticate_with_dev_identity_headers_returns_401(client):
    """
    Summary: Old developer identity headers cannot be used to impersonate a user.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    # Arrange (Given)
    headers = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Attendee"}

    # Act + Assert (When / Then)
    assert client.get("/registrations?eventId=22222222-2222-4222-8222-222222222222", headers=headers).status_code == 401


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
    assert client.get("/registrations?eventId=22222222-2222-4222-8222-222222222222", headers=headers).status_code == 401


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
    assert client.get("/registrations?eventId=22222222-2222-4222-8222-222222222222", headers={"X-Internal-Token": "guess"}).status_code == 401


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
    assert client.get("/registrations?eventId=22222222-2222-4222-8222-222222222222", headers=bearer(USER_ID, "Attendee")).status_code == 503


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
    assert client.get("/registrations?eventId=22222222-2222-4222-8222-222222222222", headers=bearer(USER_ID, "Attendee")).status_code == 503


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


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_authenticate_with_internal_token_lets_dispatcher_read_event_registrations(client):
    """
    Summary: The notification dispatcher can read an event's registrations without a signed-in user.
    Supporting design check: service-to-service calls authenticate with
        X-Internal-Token
    Double: Stub (cursor returns no rows)
    """
    response = client.get(f"/registrations?eventId={EVENT}", headers={"X-Internal-Token": "internal-test-token"})

    assert response.status_code == 200


def test_authenticate_with_internal_token_allows_background_worker(client):
    """
    Summary: A background worker presenting the internal token gets past sign-in checking.
    Supporting design check: service-to-service calls authenticate with
        X-Internal-Token
    Double: None
    """
    response = client.get("/registrations?eventId=22222222-2222-4222-8222-222222222222", headers={"X-Internal-Token": "internal-test-token"})

    assert response.status_code not in (401, 503)
