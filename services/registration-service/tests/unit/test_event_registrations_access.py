"""SCRUM-9 Role-based viewing control for events: Registration Service unit tests.

Story:      As a registered user, I want to view only information appropriate to my
            role and relationship to an event, so that I can access the information
            relevant to my responsibilities without viewing restricted information.
Real:       Flask app, GET /registrations route, token verification and role check.
Doubled:    psycopg2 (mocked cursor).
Not proven: that the caller is this event's organiser or assigned coordinator; an atomic
            cannot ask Event Service, so Attendee Registration Service checks that
            (its tests). Modification of registrations is not covered here (SCRUM-10).

AC1  Given an authenticated user is permitted to view information based on their role and
     relationship to the event, when they access that information, then the information
     is made available to them.
AC2  Given an authenticated user's role does not permit them to view particular information,
     when they attempt to access that information, then access is denied.
AC3  Not covered here: relationship to the event is checked in Attendee Registration Service.
AC4  Not covered here: same reason as AC3.
AC5  Given two authenticated users have different roles or relationships to the same event,
     when they access information relating to that event, then each user can only view the
     information permitted by their own role and relationship to the event.
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

@pytest.mark.parametrize("role", ["Event Organiser", "Event Coordinator", "Event Coordinator Lead"])
def test_ac1_event_team_roles_can_list_an_events_registrations(setup, role):
    """Normal: the roles that run an event may read its registrations."""
    client, _ = setup

    assert signed_in(client, USER_ID, role).get(f"/registrations?eventId={EVENT_ID}").status_code == 200


# AC2 ----

@pytest.mark.parametrize("role", ["Attendee", "Venue Staff", "Technical Support", "Safety Officer"])
def test_ac2_other_roles_cannot_list_an_events_registrations(setup, role):
    """Failure: nobody outside the event team gets the full list; nothing is queried."""
    client, cursor = setup

    response = signed_in(client, USER_ID, role).get(f"/registrations?eventId={EVENT_ID}")

    assert response.status_code == 403
    cursor.execute.assert_not_called()


# AC5 ----

def test_ac5_attendee_sees_only_their_own_registrations(setup):
    """Normal: the same endpoint gives an Attendee their own rows, scoped by token."""
    client, cursor = setup

    response = signed_in(client, USER_ID, "Attendee").get("/registrations")

    assert response.status_code == 200
    assert cursor.execute.call_args.args[1] == [USER_ID]
