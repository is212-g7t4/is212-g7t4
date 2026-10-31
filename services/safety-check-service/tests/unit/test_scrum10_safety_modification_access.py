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
- Who may submit, re-check or withdraw a safety check: only coordinators and
  the Lead; every other role is refused before anything is read or changed, and
  a refusal leaves their viewing access unaffected.
- We check the status, and that refused changes reach no other service.

Doubled
-------
- Event, Safety Check Record, Venue Availability, Venue, Equipment Request and
  User Services: answer as each test needs, fail, or do not answer in time
  [Stub]; we check which were asked, in what order, and what they were sent
  [Mock].
- Sign-in: a test key signs the caller's token (tests/conftest.py) [Stub].

Not proven
----------
- That only the event's assigned coordinator can act (-> the SCRUM-149,
  SCRUM-153 and SCRUM-164 tests here, which check the assignment).
"""
import pytest

from app import clients, create_app
from tests.unit.factories import OFFICER_ID, bearer, signed_in

COORDINATOR_ROUTES = [
    "/safety-checks",
    "/safety-checks/resubmit",
    "/safety-checks/recheck",
    "/safety-checks/withdraw-for-venue-change",
    "/safety-checks/restore-after-venue-change",
]


# AC1 ----

@pytest.mark.parametrize("role", ["Event Coordinator", "Event Coordinator Lead"])
@pytest.mark.parametrize("path", COORDINATOR_ROUTES, ids=["submit", "resubmit", "recheck", "withdraw_for_venue_change", "restore_after_venue_change"])
def test_safety_actions_when_coordinator_role_reach_handler_checks(path, role):
    """
    Summary: Coordinators and the Lead get past the role check to submit, re-check or withdraw.
    AC1: Given an authenticated user is permitted to modify information based
        on their role and relationship to the event, when they make a valid
        change to that information, then the change is allowed.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub].
    """
    client = signed_in(create_app().test_client(), role=role)

    response = client.post(path, json={})

    assert response.status_code == 400
    assert "eventId" in response.json["message"]


# AC2 ----

@pytest.mark.parametrize("role", ["Safety Officer", "Venue Staff", "Technical Support", "Event Organiser", "Attendee"])
@pytest.mark.parametrize("path", COORDINATOR_ROUTES, ids=["submit", "resubmit", "recheck", "withdraw_for_venue_change", "restore_after_venue_change"])
def test_safety_actions_when_not_coordinator_return_403(path, role):
    """
    Summary: Every other role is refused submitting, re-checking or withdrawing.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: None
    """
    client = create_app().test_client()

    response = client.post(path, json={}, headers=bearer(OFFICER_ID, role))

    assert response.status_code == 403
    assert response.json["message"] == "Your role cannot change this information."


# AC4 ----

def test_queue_after_refused_submission_still_viewable_by_officer(monkeypatch):
    """
    Summary: A Safety Officer refused a submission can still see their queue.
    AC4: Given a user is permitted to view particular information but is not
        permitted to modify it, when they attempt to change that information,
        then the modification is prevented while their permitted viewing access
        remains unaffected.
    Double: Event Service and the other services hold what the queue needs
        [Stub].
    """
    monkeypatch.setattr(clients, "list_events_by_status", lambda status, viewer_role: [])
    monkeypatch.setattr(clients, "list_venues", lambda: [])
    officer = signed_in(create_app().test_client(), OFFICER_ID, "Safety Officer")

    before = officer.get("/safety-checks/queue")
    refused = officer.post("/safety-checks", json={})

    after = officer.get("/safety-checks/queue")

    assert (before.status_code, refused.status_code, after.status_code) == (200, 403, 200)
    assert before.json == after.json
