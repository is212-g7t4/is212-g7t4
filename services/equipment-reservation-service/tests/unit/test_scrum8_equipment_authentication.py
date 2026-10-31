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
- Downstream services: never reached - every request here is refused before any
  call.
- jwt.PyJWKClient: Mock - verifies the JWKS URL built from SUPABASE_URL.

- Review-access regressions also control the database/HTTP boundary with stubs and the service world with a Fake; refusal and caller-token propagation are checked.

Not proven
----------
- AC1: Local unauthenticated access refusal is checked.
- AC2: Local token-role checks and downstream identity forwarding are checked; assignment persistence belongs to Event Service.
- AC3: Invalid-token refusal is checked; real sign-in failure belongs to User/Supabase.
- Supporting validation, transport, retry, authentication configuration and defensive checks retain useful regressions, but their exact limits/failure contracts are not separate Jira ACs; Product Owner clarification remains pending.
- Real Supabase issuance, other services, browser rendering and actual broker durability are NOT COVERED ANYWHERE in this module.
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
def client():
    from app import create_app

    return create_app().test_client()


def test_internal_token_when_review_list_requested_returns_401(client):
    """Summary: A background worker's internal token cannot open Technical Support's review list.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
Double: None
"""
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get("/equipment-reservations", headers={"X-Internal-Token": "internal-test-token"})

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_authenticate_with_dev_role_header_uses_token_role_instead(client):
    """Summary: A retired developer role header cannot raise an attendee to Technical Support.
AC2: Given a system user successfully authenticates, when they access protected information or functionality, then their access is evaluated according to their role and relationship to the relevant event.
Double: Stub (Supabase signing-key lookup returns the local test public key; signature and claims verification run unchanged).
"""
    # Arrange (Given)
    headers = {**bearer(USER_ID, "Attendee"), "X-Dev-Role": "Technical Support"}

    # Act + Assert (When / Then)
    assert client.get("/equipment-reservations", headers=headers).status_code == 403




def test_authenticate_without_token_returns_401_sign_in_message(client):
    """Summary: A request with no sign-in token is turned away with a sign-in prompt.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
Double: None
"""
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get("/equipment-reservations")

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
    assert client.get("/equipment-reservations", headers={"Authorization": "Basic abc"}).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(bearer(USER_ID, "Technical Support", key=ec.generate_private_key(ec.SECP256R1())), id="forged-signature"),
        pytest.param(bearer(USER_ID, "Technical Support", exp=1893456000 - 60), id="expired"),
        pytest.param(bearer(USER_ID, "Technical Support", aud="anon"), id="wrong-audience"),
        pytest.param({"Authorization": "Bearer not-a-jwt"}, id="malformed"),
    ],
)
def test_authenticate_with_invalid_token_returns_401_session_expired(client, headers):
    """Summary: Forged, expired, wrong-audience or malformed tokens are all refused.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
Double: Stub (Supabase signing-key lookup returns the local test public key; signature and claims verification run unchanged).
"""
    # Arrange (Given): client, headers, from fixtures

    # Act (When)
    response = client.get("/equipment-reservations", headers=headers)

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Your session is invalid or has expired. Sign in again."}


def test_authenticate_with_token_missing_subject_returns_401(client):
    """Summary: A token that names no user is refused.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
Double: Stub (Supabase signing-key lookup returns the local test public key; signature and claims verification run unchanged).
"""
    # Arrange (Given)
    token = jwt.encode({"aud": "authenticated", "exp": 1893456000 + 60}, TEST_SIGNING_KEY, algorithm="ES256")

    # Act + Assert (When / Then)
    assert client.get("/equipment-reservations", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_authenticate_with_dev_identity_headers_returns_401(client):
    """Summary: Old developer identity headers cannot be used to impersonate a user.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
Double: None
"""
    # Arrange (Given)
    headers = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Technical Support"}

    # Act + Assert (When / Then)
    assert client.get("/equipment-reservations", headers=headers).status_code == 401


def test_authenticate_with_internal_token_cannot_act_as_a_user(client):
    """Summary: A background worker's internal token cannot perform an action that needs a signed-in user.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
Double: None
"""
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.post(CREATE_URL, headers={"X-Internal-Token": "internal-test-token"}, json={"items": [new_item()]})

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
    assert client.get("/equipment-reservations", headers=headers).status_code == 401


def test_authenticate_with_wrong_internal_token_returns_401(client):
    """Summary: Guessing the internal token does not get a caller in.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
Double: None
"""
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert client.get("/equipment-reservations", headers={"X-Internal-Token": "guess"}).status_code == 401


def test_authenticate_when_supabase_url_missing_returns_503(client, monkeypatch):
    """Summary: When sign-in checking is not configured, protected endpoints stay closed.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
Double: Stub (Supabase signing-key lookup returns the local test public key; signature and claims verification run unchanged).
"""
    # Arrange (Given)
    monkeypatch.delenv("SUPABASE_URL")

    # Act + Assert (When / Then)
    assert client.get("/equipment-reservations", headers=bearer(USER_ID, "Technical Support")).status_code == 503


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
    assert client.get("/equipment-reservations", headers=bearer(USER_ID, "Technical Support")).status_code == 503


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
Double: Stub (Supabase signing-key lookup returns the local test public key; signature and claims verification run unchanged).
"""
    from flask import Flask

    from app.auth import authenticate

    with Flask(__name__).test_request_context("/anything", headers=bearer("", "Attendee")):
        response, status = authenticate()

    assert status == 401


import httpx


from app import clients, create_app

from app.availability import RESERVING_EVENT_STATUSES, effective_available_stock, evaluate_request

from app.clients import DownstreamError

from tests.unit.factories import COORDINATOR, CREATE_URL, LEAD, TS, bearer, new_item, rows

from tests.unit.fakes import END, LAPTOP, MIC, OTHER, START, TABLE, TARGET, THIRD, USER, FakeResponse, equipment, line

HEADERS = {"Authorization": "Bearer user-token", "Cookie": "must-not-be-forwarded"}

MIC_STOCK = {"id": "e1", "status": "Available", "totalQuantity": 10}



def test_list_requests_client_forwards_only_token_and_filters(sent):
    """Summary: Request lookups carry the caller's token and filters, never their cookies.
AC2: Given a system user successfully authenticates, when they access protected information or functionality, then their access is evaluated according to their role and relationship to the relevant event.
Double: Stub (canned downstream HTTP responses), Mock (recorded outbound method, URL, headers or no-call contract).
"""
    # Arrange (Given): test data and external adapters from fixtures.
    calls, fake = sent
    fake.response = FakeResponse(body={"requests": [1]})

    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    with create_app().test_request_context(headers=HEADERS):
        assert clients.list_requests("Approved", ["a", "b"]) == [1]

    method, url, kwargs = calls[0]
    assert (method, url) == ("GET", "http://localhost:5011/equipment-requests")
    assert kwargs["params"] == {"status": "Approved", "eventIds": "a,b"}
    assert kwargs["headers"] == {"Authorization": "Bearer user-token"}


@pytest.mark.parametrize("headers,code", [({}, 401), ({"X-Dev-User-Id": USER, "X-Dev-Role": "Technical Support"}, 401), (bearer(USER, "Attendee"), 403)], ids=["no_token", "dev_headers", "attendee"])
def test_review_list_without_permitted_role_is_refused(world, client, headers, code):
    """Summary: The review list is not shown to anonymous callers, retired developer headers or attendees.
AC1: Given a system user has not been successfully authenticated, when they attempt to access protected information or functionality, then access is denied.
AC2: Given a system user successfully authenticates, when they access protected information or functionality, then their access is evaluated according to their role and relationship to the relevant event.
Double: Fake (downstream service world); Stub (HTTP responses); Mock (recorded requests inspected)
"""
    # Arrange (Given): world, client, headers, code, from fixtures

    # Act + Assert (When / Then)
    # Review AC1/AC3 (access): deny anonymous (SCRUM-8: DEV headers are not a sign-in) and unrelated-role readers.
    # Arrange (Given): test data and external adapters from fixtures.
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    assert client.get("/equipment-reservations", headers=headers).status_code == code
    assert world.calls == []


@pytest.mark.parametrize("offset, expected_status", [(-1, 401), (0, 401), (1, 403)], ids=["one-second-expired", "exact-expiry", "one-second-valid"])
def test_authenticate_when_token_near_expiry_refuses_at_and_after_deadline(client, offset, expected_status):
    """Summary: A session expires at its exact deadline, not one second before or after it.
    AC2: Given a system user successfully authenticates, when they access protected information or functionality, then their access is evaluated according to their role and relationship to the relevant event.
    AC3: Given a system user's authentication attempt is unsuccessful, when the authentication attempt is completed, then they remain unable to access protected information or functionality.
    Double: Stub (fixed JWT verification clock and local signing-key lookup; route authorization/validation remains real).
    """
    # Arrange (Given): the fixed verification clock is 2030-01-01T00:00:00Z.
    headers = bearer(USER_ID, "Attendee", exp=1893456000 + offset)
    # Act (When)
    response = client.get("/equipment-reservations", headers=headers)
    # Assert (Then)
    assert response.status_code == expected_status
    if expected_status == 401:
        assert response.json == {"message": "Your session is invalid or has expired. Sign in again."}
