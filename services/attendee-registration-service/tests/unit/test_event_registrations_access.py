"""SCRUM-9 Role-based viewing control for events: Attendee Registration unit tests.

Story:      As a registered user, I want to view only information appropriate to my
            role and relationship to an event, so that I can access the information
            relevant to my responsibilities without viewing restricted information.
Real:       Flask app, GET /events/<id>/registrations route, can_view_event in app/clients.py.
Doubled:    httpx.get (Event Service answer) and the Registration/User lookups.
Not proven: Event Service's own organiser/coordinator rules (event-service tests);
            that the real services accept these requests.
            Modification of registrations is not covered here (SCRUM-10).

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
from tests.unit.factories import signed_in

EVENT_ID = "25c9fe40-c44d-4d79-8d5d-de66d40c1678"
OTHER_EVENT_ID = "35c9fe40-c44d-4d79-8d5d-de66d40c1678"
ROW = {"registration_id": "r1", "event_id": EVENT_ID, "attendee_id": None, "status": "Confirmed"}


def as_role(role):
    app = create_app({"TESTING": True, "FRONTEND_ORIGIN": "http://localhost:5174"})
    return signed_in(app.test_client(), role=role)


def event_service_says(monkeypatch, status):
    """Event Service answers every event lookup with this status."""
    request = httpx.Request("GET", "http://event.test")
    get = Mock(return_value=httpx.Response(status, json={}, request=request))
    monkeypatch.setattr(clients.httpx, "get", get)
    return get


@pytest.fixture
def registrations(monkeypatch):
    fetch = Mock(return_value=[ROW])
    monkeypatch.setattr("app.routes.get_event_registrations", fetch)
    return fetch


# AC1 ----

@pytest.mark.parametrize("role", ["Event Organiser", "Event Coordinator", "Event Coordinator Lead"])
def test_ac1_organiser_coordinator_and_lead_can_list_registrations(monkeypatch, registrations, role):
    """Normal: the roles with a stake in the event get the list once Event Service allows them."""
    event_service_says(monkeypatch, 200)

    response = as_role(role).get(f"/events/{EVENT_ID}/registrations")

    assert response.status_code == 200
    assert response.json["registrations"][0]["registration_id"] == "r1"


# AC2 ----

@pytest.mark.parametrize("role", ["Attendee", "Venue Staff", "Technical Support", "Safety Officer"])
def test_ac2_other_roles_are_denied_without_asking_event_service(monkeypatch, registrations, role):
    """Failure: attendee names and emails are not for roles outside the event's team."""
    get = event_service_says(monkeypatch, 200)

    response = as_role(role).get(f"/events/{EVENT_ID}/registrations")

    assert response.status_code == 403
    get.assert_not_called()
    registrations.assert_not_called()


# AC3 ----

def test_ac3_no_relationship_to_the_event_is_denied(monkeypatch, registrations):
    """Failure: Event Service refuses (not your event), so no registrations are read."""
    event_service_says(monkeypatch, 403)

    response = as_role("Event Organiser").get(f"/events/{EVENT_ID}/registrations")

    assert response.status_code == 403
    registrations.assert_not_called()


def test_ac3_unknown_event_is_reported_as_not_found(monkeypatch, registrations):
    """Failure: an event that does not exist is a 404, not an empty list."""
    event_service_says(monkeypatch, 404)

    assert as_role("Event Coordinator").get(f"/events/{EVENT_ID}/registrations").status_code == 404


# AC4 ----

def test_ac4_only_the_event_the_user_is_related_to_is_listed(monkeypatch, registrations):
    """Conflict: asking for two events returns one list and one refusal."""
    request = httpx.Request("GET", "http://event.test")
    monkeypatch.setattr(clients.httpx, "get", lambda url, **kw: httpx.Response(
        200 if url.endswith(EVENT_ID) else 403, json={}, request=request))
    coordinator = as_role("Event Coordinator")

    mine = coordinator.get(f"/events/{EVENT_ID}/registrations")
    other = coordinator.get(f"/events/{OTHER_EVENT_ID}/registrations")

    assert (mine.status_code, other.status_code) == (200, 403)


# AC5 ----

def test_ac5_each_role_is_judged_on_its_own_relationship_to_the_same_event(monkeypatch):
    """Normal: the Lead is asked as 'any event', the organiser as 'one I created'."""
    get = event_service_says(monkeypatch, 200)

    clients.can_view_event(EVENT_ID, "Event Coordinator Lead")
    clients.can_view_event(EVENT_ID, "Event Organiser")

    lead_params, organiser_params = (call.kwargs["params"] for call in get.call_args_list)
    assert lead_params == {"viewerRole": "me"}
    assert organiser_params == {"organiserId": "me"}


def test_event_service_failure_is_reported_as_unavailable(monkeypatch, registrations):
    """Failure: if Event Service cannot answer, nothing is disclosed."""
    event_service_says(monkeypatch, 503)

    response = as_role("Event Coordinator").get(f"/events/{EVENT_ID}/registrations")

    assert response.status_code == 502
    registrations.assert_not_called()
