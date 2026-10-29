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
REGISTRATION = "33333333-3333-4333-8333-333333333333"
OTHER = "44444444-4444-4444-8444-444444444444"


@pytest.fixture
def client(monkeypatch):
    from app import create_app

    monkeypatch.setattr("app.list_registrations", lambda *args: [])
    return create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"}).test_client()


def test_background_worker_can_read_an_events_registrations(client):
    """The registration dispatcher reads an event's registrations without a signed-in user."""
    response = client.get(f"/registrations?eventId={EVENT}", headers={"X-Internal-Token": "internal-test-token"})

    assert response.status_code == 200


def test_registration_is_for_the_signed_in_attendee_not_the_body(client, monkeypatch):
    calls = []
    monkeypatch.setattr("app.create_registration", lambda *args, **kwargs: calls.append(args) or {})

    response = client.post(
        "/registrations", json={"eventId": EVENT, "attendeeId": OTHER, "capacity": 5}, headers=bearer(USER_ID, "Attendee")
    )

    assert response.status_code == 201
    assert calls == [("unused-test-url", EVENT, USER_ID, 5)]


def test_withdrawal_is_for_the_signed_in_attendee_not_the_body(client, monkeypatch):
    calls = []
    monkeypatch.setattr("app.withdraw_registration", lambda *args, **kwargs: calls.append(args) or {})

    response = client.patch(
        f"/registrations/{REGISTRATION}/withdraw", json={"attendeeId": OTHER}, headers=bearer(USER_ID, "Attendee")
    )

    assert response.status_code == 200
    assert calls == [("unused-test-url", REGISTRATION, USER_ID)]


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/registrations", {"eventId": EVENT, "capacity": 5}),
        ("patch", f"/registrations/{REGISTRATION}/withdraw", {}),
    ],
)
def test_internal_token_cannot_act_as_an_attendee(client, method, path, body):
    response = getattr(client, method)(path, json=body, headers={"X-Internal-Token": "internal-test-token"})

    assert response.status_code == 401




def test_request_without_token_is_denied(client):
    response = client.get("/registrations?eventId=22222222-2222-4222-8222-222222222222")

    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_non_bearer_authorization_is_denied(client):
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
def test_invalid_token_is_denied(client, headers):
    response = client.get("/registrations?eventId=22222222-2222-4222-8222-222222222222", headers=headers)

    assert response.status_code == 401
    assert response.json == {"message": "Your session is invalid or has expired. Sign in again."}


def test_token_without_subject_is_denied(client):
    token = jwt.encode({"aud": "authenticated", "exp": int(time.time()) + 60}, TEST_SIGNING_KEY, algorithm="ES256")
    assert client.get("/registrations?eventId=22222222-2222-4222-8222-222222222222", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_dev_identity_headers_no_longer_grant_access(client):
    headers = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Attendee"}
    assert client.get("/registrations?eventId=22222222-2222-4222-8222-222222222222", headers=headers).status_code == 401


def test_background_worker_internal_tokenpasses_authentication(client):
    response = client.get("/registrations?eventId=22222222-2222-4222-8222-222222222222", headers={"X-Internal-Token": "internal-test-token"})

    assert response.status_code not in (401, 503)


def test_user_token_takes_precedence_over_an_internal_token(client):
    headers = {"X-Internal-Token": "internal-test-token", "Authorization": "Bearer not-a-jwt"}
    assert client.get("/registrations?eventId=22222222-2222-4222-8222-222222222222", headers=headers).status_code == 401


def test_wrong_internal_token_is_denied(client):
    assert client.get("/registrations?eventId=22222222-2222-4222-8222-222222222222", headers={"X-Internal-Token": "guess"}).status_code == 401


def test_health_and_preflight_need_no_token(client):
    assert client.get("/health").status_code == 200
    assert client.options("/registrations?eventId=22222222-2222-4222-8222-222222222222").status_code == 200


def test_unconfigured_verification_fails_closed(client, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL")

    assert client.get("/registrations?eventId=22222222-2222-4222-8222-222222222222", headers=bearer(USER_ID, "Attendee")).status_code == 503


def test_unreachable_signing_keys_fail_closed(client, monkeypatch):
    def unreachable(token):
        raise jwt.PyJWKClientConnectionError("down")

    monkeypatch.setattr("app.auth.signing_key", unreachable)

    assert client.get("/registrations?eventId=22222222-2222-4222-8222-222222222222", headers=bearer(USER_ID, "Attendee")).status_code == 503


def test_signing_keys_come_from_the_supabase_jwks_endpoint(monkeypatch):
    jwks = MagicMock()
    created = []
    monkeypatch.setattr("app.auth.jwt.PyJWKClient", lambda url: created.append(url) or jwks)
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test/")

    key = real_signing_key("token")

    assert created == ["https://project.supabase.test/auth/v1/.well-known/jwks.json"]
    jwks.get_signing_key_from_jwt.assert_called_once_with("token")
    assert key is jwks.get_signing_key_from_jwt.return_value.key
