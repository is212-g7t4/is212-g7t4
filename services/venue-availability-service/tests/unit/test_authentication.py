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
- psycopg2.connect: Stub - a MagicMock connection whose cursor returns no rows.
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
VENUE = "33333333-3333-4333-8333-333333333333"
BOOKING = dict(
    eventId=EVENT,
    venueId=VENUE,
    requestedBy="99999999-9999-4999-8999-999999999999",
    requestedStartTime="2099-10-01T09:00",
    requestedEndTime="2099-10-01T12:00",
    requiredCapacity=10,
    venueRequirements="",
)


@pytest.fixture
def client(monkeypatch):
    from app import create_app

    monkeypatch.setattr("app.list_event_bookings", lambda *args: [])
    return create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"}).test_client()


def test_create_booking_with_requester_in_body_records_signed_in_user(client, monkeypatch):
    """
    Summary: The requester recorded is the signed-in coordinator, never one named in the body.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event.
    Double: Mock (create_booking records its arguments)
    """
    # Arrange (Given)
    calls = []
    monkeypatch.setattr("app.create_booking", lambda *args, **kwargs: calls.append(args) or {"id": "b"})

    # Act (When)
    response = client.post("/venue-bookings", json=BOOKING, headers=bearer(USER_ID, "Event Coordinator"))

    # Assert (Then)
    assert response.status_code == 201
    assert USER_ID in calls[0]
    assert BOOKING["requestedBy"] not in calls[0]


def test_internal_token_when_booking_requested_returns_401(client):
    """
    Summary: A background worker's internal token cannot request a booking.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.post("/venue-bookings", json=BOOKING, headers={"X-Internal-Token": "internal-test-token"})

    # Assert (Then)
    assert response.status_code == 401


def test_internal_token_when_closure_requested_returns_401(client):
    """
    Summary: A background worker's internal token cannot record a closure.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get("/venue-closures", headers={"X-Internal-Token": "internal-test-token"})

    # Assert (Then)
    assert response.status_code == 401


def test_decide_booking_with_reviewer_in_body_records_signed_in_user(client, monkeypatch):
    """
    Summary: The reviewer recorded is the signed-in staff member, never one named in the body.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event.
    Double: Mock (review_booking records its arguments)
    """
    # Arrange (Given)
    decided = []
    monkeypatch.setattr("app.decide_booking", lambda database_url, booking_id, reviewed_by, *rest: decided.append(reviewed_by) or {})

    # Act (When)
    client.patch(
        f"/venue-bookings/{EVENT}/approve",
        json={"reviewedBy": "99999999-9999-4999-8999-999999999999"},
        headers=bearer(USER_ID, "Venue Staff"),
    )

    # Assert (Then)
    assert decided == [USER_ID]


def test_internal_token_when_booking_decision_requested_returns_401(client):
    """
    Summary: A background worker's internal token cannot approve or reject a booking.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.patch(f"/venue-bookings/{EVENT}/approve", json={}, headers={"X-Internal-Token": "internal-test-token"})

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
    response = client.get("/events/22222222-2222-4222-8222-222222222222/venue-bookings")

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
    assert client.get("/events/22222222-2222-4222-8222-222222222222/venue-bookings", headers={"Authorization": "Basic abc"}).status_code == 401


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
    Summary: Forged, expired, wrong-audience or malformed tokens are all refused.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    # Arrange (Given): client, headers, from fixtures

    # Act (When)
    response = client.get("/events/22222222-2222-4222-8222-222222222222/venue-bookings", headers=headers)

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
    assert client.get("/events/22222222-2222-4222-8222-222222222222/venue-bookings", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_authenticate_with_dev_identity_headers_returns_401(client):
    """
    Summary: Old developer identity headers cannot be used to impersonate a user.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None
    """
    # Arrange (Given)
    headers = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Event Coordinator"}

    # Act + Assert (When / Then)
    assert client.get("/events/22222222-2222-4222-8222-222222222222/venue-bookings", headers=headers).status_code == 401


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
    assert client.get("/events/22222222-2222-4222-8222-222222222222/venue-bookings", headers=headers).status_code == 401


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
    assert client.get("/events/22222222-2222-4222-8222-222222222222/venue-bookings", headers={"X-Internal-Token": "guess"}).status_code == 401


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
    assert client.get("/events/22222222-2222-4222-8222-222222222222/venue-bookings", headers=bearer(USER_ID, "Event Coordinator")).status_code == 503


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
    assert client.get("/events/22222222-2222-4222-8222-222222222222/venue-bookings", headers=bearer(USER_ID, "Event Coordinator")).status_code == 503


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


def test_authenticate_with_internal_token_lets_worker_read_event_bookings(client):
    """
    Summary: A background worker can read an event's bookings without a signed-in user.
    Supporting design check: service-to-service calls authenticate with
        X-Internal-Token
    Double: Stub (cursor returns no rows)
    """
    response = client.get(f"/events/{EVENT}/venue-bookings", headers={"X-Internal-Token": "internal-test-token"})

    assert response.status_code == 200


def test_authenticate_with_internal_token_allows_background_worker(client):
    """
    Summary: A background worker presenting the internal token gets past sign-in checking.
    Supporting design check: service-to-service calls authenticate with
        X-Internal-Token
    Double: None
    """
    response = client.get("/events/22222222-2222-4222-8222-222222222222/venue-bookings", headers={"X-Internal-Token": "internal-test-token"})

    assert response.status_code not in (401, 503)


def test_health_and_preflight_without_token_are_answered(client):
    """
    Summary: Health checks and browser preflights need no sign-in.
    Supporting design check: /health and CORS preflight answer without a token
    Double: None
    """
    assert client.get("/health").status_code == 200
    assert client.options("/events/22222222-2222-4222-8222-222222222222/venue-bookings").status_code == 200
