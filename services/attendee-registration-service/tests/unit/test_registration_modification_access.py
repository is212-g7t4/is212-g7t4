"""SCRUM-10 Role-Based Modification Control: Attendee Registration Service unit tests.

Story:      As a registered user, I want to modify only information appropriate to my
            role and relationship to an event, so that I can perform my responsibilities
            without changing information outside my permissions.
Real:       Flask app, routes, token verification and role checks.
Doubled:    every downstream service (Event, Registration, User); the unit tier's socket block
            fails any call that is not stubbed, so a refused change is also proven to send
            nothing downstream.
Not proven: that the attendee owns the registration they withdraw (Registration Service
            checks that and has its own tests); that a refused change leaves the stored
            registration untouched (Registration Service); Supabase issuing the token.

AC1  Given an authenticated user is permitted to modify information based on their role and
     relationship to the event, when they make a valid change to that information, then the
     change is allowed.
AC2  Given an authenticated user's role does not permit them to modify particular information,
     when they attempt to change that information, then the modification is prevented and the
     existing information remains unchanged.
AC3  Not covered here: ownership of a registration is decided by Registration Service.
AC4  Given a user is permitted to view particular information but is not permitted to modify it,
     when they attempt to change that information, then the modification is prevented while their
     permitted viewing access remains unaffected.
AC5  Not covered here: see AC3.
"""
import pytest

from app import create_app
from tests.unit.factories import bearer, signed_in

ATTENDEE_ID = "56b34ab1-92cd-4b35-83c7-f04e176e2bd0"
REGISTRATION_ID = "9f725c7a-ac3d-4d4a-937a-84db7906be71"
ROUTES = [
    ("post", "/registrations"),
    ("patch", f"/registrations/{REGISTRATION_ID}/withdraw"),
]


# AC1 ----

def test_ac1_the_attendee_role_gets_past_the_gate_to_registration_validation():
    """Normal: an Attendee reaches the handler, which then asks for the required fields."""
    client = signed_in(create_app().test_client(), ATTENDEE_ID, "Attendee")

    response = client.post("/registrations", json={})

    assert response.status_code == 400
    assert response.json["message"] == "Complete the required registration fields."


# AC2 ----

@pytest.mark.parametrize(
    "role", ["Event Organiser", "Event Coordinator", "Event Coordinator Lead", "Venue Staff", "Technical Support", "Safety Officer"]
)
@pytest.mark.parametrize("method, path", ROUTES)
def test_ac2_only_the_attendee_role_may_register_or_withdraw(method, path, role):
    """Failure: every other role is refused before anything is read, and nothing is sent downstream."""
    client = create_app().test_client()

    response = getattr(client, method)(path, json={}, headers=bearer(ATTENDEE_ID, role))

    assert response.status_code == 403
    assert response.json["message"] == "Your role cannot change this information."


# AC4 ----

def test_ac4_an_attendee_keeps_viewing_registrations_when_another_roles_change_is_refused(monkeypatch):
    """Conflict: a refused registration by a non-attendee does not disturb the attendee's own list."""
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda: [])
    monkeypatch.setattr("app.routes.get_confirmed_events", lambda: [])
    app = create_app()
    attendee = signed_in(app.test_client(), ATTENDEE_ID, "Attendee")
    organiser = signed_in(app.test_client(), ATTENDEE_ID, "Event Organiser")

    before = attendee.get("/registrations")
    refused = organiser.post("/registrations", json={})
    after = attendee.get("/registrations")

    assert (before.status_code, refused.status_code, after.status_code) == (200, 403, 200)
    assert before.json == after.json
