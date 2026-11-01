"""
SUPPORTING DESIGN CHECKS: Coordinator Assignment Service health check and CORS

User Story
----------
Supporting/supplementary design checks. No story or acceptance
criterion describes the behaviour these tests check; it is plumbing
that every story of this service relies on.

Real
----
- create_app(): the /health route and the CORS after_request hook (the
  configured FRONTEND_ORIGIN, its 127.0.0.1/localhost twin, and a blank
  origin) run for real.
- Assertions are on status codes and the CORS response headers.

Doubled
-------
- Supabase JWKS: Stub (tests/conftest.py) - never reached: these paths
  skip sign-in.

Not proven
----------
- That a real browser accepts the CORS headers (-> frontend Playwright e2e
  suite, which runs against the configured origin).
"""

import pytest

from app import create_app


@pytest.fixture
def client():
    return create_app().test_client()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_health_when_called_without_token_returns_ok(client):
    """
    Summary: GET /health with no Authorization header is answered 200 {"status": "ok"}.
    Supporting design check: /health answers without a token
    Double: None; /health skips sign-in, so the Supabase signing-key stub in
        conftest is never reached
    """
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json == {"status": "ok"}


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:5174", "http://127.0.0.1:5174"],
    ids=["configured_origin", "loopback_twin"],
)
def test_preflight_when_origin_is_the_frontend_returns_cors_headers(client, origin):
    """
    Summary: OPTIONS /coordinators with no token, sent from http://localhost:5174
        or its http://127.0.0.1:5174 twin, is answered 200 with that origin echoed in
        Access-Control-Allow-Origin, Vary: Origin and Authorization listed in
        Access-Control-Allow-Headers.
    Supporting design check: the configured frontend origin may call
        Coordinator Assignment Service from a browser
    Double: None; OPTIONS skips sign-in, so the Supabase signing-key stub in
        conftest is never reached
    """
    response = client.options("/coordinators", headers={"Origin": origin})

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert response.headers["Vary"] == "Origin"
    assert "Authorization" in response.headers["Access-Control-Allow-Headers"]


def test_unauthorised_response_when_origin_is_the_frontend_carries_cors_headers(client):
    """
    Summary: GET /coordinators with no token, sent from http://localhost:5174, is
        answered 401 and the 401 carries Access-Control-Allow-Origin:
        http://localhost:5174 and Vary: Origin, so the browser lets the frontend
        read the sign-in error.
    Supporting design check: CORS headers are on real responses, including
        errors, not only on preflights
    Double: None; the request is stopped at sign-in, so the Supabase signing-key
        stub in conftest is never reached
    """
    response = client.get("/coordinators", headers={"Origin": "http://localhost:5174"})

    assert response.status_code == 401
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert response.headers["Vary"] == "Origin"


def test_preflight_when_origin_is_unknown_sends_no_cors_headers(client):
    """
    Summary: OPTIONS /coordinators from https://other.example is answered 200
        but carries no Access-Control-Allow-Origin header.
    Supporting design check: other origins get no CORS grant
    Double: None; OPTIONS skips sign-in, so the Supabase signing-key stub in
        conftest is never reached
    """
    response = client.options("/coordinators", headers={"Origin": "https://other.example"})

    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_when_frontend_origin_is_blank_allows_no_origin(monkeypatch):
    """
    Summary: With FRONTEND_ORIGIN set to "", OPTIONS /coordinators from
        http://localhost:5174 carries no Access-Control-Allow-Origin header, so no
        origin (not even the usual frontend one) is allowed.
    Supporting design check: an empty FRONTEND_ORIGIN grants no origin
    Double: None (FRONTEND_ORIGIN is set with monkeypatch.setenv); OPTIONS skips
        sign-in, so the Supabase signing-key stub in conftest is never reached
    """
    monkeypatch.setenv("FRONTEND_ORIGIN", "")
    client = create_app().test_client()

    response = client.options("/coordinators", headers={"Origin": "http://localhost:5174"})

    assert "Access-Control-Allow-Origin" not in response.headers
