"""
SUPPORTING DESIGN CHECKS: Equipment Request Service health check, browser access and service plumbing

User Story
----------
Supporting/supplementary design checks. No story or acceptance
criterion describes the behaviour these tests check; it is plumbing
that every story of this service relies on.

Real
----
- create_app(), its routes, browser-access (CORS) response hook, missing-database
  guard and database-error handler run for real. The cases check that:
  - /health returns 200 and {"status": "ok"} without a login token.
  - Browser permission checks (OPTIONS, also called preflight) allow the
    configured frontend and its localhost/127.0.0.1 twin, including permission
    to send an Authorization header. A separate preflight allows POST
    (submission) and PATCH (review); neither preflight needs a login token.
  - An unknown website gets no browser-access permission header; blank or unset
    FRONTEND_ORIGIN also grants no website access.
  - An equipment-request read returns 503 (service unavailable) when DATABASE_URL
    is missing, or when the database stub raises an error. The error response
    must not expose the simulated secret from that error.
- A login token is signed proof of the caller's user ID and role, sent in the
  Authorization: Bearer header. The two database-route checks send synthetic
  signed tokens for a Technical Support user so they reach the database checks
  rather than being refused for missing login. Health and OPTIONS skip login.

Doubled
-------
- Supabase signing-key lookup: Stub (tests/conftest.py) - supplies the test public
  key to verify synthetic login tokens without contacting the real sign-in
  system. Health and OPTIONS do not reach this stub.
- psycopg2.connect: Stub (tests/unit/conftest.py `setup`) - the cursor raises OperationalError for the database-failure test.

Not proven
----------
- That a real browser accepts the CORS headers: NOT PROVEN here; former mocked frontend browser tests were retired, not replaced.
- A real database outage is not injected here; the error is supplied by a Stub. Disposable integration transaction failures do not establish network-outage handling.

Exception: no approved Jira AC owns health/CORS/plumbing; preserve these useful checks pending a PO ownership decision. Do not invent a SCRUM key.
"""

import psycopg2
import pytest

from app import create_app
from tests.unit.factories import EVENT_ID, ORIGIN, USER_ID, bearer


@pytest.fixture
def client():
    return create_app({"FRONTEND_ORIGIN": ORIGIN}).test_client()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_health_when_called_without_token_returns_ok(client):
    """Summary: Anyone can check that Equipment Request Service is up without signing in.
    Double: None reached on public/pre-validation paths; installed JWKS/database stubs remain unused
    Exception: Supporting design check: no live Jira AC specifies this rule; PO ownership/acceptance decision required.
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
    Double: None reached on public/pre-validation paths; installed JWKS/database stubs remain unused
    Exception: Supporting design check: no live Jira AC specifies this rule; PO ownership/acceptance decision required.
    """
    response = client.options("/equipment-requests", headers={"Origin": origin})

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert response.headers["Vary"] == "Origin"
    assert "Authorization" in response.headers["Access-Control-Allow-Headers"]


def test_preflight_when_origin_is_unknown_sends_no_cors_headers(client):
    """Summary: A website other than the frontend is not granted browser access.
    Double: None reached on public/pre-validation paths; installed JWKS/database stubs remain unused
    Exception: Supporting design check: no live Jira AC specifies this rule; PO ownership/acceptance decision required.
    """
    response = client.options("/equipment-requests", headers={"Origin": "https://other.example"})

    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_when_frontend_origin_is_blank_allows_no_origin(monkeypatch):
    """Summary: Blanking FRONTEND_ORIGIN switches browser access off rather than allowing everyone.
    Double: None reached on public/pre-validation paths; installed JWKS/database stubs remain unused
    Exception: Supporting design check: no live Jira AC specifies this rule; PO ownership/acceptance decision required.
    """
    monkeypatch.setenv("FRONTEND_ORIGIN", "")
    client = create_app().test_client()

    response = client.options("/equipment-requests", headers={"Origin": "http://localhost:5174"})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_when_frontend_asks_allows_patch_and_post(setup):
    """Summary: The frontend may send the review (PATCH) and submission (POST) requests from a browser.
    Double: Stub (installed database adapter; may remain unused on validation refusals); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    Exception: Supporting design check: no live Jira AC specifies this rule; PO ownership/acceptance decision required.
    """
    client, _, _ = setup

    response = client.options(f"/events/{EVENT_ID}/equipment-requests", headers={"Origin": ORIGIN})

    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert "PATCH" in response.headers["Access-Control-Allow-Methods"]
    assert "POST" in response.headers["Access-Control-Allow-Methods"]


def test_equipment_requests_when_database_url_missing_returns_503():
    """Summary: Equipment requests report themselves unavailable when no database is configured.
    Double: Stub (test JWKS public key; no database is reached)
    Exception: Supporting design check: no live Jira AC specifies this rule; PO ownership/acceptance decision required.
    """
    client = create_app({"DATABASE_URL": None}).test_client()

    response = client.get("/equipment-requests", headers=bearer(USER_ID, "Technical Support"))

    assert response.status_code == 503


def test_equipment_requests_when_database_fails_returns_503_without_internals(setup):
    """Summary: A database outage gives a 503 that leaks no credentials.
    Double: Stub (canned database results/errors); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    Exception: Supporting design check: no live Jira AC specifies this rule; PO ownership/acceptance decision required.
    """
    client, cursor, _ = setup
    cursor.execute.side_effect = psycopg2.OperationalError("password=secret")

    response = client.get("/equipment-requests", headers=bearer(USER_ID, "Technical Support"))

    assert response.status_code == 503
    assert "secret" not in response.get_data(as_text=True)


def test_health_when_frontend_origin_unset_allows_no_browser_origin(client):
    """Summary: With no frontend origin configured, no website gets browser access.
    Double: None reached on public/pre-validation paths; installed JWKS/database stubs remain unused
    Exception: Supporting design check: no live Jira AC specifies this rule; PO ownership/acceptance decision required.
    """
    client.application.config["FRONTEND_ORIGIN"] = None
    response = client.get("/health", headers={"Origin": "https://untrusted.invalid"})
    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers
