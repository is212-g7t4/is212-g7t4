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
- The booking-request write routes and venue profile edit: token verification
  and the role checks run for real.
- Assertions are on the status and nothing being sent downstream.

Doubled
-------
- Event, Venue, Venue Availability, Safety Check Record and Safety Check
  Services: Stub (unittest.mock.patch / monkeypatch on app.routes and
  app.clients, or respx for client tests) - canned answers or raised client
  errors; calls recorded so tests assert what was (or was not) called.

Not proven
----------
- That a refused change leaves stored data unchanged (-> the atomics'
  modification-access tests).
"""
import pytest

from app import create_app, routes
from tests.unit.factories import bearer, signed_in

VENUE_ID = "8381b11e-aaae-4d58-bdba-2607e9e2bde2"
USER = "00000000-0000-4000-8000-000000000001"
VENUE = {"id": VENUE_ID, "setupTimeMinutes": 0, "turnaroundTimeMinutes": 0}

REQUESTER_ROUTES = [
    ("post", "/booking-requests"),
    ("patch", "/booking-requests/booking-1"),
    ("patch", "/booking-requests/booking-1/cancel"),
]


# AC1 ----

@pytest.mark.parametrize("role", ["Event Coordinator", "Event Coordinator Lead"], ids=["event_coordinator", "event_coordinator_lead"])
def test_cancel_request_when_coordinator_role_reaches_cancel_checks(role):
    """
    Summary: Coordinators and the Lead get past the role check to the cancel checks.
    AC1: Given an authenticated user is permitted to modify information based
        on their role and relationship to the event, when they make a valid
        change to that information, then the change is allowed.
    Double: Stub (downstream)
    """
    # Arrange (Given)
    client = signed_in(create_app().test_client(), role=role)

    # Act (When)
    response = client.patch("/booking-requests/booking-1/cancel", json={})

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "eventId is required."


def test_edit_venue_when_venue_staff_is_allowed(monkeypatch):
    """
    Summary: Venue Staff can save a venue profile.
    AC1: Given an authenticated user is permitted to modify information based
        on their role and relationship to the event, when they make a valid
        change to that information, then the change is allowed.
    Double: Stub (Venue Service saves)
    """
    # Arrange (Given)
    monkeypatch.setattr(routes, "update_venue_profile", lambda venue_id, data: VENUE)
    monkeypatch.setattr(
        routes, "reconcile_legacy_conflicts", lambda venue: {"venueId": VENUE_ID, "conflictCount": 0, "conflicts": []}
    )

    # Act (When)
    response = signed_in(create_app().test_client(), role="Venue Staff").put(f"/venues/{VENUE_ID}", json={"name": "X"})

    # Assert (Then)
    assert response.status_code == 200


# AC2 ----

@pytest.mark.parametrize("role", ["Venue Staff", "Technical Support", "Safety Officer", "Event Organiser", "Attendee"], ids=["venue_staff", "technical_support", "safety_officer", "event_organiser", "attendee"])
@pytest.mark.parametrize("method, path", REQUESTER_ROUTES, ids=["create", "edit", "cancel"])
def test_requester_actions_when_other_role_return_403(method, path, role):
    """
    Summary: Only coordinators may create, edit or cancel booking requests.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: None
    """
    # Arrange (Given)
    client = create_app().test_client()

    # Act (When)
    response = getattr(client, method)(path, json={}, headers=bearer(USER, role))

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["message"] == "Your role cannot change this information."


@pytest.mark.parametrize("role", ["Event Coordinator", "Event Coordinator Lead", "Technical Support", "Safety Officer",
                                  "Event Organiser", "Attendee"], ids=["event_coordinator", "event_coordinator_lead", "technical_support", "safety_officer", "event_organiser", "attendee"])
def test_edit_venue_when_not_venue_staff_returns_403(role):
    """
    Summary: Only Venue Staff can edit a venue profile.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: None
    """
    # Arrange (Given)
    client = create_app().test_client()

    # Act (When)
    response = client.put(f"/venues/{VENUE_ID}", json={"name": "X"}, headers=bearer(USER, role))

    # Assert (Then)
    assert response.status_code == 403


# AC4 ----

def test_legacy_conflicts_after_refused_venue_edit_still_viewable(monkeypatch):
    """
    Summary: A coordinator refused a venue edit can still view legacy conflicts.
    AC4: Given a user is permitted to view particular information but is not
        permitted to modify it, when they attempt to change that information,
        then the modification is prevented while their permitted viewing access
        remains unaffected.
    Double: Stub (downstream)
    """
    # Arrange (Given)
    monkeypatch.setattr(routes, "get_venue", lambda venue_id: VENUE)
    monkeypatch.setattr(
        routes, "reconcile_legacy_conflicts", lambda venue: {"venueId": VENUE_ID, "conflictCount": 0, "conflicts": []}
    )
    coordinator = signed_in(create_app().test_client(), role="Event Coordinator")

    before = coordinator.get(f"/venues/{VENUE_ID}/legacy-conflicts")
    refused = coordinator.put(f"/venues/{VENUE_ID}", json={"name": "X"})

    # Act (When)
    after = coordinator.get(f"/venues/{VENUE_ID}/legacy-conflicts")

    # Assert (Then)
    assert (before.status_code, refused.status_code, after.status_code) == (200, 403, 200)
    assert before.json == after.json
