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
RECORD = "33333333-3333-4333-8333-333333333333"
INTERNAL = {"X-Internal-Token": "internal-test-token"}


@pytest.fixture
def client(monkeypatch):
    from app import create_app

    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value.fetchall.return_value = []
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    return create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"}).test_client()


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/safety-check-records", {"eventId": EVENT}),
        ("patch", f"/safety-check-records/{RECORD}/decision", {"status": "Safety Approved"}),
        ("post", f"/safety-check-records/{RECORD}/withdraw", {"reason": "Venue moved"}),
    ],
)
def test_internal_token_cannot_record_a_users_action(client, method, path, body):
    """Submitter, decider and withdrawer are the signed-in user whose token is forwarded."""
    response = getattr(client, method)(path, json=body, headers=INTERNAL)

    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}




def test_request_without_token_is_denied(client):
    response = client.get("/safety-check-records?eventId=22222222-2222-4222-8222-222222222222")

    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_non_bearer_authorization_is_denied(client):
    assert client.get("/safety-check-records?eventId=22222222-2222-4222-8222-222222222222", headers={"Authorization": "Basic abc"}).status_code == 401


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
    response = client.get("/safety-check-records?eventId=22222222-2222-4222-8222-222222222222", headers=headers)

    assert response.status_code == 401
    assert response.json == {"message": "Your session is invalid or has expired. Sign in again."}


def test_token_without_subject_is_denied(client):
    token = jwt.encode({"aud": "authenticated", "exp": int(time.time()) + 60}, TEST_SIGNING_KEY, algorithm="ES256")
    assert client.get("/safety-check-records?eventId=22222222-2222-4222-8222-222222222222", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_dev_identity_headers_no_longer_grant_access(client):
    headers = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Event Coordinator"}
    assert client.get("/safety-check-records?eventId=22222222-2222-4222-8222-222222222222", headers=headers).status_code == 401


def test_internal_token_alone_is_refused_by_authentication():
    """SCRUM-10: no background worker calls this service, so the internal token is not a way in."""
    from flask import Flask

    from app.auth import authenticate

    with Flask(__name__).test_request_context("/anything", headers={"X-Internal-Token": "internal-test-token"}):
        response, status = authenticate()

    assert status == 401
    assert response.json == {"message": "Sign in to continue."}


def test_user_token_takes_precedence_over_an_internal_token(client):
    headers = {"X-Internal-Token": "internal-test-token", "Authorization": "Bearer not-a-jwt"}
    assert client.get("/safety-check-records?eventId=22222222-2222-4222-8222-222222222222", headers=headers).status_code == 401


def test_wrong_internal_token_is_denied(client):
    assert client.get("/safety-check-records?eventId=22222222-2222-4222-8222-222222222222", headers={"X-Internal-Token": "guess"}).status_code == 401


def test_health_and_preflight_need_no_token(client):
    assert client.get("/health").status_code == 200
    assert client.options("/safety-check-records?eventId=22222222-2222-4222-8222-222222222222").status_code == 200


def test_unconfigured_verification_fails_closed(client, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL")

    assert client.get("/safety-check-records?eventId=22222222-2222-4222-8222-222222222222", headers=bearer(USER_ID, "Event Coordinator")).status_code == 503


def test_unreachable_signing_keys_fail_closed(client, monkeypatch):
    def unreachable(token):
        raise jwt.PyJWKClientConnectionError("down")

    monkeypatch.setattr("app.auth.signing_key", unreachable)

    assert client.get("/safety-check-records?eventId=22222222-2222-4222-8222-222222222222", headers=bearer(USER_ID, "Event Coordinator")).status_code == 503


def test_signing_keys_come_from_the_supabase_jwks_endpoint(monkeypatch):
    jwks = MagicMock()
    created = []
    monkeypatch.setattr("app.auth.jwt.PyJWKClient", lambda url: created.append(url) or jwks)
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test/")

    key = real_signing_key("token")

    assert created == ["https://project.supabase.test/auth/v1/.well-known/jwks.json"]
    jwks.get_signing_key_from_jwt.assert_called_once_with("token")
    assert key is jwks.get_signing_key_from_jwt.return_value.key


def test_a_token_without_a_subject_is_refused_by_authentication():
    """SCRUM-10: authentication guarantees a user id, so handlers need not re-check it."""
    from flask import Flask

    from app.auth import authenticate

    with Flask(__name__).test_request_context("/anything", headers=bearer("", "Attendee")):
        response, status = authenticate()

    assert status == 401
