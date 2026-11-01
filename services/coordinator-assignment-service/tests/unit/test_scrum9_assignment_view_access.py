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
- GET /coordinators, /queue and /workload: token verification and the role
  check (the role is the token's, not a User Service lookup) run for real.
- Assertions are on the status each role gets, and on whether the downstream
  lookup was made.
- AC5 (different roles on the same view each get their own answer) is shown by
  the AC1 test (Lead gets 200) read together with the AC2 tests (every other
  role gets 403 on the same URLs); it has no separate test.

Doubled
-------
- get_available_coordinators, get_assignment_events, get_active_events: Stub
  (autouse `no_downstream_calls` over tests/conftest.py `downstream`) - each
  returns an empty list, so an allowed role gets 200 without User or Event
  Service. The AC2 tests also use them as Mocks, asserting they are not called.

Not proven
----------
- AC3 and AC4: these three views are role-only; no per-event relationship
  applies, so there is nothing to test here. Per-event visibility is Event
  Service's (-> event-service unit tests for SCRUM-9).
- That the UI hides the Lead's pages from other roles (-> frontend
  Navigation.test.tsx and e2e role-switching.spec.ts).
"""
import pytest

from app import create_app
from tests.unit.factories import bearer

VIEWS = ["/coordinators", "/queue", "/workload"]
LEAD_VIEW_REFUSALS = {
    "/queue": "Only the Event Coordinator Lead can view the unassigned queue",
    "/workload": "Only the Event Coordinator Lead can view coordinator workload",
}


@pytest.fixture(autouse=True)
def no_downstream_calls(downstream):
    """Every view answers from empty stubs; see tests/conftest.py."""
    return downstream


def get(path, role):
    return create_app().test_client().get(path, headers=bearer("user-1", role))


@pytest.mark.parametrize("path", VIEWS, ids=["coordinators", "queue", "workload"])
def test_assignment_views_when_lead_return_200(path):
    """
    Summary: GET /coordinators, /queue and /workload with an Event Coordinator
        Lead token are each answered 200.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: Stub (the autouse downstream fixture: get_available_coordinators,
        get_assignment_events and get_active_events all return [])
    """
    # Arrange (Given): path, from fixtures

    # Act + Assert (When / Then)
    assert get(path, "Event Coordinator Lead").status_code == 200


@pytest.mark.parametrize(
    "role",
    ["Event Coordinator", "Event Organiser", "Attendee", "Venue Staff", "Technical Support", "Safety Officer", None],
    ids=["coordinator", "organiser", "attendee", "venue_staff", "technical_support", "safety_officer", "no_role_claim"],
)
def test_get_coordinators_when_role_not_lead_returns_403(downstream, role):
    """
    Summary: GET /coordinators with a token whose role is Event Coordinator,
        Event Organiser, Attendee, Venue Staff, Technical Support, Safety
        Officer, or missing altogether is answered 403 {"error": "Only the Event
        Coordinator Lead can list coordinators"} and
        get_available_coordinators is never called.
    AC2: Given an authenticated user's role does not permit them to view
        particular information, when they attempt to access that information,
        then access is denied.
    Double: Mock (get_available_coordinators, via the downstream fixture,
        asserted not called)
    """
    # Arrange (Given): downstream, role, from fixtures

    # Act (When)
    response = get("/coordinators", role)

    # Assert (Then)
    assert response.status_code == 403
    assert response.json == {"error": "Only the Event Coordinator Lead can list coordinators"}
    downstream.coordinators.assert_not_called()


@pytest.mark.parametrize("path", ["/queue", "/workload"], ids=["queue", "workload"])
@pytest.mark.parametrize(
    "role",
    ["Venue Staff", "Technical Support", "Safety Officer", None],
    ids=["venue_staff", "technical_support", "safety_officer", "no_role_claim"],
)
def test_lead_views_when_role_not_lead_returns_403_without_fetching(downstream, path, role):
    """
    Summary: GET /queue and GET /workload with a Venue Staff, Technical
        Support, Safety Officer or missing-role token are each answered 403 with
        the route's own "Only the Event Coordinator Lead can …" message and
        no events are fetched. (Event Coordinator, Event Organiser and Attendee
        are covered for these two views by the SCRUM-158 and SCRUM-161 tests.)
    AC2: Given an authenticated user's role does not permit them to view
        particular information, when they attempt to access that information,
        then access is denied.
    Double: Mock (get_assignment_events and get_active_events, via the
        downstream fixture, asserted not called)
    """
    # Arrange (Given): downstream, path, role, from fixtures

    # Act (When)
    response = get(path, role)

    # Assert (Then)
    assert response.status_code == 403
    assert response.json == {"error": LEAD_VIEW_REFUSALS[path]}
    downstream.queue.assert_not_called()
    downstream.active.assert_not_called()
