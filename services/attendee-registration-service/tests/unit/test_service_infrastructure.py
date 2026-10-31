"""
SUPPORTING DESIGN CHECKS: Attendee Registration Service health check, browser access and service plumbing

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
- None: health checks and browser preflights skip sign-in.

Not proven
----------
- That a real browser accepts the CORS headers (-> E2E journeys, which run
  the real frontend against the real services).
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
    Summary: Anyone can check that Attendee Registration Service is up without signing in.
    Supporting design check: /health answers without a token
    Double: None
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
    Summary: The browser's preflight from the frontend (by name or loopback address) is allowed without a token.
    Supporting design check: the configured frontend origin may call Attendee
        Registration Service from a browser
    Double: None
    """
    response = client.options("/registrations", headers={"Origin": origin})

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert response.headers["Vary"] == "Origin"
    assert "Authorization" in response.headers["Access-Control-Allow-Headers"]


def test_preflight_when_origin_is_unknown_sends_no_cors_headers(client):
    """
    Summary: A website other than the frontend is not granted browser access.
    Supporting design check: other origins get no CORS grant
    Double: None
    """
    response = client.options("/registrations", headers={"Origin": "https://other.example"})

    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_when_frontend_origin_is_blank_allows_no_origin(monkeypatch):
    """
    Summary: Blanking FRONTEND_ORIGIN switches browser access off rather than allowing everyone.
    Supporting design check: an empty FRONTEND_ORIGIN grants no origin
    Double: None
    """
    monkeypatch.setenv("FRONTEND_ORIGIN", "")
    client = create_app().test_client()

    response = client.options("/registrations", headers={"Origin": "http://localhost:5174"})

    assert "Access-Control-Allow-Origin" not in response.headers
