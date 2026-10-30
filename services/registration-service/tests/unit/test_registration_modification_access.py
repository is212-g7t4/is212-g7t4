"""SCRUM-10 Role-Based Modification Control: Registration Service unit tests.

Story:      As a registered user, I want to modify only information appropriate to my
            role and relationship to an event, so that I can perform my responsibilities
            without changing information outside my permissions.
Real:       Flask app, routes, token verification and role checks, the ownership error mapping.
Doubled:    psycopg2 (mocked cursor) and, in AC1 and AC3, the model functions behind the routes.
Not proven: that a refused change leaves the stored registration untouched in a real database
            (tests/integration covers registration rules, not SCRUM-10); Supabase issuing the token.

AC1  Given an authenticated user is permitted to modify information based on their role and
     relationship to the event, when they make a valid change to that information, then the
     change is allowed.
AC2  Given an authenticated user's role does not permit them to modify particular information,
     when they attempt to change that information, then the modification is prevented and the
     existing information remains unchanged.
AC3  Given an authenticated user's relationship to an event does not permit them to modify that
     event's information, when they attempt to make a change, then the modification is prevented
     and the existing information remains unchanged.
AC4  Given a user is permitted to view particular information but is not permitted to modify it,
     when they attempt to change that information, then the modification is prevented while their
     permitted viewing access remains unaffected.
AC5  Not covered here: a registration belongs to one attendee and one event, so there is no
     attendee who may change one registration but not another that they own.
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

def test_ac1_an_attendee_registers_for_an_event(setup, monkeypatch):
    """Normal: the Attendee role is permitted to register."""
    client, _ = setup
    monkeypatch.setattr("app.create_registration", lambda *args: {
        "registration_id": REGISTRATION_ID, "event_id": EVENT_ID, "attendee_id": ATTENDEE_ID, "status": "Confirmed",
    })

    response = signed_in(client, ATTENDEE_ID, "Attendee").post("/registrations", json={"eventId": EVENT_ID, "capacity": 30})

    assert response.status_code == 201


# AC2 ----

@pytest.mark.parametrize(
    "role", ["Event Organiser", "Event Coordinator", "Event Coordinator Lead", "Venue Staff", "Technical Support", "Safety Officer"]
)
@pytest.mark.parametrize("method, path", ROUTES)
def test_ac2_only_the_attendee_role_may_register_or_withdraw(setup, method, path, role):
    """Failure: every other role is refused before the body is read or the database touched."""
    client, cursor = setup

    response = getattr(client, method)(path, json={}, headers=bearer(ATTENDEE_ID, role))

    assert response.status_code == 403
    assert response.json["message"] == "Your role cannot change this information."
    cursor.execute.assert_not_called()


# AC3 ----

def test_ac3_an_attendee_cannot_withdraw_someone_elses_registration(setup, monkeypatch):
    """Failure: the Attendee role is not enough without owning the registration."""
    client, _ = setup
    monkeypatch.setattr("app.withdraw_registration", MagicMock(side_effect=RegistrationOwnershipError()))

    response = signed_in(client, OTHER_ATTENDEE_ID, "Attendee").patch(
        f"/registrations/{REGISTRATION_ID}/withdraw", json={}
    )

    assert response.status_code == 403
    assert response.json["code"] == "REGISTRATION_NOT_OWNED"


# AC4 ----

def test_ac4_an_organiser_keeps_viewing_registrations_when_their_change_is_refused(setup):
    """Conflict: the refused registration does not disturb the registration view the role still has."""
    client, cursor = setup
    cursor.fetchall.return_value = []
    organiser = signed_in(client, ATTENDEE_ID, "Event Organiser")

    before = organiser.get(f"/registrations?eventId={EVENT_ID}")
    refused = organiser.post("/registrations", json={"eventId": EVENT_ID, "capacity": 30})
    after = organiser.get(f"/registrations?eventId={EVENT_ID}")

    assert (before.status_code, refused.status_code, after.status_code) == (200, 403, 200)
    assert before.json == after.json
