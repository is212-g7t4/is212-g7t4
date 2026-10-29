"""SCRUM-8 AC1/AC3: without a valid Supabase access token, protected endpoints are denied.

Tokens are signed with a throwaway ES256 key; tests/unit/conftest.py makes the
verifier trust it instead of fetching Supabase's JWKS.
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


def test_background_worker_can_read_an_events_bookings(client):
    """Notification dispatchers read event bookings without a signed-in user."""
    response = client.get(f"/events/{EVENT}/venue-bookings", headers={"X-Internal-Token": "internal-test-token"})

    assert response.status_code == 200


def test_booking_requester_is_the_signed_in_coordinator_not_the_body(client, monkeypatch):
    calls = []
    monkeypatch.setattr("app.create_booking", lambda *args, **kwargs: calls.append(args) or {"id": "b"})

    response = client.post("/venue-bookings", json=BOOKING, headers=bearer(USER_ID, "Event Coordinator"))

    assert response.status_code == 201
    assert USER_ID in calls[0]
    assert BOOKING["requestedBy"] not in calls[0]


def test_internal_token_cannot_request_a_booking(client):
    response = client.post("/venue-bookings", json=BOOKING, headers={"X-Internal-Token": "internal-test-token"})

    assert response.status_code == 401


def test_internal_token_cannot_manage_closures(client):
    response = client.get("/venue-closures", headers={"X-Internal-Token": "internal-test-token"})

    assert response.status_code == 401


def test_reviewer_is_the_signed_in_staff_member_not_the_body(client, monkeypatch):
    decided = []
    monkeypatch.setattr("app.decide_booking", lambda database_url, booking_id, reviewed_by, *rest: decided.append(reviewed_by) or {})

    client.patch(
        f"/venue-bookings/{EVENT}/approve",
        json={"reviewedBy": "99999999-9999-4999-8999-999999999999"},
        headers=bearer(USER_ID, "Venue Staff"),
    )

    assert decided == [USER_ID]


def test_internal_token_cannot_decide_a_booking(client):
    response = client.patch(f"/venue-bookings/{EVENT}/approve", json={}, headers={"X-Internal-Token": "internal-test-token"})

    assert response.status_code == 401




def test_request_without_token_is_denied(client):
    response = client.get("/events/22222222-2222-4222-8222-222222222222/venue-bookings")

    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_non_bearer_authorization_is_denied(client):
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
def test_invalid_token_is_denied(client, headers):
    response = client.get("/events/22222222-2222-4222-8222-222222222222/venue-bookings", headers=headers)

    assert response.status_code == 401
    assert response.json == {"message": "Your session is invalid or has expired. Sign in again."}


def test_token_without_subject_is_denied(client):
    token = jwt.encode({"aud": "authenticated", "exp": int(time.time()) + 60}, TEST_SIGNING_KEY, algorithm="ES256")
    assert client.get("/events/22222222-2222-4222-8222-222222222222/venue-bookings", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_dev_identity_headers_no_longer_grant_access(client):
    headers = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Event Coordinator"}
    assert client.get("/events/22222222-2222-4222-8222-222222222222/venue-bookings", headers=headers).status_code == 401


def test_background_worker_internal_tokenpasses_authentication(client):
    response = client.get("/events/22222222-2222-4222-8222-222222222222/venue-bookings", headers={"X-Internal-Token": "internal-test-token"})

    assert response.status_code not in (401, 503)


def test_user_token_takes_precedence_over_an_internal_token(client):
    headers = {"X-Internal-Token": "internal-test-token", "Authorization": "Bearer not-a-jwt"}
    assert client.get("/events/22222222-2222-4222-8222-222222222222/venue-bookings", headers=headers).status_code == 401


def test_wrong_internal_token_is_denied(client):
    assert client.get("/events/22222222-2222-4222-8222-222222222222/venue-bookings", headers={"X-Internal-Token": "guess"}).status_code == 401


def test_health_and_preflight_need_no_token(client):
    assert client.get("/health").status_code == 200
    assert client.options("/events/22222222-2222-4222-8222-222222222222/venue-bookings").status_code == 200


def test_unconfigured_verification_fails_closed(client, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL")

    assert client.get("/events/22222222-2222-4222-8222-222222222222/venue-bookings", headers=bearer(USER_ID, "Event Coordinator")).status_code == 503


def test_unreachable_signing_keys_fail_closed(client, monkeypatch):
    def unreachable(token):
        raise jwt.PyJWKClientConnectionError("down")

    monkeypatch.setattr("app.auth.signing_key", unreachable)

    assert client.get("/events/22222222-2222-4222-8222-222222222222/venue-bookings", headers=bearer(USER_ID, "Event Coordinator")).status_code == 503


def test_signing_keys_come_from_the_supabase_jwks_endpoint(monkeypatch):
    jwks = MagicMock()
    created = []
    monkeypatch.setattr("app.auth.jwt.PyJWKClient", lambda url: created.append(url) or jwks)
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test/")

    key = real_signing_key("token")

    assert created == ["https://project.supabase.test/auth/v1/.well-known/jwks.json"]
    jwks.get_signing_key_from_jwt.assert_called_once_with("token")
    assert key is jwks.get_signing_key_from_jwt.return_value.key
