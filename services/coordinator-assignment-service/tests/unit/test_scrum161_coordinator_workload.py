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

Real
----
- GET /workload: the signed-in and Lead checks, the grouping of active events
  by coordinator (assigned, unassigned, coordinator no longer listed), the
  events passed through unchanged (AC2), and the refusal of write methods
  (AC5) run for real, as does get_active_events().
- Assertions are on the grouped response, on the status for write methods, and
  on Event Service not being asked when the caller may not see the view.

Doubled
-------
- get_available_coordinators, get_active_events: Stub - canned pool and events
  (or raise). The downstream fixture's get_active_events is also a Mock: the
  tests that refuse a caller (403, 405) assert it is not called.
- httpx.get (client test): Stub - canned Event Service reply.

Not proven
----------
- That Event Service's /events/active excludes Confirmed, Cancelled and
  Rejected events and carries organiser, date/time and status (AC2, AC4) (->
  event-service/tests/unit/test_scrum161_active_events.py). This file only proves that
  /workload passes through whatever events it is given.
- That the page itself shows no edit controls (AC5 in the UI) (-> frontend
  CoordinatorWorkloadPage.test.tsx). Here AC5 is only that the endpoint accepts
  no writes.
"""

from unittest.mock import Mock

import httpx
import pytest

from app import clients, create_app
from tests.unit.factories import COORDINATOR, LEAD, as_lead, bearer


def workload(headers=None):
    return create_app().test_client().get("/workload", headers=as_lead() if headers is None else headers)


def test_ac1_ac3_workload_when_lead_lists_every_coordinator_with_their_events(downstream):
    """
    Summary: GET /workload as the Lead returns every coordinator in the pool
        (the Lead included, with "events": []) with their own assigned events
        under "events", and an event with coordinatorId None under "unassigned".
    AC1: Lead sees every Event Coordinator with the active events currently
        assigned to them
    AC3: Unassigned events are visible and clearly marked as unassigned
    Double: Stub (get_available_coordinators returns [LEAD, COORDINATOR];
        get_active_events returns one event assigned to COORDINATOR and one with
        coordinatorId None)
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


def test_ac1_workload_when_coordinator_no_longer_listed_keeps_event_visible(downstream):
    """
    Summary: GET /workload as the Lead puts an event whose coordinatorId is not
        in the pool under "otherAssigned" and leaves it out of every
        coordinator's "events".
    AC1: Lead sees every Event Coordinator with the active events currently
        assigned to them
    Double: Stub (get_available_coordinators returns [COORDINATOR];
        get_active_events returns one event assigned to "user-gone")
    """
    downstream.coordinators.return_value = [COORDINATOR]
    orphan = {"id": "EVT-003", "coordinatorId": "user-gone", "status": "Approved"}
    downstream.active.return_value = [orphan]

    response = workload()

    assert response.status_code == 200
    assert response.json["otherAssigned"] == [orphan]
    assert response.json["coordinators"] == [{**COORDINATOR, "events": []}]


def test_ac2_workload_when_events_listed_keeps_name_organiser_date_time_and_status(downstream):
    """
    Summary: GET /workload as the Lead hands back an assigned event with its
        eventName, organiserId, preferredStartDate/EndDate and status exactly
        as Event Service sent them (no field dropped or renamed).
    AC2: Each event shows: name, organiser, date/time, current status
    Double: Stub (get_available_coordinators returns [COORDINATOR];
        get_active_events returns one fully populated event assigned to
        COORDINATOR)
    """
    downstream.coordinators.return_value = [COORDINATOR]
    event = {
        "id": "EVT-004",
        "eventName": "Community Workshop",
        "organiserId": "user-organiser",
        "preferredStartDate": "2030-03-01T09:00:00+08:00",
        "preferredEndDate": "2030-03-01T17:00:00+08:00",
        "status": "Under Review",
        "coordinatorId": "user-coordinator",
    }
    downstream.active.return_value = [event]

    response = workload()

    assert response.status_code == 200
    assert response.json["coordinators"][0]["events"] == [event]


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_ac5_workload_when_written_to_returns_405_without_fetching(downstream, method):
    """
    Summary: POST, PUT, PATCH and DELETE on /workload with a Lead token are each
        answered 405 and get_active_events is never called.
    AC5: The view is read-only: event details cannot be edited from it
    Double: Mock (get_active_events, via the downstream fixture, asserted not
        called); get_available_coordinators is stubbed but not asserted on
    """
    response = getattr(create_app().test_client(), method)("/workload", headers=as_lead(), json={"eventName": "Changed"})

    assert response.status_code == 405
    downstream.active.assert_not_called()


@pytest.mark.parametrize("role", ["Event Coordinator", "Event Organiser", "Attendee"], ids=["event_coordinator", "event_organiser", "attendee"])
def test_ac6_workload_when_role_not_lead_returns_403_without_fetching(downstream, role):
    """
    Summary: GET /workload with an Event Coordinator, Event Organiser or
        Attendee token is answered 403 {"error": "Only the Event Coordinator
        Lead can view coordinator workload"} and neither get_available_coordinators
        nor get_active_events is called.
    AC6: Only the Lead can access this view
    Double: Mock (get_available_coordinators and get_active_events, via the
        downstream fixture, asserted not called)
    """
    response = workload(headers=bearer("someone", role))

    assert response.status_code == 403
    assert response.json == {"error": "Only the Event Coordinator Lead can view coordinator workload"}
    downstream.coordinators.assert_not_called()
    downstream.active.assert_not_called()


def test_ac1_workload_when_event_service_fails_returns_500(downstream):
    """
    Summary: GET /workload as the Lead is answered 500 "Failed to fetch
        coordinator workload..." when get_active_events raises, instead of an
        empty workload.
    AC1: Lead sees every Event Coordinator with the active events currently
        assigned to them (error path: a failed read must not look like an empty
        workload)
    Double: Stub (get_available_coordinators returns [COORDINATOR];
        get_active_events raises Exception("Event Service down"))
    """
    downstream.coordinators.return_value = [COORDINATOR]
    downstream.active.side_effect = Exception("Event Service down")

    response = workload()

    assert response.status_code == 500
    assert "Failed to fetch coordinator workload" in response.json["error"]


def test_ac1_workload_when_pool_lookup_fails_returns_500(downstream):
    """
    Summary: GET /workload as the Lead is answered 500 "Failed to fetch
        coordinator workload..." when get_available_coordinators raises, instead
        of an empty workload.
    AC1: Lead sees every Event Coordinator with the active events currently
        assigned to them (error path: a failed read must not look like an empty
        workload)
    Double: Stub (get_available_coordinators raises Exception("User Service
        down"); get_active_events returns [])
    """
    downstream.coordinators.side_effect = Exception("User Service down")

    response = workload()

    assert response.status_code == 500
    assert "Failed to fetch coordinator workload" in response.json["error"]


@pytest.mark.parametrize(
    "event",
    [
        pytest.param({"id": "EVT-005", "coordinatorId": None, "status": "Submitted"}, id="coordinator_null"),
        pytest.param({"id": "EVT-005", "coordinatorId": "", "status": "Submitted"}, id="coordinator_blank"),
        pytest.param({"id": "EVT-005", "status": "Submitted"}, id="coordinator_missing"),
    ],
)
def test_ac3_workload_when_event_has_no_coordinator_value_lists_it_as_unassigned(downstream, event):
    """
    Summary: GET /workload as the Lead lists an event whose coordinatorId is
        null, "" or absent under "unassigned", not under any coordinator or
        "otherAssigned".
    AC3: Unassigned events are visible and clearly marked as unassigned
    Double: Stub (get_available_coordinators returns [COORDINATOR];
        get_active_events returns the one parametrised event)
    """
    downstream.coordinators.return_value = [COORDINATOR]
    downstream.active.return_value = [event]

    response = workload()

    assert response.status_code == 200
    assert response.json == {
        "coordinators": [{**COORDINATOR, "events": []}],
        "unassigned": [event],
        "otherAssigned": [],
    }


def test_ac1_active_events_when_fetched_come_from_event_service(monkeypatch):
    """
    Summary: clients.get_active_events() requests {EVENT_SERVICE_URL}/events/active
        and returns the "events" list from the reply.
    AC1: Lead sees every Event Coordinator with the active events currently
        assigned to them
    Double: Stub (httpx.get is replaced with a canned 200 reply holding one
        event; the URL it was called with is inspected)
    """
    get = Mock(return_value=httpx.Response(200, json={"events": [{"id": "evt-1"}]}, request=httpx.Request("GET", "http://e.test")))
    monkeypatch.setattr(clients.httpx, "get", get)

    assert clients.get_active_events() == [{"id": "evt-1"}]
    assert get.call_args.args[0] == f"{clients.EVENT_SERVICE_URL}/events/active"
