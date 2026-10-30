"""SCRUM-9 Role-based viewing control for events: Coordinator Assignment unit tests.

Story:      As a registered user, I want to view only information appropriate to my
            role and relationship to an event, so that I can access the information
            relevant to my responsibilities without viewing restricted information.
Real:       Flask app, GET /coordinators, /queue and /workload routes, token verification
            and the role check (the role is the token's, not a User Service lookup).
Doubled:    the downstream coordinator and event lookups.
Not proven: Event Service's own visibility rules. Assigning a coordinator is not
            covered here (SCRUM-10).

AC1  Given an authenticated user is permitted to view information based on their role and
     relationship to the event, when they access that information, then the information
     is made available to them.
AC2  Given an authenticated user's role does not permit them to view particular information,
     when they attempt to access that information, then access is denied.
AC3  Not covered here: these views are role-only; no per-event relationship applies.
AC4  Not covered here: same reason as AC3.
AC5  Given two authenticated users have different roles or relationships to the same event,
     when they access information relating to that event, then each user can only view the
     information permitted by their own role and relationship to the event.
"""
from unittest.mock import patch

import pytest

from app import create_app
from tests.unit.factories import bearer

VIEWS = ["/coordinators", "/queue", "/workload"]


@pytest.fixture(autouse=True)
def downstream():
    with patch("app.routes.get_available_coordinators", return_value=[]), \
         patch("app.routes.get_assignment_events", return_value=[]), \
         patch("app.routes.get_active_events", return_value=[]):
        yield


def get(path, role):
    return create_app().test_client().get(path, headers=bearer("user-1", role))


# AC1 ----

@pytest.mark.parametrize("path", VIEWS)
def test_ac1_lead_can_view_coordinators_queue_and_workload(path):
    """Normal: assignment is the Lead's job, so the Lead sees all three."""
    assert get(path, "Event Coordinator Lead").status_code == 200


# AC2 ----

@pytest.mark.parametrize("path", VIEWS)
@pytest.mark.parametrize("role", ["Event Coordinator", "Event Organiser", "Attendee"])
def test_ac2_other_roles_cannot_view_coordinators_queue_or_workload(path, role):
    """Failure: coordinator lists and the assignment queue are the Lead's alone."""
    assert get(path, role).status_code == 403


# AC5 ----

def test_ac5_lead_and_coordinator_get_different_answers_for_the_same_queue():
    """Conflict: two users, one queue, only the Lead may open it."""
    assert (get("/queue", "Event Coordinator Lead").status_code, get("/queue", "Event Coordinator").status_code) == (200, 403)


def test_coordinator_lookup_failure_is_an_error_not_an_empty_list():
    """Failure: if the pool cannot be read the Lead sees an error, not 'no coordinators'."""
    with patch("app.routes.get_available_coordinators", side_effect=Exception("User Service down")):
        response = get("/coordinators", "Event Coordinator Lead")

    assert response.status_code == 500
