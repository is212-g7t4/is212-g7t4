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
- Downstream clients: Stub where reached (monkeypatch); most requests here are
  refused at sign-in.
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


@pytest.fixture
def client():
    from app import create_app

    return create_app().test_client()


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("patch", f"/events/{EVENT}/details", {"changes": {"eventName": "x"}}),
        ("get", "/change-requests", None),
        ("patch", f"/change-requests/{EVENT}", {"decision": "Approved"}),
    ],
    ids=["edit_details", "list_change_requests", "decide_change_request"],
)
def test_ac1_internal_token_when_coordinator_action_requested_returns_401(client, method, path, body):
    """
    Summary: PATCH /events/<id>/details, GET /change-requests and PATCH
        /change-requests/<id> sent with only a valid X-Internal-Token (no
        user token) are each answered 401 {"message": "Sign in to continue."}.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Stub (Supabase signing key via conftest; INTERNAL_SERVICE_TOKEN set
        to internal-test-token); no downstream client is reached
    """
    # Arrange (Given): client, method, path, body, from fixtures

    # Act (When)
    response = getattr(client, method)(path, json=body, headers={"X-Internal-Token": "internal-test-token"})

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_ac2_update_details_with_editor_in_body_uses_signed_in_user(client, monkeypatch):
    """
    Summary: PATCH /events/<id>/details with a coordinatorId of "someone-else"
        in the body and a token for USER_ID makes the service look up USER_ID
        (the token's user) in User Service, never the id from the body.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event.
    Double: Stub (get_user raises UserNotFoundError; Supabase signing key via
        conftest), Mock (get_user records the user id it was called with)
    """
    # Arrange (Given)
    from app import clients

    looked_up = []

    def unknown(user_id):
        looked_up.append(user_id)
        raise clients.UserNotFoundError

    monkeypatch.setattr(clients, "get_user", unknown)

    # Act (When)
    client.patch(
        f"/events/{EVENT}/details",
        json={"coordinatorId": "someone-else", "changes": {"eventName": "x"}},
        headers=bearer(USER_ID, "Event Coordinator"),
    )

    # Assert (Then)
    assert looked_up == [USER_ID]


def test_ac1_authenticate_without_token_returns_401_sign_in_message(client):
    """
    Summary: GET /change-requests with no Authorization header is answered
        401 {"message": "Sign in to continue."}.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Stub (Supabase signing key via conftest, unused because there is
        no token); no downstream client is reached
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get("/change-requests")

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_ac3_authenticate_with_non_bearer_scheme_returns_401(client):
    """
    Summary: GET /change-requests with "Authorization: Basic abc" is answered
        401.
    AC3: Given a system user's authentication attempt is unsuccessful, when
        the authentication attempt is completed, then they remain unable to
        access protected information or functionality.
    Double: Stub (Supabase signing key via conftest, unused because the scheme
        is rejected first); no downstream client is reached
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert client.get("/change-requests", headers={"Authorization": "Basic abc"}).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(bearer(USER_ID, "Event Coordinator", key=ec.generate_private_key(ec.SECP256R1())), id="forged-signature"),
        pytest.param(bearer(USER_ID, "Event Coordinator", exp=int(time.time()) - 60), id="expired"),
        pytest.param(bearer(USER_ID, "Event Coordinator", aud="anon"), id="wrong-audience"),
        pytest.param({"Authorization": "Bearer not-a-jwt"}, id="malformed"),
    ],
)
def test_ac3_authenticate_with_invalid_token_returns_401_session_expired(client, headers):
    """
    Summary: GET /change-requests with a bearer token signed by a different
        key, already expired, issued for audience "anon", or not a token at
        all is answered 401 "Your session is invalid or has expired. Sign in
        again."
    AC3: Given a system user's authentication attempt is unsuccessful, when
        the authentication attempt is completed, then they remain unable to
        access protected information or functionality.
    Double: Stub (Supabase signing key via conftest returns the test public
        key, so the forged-signature token fails verification); no downstream
        client is reached
    """
    # Arrange (Given): client, headers, from fixtures

    # Act (When)
    response = client.get("/change-requests", headers=headers)

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Your session is invalid or has expired. Sign in again."}


def test_ac3_authenticate_with_token_missing_subject_returns_401(client):
    """
    Summary: GET /change-requests with a correctly signed, unexpired token
        that has no "sub" claim is answered 401.
    AC3: Given a system user's authentication attempt is unsuccessful, when
        the authentication attempt is completed, then they remain unable to
        access protected information or functionality.
    Double: Stub (Supabase signing key via conftest accepts the test key);
        no downstream client is reached
    """
    # Arrange (Given)
    token = jwt.encode({"aud": "authenticated", "exp": int(time.time()) + 60}, TEST_SIGNING_KEY, algorithm="ES256")

    # Act + Assert (When / Then)
    assert client.get("/change-requests", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_ac1_authenticate_with_dev_identity_headers_returns_401(client):
    """
    Summary: GET /change-requests with only X-Dev-User-Id and X-Dev-Role
        headers (no token) is answered 401.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Stub (Supabase signing key via conftest, unused because there is
        no token); no downstream client is reached
    """
    # Arrange (Given)
    headers = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Event Coordinator"}

    # Act + Assert (When / Then)
    assert client.get("/change-requests", headers=headers).status_code == 401


def test_ac1_authenticate_with_internal_token_cannot_act_as_a_user(client):
    """
    Summary: GET /change-requests with only a valid X-Internal-Token is
        answered 401 {"message": "Sign in to continue."}.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Stub (INTERNAL_SERVICE_TOKEN set to internal-test-token; Supabase
        signing key via conftest); no downstream client is reached
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get("/change-requests", headers={"X-Internal-Token": "internal-test-token"})

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_ac3_authenticate_with_bad_user_token_and_internal_token_returns_401(client):
    """
    Summary: GET /change-requests with a valid X-Internal-Token and a
        malformed Authorization header is answered 401, so the internal token
        does not rescue a failed user sign-in.
    AC3: Given a system user's authentication attempt is unsuccessful, when
        the authentication attempt is completed, then they remain unable to
        access protected information or functionality.
    Double: Stub (INTERNAL_SERVICE_TOKEN set to internal-test-token; Supabase
        signing key via conftest); no downstream client is reached
    """
    # Arrange (Given)
    headers = {"X-Internal-Token": "internal-test-token", "Authorization": "Bearer not-a-jwt"}

    # Act + Assert (When / Then)
    assert client.get("/change-requests", headers=headers).status_code == 401


def test_ac3_authenticate_with_wrong_internal_token_returns_401(client):
    """
    Summary: GET /change-requests with X-Internal-Token "guess" (not the
        configured token) is answered 401.
    AC3: Given a system user's authentication attempt is unsuccessful, when
        the authentication attempt is completed, then they remain unable to
        access protected information or functionality.
    Double: Stub (INTERNAL_SERVICE_TOKEN set to internal-test-token; Supabase
        signing key via conftest); no downstream client is reached
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert client.get("/change-requests", headers={"X-Internal-Token": "guess"}).status_code == 401


def test_ac3_authenticate_when_supabase_url_missing_returns_503(client, monkeypatch):
    """
    Summary: With SUPABASE_URL removed from the environment, GET
        /change-requests with an otherwise valid coordinator token is
        answered 503, not allowed through.
    AC3: Given a system user's authentication attempt is unsuccessful, when
        the authentication attempt is completed, then they remain unable to
        access protected information or functionality.
    Double: Stub (Supabase signing key via conftest; SUPABASE_URL deleted with
        monkeypatch); no downstream client is reached
    """
    # Arrange (Given)
    monkeypatch.delenv("SUPABASE_URL")

    # Act + Assert (When / Then)
    assert client.get("/change-requests", headers=bearer(USER_ID, "Event Coordinator")).status_code == 503


def test_ac3_authenticate_when_jwks_unreachable_returns_503(client, monkeypatch):
    """
    Summary: When fetching Supabase's signing key raises
        PyJWKClientConnectionError, GET /change-requests with an otherwise
        valid coordinator token is answered 503, not allowed through.
    AC3: Given a system user's authentication attempt is unsuccessful, when
        the authentication attempt is completed, then they remain unable to
        access protected information or functionality.
    Double: Stub (app.auth.signing_key raises PyJWKClientConnectionError,
        replacing the conftest key stub); no downstream client is reached
    """
    # Arrange (Given)
    def unreachable(token):
        raise jwt.PyJWKClientConnectionError("down")

    monkeypatch.setattr("app.auth.signing_key", unreachable)

    # Act + Assert (When / Then)
    assert client.get("/change-requests", headers=bearer(USER_ID, "Event Coordinator")).status_code == 503


def test_signing_key_fetches_key_from_supabase_jwks_url(monkeypatch):
    """
    Summary: signing_key("token") builds a PyJWKClient for the JWKS URL
        derived from SUPABASE_URL (https://project.supabase.test/auth/v1/.well-known/jwks.json)
        and returns the key for that token.
    Supporting design check: tokens are verified against the Supabase
        project's published signing keys
    Double: Mock (jwt.PyJWKClient replaced by a recorder that captures the URL
        and returns a MagicMock whose get_signing_key_from_jwt is asserted
        called once with "token"); the conftest key stub is bypassed by calling
        the real signing_key
    """
    jwks = MagicMock()
    created = []
    monkeypatch.setattr("app.auth.jwt.PyJWKClient", lambda url: created.append(url) or jwks)
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test/")

    key = real_signing_key("token")

    assert created == ["https://project.supabase.test/auth/v1/.well-known/jwks.json"]
    jwks.get_signing_key_from_jwt.assert_called_once_with("token")
    assert key is jwks.get_signing_key_from_jwt.return_value.key


def test_ac1_authenticate_with_internal_token_alone_returns_401():
    """
    Summary: Calling app.auth.authenticate() directly inside a request that has
        only a valid X-Internal-Token returns status 401 and {"message": "Sign
        in to continue."}.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None (a bare Flask request context calls authenticate(); the
        autouse Supabase key stub is in place but unused, and the internal
        token is set by the module's autouse fixture)
    """
    from flask import Flask

    from app.auth import authenticate

    with Flask(__name__).test_request_context("/anything", headers={"X-Internal-Token": "internal-test-token"}):
        response, status = authenticate()

    assert status == 401
    assert response.json == {"message": "Sign in to continue."}


def test_ac3_authenticate_with_blank_subject_returns_401():
    """
    Summary: Calling app.auth.authenticate() directly with a valid token whose
        "sub" claim is an empty string returns status 401.
    AC3: Given a system user's authentication attempt is unsuccessful, when
        the authentication attempt is completed, then they remain unable to
        access protected information or functionality.
    Double: Stub (Supabase signing key via conftest accepts the test key); a
        bare Flask request context, no downstream client
    """
    from flask import Flask

    from app.auth import authenticate

    with Flask(__name__).test_request_context("/anything", headers=bearer("", "Attendee")):
        response, status = authenticate()

    assert status == 401
