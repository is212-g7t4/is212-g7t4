"""SCRUM-9 Role-based viewing control for events: Venue Booking unit tests.

Story:      As a registered user, I want to view only information appropriate to my
            role and relationship to an event, so that I can access the information
            relevant to my responsibilities without viewing restricted information.
Real:       Flask app, GET /events/<id>/booking-requests route, token verification,
            get_event_as in app/clients.py.
Doubled:    httpx.get (Event Service answer), the booking and venue lookups.
Not proven: Event Service's own organiser/coordinator rules (event-service tests).
            Modification of booking requests is not covered here (SCRUM-10).

AC1  Given an authenticated user is permitted to view information based on their role and
     relationship to the event, when they access that information, then the information
     is made available to them.
AC2  Given an authenticated user's role does not permit them to view particular information,
     when they attempt to access that information, then access is denied.
AC3  Given an authenticated user's relationship to an event does not permit them to view that
     event's information, when they attempt to access the information, then access is denied.
AC4  Given a user is permitted to view information for one event but does not have the
     required relationship to another event, when they attempt to view information for both
     events, then they can only view the information for which they have the required access.
AC5  Given two authenticated users have different roles or relationships to the same event,
     when they access information relating to that event, then each user can only view the
     information permitted by their own role and relationship to the event.
"""
from unittest.mock import Mock

import httpx
import pytest

from app import clients, create_app
from app.clients import EventNotAssignedError
from tests.unit.factories import signed_in

EVENT = "evt-1"
OTHER_EVENT = "evt-2"


def as_role(role):
    return signed_in(create_app().test_client(), role=role)


def event_service_says(monkeypatch, status):
    request = httpx.Request("GET", "http://event.test")
    get = Mock(return_value=httpx.Response(status, json={}, request=request))
    monkeypatch.setattr(clients.httpx, "get", get)
    return get


@pytest.fixture
def downstream(monkeypatch):
    """Bookings and venues exist; only the event lookup differs per test."""
    monkeypatch.setattr("app.routes.get_event_bookings", lambda event_id: [{"id": "b1", "venueId": "v1"}])
    monkeypatch.setattr("app.routes.get_venues", lambda: [{"id": "v1", "name": "Hall"}])


# AC1 ----

@pytest.mark.parametrize("role", ["Event Organiser", "Event Coordinator Lead", "Venue Staff"])
def test_ac1_organiser_lead_and_venue_staff_can_list_an_events_requests(monkeypatch, downstream, role):
    """Normal: roles with a stake in the venue request get it once Event Service allows them."""
    event_service_says(monkeypatch, 200)

    response = as_role(role).get(f"/events/{EVENT}/booking-requests")

    assert response.status_code == 200
    assert response.json["bookings"][0]["venueName"] == "Hall"


# AC2 ----

@pytest.mark.parametrize("role", ["Attendee", "Technical Support", "Safety Officer"])
def test_ac2_other_roles_are_denied_without_asking_event_service(monkeypatch, downstream, role):
    """Failure: venue requests are not for roles with no part in them."""
    get = event_service_says(monkeypatch, 200)

    assert as_role(role).get(f"/events/{EVENT}/booking-requests").status_code == 403
    get.assert_not_called()


# AC3 ----

def test_ac3_organiser_of_a_different_event_is_denied(monkeypatch, downstream):
    """Failure: Event Service says this is not their event."""
    event_service_says(monkeypatch, 403)

    assert as_role("Event Organiser").get(f"/events/{EVENT}/booking-requests").status_code == 403


# AC4 ----

def test_ac4_coordinator_gets_only_the_event_they_are_assigned_to(monkeypatch, downstream):
    """Conflict: asking for two events returns one list and one refusal."""
    def get_event(event_id):
        if event_id != EVENT:
            raise EventNotAssignedError
    monkeypatch.setattr("app.routes.get_event", get_event)
    coordinator = as_role("Event Coordinator")

    mine = coordinator.get(f"/events/{EVENT}/booking-requests")
    other = coordinator.get(f"/events/{OTHER_EVENT}/booking-requests")

    assert (mine.status_code, other.status_code) == (200, 403)


# AC5 ----

def test_ac5_each_role_asks_event_service_the_question_that_fits_it(monkeypatch):
    """Normal: the organiser is asked as 'one I created', the Lead and Venue Staff as 'any event'."""
    get = event_service_says(monkeypatch, 200)

    for role in ("Event Organiser", "Event Coordinator Lead", "Venue Staff"):
        clients.get_event_as(EVENT, role)

    assert [call.kwargs["params"] for call in get.call_args_list] == [
        {"organiserId": "me"}, {"viewerRole": "me"}, {"viewerRole": "me"},
    ]


def test_event_service_not_found_is_reported_as_not_found(monkeypatch, downstream):
    """Failure: an event that does not exist is a 404."""
    event_service_says(monkeypatch, 404)

    assert as_role("Venue Staff").get(f"/events/{EVENT}/booking-requests").status_code == 404
