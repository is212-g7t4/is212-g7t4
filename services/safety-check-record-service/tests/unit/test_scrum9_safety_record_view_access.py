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
- Who may see an event's safety rounds: staff whose work involves the safety
  check may; Attendees and Event Organisers may not.
- We check who gets the rounds and who is refused.

Doubled
-------
- Safety records (database): hold the rounds each test needs, accept new ones,
  or cannot be reached [Stub]; we check what is saved, and that rounds are
  locked before they change [Mock].
- Sign-in: a test key signs the caller's token (tests/unit/conftest.py) [Stub].

Not proven
----------
- That each caller only sees rounds for events they are related to (->
  safety-check-service SCRUM-9 tests, which check the relationship).
"""
from unittest.mock import MagicMock

import pytest

from app import create_app
from tests.unit.factories import COORDINATOR_ID, EVENT_ID, signed_in


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), cursor


def list_as(client, role):
    return signed_in(client, COORDINATOR_ID, role).get(f"/safety-check-records?eventId={EVENT_ID}")


# AC1 ----

@pytest.mark.parametrize(
    "role", ["Event Coordinator", "Event Coordinator Lead", "Safety Officer", "Venue Staff", "Technical Support"],
    ids=["event_coordinator", "event_coordinator_lead", "safety_officer", "venue_staff", "technical_support"],
)
def test_list_rounds_when_safety_related_role_returns_200(setup, role):
    """
    Summary: Coordinators, the Lead, Safety Officers, Venue Staff and Technical Support can see safety rounds.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: The safety records hold no such round [Stub].
    """
    client, _ = setup

    assert list_as(client, role).status_code == 200


# AC2 ----

@pytest.mark.parametrize("role", ["Attendee", "Event Organiser"], ids=["attendee", "event_organiser"])
def test_list_rounds_when_attendee_or_organiser_returns_403(setup, role):
    """
    Summary: Attendees and organisers cannot see safety rounds.
    AC2: Given an authenticated user's role does not permit them to view
        particular information, when they attempt to access that information,
        then access is denied.
    Double: We check the safety records are never touched [Mock].
    """
    client, cursor = setup

    assert list_as(client, role).status_code == 403
    cursor.execute.assert_not_called()


# AC5 ----

def test_list_rounds_for_same_event_answers_each_by_own_role(setup):
    """
    Summary: The same event's rounds are open to a Safety Officer but not an attendee.
    AC5: Given two authenticated users have different roles or relationships to
        the same event, when they access information relating to that event,
        then each user can only view the information permitted by their own
        role and relationship to the event.
    Double: The safety records hold no such round [Stub].
    """
    client, _ = setup

    officer = list_as(client, "Safety Officer")

    attendee = list_as(client, "Attendee")

    assert (officer.status_code, attendee.status_code) == (200, 403)
