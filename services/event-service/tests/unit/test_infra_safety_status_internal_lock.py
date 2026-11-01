"""
SUPPORTING DESIGN CHECKS: service-to-service lock on PATCH /events/<id>/safety-status

User Story
----------
Supporting/supplementary design checks. No story or acceptance
criterion describes the behaviour these tests check; it is plumbing
that the safety stories (SCRUM-149, SCRUM-150, SCRUM-151) rely on. Only Safety
Check Service may move an event through the safety statuses, and it proves
that with the X-Internal-Token header.

Real
----
- The Event Service routes in app/__init__.py and the rules in app/models.py,
  run through a real create_app(): the internal-token check in front of
  PATCH /events/<id>/safety-status, the CORS headers, and the startup warning.
- Assertions are on the HTTP status, the response body and code, the CORS
  headers, the log text, and whether the cursor was used.

Doubled
-------
- psycopg2.connect: Stub (fixture) - a MagicMock connection whose cursor
  returns canned rows; Mock - its execute calls are asserted to prove what was
  (or was not) read or written.
- Supabase JWKS: Stub (tests/conftest.py) - tokens are signed with a throwaway
  ES256 key.

Not proven
----------
- That the SQL runs against the real Postgres schema, constraints and row locks
  (-> tests/integration/ against a throwaway postgres:17.6).
- Which roles may call the endpoint with the token (->
  test_scrum10_event_modification_access.py).
- The approval itself (-> test_scrum150_safety_approve_status.py).
"""
from unittest.mock import MagicMock

import pytest

from app import create_app
from tests.unit.factories import signed_in


@pytest.fixture
def unconfigured(monkeypatch):
    """Same as `setup`, but with no INTERNAL_SERVICE_TOKEN configured."""
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": "unused-test-url",
            "INTERNAL_SERVICE_TOKEN": None,
        }
    )
    return signed_in(app.test_client()), connection, cursor

EVENT_ID = "00000000-0000-0000-0000-000000000001"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
SAFETY_CHECK_ID = "55555555-5555-4555-8555-555555555555"
INTERNAL_TOKEN = "test-internal-token"


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": "unused-test-url",
            "INTERNAL_SERVICE_TOKEN": INTERNAL_TOKEN,
        }
    )
    return signed_in(app.test_client()), connection, cursor


def body():
    return {
        "status": "Pending Safety Check",
        "coordinatorId": COORDINATOR_ID,
        "safetyCheckId": SAFETY_CHECK_ID,
        "roundNumber": 1,
    }


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_safety_status_without_the_internal_token_header_is_refused_when_the_lock_is_configured(setup):
    """
    Summary: PATCH /events/<id>/safety-status with a signed-in user but no X-Internal-Token header answers 403 with code INTERNAL_ONLY and no query is sent.
    Supporting design check: the safety-status route is only for the service
        that holds the internal token
    Double: Mock (cursor.execute asserted never called); the server's INTERNAL_SERVICE_TOKEN is configured
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = client.patch(f"/events/{EVENT_ID}/safety-status", json=body())

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["code"] == "INTERNAL_ONLY"
    cursor.execute.assert_not_called()


def test_safety_status_with_the_wrong_internal_token_is_refused_when_the_lock_is_configured(setup):
    """
    Summary: PATCH /events/<id>/safety-status with X-Internal-Token "not-the-token" answers 403 with code INTERNAL_ONLY and no query is sent.
    Supporting design check: a wrong internal token is refused like a missing
        one
    Double: Mock (cursor.execute asserted never called); the server's INTERNAL_SERVICE_TOKEN is configured
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/safety-status",
        json=body(),
        headers={"X-Internal-Token": "not-the-token"},
    )

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["code"] == "INTERNAL_ONLY"
    cursor.execute.assert_not_called()


def test_safety_status_stays_closed_with_503_when_no_internal_token_is_configured(unconfigured):
    """
    Summary: With INTERNAL_SERVICE_TOKEN unset, PATCH /events/<id>/safety-status answers 503 with code INTERNAL_AUTH_NOT_CONFIGURED and no query is sent, so the route is not left open.
    Supporting design check: an unconfigured lock fails closed
    Double: Mock (cursor.execute asserted never called)
    """
    # Arrange (Given)
    client, _, cursor = unconfigured

    # Act (When)
    response = client.patch(f"/events/{EVENT_ID}/safety-status", json=body())

    # Assert (Then)
    assert response.status_code == 503
    assert response.json["code"] == "INTERNAL_AUTH_NOT_CONFIGURED"
    cursor.execute.assert_not_called()


def test_an_internal_token_header_does_not_open_the_route_when_the_server_has_no_token_configured(unconfigured):
    """
    Summary: With INTERNAL_SERVICE_TOKEN unset, PATCH /events/<id>/safety-status carrying X-Internal-Token "anything" still answers 503 and no query is sent.
    Supporting design check: sending a header does not open an unconfigured
        lock
    Double: Mock (cursor.execute asserted never called)
    """
    # Arrange (Given)
    client, _, cursor = unconfigured

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/safety-status",
        json=body(),
        headers={"X-Internal-Token": "anything"},
    )

    # Assert (Then)
    assert response.status_code == 503
    cursor.execute.assert_not_called()


def test_safety_status_with_the_right_internal_token_gets_past_the_lock(setup):
    """
    Summary: PATCH /events/<id>/safety-status with the configured X-Internal-Token reaches the model and answers 404 for an event the database does not have, not 403.
    Supporting design check: the right token passes the lock
    Double: Stub (cursor.fetchone returns None); only the 404 status is asserted
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/safety-status",
        json=body(),
        headers={"X-Internal-Token": INTERNAL_TOKEN},
    )

    # Assert (Then)
    # Past the lock: reaches the model and gets the normal 404, not 403.
    assert response.status_code == 404


def test_cors_preflight_does_not_allow_the_internal_token_header(setup):
    """
    Summary: An OPTIONS request to /events/<id>/safety-status from the frontend origin returns Access-Control-Allow-Headers without X-Internal-Token.
    Supporting design check: a browser must not be able to send the internal
        token header
    Double: None for the database; only the CORS response headers are asserted
    """
    # Arrange (Given)
    client, _, _ = setup

    # Act (When)
    response = client.options(
        f"/events/{EVENT_ID}/safety-status", headers={"Origin": "http://localhost:5174"}
    )

    # Assert (Then)
    assert "X-Internal-Token" not in response.headers.get(
        "Access-Control-Allow-Headers", ""
    )


def test_startup_warns_when_the_internal_token_lock_is_off(monkeypatch, caplog):
    """
    Summary: Creating the app with an empty INTERNAL_SERVICE_TOKEN logs a WARNING containing "INTERNAL_SERVICE_TOKEN is not set".
    Supporting design check: running with the lock off is made visible
    Double: Stub (psycopg2.connect returns a MagicMock connection); the log text is the only assertion
    """
    # Arrange (Given)
    connection = MagicMock()
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )

    # Act (When)
    with caplog.at_level("WARNING"):
        create_app({"TESTING": True, "INTERNAL_SERVICE_TOKEN": ""})

    # Assert (Then)
    assert "INTERNAL_SERVICE_TOKEN is not set" in caplog.text


def test_startup_does_not_warn_when_the_internal_token_lock_is_on(monkeypatch, caplog):
    """
    Summary: Creating the app with INTERNAL_SERVICE_TOKEN set logs no "INTERNAL_SERVICE_TOKEN is not set" warning.
    Supporting design check: no warning when the lock is configured
    Double: Stub (psycopg2.connect returns a MagicMock connection); the log text is the only assertion
    """
    # Arrange (Given)
    connection = MagicMock()
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )

    # Act (When)
    with caplog.at_level("WARNING"):
        create_app({"TESTING": True, "INTERNAL_SERVICE_TOKEN": INTERNAL_TOKEN})

    # Assert (Then)
    assert "INTERNAL_SERVICE_TOKEN is not set" not in caplog.text
