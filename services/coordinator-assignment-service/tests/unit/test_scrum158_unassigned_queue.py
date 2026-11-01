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

Real
----
- GET /queue: the Lead check (taken from the token) and the error mapping run
  for real, as does get_assignment_events().
- Assertions are on the status, the events returned and whether Event Service
  is asked at all.

Doubled
-------
- get_assignment_events: Stub / Mock - returns canned events, raises, or is
  asserted not called when the caller may not see the queue.
- httpx.get (client test): Stub - canned Event Service reply; the URL is
  inspected.

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
    Summary: GET /queue as the Lead returns, in the same order, the two
        Submitted events with no coordinator that get_assignment_events gives it,
        and asks for them once. The route does not filter, so which events
        qualify is Event Service's (-> its SCRUM-158 tests).
    AC1: Queue shows only submitted events with no assigned coordinator
    Double: Stub (get_assignment_events returns two Submitted events with
        coordinatorId None), asserted called once with no arguments
    """
    queue = [
        {"id": "EVT-001", "coordinatorId": None, "status": "Submitted"},
        {"id": "EVT-002", "coordinatorId": None, "status": "Submitted"},
    ]
    downstream.queue.return_value = queue

    response = create_app().test_client().get("/queue", headers=as_lead())

    assert response.status_code == 200
    assert response.json == {"events": queue}
    downstream.queue.assert_called_once_with()


def test_queue_when_lead_keeps_entry_fields_as_event_service_sent_them(downstream):
    """
    Summary: GET /queue as the Lead hands back a Submitted event with its
        eventName, organiserId, preferredStartDate/EndDate, expectedAttendance
        and submittedAt exactly as Event Service sent them (no field dropped or
        renamed).
    AC2: Each entry shows: event name, organiser name, proposed date/time,
        expected attendance, submission date (organiserId is passed through;
        turning it into a name is not done in this service)
    Double: Stub (get_assignment_events returns one fully populated Submitted
        event)
    """
    event = {
        "id": "EVT-010",
        "eventName": "Community Workshop",
        "organiserId": "user-organiser",
        "preferredStartDate": "2030-03-01T09:00:00+08:00",
        "preferredEndDate": "2030-03-01T17:00:00+08:00",
        "expectedAttendance": "40",
        "submittedAt": "2030-02-01T10:00:00+00:00",
        "coordinatorId": None,
        "status": "Submitted",
    }
    downstream.queue.return_value = [event]

    response = create_app().test_client().get("/queue", headers=as_lead())

    assert response.status_code == 200
    assert response.json == {"events": [event]}


@pytest.mark.parametrize("role", ["Event Coordinator", "Event Organiser", "Attendee"], ids=["event_coordinator", "event_organiser", "attendee"])
def test_queue_when_role_not_lead_returns_403_without_fetching(downstream, role):
    """
    Summary: GET /queue with an Event Coordinator, Event Organiser or Attendee
        token is answered 403 {"error": "Only the Event Coordinator Lead can
        view the unassigned queue"} and get_assignment_events is never called.
    AC4: Event Coordinators and other roles cannot access the queue
    Double: Mock (get_assignment_events, via the downstream fixture, asserted
        not called)
    """
    response = create_app().test_client().get("/queue", headers=bearer("someone", role))

    assert response.status_code == 403
    assert response.json == {"error": "Only the Event Coordinator Lead can view the unassigned queue"}
    downstream.queue.assert_not_called()


def test_queue_when_event_service_fails_returns_500(downstream):
    """
    Summary: GET /queue as the Lead is answered 500 "Failed to fetch assignment
        events..." when get_assignment_events raises, instead of an empty queue.
    AC1: Queue shows only submitted events with no assigned coordinator (error
        path: a failed read must not look like an empty queue)
    Double: Stub (get_assignment_events raises Exception("Event Service down"))
    """
    downstream.queue.side_effect = Exception("Event Service down")

    response = create_app().test_client().get("/queue", headers=as_lead())

    assert response.status_code == 500
    assert "Failed to fetch assignment events" in response.json["error"]


def test_assignment_events_when_fetched_asks_event_service_for_unassigned_events(monkeypatch):
    """
    Summary: clients.get_assignment_events() requests
        {EVENT_SERVICE_URL}/events/unassigned (not /events/submitted, which also
        lists assigned requests) and returns the "events" list from the reply.
    AC1: Queue shows only submitted events with no assigned coordinator (which
        events are listed is decided by Event Service, not proven here)
    Double: Stub (httpx.get is replaced with a canned 200 reply holding one
        Submitted event; the URL it was called with, and that it sent no query
        params, are inspected)
    """
    events = [{"id": "evt-1", "coordinatorId": None, "status": "Submitted"}]
    get = Mock(return_value=httpx.Response(200, json={"events": events}, request=httpx.Request("GET", "http://e.test")))
    monkeypatch.setattr(clients.httpx, "get", get)

    assert clients.get_assignment_events() == events
    assert get.call_args.args[0] == f"{clients.EVENT_SERVICE_URL}/events/unassigned"
    assert "params" not in get.call_args.kwargs
