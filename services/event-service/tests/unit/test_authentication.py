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
- psycopg2.connect: Stub where a route needs the database - a MagicMock
  connection.
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
OTHER = "44444444-4444-4444-8444-444444444444"
ROUND = "55555555-5555-4555-8555-555555555555"
INTERNAL = {"X-Internal-Token": "internal-test-token"}


@pytest.fixture
def client(monkeypatch):
    from app import create_app

    monkeypatch.setattr("app.list_unassigned", lambda *args: [])
    return create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"}).test_client()


@pytest.mark.parametrize(
    "method,path,body,headers",
    [
        ("post", "/events/drafts", {}, INTERNAL),
        ("get", "/events/drafts", None, INTERNAL),
        ("patch", f"/events/drafts/{EVENT}", {}, INTERNAL),
        ("post", f"/events/drafts/{EVENT}/submit", {}, INTERNAL),
        ("delete", f"/events/drafts/{EVENT}", None, INTERNAL),
        ("get", "/events/submitted", None, INTERNAL),
        ("get", f"/events?organiserId={OTHER}", None, INTERNAL),
        ("get", "/events", None, INTERNAL),
        ("get", f"/events/{EVENT}?organiserId={OTHER}", None, INTERNAL),
        ("get", f"/events/{EVENT}", None, INTERNAL),
        ("post", f"/events/{EVENT}/change-requests", {}, INTERNAL),
        ("get", "/change-requests", None, INTERNAL),
        ("get", f"/change-requests/{EVENT}", None, INTERNAL),
        ("patch", f"/change-requests/{EVENT}/decision", {}, INTERNAL),
        ("patch", f"/events/{EVENT}", {"assignedCoordinatorId": OTHER}, INTERNAL),
        ("patch", f"/events/{EVENT}/progress", {}, INTERNAL),
        ("patch", f"/events/{EVENT}/details", {}, INTERNAL),
        (
            "patch",
            f"/events/{EVENT}/safety-status",
            {"status": "Pending Safety Check", "safetyCheckId": ROUND, "roundNumber": 1},
            INTERNAL,
        ),
        (
            "patch",
            f"/events/{EVENT}/safety-status",
            {"status": "Confirmed", "safetyCheckId": ROUND, "roundNumber": 1},
            INTERNAL,
        ),
        ("patch", f"/events/{EVENT}/approve", {}, INTERNAL),
        ("patch", f"/events/{EVENT}/clarification-request", {}, INTERNAL),
        ("patch", f"/events/{EVENT}/clarification-response", {}, INTERNAL),
        ("patch", f"/events/{EVENT}/amendment-request", {}, INTERNAL),
        ("patch", f"/events/{EVENT}/amendment-response", {}, INTERNAL),
        ("patch", f"/events/{EVENT}/reject", {}, INTERNAL),
    ],
    ids=["post_events_drafts_internal", "get_events_drafts_none_internal", "patch_f_events_drafts_event_internal", "post_f_events_drafts_event_submit_internal", "delete_f_events_drafts_event_none_internal", "get_events_submitted_none_internal", "get_f_events_organiserid_other_none_internal", "get_events_none_internal", "get_f_events_event_organiserid_other_none_intern", "get_f_events_event_none_internal", "post_f_events_event_change_requests_internal", "get_change_requests_none_internal", "get_f_change_requests_event_none_internal", "patch_f_change_requests_event_decision_internal", "patch_f_events_event_assignedcoordinatorid_other", "patch_f_events_event_progress_internal", "patch_f_events_event_details_internal", "patch_f_events_event_safety_status_status_pendin", "patch_f_events_event_safety_status_status_confir", "patch_f_events_event_approve_internal", "patch_f_events_event_clarification_request_inter", "patch_f_events_event_clarification_response_inte", "patch_f_events_event_amendment_request_internal", "patch_f_events_event_amendment_response_internal", "patch_f_events_event_reject_internal"],
)
def test_internal_token_when_action_needs_a_user_returns_401(client, method, path, body, headers):
    """
    Summary: An internal token alone cannot be used to act on a user's behalf.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Stub (test signing key from tests/conftest.py; unused because only an internal token is sent)
    """
    # Arrange (Given): client, method, path, body, headers, from fixtures

    # Act (When)
    response = getattr(client, method)(path, json=body, headers=headers)

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_save_draft_owner_comes_from_token_not_body(client, monkeypatch):
    """
    Summary: A draft belongs to the signed-in organiser, whatever organiser id the body names.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Stub (test signing key), Mock (app.save_draft records the owner it was given; asserted to be the token's user)
    """
    # Arrange (Given)
    calls = []
    monkeypatch.setattr("app.save_draft", lambda *args: calls.append(args) or {})

    # Act (When)
    response = client.post(
        "/events/drafts", json={"organiserId": OTHER, "eventName": "Draft"}, headers=bearer(USER_ID, "Event Organiser")
    )

    # Assert (Then)
    assert response.status_code == 201
    assert calls[0][1] == USER_ID


def test_view_all_uses_token_role_not_query(client):
    """
    Summary: Seeing every event depends on the token's role, not on a query parameter.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Stub (test signing key; the token carries the Event Coordinator role)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get("/events?viewerRole=Event+Coordinator+Lead", headers=bearer(USER_ID, "Event Coordinator"))

    # Assert (Then)
    assert response.status_code == 403
    assert response.json == {"message": "This role cannot view all internal events."}


def test_submit_with_internal_token_records_no_organiser(client, monkeypatch):
    """
    Summary: A background submission with the internal token is recorded with no organiser.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Mock (app.submit_event records the details it was given; asserted to carry no organiserId)
    """
    # Arrange (Given)
    submitted = []
    monkeypatch.setattr("app.submit_event", lambda database_url, details: submitted.append(details) or {})

    body = {
        "eventName": "Community Workshop",
        "description": "A workshop",
        "purpose": "Learning",
        "preferredStartDate": "2026-10-01T09:00",
        "preferredEndDate": "2026-10-01T17:00",
        "expectedAttendance": "25",
    }

    # Act (When)
    response = client.post("/events", json=body, headers=INTERNAL)

    # Assert (Then)
    assert response.status_code == 201
    assert "organiserId" not in submitted[0]


def test_authenticate_without_token_returns_401_sign_in_message(client):
    """
    Summary: A request with no sign-in token is turned away with a sign-in prompt.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Stub (test signing key; not reached because no token is sent)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get("/events/unassigned")

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_authenticate_with_non_bearer_scheme_returns_401(client):
    """
    Summary: Credentials sent in any form other than a bearer token are refused.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Stub (test signing key; not reached because the scheme is Basic)
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert client.get("/events/unassigned", headers={"Authorization": "Basic abc"}).status_code == 401


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
    Double: Stub (test signing key; the forged, expired, wrong-audience and malformed tokens are each checked against it)
    """
    # Arrange (Given): client, headers, from fixtures

    # Act (When)
    response = client.get("/events/unassigned", headers=headers)

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Your session is invalid or has expired. Sign in again."}


def test_authenticate_with_token_missing_subject_returns_401(client):
    """
    Summary: A token that names no user is refused.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Stub (test signing key; the token is validly signed but has no subject)
    """
    # Arrange (Given)
    token = jwt.encode({"aud": "authenticated", "exp": int(time.time()) + 60}, TEST_SIGNING_KEY, algorithm="ES256")

    # Act + Assert (When / Then)
    assert client.get("/events/unassigned", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_authenticate_with_dev_identity_headers_returns_401(client):
    """
    Summary: Old developer identity headers cannot be used to impersonate a user.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Stub (test signing key; not reached because no Authorization header is sent)
    """
    # Arrange (Given)
    headers = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Event Coordinator"}

    # Act + Assert (When / Then)
    assert client.get("/events/unassigned", headers=headers).status_code == 401


def test_authenticate_with_bad_user_token_and_internal_token_returns_401(client):
    """
    Summary: A bad user token is refused even when an internal token is also sent.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Stub (test signing key; the malformed bearer token is checked against it despite the internal token)
    """
    # Arrange (Given)
    headers = {"X-Internal-Token": "internal-test-token", "Authorization": "Bearer not-a-jwt"}

    # Act + Assert (When / Then)
    assert client.get("/events/unassigned", headers=headers).status_code == 401


def test_authenticate_with_wrong_internal_token_returns_401(client):
    """
    Summary: Guessing the internal token does not get a caller in.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Stub (test signing key; not reached because no Authorization header is sent)
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert client.get("/events/unassigned", headers={"X-Internal-Token": "guess"}).status_code == 401


def test_authenticate_when_supabase_url_missing_returns_503(client, monkeypatch):
    """
    Summary: When sign-in checking is not configured, protected endpoints stay closed.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Stub (test signing key; not reached because SUPABASE_URL is removed first)
    """
    # Arrange (Given)
    monkeypatch.delenv("SUPABASE_URL")

    # Act + Assert (When / Then)
    assert client.get("/events/unassigned", headers=bearer(USER_ID, "Event Coordinator")).status_code == 503


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
    assert client.get("/events/unassigned", headers=bearer(USER_ID, "Event Coordinator")).status_code == 503


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


def test_authenticate_with_internal_token_allows_background_worker(client):
    """
    Summary: A background worker presenting the internal token gets past sign-in checking.
    Supporting design check: service-to-service calls authenticate with
        X-Internal-Token
    Double: Stub (app.list_unassigned returns [] via the client fixture; the signing key is unused without a user token)
    """
    response = client.get("/events/unassigned", headers={"X-Internal-Token": "internal-test-token"})

    assert response.status_code not in (401, 503)


def test_health_and_preflight_without_token_are_answered(client):
    """
    Summary: The health check and browser preflights are answered without signing in.
    Supporting design check: /health and OPTIONS answer without a token
    Double: None (these paths skip authentication, so nothing test-specific is stubbed)
    """
    assert client.get("/health").status_code == 200
    assert client.options("/events/unassigned").status_code == 200
