"""
SCRUM-158: View Unassigned Event Queue

User Story
----------
As an Event Coordinator Lead, I want to view a queue of submitted event
requests that have not yet been assigned, so that I can see which requests need
a coordinator.

Acceptance Criteria
-------------------
AC1: Queue shows only submitted events with no assigned coordinator
AC2: Each entry shows: event name, organiser name, proposed date/time, expected
     attendance, submission date
AC3: An event leaves the queue once a coordinator is assigned
AC4: Event Coordinators and other roles cannot access the queue

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
- GET /queue: the signed-in check, the role check (taken from the token) and
  the error mapping run for real, as does get_assignment_events().
- Assertions are on the status, the events returned and whether Event Service
  is asked at all.

Doubled
-------
- get_assignment_events: Stub / Mock - returns canned events, raises, or is
  asserted not called when the caller may not see the queue.
- httpx.get (client test): Stub - canned Event Service reply; the URL and
  viewerRole parameter are inspected.

Not proven
----------
- That Event Service returns only submitted events with no coordinator, with
  organiser, date, attendance and submission date, and drops an event once
  assigned (AC1-AC3) (-> event-service unit tests for SCRUM-158).
- That the queue page renders each field (-> frontend e2e
  review-requests.spec.ts).
"""

from unittest.mock import Mock

import httpx
import pytest

from app import clients, create_app
from tests.unit.factories import as_lead, bearer


def test_queue_when_lead_returns_event_service_worklist(downstream):
    """
    Summary: The Lead sees the submitted requests Event Service lists for assignment.
    AC1: Queue shows only submitted events with no assigned coordinator
    Double: Mock (get_assignment_events returns two events and is called once)
    """
    downstream.queue.return_value = [
        {"id": "EVT-001", "coordinatorId": None, "status": "Submitted"},
        {"id": "EVT-002", "coordinatorId": "user-coordinator", "status": "Under Review"},
    ]

    response = create_app().test_client().get("/queue", headers=as_lead())

    assert response.status_code == 200
    assert response.json == {"events": [
        {"id": "EVT-001", "coordinatorId": None, "status": "Submitted"},
        {"id": "EVT-002", "coordinatorId": "user-coordinator", "status": "Under Review"},
    ]}
    downstream.queue.assert_called_once_with()


@pytest.mark.parametrize("role", ["Event Coordinator", "Event Organiser", "Attendee"], ids=["event_coordinator", "event_organiser", "attendee"])
def test_queue_when_role_not_lead_returns_403_without_fetching(downstream, role):
    """
    Summary: Coordinators, organisers and attendees cannot open the queue and no events are fetched for them.
    AC4: Event Coordinators and other roles cannot access the queue
    Double: Mock (get_assignment_events not called)
    """
    response = create_app().test_client().get("/queue", headers=bearer("someone", role))

    assert response.status_code == 403
    downstream.queue.assert_not_called()


def test_queue_without_token_returns_401(downstream):
    """
    Summary: Nobody can open the queue without signing in.
    SCRUM-8 AC1: Given a system user has not been successfully authenticated,
        when they attempt to access protected information or functionality,
        then access is denied.
    Double: None
    """
    # Arrange (Given): downstream, from fixtures

    # Act (When)
    response = create_app().test_client().get("/queue")

    # Assert (Then)
    assert response.status_code == 401


def test_queue_when_event_service_fails_returns_500(downstream):
    """
    Summary: If the queue cannot be read, the Lead sees an error rather than an empty queue.
    AC1: Queue shows only submitted events with no assigned coordinator
    Double: Stub (get_assignment_events raises)
    """
    downstream.queue.side_effect = Exception("Event Service down")

    response = create_app().test_client().get("/queue", headers=as_lead())

    assert response.status_code == 500
    assert "Failed to fetch assignment events" in response.json["error"]


def test_assignment_events_when_fetched_asks_event_service_for_lead_view(monkeypatch):
    """
    Summary: The queue is Event Service's submitted-request list, asked for in the Lead's view.
    AC1: Queue shows only submitted events with no assigned coordinator
    Double: Stub (httpx.get returns two events)
    """
    events = [
        {"id": "evt-1", "coordinatorId": None, "status": "Submitted"},
        {"id": "evt-2", "coordinatorId": "coord", "status": "Under Review"},
    ]
    get = Mock(return_value=httpx.Response(200, json={"events": events}, request=httpx.Request("GET", "http://e.test")))
    monkeypatch.setattr(clients.httpx, "get", get)

    assert clients.get_assignment_events() == events
    assert get.call_args.args[0] == f"{clients.EVENT_SERVICE_URL}/events/submitted"
    assert get.call_args.kwargs["params"] == {"viewerRole": "Event Coordinator Lead"}
