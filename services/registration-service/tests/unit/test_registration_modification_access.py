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
- POST /registrations and PATCH /registrations/<id>/withdraw: token
  verification, the Attendee-only role check and the ownership error mapping
  run for real.
- Assertions are on the status and on the database not being touched.

Doubled
-------
- psycopg2.connect: Stub (`setup`) - mocked cursor; the model functions are a
  Stub in AC1 and AC3.

Not proven
----------
- That a refused change leaves the stored registration unchanged in real
  PostgreSQL (NOT COVERED ANYWHERE: the integration tests cover registration
  rules, not SCRUM-10).
"""
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.models import RegistrationOwnershipError
from tests.unit.factories import bearer, signed_in

EVENT_ID = "25c9fe40-c44d-4d79-8d5d-de66d40c1678"
REGISTRATION_ID = "9f725c7a-ac3d-4d4a-937a-84db7906be71"
ATTENDEE_ID = "56b34ab1-92cd-4b35-83c7-f04e176e2bd0"
OTHER_ATTENDEE_ID = "67c45bc2-a3de-4c46-94d8-015f287f3ce1"
ROUTES = [
    ("post", "/registrations"),
    ("patch", f"/registrations/{REGISTRATION_ID}/withdraw"),
]


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), cursor


# AC1 ----

def test_register_when_attendee_saves_registration(setup, monkeypatch):
    """
    Summary: An attendee is allowed to register.
    AC1: Given an authenticated user is permitted to modify information based
        on their role and relationship to the event, when they make a valid
        change to that information, then the change is allowed.
    Double: Stub (create_registration returns the saved row)
    """
    # Arrange (Given)
    client, _ = setup
    monkeypatch.setattr("app.create_registration", lambda *args: {
        "registration_id": REGISTRATION_ID, "event_id": EVENT_ID, "attendee_id": ATTENDEE_ID, "status": "Confirmed",
    })

    # Act (When)
    response = signed_in(client, ATTENDEE_ID, "Attendee").post("/registrations", json={"eventId": EVENT_ID, "capacity": 30})

    # Assert (Then)
    assert response.status_code == 201


# AC2 ----

@pytest.mark.parametrize(
    "role", ["Event Organiser", "Event Coordinator", "Event Coordinator Lead", "Venue Staff", "Technical Support", "Safety Officer"],
    ids=["event_organiser", "event_coordinator", "event_coordinator_lead", "venue_staff", "technical_support", "safety_officer"],
)
@pytest.mark.parametrize("method, path", ROUTES, ids=["register", "withdraw"])
def test_register_or_withdraw_when_not_attendee_returns_403_before_database(setup, method, path, role):
    """
    Summary: Every role other than Attendee is refused before the body is read or the database touched.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Mock (cursor not executed)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = getattr(client, method)(path, json={}, headers=bearer(ATTENDEE_ID, role))

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["message"] == "Your role cannot change this information."
    cursor.execute.assert_not_called()


# AC3 ----

def test_withdraw_when_registration_not_owned_returns_403(setup, monkeypatch):
    """
    Summary: Being an attendee is not enough to withdraw someone else's registration.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to modify that event's information, when they attempt to make a
        change, then the modification is prevented and the existing information
        remains unchanged.
    Double: Stub (withdraw_registration raises RegistrationOwnershipError)
    """
    # Arrange (Given)
    client, _ = setup
    monkeypatch.setattr("app.withdraw_registration", MagicMock(side_effect=RegistrationOwnershipError()))

    # Act (When)
    response = signed_in(client, OTHER_ATTENDEE_ID, "Attendee").patch(
        f"/registrations/{REGISTRATION_ID}/withdraw", json={}
    )

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["code"] == "REGISTRATION_NOT_OWNED"


# AC4 ----

def test_event_registrations_after_refused_change_still_viewable_by_organiser(setup):
    """
    Summary: An organiser refused a registration change can still view the event's registrations.
    AC4: Given a user is permitted to view particular information but is not
        permitted to modify it, when they attempt to change that information,
        then the modification is prevented while their permitted viewing access
        remains unaffected.
    Double: Stub (cursor returns no rows)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = []
    organiser = signed_in(client, ATTENDEE_ID, "Event Organiser")

    before = organiser.get(f"/registrations?eventId={EVENT_ID}")
    refused = organiser.post("/registrations", json={"eventId": EVENT_ID, "capacity": 30})

    # Act (When)
    after = organiser.get(f"/registrations?eventId={EVENT_ID}")

    # Assert (Then)
    assert (before.status_code, refused.status_code, after.status_code) == (200, 403, 200)
    assert before.json == after.json
