"""
SUPPORTING DESIGN CHECKS: Event Workflow Service HTTP plumbing (health and CORS)

User Story
----------
Supporting/supplementary design checks. No story or acceptance
criterion describes the behaviour these tests check; it is plumbing
that every story of this service relies on.

Real
----
- create_app(): the /health route, the token check that skips health and
  preflight requests, and the CORS headers for the configured frontend origin
  run for real.
- Assertions are on the status, body and Access-Control-Allow-Origin header.

Doubled
-------
- Supabase signing key: Stub (autouse fixture in conftest.py); no test here
  sends a token, so it is never used.
- FRONTEND_ORIGIN: set with monkeypatch where a test needs it empty.

Not proven
----------
- That the deployed gateway forwards the Origin header (NOT COVERED ANYWHERE).
"""
import pytest

from app import create_app
from tests.unit.factories import signed_in


@pytest.fixture
def client():
    return create_app().test_client()


def test_health_and_preflight_without_token_are_answered(client):
    """
    Summary: GET /health and OPTIONS /change-requests, both sent with no
        token, are answered 200 instead of 401.
    Supporting design check: /health and CORS preflight answer without a token
    Double: None (no downstream client and no token; the conftest signing-key
        stub is not exercised)
    """
    assert client.get("/health").status_code == 200
    assert client.options("/change-requests").status_code == 200


def test_health_when_called_returns_ok(client):
    """
    Summary: GET /health with no token answers {"status": "ok"}.
    Supporting design check: /health answers without a token
    Double: None (no downstream client and no token)
    """
    assert client.get("/health").json == {"status": "ok"}


def test_preflight_from_frontend_only_is_allowed(client):
    """
    Summary: OPTIONS /health from Origin http://localhost:5174 gets that origin
        echoed in Access-Control-Allow-Origin; from http://evil.example it gets
        no such header.
    Supporting design check: CORS for the configured frontend origin
    Double: None (default FRONTEND_ORIGIN is used; no downstream client)
    """
    allowed = client.options("/health", headers={"Origin": "http://localhost:5174"})
    denied = client.options("/health", headers={"Origin": "http://evil.example"})

    assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert "Access-Control-Allow-Origin" not in denied.headers


def test_preflight_with_no_frontend_origin_allows_nothing(monkeypatch):
    """
    Summary: With FRONTEND_ORIGIN set to an empty string, OPTIONS /health from
        http://localhost:5174 gets no Access-Control-Allow-Origin header.
    Supporting design check: CORS for the configured frontend origin
    Double: Stub (FRONTEND_ORIGIN set to "" via monkeypatch; Supabase signing
        key via conftest); no downstream client
    """
    monkeypatch.setenv("FRONTEND_ORIGIN", "")

    response = signed_in(create_app().test_client()).options("/health", headers={"Origin": "http://localhost:5174"})

    assert "Access-Control-Allow-Origin" not in response.headers
