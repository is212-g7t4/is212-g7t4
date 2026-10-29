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


VENUE = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def client(monkeypatch):
    from app import create_app

    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = None
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    return create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"}).test_client()


def test_signed_in_user_can_browse_venues(client):
    assert client.get("/venues", headers=bearer(USER_ID, "Event Organiser")).status_code == 200


def test_background_worker_can_look_up_a_venue(client):
    """Notification dispatchers resolve venue names without a signed-in user."""
    response = client.get(f"/venues/{VENUE}", headers={"X-Internal-Token": "internal-test-token"})

    assert response.status_code == 404  # past authentication, into the lookup


def test_safety_editor_role_comes_from_the_token_not_dev_headers(client):
    headers = {**bearer(USER_ID, "Attendee"), "X-Dev-Role": "Venue Staff"}

    response = client.put(f"/venues/{VENUE}/safety-info", json={}, headers=headers)

    assert response.status_code == 403


def test_internal_token_cannot_edit_safety_information(client):
    response = client.put(f"/venues/{VENUE}/safety-info", json={}, headers={"X-Internal-Token": "internal-test-token"})

    assert response.status_code == 401




def test_request_without_token_is_denied(client):
    response = client.get("/venues")

    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_non_bearer_authorization_is_denied(client):
    assert client.get("/venues", headers={"Authorization": "Basic abc"}).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(bearer(USER_ID, "Venue Staff", key=ec.generate_private_key(ec.SECP256R1())), id="forged-signature"),
        pytest.param(bearer(USER_ID, "Venue Staff", exp=int(time.time()) - 60), id="expired"),
        pytest.param(bearer(USER_ID, "Venue Staff", aud="anon"), id="wrong-audience"),
        pytest.param({"Authorization": "Bearer not-a-jwt"}, id="malformed"),
    ],
)
def test_invalid_token_is_denied(client, headers):
    response = client.get("/venues", headers=headers)

    assert response.status_code == 401
    assert response.json == {"message": "Your session is invalid or has expired. Sign in again."}


def test_token_without_subject_is_denied(client):
    token = jwt.encode({"aud": "authenticated", "exp": int(time.time()) + 60}, TEST_SIGNING_KEY, algorithm="ES256")
    assert client.get("/venues", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_dev_identity_headers_no_longer_grant_access(client):
    headers = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Venue Staff"}
    assert client.get("/venues", headers=headers).status_code == 401


def test_background_worker_internal_tokenpasses_authentication(client):
    response = client.get("/venues", headers={"X-Internal-Token": "internal-test-token"})

    assert response.status_code not in (401, 503)


def test_user_token_takes_precedence_over_an_internal_token(client):
    headers = {"X-Internal-Token": "internal-test-token", "Authorization": "Bearer not-a-jwt"}
    assert client.get("/venues", headers=headers).status_code == 401


def test_wrong_internal_token_is_denied(client):
    assert client.get("/venues", headers={"X-Internal-Token": "guess"}).status_code == 401


def test_health_and_preflight_need_no_token(client):
    assert client.get("/health").status_code == 200
    assert client.options("/venues").status_code == 200


def test_unconfigured_verification_fails_closed(client, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL")

    assert client.get("/venues", headers=bearer(USER_ID, "Venue Staff")).status_code == 503


def test_unreachable_signing_keys_fail_closed(client, monkeypatch):
    def unreachable(token):
        raise jwt.PyJWKClientConnectionError("down")

    monkeypatch.setattr("app.auth.signing_key", unreachable)

    assert client.get("/venues", headers=bearer(USER_ID, "Venue Staff")).status_code == 503


def test_signing_keys_come_from_the_supabase_jwks_endpoint(monkeypatch):
    jwks = MagicMock()
    created = []
    monkeypatch.setattr("app.auth.jwt.PyJWKClient", lambda url: created.append(url) or jwks)
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test/")

    key = real_signing_key("token")

    assert created == ["https://project.supabase.test/auth/v1/.well-known/jwks.json"]
    jwks.get_signing_key_from_jwt.assert_called_once_with("token")
    assert key is jwks.get_signing_key_from_jwt.return_value.key
