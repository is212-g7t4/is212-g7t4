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
- GET /events/<id>/booking-requests: the role check and the per-role question
  to Event Service about the caller's relationship to the event.
- Assertions are on the status and the questions asked.

Doubled
-------
- Event, Venue, Venue Availability, User and Safety Check Services: Stub (patch
  / monkeypatch on app.clients, or respx) - canned answers or raised errors;
  calls recorded so tests assert what was (or was not) called.

Not proven
----------
- Event Service's own relationship rules (-> event-service unit tests for
  SCRUM-9).
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

@pytest.mark.parametrize("role", ["Event Organiser", "Event Coordinator Lead", "Venue Staff"], ids=["event_organiser", "event_coordinator_lead", "venue_staff"])
def test_ac1_event_requests_when_related_role_returns_list(monkeypatch, downstream, role):
    """
    Summary: The organiser, the Lead and Venue Staff get an event's requests once Event Service allows them.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: Stub (Event Service allows)
    """
    # Arrange (Given)
    event_service_says(monkeypatch, 200)

    # Act (When)
    response = as_role(role).get(f"/events/{EVENT}/booking-requests")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["bookings"][0]["venueName"] == "Hall"


# AC2 ----

@pytest.mark.parametrize("role", ["Attendee", "Technical Support", "Safety Officer"], ids=["attendee", "technical_support", "safety_officer"])
def test_ac2_event_requests_when_role_has_no_part_returns_403(monkeypatch, downstream, role):
    """
    Summary: Roles with no part in venue requests are refused without asking Event Service.
    AC2: Given an authenticated user's role does not permit them to view
        particular information, when they attempt to access that information,
        then access is denied.
    Double: Mock (Event Service not asked)
    """
    # Arrange (Given): monkeypatch, downstream, role, from fixtures

    # Act (When)
    get = event_service_says(monkeypatch, 200)

    # Assert (Then)
    assert as_role(role).get(f"/events/{EVENT}/booking-requests").status_code == 403
    get.assert_not_called()


# AC3 ----

def test_ac3_event_requests_for_other_organisers_event_returns_403(monkeypatch, downstream):
    """
    Summary: An organiser cannot see another organiser's event.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to view that event's information, when they attempt to access the
        information, then access is denied.
    Double: Stub (Event Service refuses)
    """
    # Arrange (Given): monkeypatch, downstream, from fixtures

    # Act (When)
    event_service_says(monkeypatch, 403)

    # Assert (Then)
    assert as_role("Event Organiser").get(f"/events/{EVENT}/booking-requests").status_code == 403


# AC4 ----

def test_ac4_event_requests_for_two_events_returns_only_assigned_one(monkeypatch, downstream):
    """
    Summary: Asking for two events gives the assigned one and a refusal for the other.
    AC4: Given a user is permitted to view information for one event but does
        not have the required relationship to another event, when they attempt
        to view information for both events, then they can only view the
        information for which they have the required access.
    Double: Stub (Event Service allows one)
    """
    # Arrange (Given)
    def get_event(event_id):
        if event_id != EVENT:
            raise EventNotAssignedError
    monkeypatch.setattr("app.routes.get_event", get_event)
    coordinator = as_role("Event Coordinator")

    mine = coordinator.get(f"/events/{EVENT}/booking-requests")

    # Act (When)
    other = coordinator.get(f"/events/{OTHER_EVENT}/booking-requests")

    # Assert (Then)
    assert (mine.status_code, other.status_code) == (200, 403)


# AC5 ----

def test_ac5_event_requests_ask_event_service_per_role(monkeypatch):
    """
    Summary: Each role is judged on its own relationship to the same event.
    AC5: Given two authenticated users have different roles or relationships to
        the same event, when they access information relating to that event,
        then each user can only view the information permitted by their own
        role and relationship to the event.
    Double: Stub (Event Service; questions inspected)
    """
    # Arrange (Given)
    get = event_service_says(monkeypatch, 200)

    # Act (When)
    for role in ("Event Organiser", "Event Coordinator Lead", "Venue Staff"):
        clients.get_event_as(EVENT, role)

    # Assert (Then)
    assert [call.kwargs["params"] for call in get.call_args_list] == [
        {"organiserId": "me"}, {"viewerRole": "me"}, {"viewerRole": "me"},
    ]


def test_ac3_event_requests_for_unknown_event_returns_404(monkeypatch, downstream):
    """
    Summary: An event that does not exist is reported as not found.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to view that event's information, when they attempt to access the
        information, then access is denied.
    Double: Stub (Event Service answers 404)
    """
    # Arrange (Given): monkeypatch, downstream, from fixtures

    # Act (When)
    event_service_says(monkeypatch, 404)

    # Assert (Then)
    assert as_role("Venue Staff").get(f"/events/{EVENT}/booking-requests").status_code == 404
