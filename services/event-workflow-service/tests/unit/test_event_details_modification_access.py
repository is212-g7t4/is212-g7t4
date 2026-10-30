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
- PATCH /events/<id>/details: token verification and the coordinator-role gate
  run for real.
- Assertions are on the status.

Doubled
-------
- Downstream clients: Stub where the gate is passed.

Not proven
----------
- That the coordinator is the event's assigned one (AC3): Event Service decides
  (-> event-service test_event_modification_access.py).
"""
import pytest

from app import create_app
from tests.unit.factories import bearer, signed_in

EVENT_ID = "00000000-0000-0000-0000-000000000001"
USER = "00000000-0000-4000-8000-000000000001"


# AC1 ----

@pytest.mark.parametrize("role", ["Event Coordinator", "Event Coordinator Lead"], ids=["event_coordinator", "event_coordinator_lead"])
def test_update_details_when_coordinator_role_reaches_change_checks(role):
    """
    Summary: Coordinators and the Lead get past the role check to the change checks.
    AC1: Given an authenticated user is permitted to modify information based
        on their role and relationship to the event, when they make a valid
        change to that information, then the change is allowed.
    Double: Stub (downstream clients)
    """
    # Arrange (Given)
    client = signed_in(create_app().test_client(), role=role)

    # Act (When)
    response = client.patch(f"/events/{EVENT_ID}/details", json={})

    # Assert (Then)
    assert response.status_code == 400
    assert "changes" in response.json["message"]


# AC2 ----

@pytest.mark.parametrize(
    "role", ["Event Organiser", "Venue Staff", "Technical Support", "Safety Officer", "Attendee"],
    ids=["event_organiser", "venue_staff", "technical_support", "safety_officer", "attendee"],
)
def test_update_details_when_not_coordinator_returns_403(role):
    """
    Summary: Every other role is refused editing event details.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: None
    """
    # Arrange (Given)
    client = create_app().test_client()

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/details", json={"changes": {"eventName": "X"}}, headers=bearer(USER, role)
    )

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["code"] == "NOT_ASSIGNED_COORDINATOR"
    assert response.json["message"] == "Your role cannot change this information."
