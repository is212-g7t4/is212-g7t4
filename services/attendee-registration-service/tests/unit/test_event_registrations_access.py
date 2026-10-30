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
- GET /events/<id>/registrations: the role check and clients.can_view_event
  (asking Event Service whether this caller may see this event) run for real.
- Assertions are on the status and on whether registrations are read.

Doubled
-------
- httpx.get (Event Service's answer): Stub - allows, refuses or 404s.
- get_event_registrations: Mock (`registrations` fixture) - returns one row and
  is asserted not called when access is denied.

Not proven
----------
- Event Service's own organiser/coordinator rules (-> event-service unit tests
  for SCRUM-9).
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

@pytest.mark.parametrize("role", ["Event Organiser", "Event Coordinator", "Event Coordinator Lead"], ids=["event_organiser", "event_coordinator", "event_coordinator_lead"])
def test_event_registrations_when_event_team_allowed_returns_list(monkeypatch, registrations, role):
    """
    Summary: Organisers, coordinators and the Lead get the list once Event Service allows them.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: Stub (Event Service allows), Mock (registrations read)
    """
    # Arrange (Given)
    event_service_says(monkeypatch, 200)

    # Act (When)
    response = as_role(role).get(f"/events/{EVENT_ID}/registrations")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["registrations"][0]["registration_id"] == "r1"


# AC2 ----

@pytest.mark.parametrize("role", ["Attendee", "Venue Staff", "Technical Support", "Safety Officer"], ids=["attendee", "venue_staff", "technical_support", "safety_officer"])
def test_event_registrations_when_role_not_on_event_team_returns_403(monkeypatch, registrations, role):
    """
    Summary: Roles outside the event team are refused without even asking Event Service.
    AC2: Given an authenticated user's role does not permit them to view
        particular information, when they attempt to access that information,
        then access is denied.
    Double: Mock (registrations not read)
    """
    # Arrange (Given)
    get = event_service_says(monkeypatch, 200)

    # Act (When)
    response = as_role(role).get(f"/events/{EVENT_ID}/registrations")

    # Assert (Then)
    assert response.status_code == 403
    get.assert_not_called()
    registrations.assert_not_called()


# AC3 ----

def test_event_registrations_when_not_related_to_event_returns_403(monkeypatch, registrations):
    """
    Summary: A user with no relationship to the event is refused and nothing is read.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to view that event's information, when they attempt to access the
        information, then access is denied.
    Double: Stub (Event Service refuses), Mock (registrations not read)
    """
    # Arrange (Given)
    event_service_says(monkeypatch, 403)

    # Act (When)
    response = as_role("Event Organiser").get(f"/events/{EVENT_ID}/registrations")

    # Assert (Then)
    assert response.status_code == 403
    registrations.assert_not_called()


def test_event_registrations_when_event_unknown_returns_404(monkeypatch, registrations):
    """
    Summary: An event that does not exist is reported as not found, not as an empty list.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to view that event's information, when they attempt to access the
        information, then access is denied.
    Double: Stub (Event Service answers 404)
    """
    # Arrange (Given): monkeypatch, registrations, from fixtures

    # Act (When)
    event_service_says(monkeypatch, 404)

    # Assert (Then)
    assert as_role("Event Coordinator").get(f"/events/{EVENT_ID}/registrations").status_code == 404


# AC4 ----

def test_event_registrations_for_two_events_returns_only_the_related_one(monkeypatch, registrations):
    """
    Summary: Asking for two events gives the list for the related one and a refusal for the other.
    AC4: Given a user is permitted to view information for one event but does
        not have the required relationship to another event, when they attempt
        to view information for both events, then they can only view the
        information for which they have the required access.
    Double: Stub (Event Service allows one event, refuses the other)
    """
    # Arrange (Given)
    request = httpx.Request("GET", "http://event.test")
    monkeypatch.setattr(clients.httpx, "get", lambda url, **kw: httpx.Response(
        200 if url.endswith(EVENT_ID) else 403, json={}, request=request))
    coordinator = as_role("Event Coordinator")

    mine = coordinator.get(f"/events/{EVENT_ID}/registrations")

    # Act (When)
    other = coordinator.get(f"/events/{OTHER_EVENT_ID}/registrations")

    # Assert (Then)
    assert (mine.status_code, other.status_code) == (200, 403)


# AC5 ----

def test_event_registrations_judge_each_role_on_its_own_relationship(monkeypatch):
    """
    Summary: The Lead and the organiser are each judged on their own relationship to the same event.
    AC5: Given two authenticated users have different roles or relationships to
        the same event, when they access information relating to that event,
        then each user can only view the information permitted by their own
        role and relationship to the event.
    Double: Stub (Event Service answers per role; requests inspected)
    """
    # Arrange (Given)
    get = event_service_says(monkeypatch, 200)

    clients.can_view_event(EVENT_ID, "Event Coordinator Lead")
    clients.can_view_event(EVENT_ID, "Event Organiser")

    lead_params, organiser_params = (call.kwargs["params"] for call in get.call_args_list)

    # Act + Assert (When / Then)
    assert lead_params == {"viewerRole": "me"}
    assert organiser_params == {"organiserId": "me"}


def test_event_registrations_when_event_service_fails_returns_502(monkeypatch, registrations):
    """
    Summary: If Event Service cannot answer, nothing is disclosed.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to view that event's information, when they attempt to access the
        information, then access is denied.
    Double: Stub (Event Service raises), Mock (registrations not read)
    """
    # Arrange (Given)
    event_service_says(monkeypatch, 503)

    # Act (When)
    response = as_role("Event Coordinator").get(f"/events/{EVENT_ID}/registrations")

    # Assert (Then)
    assert response.status_code == 502
    registrations.assert_not_called()
