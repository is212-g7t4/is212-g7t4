"""
SUPPORTING DESIGN CHECKS: Event Service health check and browser access

User Story
----------
Supporting/supplementary design checks. No story or acceptance
criterion describes the behaviour these tests check; it is plumbing
that every story of this service relies on.

Real
----
- The Event Service routes in app/__init__.py and the rules in app/models.py,
  run through a real create_app(): request validation, the caller's role and
  ownership checks from the signed token, the status rules, and the SQL and
  parameters sent to the database (including notification outbox rows).
- Assertions are on the HTTP status, the response body and the queries and
  parameters the cursor received.

Doubled
-------
- psycopg2.connect: Stub (fixture) - a MagicMock connection whose cursor
  returns canned rows; Mock - its execute calls are asserted to prove what was
  (or was not) written.
- Supabase JWKS: Stub (tests/conftest.py) - tokens are signed with a throwaway
  ES256 key.

Not proven
----------
- That the SQL runs against the real Postgres schema, constraints and row locks
  (-> tests/integration/ against a throwaway postgres:17.6).
- That the notification outbox rows are delivered (-> Notification Service
  tests and the E2E journeys).
"""

from app import create_app
from tests.unit.factories import signed_in


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_health_answers_ok_and_cors_is_granted_only_to_the_configured_frontend_origin(setup):
    """
    Summary: GET /health returns {"status": "ok"}; a preflight from http://localhost:5174 gets that origin back in Access-Control-Allow-Origin, and one from https://other.example gets no grant.
    Supporting design check: /health and the CORS grant for the frontend origin
    Double: Stub (setup fixture: psycopg2.connect returns a MagicMock connection, which neither route ever queries);
        the Supabase JWKS Stub verifies the signed token
    """
    client = setup[0]
    assert client.get("/health").json == {"status": "ok"}
    response = client.options("/events", headers={"Origin": "http://localhost:5174"})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert (
        "Access-Control-Allow-Origin"
        not in client.options(
            "/events", headers={"Origin": "https://other.example"}
        ).headers
    )


def test_unconfigured_frontend_origin_does_not_authorise_browser_access():
    """
    Summary: With FRONTEND_ORIGIN empty, /health still answers ok but returns no Access-Control-Allow-Origin header to http://localhost:5174.
    Supporting design check: an empty FRONTEND_ORIGIN grants no origin
    Double: None for the database, since the app has none configured; only the Supabase JWKS Stub,
        which verifies the signed token
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None, "FRONTEND_ORIGIN": ""}).test_client())

    response = client.get("/health", headers={"Origin": "http://localhost:5174"})

    assert response.status_code == 200
    assert response.json == {"status": "ok"}
    assert "Access-Control-Allow-Origin" not in response.headers
