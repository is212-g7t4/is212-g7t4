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
OTHER = "44444444-4444-4444-8444-444444444444"
ROUND = "55555555-5555-4555-8555-555555555555"
INTERNAL = {"X-Internal-Token": "internal-test-token"}
WORKFLOW = {**INTERNAL, "X-Internal-Service-Token": "internal-test-token"}


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
        ("get", "/change-requests", None, WORKFLOW),
        ("get", f"/change-requests/{EVENT}", None, WORKFLOW),
        ("patch", f"/change-requests/{EVENT}/decision", {}, WORKFLOW),
        ("patch", f"/events/{EVENT}", {"assignedCoordinatorId": OTHER}, INTERNAL),
        ("patch", f"/events/{EVENT}/progress", {}, INTERNAL),
        ("patch", f"/events/{EVENT}/details", {}, INTERNAL),
        (
            "patch",
            f"/events/{EVENT}/safety-status",
            {"status": "Pending Safety Check", "safetyCheckId": ROUND, "roundNumber": 1},
            WORKFLOW,
        ),
        (
            "patch",
            f"/events/{EVENT}/safety-status",
            {"status": "Confirmed", "safetyCheckId": ROUND, "roundNumber": 1},
            WORKFLOW,
        ),
        ("patch", f"/events/{EVENT}/approve", {}, INTERNAL),
        ("patch", f"/events/{EVENT}/clarification-request", {}, INTERNAL),
        ("patch", f"/events/{EVENT}/clarification-response", {}, INTERNAL),
        ("patch", f"/events/{EVENT}/amendment-request", {}, INTERNAL),
        ("patch", f"/events/{EVENT}/amendment-response", {}, INTERNAL),
        ("patch", f"/events/{EVENT}/reject", {}, INTERNAL),
    ],
)
def test_internal_token_cannot_act_as_a_user(client, method, path, body, headers):
    """Every action and view tied to a person needs that person's token, not a body or query id."""
    response = getattr(client, method)(path, json=body, headers=headers)

    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_draft_owner_is_the_signed_in_organiser_not_the_body(client, monkeypatch):
    calls = []
    monkeypatch.setattr("app.save_draft", lambda *args: calls.append(args) or {})

    response = client.post(
        "/events/drafts", json={"organiserId": OTHER, "eventName": "Draft"}, headers=bearer(USER_ID, "Event Organiser")
    )

    assert response.status_code == 201
    assert calls[0][1] == USER_ID


def test_view_all_is_judged_on_the_tokens_role_not_the_query(client):
    response = client.get("/events?viewerRole=Event+Coordinator+Lead", headers=bearer(USER_ID, "Event Coordinator"))

    assert response.status_code == 403
    assert response.json == {"message": "This role cannot view all internal events."}


def test_background_submission_has_no_organiser(client, monkeypatch):
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

    response = client.post("/events", json=body, headers=INTERNAL)

    assert response.status_code == 201
    assert "organiserId" not in submitted[0]




def test_request_without_token_is_denied(client):
    response = client.get("/events/unassigned")

    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_non_bearer_authorization_is_denied(client):
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
def test_invalid_token_is_denied(client, headers):
    response = client.get("/events/unassigned", headers=headers)

    assert response.status_code == 401
    assert response.json == {"message": "Your session is invalid or has expired. Sign in again."}


def test_token_without_subject_is_denied(client):
    token = jwt.encode({"aud": "authenticated", "exp": int(time.time()) + 60}, TEST_SIGNING_KEY, algorithm="ES256")
    assert client.get("/events/unassigned", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_dev_identity_headers_no_longer_grant_access(client):
    headers = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Event Coordinator"}
    assert client.get("/events/unassigned", headers=headers).status_code == 401


def test_background_worker_internal_tokenpasses_authentication(client):
    response = client.get("/events/unassigned", headers={"X-Internal-Token": "internal-test-token"})

    assert response.status_code not in (401, 503)


def test_user_token_takes_precedence_over_an_internal_token(client):
    headers = {"X-Internal-Token": "internal-test-token", "Authorization": "Bearer not-a-jwt"}
    assert client.get("/events/unassigned", headers=headers).status_code == 401


def test_wrong_internal_token_is_denied(client):
    assert client.get("/events/unassigned", headers={"X-Internal-Token": "guess"}).status_code == 401


def test_health_and_preflight_need_no_token(client):
    assert client.get("/health").status_code == 200
    assert client.options("/events/unassigned").status_code == 200


def test_unconfigured_verification_fails_closed(client, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL")

    assert client.get("/events/unassigned", headers=bearer(USER_ID, "Event Coordinator")).status_code == 503


def test_unreachable_signing_keys_fail_closed(client, monkeypatch):
    def unreachable(token):
        raise jwt.PyJWKClientConnectionError("down")

    monkeypatch.setattr("app.auth.signing_key", unreachable)

    assert client.get("/events/unassigned", headers=bearer(USER_ID, "Event Coordinator")).status_code == 503


def test_signing_keys_come_from_the_supabase_jwks_endpoint(monkeypatch):
    jwks = MagicMock()
    created = []
    monkeypatch.setattr("app.auth.jwt.PyJWKClient", lambda url: created.append(url) or jwks)
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test/")

    key = real_signing_key("token")

    assert created == ["https://project.supabase.test/auth/v1/.well-known/jwks.json"]
    jwks.get_signing_key_from_jwt.assert_called_once_with("token")
    assert key is jwks.get_signing_key_from_jwt.return_value.key
