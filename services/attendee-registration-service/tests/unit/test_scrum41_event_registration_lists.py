"""
SCRUM-41: View Event Info as Event Organizer

User Story
----------
As an Event Organiser, I want to view registration information for my events,
so that I can see who is attending.

Acceptance Criteria
-------------------
AC1: The Event Organiser can view a list of events that they have created.
AC2: For each approved event, the Event Organiser can see the total number of
     registrations.
AC3: The Event Organiser can click on an event to view detailed registration
     information including list of registered Attendees with name, email,
     organisation (if provided), registration date, registration status
     (Confirmed, Withdrawn), total registration count
AC4: Given the Event Organiser did not create the event, they cannot view
     registration information for that event.

Real
----
- The organiser's registration list for an event they created: each
  registration with the attendee's name, email and organisation, its date and
  status, and refusal for events they did not create.
- We check the list returned or the refusal.

Doubled
-------
- Event Service: says whether the organiser may view the event [Stub]; we check
  it was told the caller is an organiser [Mock].
- Registration and User Services: hold the registrations and attendee profiles
  [Stub].
- Sign-in: a test key signs the caller's token (tests/unit/conftest.py) [Stub].

Not proven
----------
- That Event Service knows who created the event (-> event-service SCRUM-9
  tests).
- The list of the organiser's events and the counts (AC1, AC2) (->
  registration-service test_scrum40_registration_lists_and_counts.py and
  event-service tests).
"""

from unittest.mock import Mock

import pytest

from app import create_app
from tests.unit.factories import EVENT_ID, USER, registration, signed_in

ORGANISER_ID = "77777777-7777-4777-8777-777777777777"


@pytest.fixture
def organiser():
    return signed_in(create_app().test_client(), ORGANISER_ID, "Event Organiser")


def test_ac3_event_registrations_for_organiser_include_attendee_details(organiser, monkeypatch):
    """
    Summary: The organiser of an event sees each registered attendee's name, email and organisation with the registration's date and status.
    AC3: The Event Organiser can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count
    Double: Event Service confirms the organiser may view the event, Registration
        Service holds a confirmed and a withdrawn registration, and User Service
        holds the attendee's profile [Stub]; we check the organiser's role was
        passed on for the access decision [Mock].
    """
    can_view = Mock(return_value=True)
    monkeypatch.setattr("app.routes.can_view_event", can_view)
    monkeypatch.setattr(
        "app.routes.get_event_registrations",
        lambda event_id: [registration(), registration(registration_id="registration-2", status="Withdrawn")],
    )
    monkeypatch.setattr("app.routes.get_user", lambda user_id: USER)

    response = organiser.get(f"/events/{EVENT_ID}/registrations")

    assert response.status_code == 200
    first, second = response.json["registrations"]
    assert (first["attendee_name"], first["attendee_email"], first["attendee_organization"]) == (
        "Adam Yeo", "adam@example.com", "External",
    )
    assert first["registration_date"] == "2026-10-08T02:00:00+00:00"
    assert [first["status"], second["status"]] == ["Confirmed", "Withdrawn"]
    can_view.assert_called_once_with(EVENT_ID, "Event Organiser")


def test_ac4_event_registrations_for_organiser_of_another_event_returns_403(organiser, monkeypatch):
    """
    Summary: An organiser cannot see the registrations of an event they did not create, and nothing is read.
    AC4: Given the Event Organiser did not create the event, they cannot view
        registration information for that event.
    Double: Event Service says this organiser did not create the event [Stub];
        we check no registrations are read [Mock].
    """
    read = Mock()
    monkeypatch.setattr("app.routes.can_view_event", lambda event_id, role: False)
    monkeypatch.setattr("app.routes.get_event_registrations", read)

    response = organiser.get(f"/events/{EVENT_ID}/registrations")

    assert response.status_code == 403
    assert response.json == {"message": "You cannot view the registrations for this event."}
    read.assert_not_called()
