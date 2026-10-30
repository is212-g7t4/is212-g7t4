"""SCRUM-9 Role-based viewing control for events: Safety Check Record unit tests.

Story:      As a registered user, I want to view only information appropriate to my
            role and relationship to an event, so that I can access the information
            relevant to my responsibilities without viewing restricted information.
Real:       Flask app, GET /safety-check-records route, token verification and role check.
Doubled:    psycopg2 (mocked cursor).
Not proven: that a coordinator is assigned to this event; an atomic cannot ask Event
            Service (Safety Check, Venue Booking and Equipment Reservation do).
            Modification of safety checks is not covered here (SCRUM-10).

AC1  Given an authenticated user is permitted to view information based on their role and
     relationship to the event, when they access that information, then the information
     is made available to them.
AC2  Given an authenticated user's role does not permit them to view particular information,
     when they attempt to access that information, then access is denied.
AC3  Not covered here: relationship to the event is checked by the calling composites.
AC4  Not covered here: same reason as AC3.
AC5  Given two authenticated users have different roles or relationships to the same event,
     when they access information relating to that event, then each user can only view the
     information permitted by their own role and relationship to the event.
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
    "role", ["Event Coordinator", "Event Coordinator Lead", "Safety Officer", "Venue Staff", "Technical Support"]
)
def test_ac1_safety_roles_can_list_an_events_safety_checks(setup, role):
    """Normal: the roles that handle an event's safety may read its rounds."""
    client, _ = setup

    assert list_as(client, role).status_code == 200


# AC2 ----

@pytest.mark.parametrize("role", ["Attendee", "Event Organiser"])
def test_ac2_attendees_and_organisers_cannot_list_safety_checks(setup, role):
    """Failure: remarks and flags are not for these roles; nothing is queried."""
    client, cursor = setup

    assert list_as(client, role).status_code == 403
    cursor.execute.assert_not_called()


# AC5 ----

def test_ac5_same_event_is_open_to_a_safety_officer_but_not_an_attendee(setup):
    """Conflict: two users ask for the same event and get different answers."""
    client, _ = setup

    officer = list_as(client, "Safety Officer")
    attendee = list_as(client, "Attendee")

    assert (officer.status_code, attendee.status_code) == (200, 403)
