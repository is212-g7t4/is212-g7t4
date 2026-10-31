"""
SUPPORTING DESIGN CHECKS: User Service health check, browser access and database failures

User Story
----------
Supporting/supplementary design checks. No story or acceptance
criterion describes the behaviour these tests check; it is plumbing
that every story of this service relies on.

Real
----
- create_app(): the /health route, the CORS after_request hook, the
  missing-DATABASE_URL guard and the psycopg2.Error handler run for real.
- Assertions are on status codes, the CORS response headers and the
  user-facing error message.

Doubled
-------
- User records (database): the connection fails, to show the outage
  message [Stub].
- Sign-in: a test key signs the caller's token (tests/unit/conftest.py)
  [Stub].

Not proven
----------
- That a real browser accepts the CORS headers (-> E2E journeys, which run
  the real frontend against the real services).
- That a real Postgres outage surfaces as psycopg2.Error (NOT COVERED
  ANYWHERE).
"""

import psycopg2
import pytest

from app import create_app
from tests.unit.factories import bearer

ALICE_ID = "e7334aa9-eb3a-4c45-84b5-280501b6c109"


@pytest.fixture
def client():
    return create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"}).test_client()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_health_when_called_without_token_returns_ok(client):
    """
    Summary: Anyone can check that User Service is up without signing in.
    Supporting design check: /health answers without a token
    Double: None
    """
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_preflight_when_origin_is_the_frontend_returns_cors_headers(client):
    """
    Summary: The browser's preflight from the configured frontend is allowed without a token.
    Supporting design check: the configured frontend origin may call User
        Service from a browser
    Double: None
    """
    response = client.options("/users", headers={"Origin": "http://localhost:5174"})

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert response.headers["Vary"] == "Origin"


def test_preflight_when_origin_is_unknown_sends_no_cors_headers(client):
    """
    Summary: A website other than the frontend is not granted browser access.
    Supporting design check: other origins get no CORS grant
    Double: None
    """
    response = client.options("/users", headers={"Origin": "https://other.example"})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_when_frontend_origin_is_blank_allows_no_origin():
    """
    Summary: Blanking FRONTEND_ORIGIN switches browser access off rather than allowing everyone.
    Supporting design check: an empty FRONTEND_ORIGIN grants no origin
    Double: None
    """
    client = create_app({"TESTING": True, "FRONTEND_ORIGIN": ""}).test_client()

    response = client.options("/users", headers={"Origin": "http://localhost:5174"})

    assert "Access-Control-Allow-Origin" not in response.headers


@pytest.mark.parametrize("path", ["/users", f"/users/{ALICE_ID}"], ids=["list", "get"])
def test_user_lookup_when_database_url_missing_returns_503(path):
    """
    Summary: User lookups report the service as unavailable when no database is configured.
    Supporting design check: an unconfigured User Service answers 503
    Double: None
    """
    client = create_app({"TESTING": True, "DATABASE_URL": None}).test_client()

    response = client.get(path, headers=bearer(ALICE_ID, "Event Coordinator"))

    assert response.status_code == 503


def test_user_lookup_when_database_fails_returns_503_without_internals(client, monkeypatch):
    """
    Summary: A database outage gives a plain 503 message that leaks no SQL or credentials.
    Supporting design check: database errors answer 503 with a safe message
    Double: The user records cannot be reached [Stub].
    """
    def unavailable(*args, **kwargs):
        raise psycopg2.OperationalError("password authentication failed for user postgres")

    monkeypatch.setattr("app.models.psycopg2.connect", unavailable)

    response = client.get("/users", headers=bearer(ALICE_ID, "Event Coordinator"))

    assert response.status_code == 503
    assert response.json == {
        "message": "Unable to load users. Please check the User Service database connection and schema."
    }
    assert "password" not in response.get_data(as_text=True)
