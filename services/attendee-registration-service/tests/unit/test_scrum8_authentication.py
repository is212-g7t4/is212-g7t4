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
- Attendee Registration Service's sign-in check in front of every protected
  request: the token's signature, expiry, audience and user, refusing the
  internal service token on its own, staying closed when checking is
  impossible, and passing the attendee's own sign-in on to other services.
- We check whether the caller gets in, the message they see, and who other
  services are told the caller is.

Doubled
-------
- Supabase's signing keys: a test key stands in, so tokens can be made locally
  (tests/unit/conftest.py) [Stub].
- Event and Registration Services: return what each test needs, or are
  unreachable [Stub]; we check the sign-in and attendee they receive [Mock].

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
from flask import Flask

from app import clients, create_app
from app.auth import authenticate
from app.auth import signing_key as real_signing_key
from tests.unit.factories import TEST_SIGNING_KEY, bearer

USER_ID = "e7334aa9-eb3a-4c45-84b5-280501b6c109"


@pytest.fixture(autouse=True)
def internal_service_token(monkeypatch):
    """The token background workers present as X-Internal-Token."""
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "internal-test-token")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.routes.get_confirmed_events", lambda: [])
    return create_app().test_client()


def test_registration_calls_forward_the_attendees_token_downstream(client, monkeypatch):
    """
    Summary: The attendee's own sign-in is passed on to Registration Service, so it judges the same signed-in attendee.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event.
    Double: Registration Service is unreachable; we check the sign-in sent to
        it before it failed [Mock].
    """
    calls = []

    def downstream_unavailable(url, **kwargs):
        calls.append(kwargs["headers"])
        raise RuntimeError("stop after recording the forwarded headers")

    monkeypatch.setattr(clients.httpx, "get", downstream_unavailable)
    headers = bearer(USER_ID, "Attendee")

    client.get("/registrations", headers=headers)

    assert calls == [headers]


def test_register_with_attendee_id_in_body_registers_token_user_instead(client, monkeypatch):
    """
    Summary: A registration is always for the signed-in attendee; an attendee id in the body is ignored.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event.
    Double: The event is confirmed and open [Stub]; we check who Registration
        Service is asked to register [Mock].
    """
    saved = []
    monkeypatch.setattr(
        "app.routes.get_confirmed_event",
        lambda event_id: {"id": event_id, "eventName": "E", "expectedAttendance": 5, "preferredStartDate": "2099-01-01T09:00:00", "preferredEndDate": "2099-01-01T17:00:00"},
    )
    monkeypatch.setattr("app.routes.save_registration", lambda data: saved.append(data) or {})

    client.post(
        "/registrations",
        json={"eventId": "22222222-2222-4222-8222-222222222222", "attendeeId": "someone-else"},
        headers=bearer(USER_ID, "Attendee"),
    )

    assert "attendeeId" not in saved[0]




def test_authenticate_without_token_returns_401_sign_in_message(client):
    """
    Summary: A user who has not signed in is turned away and asked to sign in.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    response = client.get("/registrations")

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
    assert client.get("/registrations", headers={"Authorization": "Basic abc"}).status_code == 401


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
    Summary: Forged, expired, wrong-audience or malformed sign-in tokens are all refused.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    response = client.get("/registrations", headers=headers)

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

    assert client.get("/registrations", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_authenticate_with_dev_identity_headers_returns_401(client):
    """
    Summary: The old developer identity headers cannot be used to pose as another user.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    headers = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Attendee"}

    assert client.get("/registrations", headers=headers).status_code == 401


def test_authenticate_with_internal_token_alone_returns_401():
    """
    Summary: The internal service token on its own is not a way into this service.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """

    with Flask(__name__).test_request_context("/anything", headers={"X-Internal-Token": "internal-test-token"}):
        response, status = authenticate()

    assert status == 401
    assert response.json == {"message": "Sign in to continue."}


def test_authenticate_with_blank_subject_returns_401():
    """
    Summary: A sign-in token naming an empty user is refused.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """

    with Flask(__name__).test_request_context("/anything", headers=bearer("", "Attendee")):
        response, status = authenticate()

    assert status == 401


def test_authenticate_with_bad_user_token_and_internal_token_returns_401(client):
    """
    Summary: A bad sign-in token is refused even when the internal service token is also sent.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    headers = {"X-Internal-Token": "internal-test-token", "Authorization": "Bearer not-a-jwt"}

    assert client.get("/registrations", headers=headers).status_code == 401


def test_authenticate_with_wrong_internal_token_returns_401(client):
    """
    Summary: Guessing the internal service token does not get a caller in.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    assert client.get("/registrations", headers={"X-Internal-Token": "guess"}).status_code == 401


def test_authenticate_when_supabase_url_missing_returns_503(client, monkeypatch):
    """
    Summary: When sign-in checking is not configured, protected pages stay closed rather than open.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    monkeypatch.delenv("SUPABASE_URL")

    assert client.get("/registrations", headers=bearer(USER_ID, "Attendee")).status_code == 503


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

    assert client.get("/registrations", headers=bearer(USER_ID, "Attendee")).status_code == 503


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
