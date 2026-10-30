"""SCRUM-150: PATCH /events/<id>/safety-status can be locked to Safety Check Service.

Moved forward from SCRUM-152 v2 (its B1), because this story opens the first
legitimate route into 'Confirmed'; configuring the lock stops a direct API
call from confirming an event and skipping the Safety Officer entirely.

The lock fails closed (SCRUM-10): without `INTERNAL_SERVICE_TOKEN` configured on this
service the endpoint answers 503. It used to be opt-in and skip the check.

Database calls are mocked; no live database writes.
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
    client, _, cursor = setup

    response = client.patch(f"/events/{EVENT_ID}/safety-status", json=body())

    assert response.status_code == 403
    assert response.json["code"] == "INTERNAL_ONLY"
    cursor.execute.assert_not_called()


def test_wrong_header_is_refused_when_the_lock_is_configured(setup):
    client, _, cursor = setup

    response = client.patch(
        f"/events/{EVENT_ID}/safety-status",
        json=body(),
        headers={"X-Internal-Service-Token": "not-the-token"},
    )

    assert response.status_code == 403
    assert response.json["code"] == "INTERNAL_ONLY"
    cursor.execute.assert_not_called()


def test_token_unconfigured_fails_closed(unconfigured):
    """SCRUM-10: no INTERNAL_SERVICE_TOKEN means the route is refused with 503, not left open."""
    client, _, cursor = unconfigured

    response = client.patch(f"/events/{EVENT_ID}/safety-status", json=body())

    assert response.status_code == 503
    assert response.json["code"] == "INTERNAL_AUTH_NOT_CONFIGURED"
    cursor.execute.assert_not_called()


def test_token_unconfigured_ignores_any_header_sent(unconfigured):
    """A header sent anyway doesn't open an unconfigured route."""
    client, _, cursor = unconfigured

    response = client.patch(
        f"/events/{EVENT_ID}/safety-status",
        json=body(),
        headers={"X-Internal-Service-Token": "anything"},
    )

    assert response.status_code == 503
    cursor.execute.assert_not_called()


def test_right_header_passes_the_lock(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = client.patch(
        f"/events/{EVENT_ID}/safety-status",
        json=body(),
        headers={"X-Internal-Service-Token": INTERNAL_TOKEN},
    )

    # Past the lock: reaches the model and gets the normal 404, not 403.
    assert response.status_code == 404


def test_cors_does_not_allow_the_internal_header(setup):
    """A browser must not be able to send this header (it isn't in CORS)."""
    client, _, _ = setup

    response = client.options(
        f"/events/{EVENT_ID}/safety-status", headers={"Origin": "http://localhost:5174"}
    )

    assert "X-Internal-Service-Token" not in response.headers.get(
        "Access-Control-Allow-Headers", ""
    )


def test_startup_warns_when_lock_is_off(monkeypatch, caplog):
    """SCRUM-152 B2: make it visible when the stack is running unlocked."""
    connection = MagicMock()
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    with caplog.at_level("WARNING"):
        create_app({"TESTING": True, "INTERNAL_SERVICE_TOKEN": ""})

    assert "INTERNAL_SERVICE_TOKEN is not set" in caplog.text


def test_startup_does_not_warn_when_lock_is_on(monkeypatch, caplog):
    connection = MagicMock()
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    with caplog.at_level("WARNING"):
        create_app({"TESTING": True, "INTERNAL_SERVICE_TOKEN": INTERNAL_TOKEN})

    assert "INTERNAL_SERVICE_TOKEN is not set" not in caplog.text


def test_coordinator_cannot_confirm_through_safety_status_when_locked(setup):
    """SCRUM-152 AC1, API path via /safety-status (not just /progress).

    A coordinator who reads their event's open-round safetyCheckId from
    GET /events/<id> and calls /safety-status directly, trying to move
    straight to 'Confirmed' without a Safety Officer's approval, is refused
    before the request ever reaches the database.
    """
    client, _, cursor = setup

    response = client.patch(
        f"/events/{EVENT_ID}/safety-status",
        json={
            "status": "Confirmed",
            "decidedBy": COORDINATOR_ID,
            "safetyCheckId": SAFETY_CHECK_ID,
            "roundNumber": 1,
        },
    )

    assert response.status_code == 403
    assert response.json["code"] == "INTERNAL_ONLY"
    cursor.execute.assert_not_called()
