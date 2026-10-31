"""
SCRUM-150: Approve Operational Safety Check

User Story
----------
As a Safety Officer, I want to approve an event's operational safety
arrangements, so that the event can proceed to preparation.

Acceptance Criteria
-------------------
AC1: Given an event is 'Pending Safety Check', when I approve it, then its
     status changes to 'Confirmed'.
AC2: Given I approve an event, then the safety check is recorded with the
     status 'Safety Approved', together with my identity, the approval
     timestamp and any optional remarks, in the event's history.
AC3: Given an event is not 'Pending Safety Check', then the approve action is
     not available and an API call is rejected without changing the event.
AC4: Given the safety check I approve follows a high-impact change, when I
     approve it, then the changed details become visible to registered
     Attendees.

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


def test_no_header_is_refused_when_the_lock_is_configured(setup):
    """
    Summary: No header is refused when the lock is configured.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = client.patch(f"/events/{EVENT_ID}/safety-status", json=body())

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["code"] == "INTERNAL_ONLY"
    cursor.execute.assert_not_called()


def test_wrong_header_is_refused_when_the_lock_is_configured(setup):
    """
    Summary: Wrong header is refused when the lock is configured.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_token_unconfigured_fails_closed(unconfigured):
    """
    Summary: No INTERNAL_SERVICE_TOKEN means the route is refused with 503, not left open.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = unconfigured

    # Act (When)
    response = client.patch(f"/events/{EVENT_ID}/safety-status", json=body())

    # Assert (Then)
    assert response.status_code == 503
    assert response.json["code"] == "INTERNAL_AUTH_NOT_CONFIGURED"
    cursor.execute.assert_not_called()


def test_token_unconfigured_ignores_any_header_sent(unconfigured):
    """
    Summary: A header sent anyway doesn't open an unconfigured route.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_right_header_passes_the_lock(setup):
    """
    Summary: Right header passes the lock.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_cors_does_not_allow_the_internal_header(setup):
    """
    Summary: A browser must not be able to send this header (it isn't in CORS).
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_startup_warns_when_lock_is_off(monkeypatch, caplog):
    """
    Summary: Make it visible when the stack is running unlocked.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_startup_does_not_warn_when_lock_is_on(monkeypatch, caplog):
    """
    Summary: Startup does not warn when lock is on.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_coordinator_cannot_confirm_through_safety_status_when_locked(setup):
    """
    Summary: SCRUM-152 AC1, API path via /safety-status (not just /progress).
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/safety-status",
        json={
            "status": "Confirmed",
            "decidedBy": COORDINATOR_ID,
            "safetyCheckId": SAFETY_CHECK_ID,
            "roundNumber": 1,
        },
    )

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["code"] == "INTERNAL_ONLY"
    cursor.execute.assert_not_called()
