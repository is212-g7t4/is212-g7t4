"""
SCRUM-10: Role-Based Modification Control for Events

User Story
----------
As a registered user, I want to modify only information appropriate to my role
and relationship to an event, so that I can perform my responsibilities without
changing information outside my permissions.

Acceptance Criteria
-------------------
AC1: Given an authenticated user is permitted to modify information based on
     their role and relationship to the event, when they make a valid change to
     that information, then the change is allowed.
AC2: Given an authenticated user's role does not permit them to modify
     particular information, when they attempt to change that information, then
     the modification is prevented and the existing information remains
     unchanged.
AC3: Given an authenticated user's relationship to an event does not permit
     them to modify that event's information, when they attempt to make a
     change, then the modification is prevented and the existing information
     remains unchanged.
AC4: Given a user is permitted to view particular information but is not
     permitted to modify it, when they attempt to change that information, then
     the modification is prevented while their permitted viewing access remains
     unaffected.
AC5: Given a user is permitted to modify information for one event but does not
     have the required access to another event, when they attempt to modify
     information for both events, then only modifications to information for
     which they have the required access are allowed.

Real
----
- POST /events/<id>/equipment-requests/safety-reset: token verification, the
  Safety Officer role check and the internal-token check run for real.
- Assertions are on the status and on the database not being touched.

Doubled
-------
- psycopg2.connect: Stub (`setup`) - a MagicMock connection.

Not proven
----------
- That a refused reset leaves the stored requests unchanged in real PostgreSQL
  (NOT COVERED ANYWHERE).
- Create and review role refusals (-> test_scrum32_create_equipment_request.py
  and test_scrum33_equipment_request_review.py).
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

def test_safety_reset_when_safety_officer_with_service_token_reaches_validation(setup):
    """
    Summary: A Safety Officer acting through Safety Check Service gets past both checks.
    AC1: Given an authenticated user is permitted to modify information based
        on their role and relationship to the event, when they make a valid
        change to that information, then the change is allowed.
    Double: Stub (MagicMock connection)
    """
    # Arrange (Given)
    client, _ = setup

    # Act (When)
    response = client.post(PATH, json={}, headers={**bearer(USER_ID, "Safety Officer"), "X-Internal-Token": TOKEN})

    # Assert (Then)
    assert response.status_code == 400


# AC2 ----

@pytest.mark.parametrize(
    "role", ["Event Coordinator", "Event Coordinator Lead", "Technical Support", "Venue Staff", "Event Organiser", "Attendee"],
    ids=["event_coordinator", "event_coordinator_lead", "technical_support", "venue_staff", "event_organiser", "attendee"],
)
def test_safety_reset_when_not_safety_officer_returns_403_even_with_service_token(setup, role):
    """
    Summary: The service token proves the route, not the person: any other role is refused.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Stub (MagicMock connection)
    """
    # Arrange (Given)
    client, connection = setup

    # Act (When)
    response = client.post(
        PATH, json={"requestIds": [REQUEST_ID]},
        headers={**bearer(USER_ID, role), "X-Internal-Token": TOKEN},
    )

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["message"] == "Your role cannot change this information."
    connection.cursor.assert_not_called()
