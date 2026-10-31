"""
SCRUM-9: Role-Based Access Control for Events

User Story
----------
As a registered user, I want to view only information appropriate to my role
and relationship to an event, so that I can access the information relevant to
my responsibilities without viewing restricted information.

Acceptance Criteria
-------------------
AC1: Given an authenticated user is permitted to view information based on
     their role and relationship to the event, when they access that
     information, then the information is made available to them.
AC2: Given an authenticated user's role does not permit them to view particular
     information, when they attempt to access that information, then access is
     denied.
AC3: Given an authenticated user's relationship to an event does not permit
     them to view that event's information, when they attempt to access the
     information, then access is denied.
AC4: Given a user is permitted to view information for one event but does not
     have the required relationship to another event, when they attempt to view
     information for both events, then they can only view the information for
     which they have the required access.
AC5: Given two authenticated users have different roles or relationships to the
     same event, when they access information relating to that event, then each
     user can only view the information permitted by their own role and
     relationship to the event.

Real
----
- GET /registrations: token verification and the role check that lets the event
  team list an event's registrations and limits an Attendee to their own run
  for real.
- Assertions are on the status and the query sent.

Doubled
-------
- psycopg2.connect: Stub / Mock (`setup`) - cursor returns no rows; asserted
  not executed for refused roles.

Not proven
----------
- AC3/AC4 (the caller's relationship to this event): an atomic cannot ask Event
  Service, so Attendee Registration Service checks it (->
  attendee-registration-service test_scrum9_event_registrations_access.py).
"""
from unittest.mock import MagicMock

import pytest

from app import create_app
from tests.unit.factories import signed_in

EVENT_ID = "22222222-2222-4222-8222-222222222222"
USER_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), cursor


# AC1 ----

@pytest.mark.parametrize("role", ["Event Organiser", "Event Coordinator", "Event Coordinator Lead"], ids=["event_organiser", "event_coordinator", "event_coordinator_lead"])
def test_ac1_list_event_registrations_when_event_team_role_returns_200(setup, role):
    """
    Summary: Organisers, coordinators and the Lead can list an event's registrations.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: Stub (cursor returns no rows)
    """
    # Arrange (Given)
    client, _ = setup

    # Act + Assert (When / Then)
    assert signed_in(client, USER_ID, role).get(f"/registrations?eventId={EVENT_ID}").status_code == 200


# AC2 ----

@pytest.mark.parametrize("role", ["Attendee", "Venue Staff", "Technical Support", "Safety Officer"], ids=["attendee", "venue_staff", "technical_support", "safety_officer"])
def test_ac2_list_event_registrations_when_other_role_returns_403_without_query(setup, role):
    """
    Summary: Nobody outside the event team can list an event's registrations.
    AC2: Given an authenticated user's role does not permit them to view
        particular information, when they attempt to access that information,
        then access is denied.
    Double: Mock (cursor not executed)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = signed_in(client, USER_ID, role).get(f"/registrations?eventId={EVENT_ID}")

    # Assert (Then)
    assert response.status_code == 403
    cursor.execute.assert_not_called()


# AC5 ----

def test_ac5_list_registrations_when_attendee_scopes_to_their_own(setup):
    """
    Summary: The same endpoint gives an attendee only their own registrations.
    AC5: Given two authenticated users have different roles or relationships to
        the same event, when they access information relating to that event,
        then each user can only view the information permitted by their own
        role and relationship to the event.
    Double: Stub (cursor returns no rows; query inspected)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = signed_in(client, USER_ID, "Attendee").get("/registrations")

    # Assert (Then)
    assert response.status_code == 200
    assert cursor.execute.call_args.args[1] == [USER_ID]
