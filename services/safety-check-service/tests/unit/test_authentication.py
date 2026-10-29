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
INTERNAL = {"X-Internal-Token": "internal-test-token"}


@pytest.fixture
def client():
    from app import create_app

    return create_app().test_client()


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", f"/safety-checks/{EVENT}/review", None),
        ("post", "/safety-checks", {"eventId": EVENT}),
        ("post", "/safety-checks/approve", {"eventId": EVENT}),
        ("post", "/safety-checks/request-changes", {"eventId": EVENT}),
        ("post", "/safety-checks/reject", {"eventId": EVENT}),
        ("post", "/safety-checks/recheck", {"eventId": EVENT}),
        ("post", "/safety-checks/withdraw-for-venue-change", {"eventId": EVENT}),
        ("post", "/safety-checks/restore-after-venue-change", {"eventId": EVENT}),
        ("get", f"/safety-checks/resubmit/readiness?eventId={EVENT}", None),
        ("get", f"/safety-checks/feedback?eventId={EVENT}", None),
        ("get", f"/safety-checks/readiness?eventId={EVENT}", None),
        ("get", "/safety-checks/queue", None),
    ],
)
def test_internal_token_cannot_act_as_a_user(client, method, path, body):
    """The coordinator or Safety Officer is always the signed-in user, never a body or query id."""
    response = getattr(client, method)(path, json=body, headers=INTERNAL)

    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_parallel_downstream_reads_carry_the_callers_token(client, monkeypatch):
    """Arrangements are read on worker threads; each still forwards the caller's token."""
    from app import clients

    monkeypatch.setattr(clients, "get_event", lambda event_id, viewer_role=None: {"id": event_id, "status": "Approved"})
    sent = []

    class Reply:
        status_code = 200
        is_success = True

        @staticmethod
        def json():
            return {"bookings": [], "requests": []}

    def request(method, url, **kwargs):
        sent.append(kwargs["headers"].get("Authorization"))
        return Reply()

    monkeypatch.setattr(clients.httpx, "request", request)
    headers = bearer(USER_ID, "Event Coordinator")

    client.get(f"/safety-checks/readiness?eventId={EVENT}", headers=headers)

    assert len(sent) == 2
    assert set(sent) == {headers["Authorization"]}




def test_request_without_token_is_denied(client):
    response = client.get("/safety-checks/queue")

    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_non_bearer_authorization_is_denied(client):
    assert client.get("/safety-checks/queue", headers={"Authorization": "Basic abc"}).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(bearer(USER_ID, "Safety Officer", key=ec.generate_private_key(ec.SECP256R1())), id="forged-signature"),
        pytest.param(bearer(USER_ID, "Safety Officer", exp=int(time.time()) - 60), id="expired"),
        pytest.param(bearer(USER_ID, "Safety Officer", aud="anon"), id="wrong-audience"),
        pytest.param({"Authorization": "Bearer not-a-jwt"}, id="malformed"),
    ],
)
def test_invalid_token_is_denied(client, headers):
    response = client.get("/safety-checks/queue", headers=headers)

    assert response.status_code == 401
    assert response.json == {"message": "Your session is invalid or has expired. Sign in again."}


def test_token_without_subject_is_denied(client):
    token = jwt.encode({"aud": "authenticated", "exp": int(time.time()) + 60}, TEST_SIGNING_KEY, algorithm="ES256")
    assert client.get("/safety-checks/queue", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_dev_identity_headers_no_longer_grant_access(client):
    headers = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Safety Officer"}
    assert client.get("/safety-checks/queue", headers=headers).status_code == 401


def test_background_worker_internal_tokencannot_act_as_a_user(client):
    response = client.get("/safety-checks/queue", headers={"X-Internal-Token": "internal-test-token"})

    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_user_token_takes_precedence_over_an_internal_token(client):
    headers = {"X-Internal-Token": "internal-test-token", "Authorization": "Bearer not-a-jwt"}
    assert client.get("/safety-checks/queue", headers=headers).status_code == 401


def test_wrong_internal_token_is_denied(client):
    assert client.get("/safety-checks/queue", headers={"X-Internal-Token": "guess"}).status_code == 401


def test_health_and_preflight_need_no_token(client):
    assert client.get("/health").status_code == 200
    assert client.options("/safety-checks/queue").status_code == 200


def test_unconfigured_verification_fails_closed(client, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL")

    assert client.get("/safety-checks/queue", headers=bearer(USER_ID, "Safety Officer")).status_code == 503


def test_unreachable_signing_keys_fail_closed(client, monkeypatch):
    def unreachable(token):
        raise jwt.PyJWKClientConnectionError("down")

    monkeypatch.setattr("app.auth.signing_key", unreachable)

    assert client.get("/safety-checks/queue", headers=bearer(USER_ID, "Safety Officer")).status_code == 503


def test_signing_keys_come_from_the_supabase_jwks_endpoint(monkeypatch):
    jwks = MagicMock()
    created = []
    monkeypatch.setattr("app.auth.jwt.PyJWKClient", lambda url: created.append(url) or jwks)
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test/")

    key = real_signing_key("token")

    assert created == ["https://project.supabase.test/auth/v1/.well-known/jwks.json"]
    jwks.get_signing_key_from_jwt.assert_called_once_with("token")
    assert key is jwks.get_signing_key_from_jwt.return_value.key
