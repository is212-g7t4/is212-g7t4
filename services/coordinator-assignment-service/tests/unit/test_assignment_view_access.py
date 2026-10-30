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
- Assertions are on the status each role gets.

Doubled
-------
- get_available_coordinators, get_assignment_events, get_active_events: Stub
  (tests/conftest.py `downstream`) - return empty lists, or raise for the
  lookup-failure test.

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


@pytest.fixture(autouse=True)
def no_downstream_calls(downstream):
    """Every view answers from empty stubs; see tests/conftest.py."""
    return downstream


def get(path, role):
    return create_app().test_client().get(path, headers=bearer("user-1", role))


@pytest.mark.parametrize("path", VIEWS, ids=["coordinators", "queue", "workload"])
def test_assignment_views_when_lead_return_200(path):
    """
    Summary: The Lead can open the coordinator list, the queue and the workload view.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: Stub (downstream lookups return empty lists)
    """
    # Arrange (Given): path, from fixtures

    # Act + Assert (When / Then)
    assert get(path, "Event Coordinator Lead").status_code == 200


@pytest.mark.parametrize("path", VIEWS, ids=["coordinators", "queue", "workload"])
@pytest.mark.parametrize("role", ["Event Coordinator", "Event Organiser", "Attendee"], ids=["coordinator", "organiser", "attendee"])
def test_assignment_views_when_role_not_lead_return_403(path, role):
    """
    Summary: Every other role is refused all three assignment views.
    AC2: Given an authenticated user's role does not permit them to view
        particular information, when they attempt to access that information,
        then access is denied.
    Double: Stub (downstream lookups return empty lists)
    """
    # Arrange (Given): path, role, from fixtures

    # Act + Assert (When / Then)
    assert get(path, role).status_code == 403


def test_queue_when_lead_and_coordinator_ask_answers_each_by_own_role():
    """
    Summary: The Lead and a coordinator asking for the same queue each get the answer their own role allows.
    AC5: Given two authenticated users have different roles or relationships to
        the same event, when they access information relating to that event,
        then each user can only view the information permitted by their own
        role and relationship to the event.
    Double: Stub (downstream lookups return empty lists)
    """
    # Act + Assert (When / Then)
    assert (get("/queue", "Event Coordinator Lead").status_code, get("/queue", "Event Coordinator").status_code) == (200, 403)


def test_get_coordinators_when_pool_lookup_fails_returns_500(downstream):
    """
    Summary: If the coordinator pool cannot be read, the Lead sees an error rather than an empty list.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: Stub (get_available_coordinators raises)
    """
    # Arrange (Given)
    downstream.coordinators.side_effect = Exception("User Service down")

    # Act (When)
    response = get("/coordinators", "Event Coordinator Lead")

    # Assert (Then)
    assert response.status_code == 500
