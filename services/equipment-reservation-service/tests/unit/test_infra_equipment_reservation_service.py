"""
SUPPORTING DESIGN CHECKS: Equipment Reservation Service health check, browser access and service plumbing

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
- app.clients base-URL resolution from the *_SERVICE_URL environment variables.
- Assertions are on status codes and the CORS response headers.

Doubled
-------
- Supabase JWKS: Stub (tests/conftest.py) - never reached: these paths
  skip sign-in.
- httpx.request: Stub (tests/unit/conftest.py `sent`) - records the call so the resolved URL can be inspected.

Not proven
----------
- That a real browser accepts the CORS headers (-> frontend Playwright e2e
  suite, which runs against the configured origin).
"""

import pytest

from app import clients, create_app
from tests.unit.fakes import FakeResponse


@pytest.fixture
def client():
    return create_app().test_client()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_health_when_called_without_token_returns_ok(client):
    """Summary: Anyone can check that Equipment Reservation Service is up without signing in.
Double: None
Supporting design check: /health answers without a token
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
    """Summary: The browser's preflight from the frontend (by name or loopback address) is allowed without a token.
Double: None
Supporting design check: the configured frontend origin may call Equipment Reservation Service from a browser
"""
    response = client.options("/equipment-reservations", headers={"Origin": origin})

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert response.headers["Vary"] == "Origin"
    assert "Authorization" in response.headers["Access-Control-Allow-Headers"]


def test_preflight_when_origin_is_unknown_sends_no_cors_headers(client):
    """Summary: A website other than the frontend is not granted browser access.
Double: None
Supporting design check: other origins get no CORS grant
"""
    response = client.options("/equipment-reservations", headers={"Origin": "https://other.example"})

    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_when_frontend_origin_is_blank_allows_no_origin(monkeypatch):
    """Summary: Blanking FRONTEND_ORIGIN switches browser access off rather than allowing everyone.
Double: None
Supporting design check: an empty FRONTEND_ORIGIN grants no origin
"""
    monkeypatch.setenv("FRONTEND_ORIGIN", "")
    client = create_app().test_client()

    response = client.options("/equipment-reservations", headers={"Origin": "http://localhost:5174"})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_when_frontend_asks_allows_patch_and_post(client):
    """Summary: The frontend may send the review (PATCH) and submission (POST) requests from a browser.
Double: None
Supporting design check: CORS grants exactly what the frontend needs
"""
    response = client.options("/equipment-reservations", headers={"Origin": "http://localhost:5174"})

    assert "PATCH" in response.headers["Access-Control-Allow-Methods"]
    assert "POST" in response.headers["Access-Control-Allow-Methods"]


def test_downstream_base_url_when_env_set_is_used_for_calls(sent, monkeypatch):
    """Summary: Each downstream service's address can be configured, as Docker Compose does.
Double: Stub (httpx.request records the URL)
Supporting design check: downstream URLs come from *_SERVICE_URL
"""
    calls, fake = sent
    fake.response = FakeResponse(body={"equipment": []})
    monkeypatch.setenv("EQUIPMENT_SERVICE_URL", "http://equipment-service:5000")

    clients.list_equipment()

    assert calls[0][1] == "http://equipment-service:5000/equipment"


def test_health_when_frontend_origin_unset_allows_no_browser_origin():
    """Summary: With no frontend origin configured, no website gets browser access.
Double: None
Supporting design check: an unset FRONTEND_ORIGIN grants no origin
"""
    client = create_app({"FRONTEND_ORIGIN": None}).test_client()
    response = client.get("/health", headers={"Origin": "https://untrusted.invalid"})
    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers


def test_request_list_when_downstream_fails_does_not_disclose_details(client, sent):
    """Summary: An unexpected service failure never exposes private downstream text to the caller.
Double: Stub (downstream HTTP failure), Stub (local signing-key lookup).
Supporting design check: unexpected downstream failures have a generic public response.
"""
    from tests.unit.factories import bearer

    _, fake = sent
    fake.response = FakeResponse(500, {"message": "synthetic-private-detail"})

    response = client.get("/equipment-reservations", headers=bearer(
        "00000000-0000-4000-8000-000000000001", "Technical Support"))

    assert response.status_code == 502
    assert response.json == {"message": "A service this request depends on failed."}
    assert "synthetic-private-detail" not in response.get_data(as_text=True)
