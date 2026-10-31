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
- POST /venues and PUT /venues/<id>: token verification and the Venue Staff
  role check run for real in front of the real handlers.
- Assertions are on the status and on the database not being touched.

Doubled
-------
- psycopg2.connect: Stub / Mock (`setup`) - mocked cursor returning saved rows;
  asserted not executed for refused roles.

Not proven
----------
- That a refused change leaves the stored row unchanged in real PostgreSQL (->
  tests/integration/test_venue_modification_access.py).
- AC3/AC5 event-relationship rules do not apply to catalogue-owned Venue rows;
  they are covered by the services that own event-scoped changes.
"""
from unittest.mock import MagicMock

import pytest

from app import create_app
from tests.unit.factories import VALID_PAYLOAD, VENUE_ID, saved_row, signed_in

STAFF = "Venue Staff"


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), cursor


# AC1 ----

def test_ac1_add_venue_when_venue_staff_saves_venue(setup):
    """
    Summary: Venue Staff can add a venue.
    AC1: Given an authenticated user is permitted to modify information based
        on their role and relationship to the event, when they make a valid
        change to that information, then the change is allowed.
    Double: Stub (cursor: no duplicate, saved row)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [None, saved_row()]

    # Act (When)
    response = signed_in(client, role=STAFF).post("/venues", json=VALID_PAYLOAD)

    # Assert (Then)
    assert response.status_code == 201


def test_ac1_edit_venue_when_venue_staff_saves_changes(setup):
    """
    Summary: Venue Staff can edit a venue profile.
    AC1: Given an authenticated user is permitted to modify information based
        on their role and relationship to the event, when they make a valid
        change to that information, then the change is allowed.
    Double: Stub (cursor: no duplicate, updated row)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [None, saved_row(venue_name="Renamed")]

    # Act (When)
    response = signed_in(client, role=STAFF).put(f"/venues/{VENUE_ID}", json={**VALID_PAYLOAD, "name": "Renamed"})

    # Assert (Then)
    assert response.status_code == 200


# AC2 ----

@pytest.mark.parametrize("role", ["Event Coordinator", "Event Coordinator Lead", "Event Organiser",
                                  "Technical Support", "Safety Officer", "Attendee"], ids=["event_coordinator", "event_coordinator_lead", "event_organiser", "technical_support", "safety_officer", "attendee"])
@pytest.mark.parametrize("method, path", [("post", "/venues"), ("put", f"/venues/{VENUE_ID}")], ids=["add", "edit"])
def test_ac2_add_or_edit_venue_when_not_venue_staff_returns_403_before_database(setup, method, path, role):
    """
    Summary: Every role other than Venue Staff is refused adding or editing a venue, and nothing is changed.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Mock (cursor not executed)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = getattr(signed_in(client, role=role), method)(path, json=VALID_PAYLOAD)

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["code"] == "VENUE_STAFF_ONLY"
    cursor.execute.assert_not_called()


# AC4 ----

def test_ac4_list_venues_after_refused_change_still_viewable_by_coordinator(setup):
    """
    Summary: A coordinator refused a venue change can still browse venues.
    AC4: Given a user is permitted to view particular information but is not
        permitted to modify it, when they attempt to change that information,
        then the modification is prevented while their permitted viewing access
        remains unaffected.
    Double: Stub (cursor returns venues)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = [saved_row()]
    coordinator = signed_in(client, role="Event Coordinator")

    before = coordinator.get("/venues")
    refused = coordinator.post("/venues", json=VALID_PAYLOAD)

    # Act (When)
    after = coordinator.get("/venues")

    # Assert (Then)
    assert (before.status_code, refused.status_code, after.status_code) == (200, 403, 200)
    assert before.json == after.json
