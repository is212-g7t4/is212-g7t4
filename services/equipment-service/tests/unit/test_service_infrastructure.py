"""
SUPPORTING DESIGN CHECKS: Equipment Service health check, browser access and service plumbing

User Story
----------
Supporting/supplementary design checks. No story or acceptance
criterion describes the behaviour these tests check; it is plumbing
that every story of this service relies on.

Real
----
- create_app(): the /health route and the CORS after_request hook (the
  configured FRONTEND_ORIGIN, its 127.0.0.1/localhost twin, and a blank
  origin) run for real, as do the missing-DATABASE_URL guards and the
  psycopg2.Error handler.
- Assertions are on status codes and the CORS response headers.

Doubled
-------
- Supabase JWKS: Stub (tests/conftest.py) - never reached: these paths
  skip sign-in.
- psycopg2.connect: Stub - a MagicMock connection, or raises
  OperationalError for the database-failure test.

Not proven
----------
- That a real browser accepts the CORS headers (-> frontend Playwright e2e
  suite, which runs against the configured origin).
- That a real Postgres outage surfaces as psycopg2.Error (NOT COVERED
  ANYWHERE).
"""

from unittest.mock import MagicMock

import psycopg2
import pytest

from app import create_app
from tests.unit.factories import bearer

VALID_ITEM = {"equipmentType": "Projector", "description": "4K", "totalQuantity": 1, "location": "Store"}
TS_HEADERS = bearer("ad3d6da3-7220-4f80-9157-2ee4abc0455c", "Technical Support")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.models.psycopg2.connect", MagicMock())
    # app/__init__.py defaults to :5173, not the :5174 Vite pins (raised as a finding).
    return create_app({"DATABASE_URL": "postgresql://x", "FRONTEND_ORIGIN": "http://localhost:5174"}).test_client()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_health_when_called_without_token_returns_ok(client):
    """
    Summary: Anyone can check that Equipment Service is up without signing in.
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
        Service from a browser
    Double: None
    """
    response = client.options("/equipment", headers={"Origin": origin})

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
    response = client.options("/equipment", headers={"Origin": "https://other.example"})

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

    response = client.options("/equipment", headers={"Origin": "http://localhost:5174"})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_when_frontend_asks_allows_post_and_no_dev_headers(client):
    """
    Summary: The frontend may send POST with a bearer token, but not the retired developer identity headers.
    Supporting design check: CORS grants exactly what the frontend needs
    Double: None
    """
    response = client.options("/equipment", headers={"Origin": "http://localhost:5174"})

    assert "POST" in response.headers["Access-Control-Allow-Methods"]
    assert "X-Dev-Role" not in response.headers["Access-Control-Allow-Headers"]


@pytest.mark.parametrize("method", ["get", "post"], ids=["list", "create"])
def test_equipment_when_database_url_missing_returns_503(method):
    """
    Summary: The catalogue reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured Equipment Service answers 503
    Double: None
    """
    client = create_app({"DATABASE_URL": None}).test_client()

    response = getattr(client, method)("/equipment", json=VALID_ITEM, headers=TS_HEADERS)

    assert response.status_code == 503


def test_equipment_when_database_fails_returns_503_without_internals(client, monkeypatch):
    """
    Summary: A database outage gives a plain 503 message that leaks no connection details.
    Supporting design check: database errors answer 503 with a safe message
    Double: Stub (psycopg2.connect raises OperationalError)
    """
    monkeypatch.setattr("app.models.psycopg2.connect", MagicMock(side_effect=psycopg2.OperationalError("secret host")))

    response = client.get("/equipment", headers=TS_HEADERS)

    assert response.status_code == 503
    assert "secret" not in response.json["message"]
