"""SCRUM-150: PATCH /events/<id>/safety-status is locked to Safety Check Service.

Moved forward from SCRUM-152 v2 (its B1), because this story opens the first
legitimate route into 'Confirmed'; without the lock, a direct API call could
confirm an event and skip the Safety Officer entirely.

Database calls are mocked; no live database writes.
"""
from unittest.mock import MagicMock

import pytest

from app import create_app

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
    return app.test_client(), connection, cursor


def body():
    return {
        "status": "Pending Safety Check",
        "coordinatorId": COORDINATOR_ID,
        "safetyCheckId": SAFETY_CHECK_ID,
        "roundNumber": 1,
    }


def test_no_header_is_refused(setup):
    client, _, cursor = setup

    response = client.patch(f"/events/{EVENT_ID}/safety-status", json=body())

    assert response.status_code == 403
    assert response.json["code"] == "INTERNAL_ONLY"
    cursor.execute.assert_not_called()


def test_wrong_header_is_refused(setup):
    client, _, cursor = setup

    response = client.patch(
        f"/events/{EVENT_ID}/safety-status",
        json=body(),
        headers={"X-Internal-Service-Token": "not-the-token"},
    )

    assert response.status_code == 403
    assert response.json["code"] == "INTERNAL_ONLY"
    cursor.execute.assert_not_called()


def test_token_unconfigured_is_503():
    client = create_app(
        {"TESTING": True, "DATABASE_URL": "unused-test-url", "INTERNAL_SERVICE_TOKEN": None}
    ).test_client()

    response = client.patch(
        f"/events/{EVENT_ID}/safety-status",
        json=body(),
        headers={"X-Internal-Service-Token": "anything"},
    )

    assert response.status_code == 503


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
