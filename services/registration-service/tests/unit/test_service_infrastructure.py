"""
SUPPORTING DESIGN CHECKS: Registration Service health check, browser access and service plumbing

User Story
----------
Supporting/supplementary design checks. No story or acceptance
criterion describes the behaviour these tests check; it is plumbing
that every story of this service relies on.

Real
----
- create_app(): the /health route, the CORS after_request hook, the
  missing-DATABASE_URL guards on every route and the psycopg2.Error handler run
  for real.
- Assertions are on status codes, the CORS response headers and the user-facing
  error message.

Doubled
-------
- psycopg2.connect: Stub (tests/unit/conftest.py `setup`) - the cursor raises
  OperationalError for the database-failure test.

Not proven
----------
- That a real browser accepts the CORS headers (-> frontend Playwright e2e
  suite, which runs against the configured origin).
- That a real Postgres outage surfaces as psycopg2.Error (->
  tests/integration/, throwaway postgres:17.6).
"""

import psycopg2
import pytest

from app import create_app
from tests.unit.factories import ATTENDEE_ID, EVENT_ID, registration_payload, signed_in


@pytest.fixture
def client():
    return create_app().test_client()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_health_when_called_without_token_returns_ok(client):
    """
    Summary: Anyone can check that Registration Service is up without signing in.
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
    Supporting design check: the configured frontend origin may call
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


def test_preflight_when_frontend_asks_allows_post_and_patch(client):
    """
    Summary: The frontend may send registration (POST) and withdrawal (PATCH) requests from a browser.
    Supporting design check: CORS grants exactly what the frontend needs
    Double: None
    """
    response = client.options("/registrations", headers={"Origin": "http://localhost:5174"})

    assert "POST" in response.headers["Access-Control-Allow-Methods"]
    assert "PATCH" in response.headers["Access-Control-Allow-Methods"]


def test_registrations_when_database_fails_returns_503_without_internals(setup):
    """
    Summary: A database outage gives a plain 503 message that leaks no credentials.
    Supporting design check: database errors answer 503 with a safe message
    Double: Stub (cursor.execute raises OperationalError)
    """
    client, _, cursor = setup
    cursor.execute.side_effect = psycopg2.OperationalError("password=secret")

    response = client.get("/registrations")

    assert response.status_code == 503
    assert "secret" not in response.get_data(as_text=True)


def test_attendee_list_when_database_url_missing_returns_503():
    """
    Summary: An attendee's list reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured Registration Service answers 503
    Double: None
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client(), ATTENDEE_ID)
    response = client.get("/registrations")
    assert response.status_code == 503


def test_event_list_when_database_url_missing_returns_503():
    """
    Summary: An event's registration list reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured Registration Service answers 503
    Double: None
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client(), ATTENDEE_ID, "Event Coordinator")
    response = client.get(f"/registrations?eventId={EVENT_ID}")
    assert response.status_code == 503


def test_counts_when_database_url_missing_returns_503(setup):
    """
    Summary: Registration counts report themselves unavailable when no database is configured.
    Supporting design check: an unconfigured Registration Service answers 503
    Double: None
    """
    client, _, _ = setup
    client.application.config["DATABASE_URL"] = None
    assert client.get(f"/registrations/counts?eventIds={EVENT_ID}").status_code == 503


def test_register_when_database_url_missing_returns_503(setup):
    """
    Summary: Registering reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured Registration Service answers 503
    Double: None
    """
    client = setup[0]
    client.application.config["DATABASE_URL"] = None
    assert client.post("/registrations", json=registration_payload()).status_code == 503
