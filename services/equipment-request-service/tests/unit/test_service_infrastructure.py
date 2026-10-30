"""
SUPPORTING DESIGN CHECKS: Equipment Request Service health check, browser access and service plumbing

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
- the missing-DATABASE_URL guard and the psycopg2.Error handler.
- Assertions are on status codes and the CORS response headers.

Doubled
-------
- Supabase JWKS: Stub (tests/conftest.py) - never reached: these paths
  skip sign-in.
- psycopg2.connect: Stub (tests/unit/conftest.py `setup`) - the cursor raises OperationalError for the database-failure test.

Not proven
----------
- That a real browser accepts the CORS headers (-> frontend Playwright e2e
  suite, which runs against the configured origin).
- That a real Postgres outage surfaces as psycopg2.Error (-> integration tests in tests/integration/, which run on a throwaway postgres:17.6).
"""

import psycopg2
import pytest

from app import create_app
from tests.unit.factories import EVENT_ID, ORIGIN, USER_ID, bearer


@pytest.fixture
def client():
    return create_app().test_client()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_health_when_called_without_token_returns_ok(client):
    """
    Summary: Anyone can check that Equipment Request Service is up without signing in.
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
    Supporting design check: the configured frontend origin may call Equipment
        Request Service from a browser
    Double: None
    """
    response = client.options("/equipment-requests", headers={"Origin": origin})

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
    response = client.options("/equipment-requests", headers={"Origin": "https://other.example"})

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

    response = client.options("/equipment-requests", headers={"Origin": "http://localhost:5174"})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_when_frontend_asks_allows_patch_and_post(setup):
    """
    Summary: The frontend may send the review (PATCH) and submission (POST) requests from a browser.
    Supporting design check: CORS grants exactly what the frontend needs
    Double: None
    """
    client, _, _ = setup

    response = client.options(f"/events/{EVENT_ID}/equipment-requests", headers={"Origin": ORIGIN})

    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert "PATCH" in response.headers["Access-Control-Allow-Methods"]
    assert "POST" in response.headers["Access-Control-Allow-Methods"]


def test_equipment_requests_when_database_url_missing_returns_503():
    """
    Summary: Equipment requests report themselves unavailable when no database is configured.
    Supporting design check: an unconfigured Equipment Request Service answers
        503
    Double: None
    """
    client = create_app({"DATABASE_URL": None}).test_client()

    response = client.get("/equipment-requests", headers=bearer(USER_ID, "Technical Support"))

    assert response.status_code == 503


def test_equipment_requests_when_database_fails_returns_503_without_internals(setup):
    """
    Summary: A database outage gives a 503 that leaks no credentials.
    Supporting design check: database errors answer 503 with a safe message
    Double: Stub (cursor.execute raises OperationalError)
    """
    client, cursor, _ = setup
    cursor.execute.side_effect = psycopg2.OperationalError("password=secret")

    response = client.get("/equipment-requests", headers=bearer(USER_ID, "Technical Support"))

    assert response.status_code == 503
    assert "secret" not in response.get_data(as_text=True)
