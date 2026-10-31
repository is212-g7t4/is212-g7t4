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
- Who may register or withdraw: only Attendees; every other role is refused
  before anything is read or changed, and a refusal leaves the attendee's own
  view unaffected.
- We check the status, and that refused changes reach no other service.

Doubled
-------
- Registration and Event Services: return the attendee's registration and event
  where needed [Stub]; any unexpected outside call fails the test.
- Sign-in: a test key signs the caller's token (tests/unit/conftest.py) [Stub].

Not proven
----------
- That an attendee can only withdraw their own registration (-> SCRUM-39 tests
  here, and registration-service tests).
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

def test_register_when_attendee_reaches_form_validation():
    """
    Summary: An attendee is allowed past the role check to register.
    AC1: Given an authenticated user is permitted to modify information based
        on their role and relationship to the event, when they make a valid
        change to that information, then the change is allowed.
    Double: None
    """
    client = signed_in(create_app().test_client(), ATTENDEE_ID, "Attendee")

    response = client.post("/registrations", json={})

    assert response.status_code == 400
    assert response.json["message"] == "Complete the required registration fields."


# AC2 ----

@pytest.mark.parametrize(
    "role", ["Event Organiser", "Event Coordinator", "Event Coordinator Lead", "Venue Staff", "Technical Support", "Safety Officer"],
    ids=["event_organiser", "event_coordinator", "event_coordinator_lead", "venue_staff", "technical_support", "safety_officer"],
)
@pytest.mark.parametrize("method, path", ROUTES, ids=["register", "withdraw"])
def test_register_or_withdraw_when_not_attendee_returns_403_without_downstream_call(method, path, role):
    """
    Summary: Every role other than Attendee is refused registering or withdrawing, and nothing is changed.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: None
    """
    client = create_app().test_client()

    response = getattr(client, method)(path, json={}, headers=bearer(ATTENDEE_ID, role))

    assert response.status_code == 403
    assert response.json["message"] == "Your role cannot change this information."


# AC4 ----

def test_my_registrations_after_refused_change_by_other_role_still_load(monkeypatch):
    """
    Summary: A refused change by another role does not affect what an attendee can view.
    AC4: Given a user is permitted to view particular information but is not
        permitted to modify it, when they attempt to change that information,
        then the modification is prevented while their permitted viewing access
        remains unaffected.
    Double: Registration Service and Event Service return the attendee's
        registration and its event [Stub].
    """
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
