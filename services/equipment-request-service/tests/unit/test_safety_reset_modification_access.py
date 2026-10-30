"""SCRUM-10 Role-Based Modification Control: Equipment Request Service unit tests.

Story:      As a registered user, I want to modify only information appropriate to my
            role and relationship to an event, so that I can perform my responsibilities
            without changing information outside my permissions.
Real:       Flask app, routes, token verification, the role check and the internal-token check.
Doubled:    psycopg2 (mocked connection).
Not proven: that a refused reset leaves the stored requests unchanged in a real database;
            Supabase issuing the token. Create and review already refuse the wrong role
            (tests/test_equipment_requests.py).

AC1  Given an authenticated user is permitted to modify information based on their role and
     relationship to the event, when they make a valid change to that information, then the
     change is allowed.
AC2  Given an authenticated user's role does not permit them to modify particular information,
     when they attempt to change that information, then the modification is prevented and the
     existing information remains unchanged.
AC3  Not covered here: a safety reset is not tied to an event's coordinator or organiser.
AC4  Not covered here: this route has no read-only counterpart for the roles it refuses.
AC5  Not covered here: see AC3.
"""
from unittest.mock import MagicMock

import pytest

from app import create_app
from tests.unit.factories import bearer

EVENT = "00000000-0000-0000-0000-000000000001"
REQUEST_ID = "2a1bfb57-a3c0-4450-897e-cc5c73690000"
USER_ID = "e7334aa9-eb3a-4c45-84b5-280501b6c109"
TOKEN = "internal-test-token"
PATH = f"/events/{EVENT}/equipment-requests/safety-reset"


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"DATABASE_URL": "postgresql://x", "INTERNAL_SERVICE_TOKEN": TOKEN})
    return app.test_client(), connection


# AC1 ----

def test_ac1_a_safety_officer_with_the_token_gets_past_both_checks(setup):
    """Normal: role and token both fit, so the handler runs and asks for valid request ids."""
    client, _ = setup

    response = client.post(PATH, json={}, headers={**bearer(USER_ID, "Safety Officer"), "X-Internal-Service-Token": TOKEN})

    assert response.status_code == 400


# AC2 ----

@pytest.mark.parametrize(
    "role", ["Event Coordinator", "Event Coordinator Lead", "Technical Support", "Venue Staff", "Event Organiser", "Attendee"]
)
def test_ac2_only_a_safety_officer_may_reset_requests_even_with_the_internal_token(setup, role):
    """Failure: the service-to-service token proves the route, not the person; the role must also fit."""
    client, connection = setup

    response = client.post(
        PATH, json={"requestIds": [REQUEST_ID]},
        headers={**bearer(USER_ID, role), "X-Internal-Service-Token": TOKEN},
    )

    assert response.status_code == 403
    assert response.json["message"] == "Your role cannot change this information."
    connection.cursor.assert_not_called()
