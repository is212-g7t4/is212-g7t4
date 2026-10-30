"""
SCRUM-161: View Coordinator Assignments and Active Events

User Story
----------
As an Event Coordinator Lead, I want to view all coordinator assignments and
active events under my supervision, so that I can balance workload and decide
when to reassign.

Acceptance Criteria
-------------------
AC1: Lead sees every Event Coordinator with the active events currently
     assigned to them
AC2: Each event shows: name, organiser, date/time, current status
AC3: Unassigned events are visible and clearly marked as unassigned
AC4: Confirmed, cancelled and rejected events are excluded
AC5: The view is read-only: event details cannot be edited from it
AC6: Only the Lead can access this view

SCRUM-8: User Authentication and Authorization

User Story
----------
As a system user, I want to securely access the system, so that I can use the
information and functionality available to me.

Acceptance Criteria
-------------------
AC1: Given a system user has not been successfully authenticated, when they
     attempt to access protected information or functionality, then access is
     denied.
AC2: Given a system user successfully authenticates, when they access protected
     information or functionality, then their access is evaluated according to
     their role and relationship to the relevant event.
AC3: Given a system user's authentication attempt is unsuccessful, when the
     authentication attempt is completed, then they remain unable to access
     protected information or functionality.

Real
----
- GET /workload: the signed-in and Lead checks and the grouping of active
  events by coordinator (assigned, unassigned, coordinator no longer listed)
  run for real, as does get_active_events().
- Assertions are on the grouped response and on Event Service not being asked
  when the caller may not see the view.

Doubled
-------
- get_available_coordinators, get_active_events: Stub - canned pool and events
  (or raise); get_active_events is a Mock where the test asserts it is not
  called.
- httpx.get (client test): Stub - canned Event Service reply.

Not proven
----------
- That Event Service's /events/active excludes Confirmed, Cancelled and
  Rejected events and carries organiser, date/time and status (AC2, AC4) (->
  event-service unit tests for SCRUM-161).
- That the page is read-only (AC5) (-> frontend
  CoordinatorWorkloadPage.test.tsx).
"""

from unittest.mock import Mock

import httpx
import pytest

from app import clients, create_app
from tests.unit.factories import COORDINATOR, LEAD, as_lead, bearer


def workload(headers=None):
    return create_app().test_client().get("/workload", headers=as_lead() if headers is None else headers)


def test_workload_when_lead_lists_every_coordinator_with_their_events(downstream):
    """
    Summary: The Lead sees every coordinator, themselves included, with their active events, and unassigned events apart.
    AC1: Lead sees every Event Coordinator with the active events currently
        assigned to them
    AC3: Unassigned events are visible and clearly marked as unassigned
    Double: Stub (pool of Lead and coordinator; one assigned and one unassigned
        event)
    """
    downstream.coordinators.return_value = [LEAD, COORDINATOR]
    assigned = {"id": "EVT-001", "coordinatorId": "user-coordinator", "status": "Under Review"}
    unassigned = {"id": "EVT-002", "coordinatorId": None, "status": "Submitted"}
    downstream.active.return_value = [assigned, unassigned]

    response = workload()

    assert response.status_code == 200
    assert response.json == {
        "coordinators": [{**LEAD, "events": []}, {**COORDINATOR, "events": [assigned]}],
        "unassigned": [unassigned],
        "otherAssigned": [],
    }


def test_workload_when_coordinator_no_longer_listed_keeps_event_visible(downstream):
    """
    Summary: An event whose coordinator left the pool still shows up instead of disappearing.
    AC1: Lead sees every Event Coordinator with the active events currently
        assigned to them
    Double: Stub (event assigned to a user outside the pool)
    """
    downstream.coordinators.return_value = [COORDINATOR]
    orphan = {"id": "EVT-003", "coordinatorId": "user-gone", "status": "Approved"}
    downstream.active.return_value = [orphan]

    response = workload()

    assert response.status_code == 200
    assert response.json["otherAssigned"] == [orphan]
    assert response.json["coordinators"] == [{**COORDINATOR, "events": []}]


@pytest.mark.parametrize("role", ["Event Coordinator", "Event Organiser", "Attendee"], ids=["event_coordinator", "event_organiser", "attendee"])
def test_workload_when_role_not_lead_returns_403_without_fetching(downstream, role):
    """
    Summary: Only the Lead can open the workload view.
    AC6: Only the Lead can access this view
    Double: Mock (get_active_events not called)
    """
    response = workload(headers=bearer("someone", role))

    assert response.status_code == 403
    downstream.active.assert_not_called()


def test_workload_without_token_returns_401(downstream):
    """
    Summary: Nobody can open the workload view without signing in.
    SCRUM-8 AC1: Given a system user has not been successfully authenticated,
        when they attempt to access protected information or functionality,
        then access is denied.
    Double: None
    """
    # Arrange (Given): downstream, from fixtures

    # Act (When)
    response = create_app().test_client().get("/workload")

    # Assert (Then)
    assert response.status_code == 401


def test_workload_when_event_service_fails_returns_500(downstream):
    """
    Summary: If active events cannot be read, the Lead sees an error rather than an empty workload.
    AC1: Lead sees every Event Coordinator with the active events currently
        assigned to them
    Double: Stub (get_active_events raises)
    """
    downstream.coordinators.return_value = [COORDINATOR]
    downstream.active.side_effect = Exception("Event Service down")

    response = workload()

    assert response.status_code == 500
    assert "Failed to fetch coordinator workload" in response.json["error"]


def test_active_events_when_fetched_come_from_event_service(monkeypatch):
    """
    Summary: Active events come from Event Service's active-events list.
    AC1: Lead sees every Event Coordinator with the active events currently
        assigned to them
    Double: Stub (httpx.get returns one event)
    """
    get = Mock(return_value=httpx.Response(200, json={"events": [{"id": "evt-1"}]}, request=httpx.Request("GET", "http://e.test")))
    monkeypatch.setattr(clients.httpx, "get", get)

    assert clients.get_active_events() == [{"id": "evt-1"}]
    assert get.call_args.args[0] == f"{clients.EVENT_SERVICE_URL}/events/active"
