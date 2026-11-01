"""
SCRUM-160: Reassign an Event

User Story
----------
As an Event Coordinator Lead, I want to reassign an event to a different
coordinator, so that work can move when responsibilities or availability
change.

Acceptance Criteria
-------------------
AC1: Given an event with an assigned coordinator that is not completed or
     rejected, when the Lead selects a different coordinator and confirms:
     - the new coordinator replaces the previous one
     - the previous coordinator loses access to manage the event
     - the Lead, previous coordinator, new coordinator, and timestamp are
       recorded in the event's detail page
AC2: Given the Lead selects the current coordinator, then the system rejects it
     as no change.

Real
----
- POST /events/<id>/assign-coordinator/<coordinator> for an already assigned
  event: the Lead check, pool check and the mapping of Event Service's refusals
  (status kept, message passed through) run for real.
- Assertions are on the status and message the Lead sees.

Doubled
-------
- get_user, get_available_coordinators: Stub - the acting Lead and pool.
- assign_event_coordinator: Mock / Stub - asserted on for the successful
  reassignment; raises Event Service's HTTPStatusError for refusals.

Not proven
----------
- That Event Service refuses "no change" and closed events, and that the
  previous coordinator loses access (-> event-service unit tests for SCRUM-160
  and integration test test_coordinator_assignment.py).
- That the Lead, previous and new coordinator and timestamp show on the event's
  detail page (-> frontend ReassignCoordinatorPanel.test.tsx).
"""

import httpx
import pytest

from app import create_app
from tests.unit.factories import COORDINATOR, LEAD, SECOND_COORDINATOR, as_lead


def reassign(coordinator_id="user-coordinator"):
    return create_app().test_client().post(
        f"/events/EVT-001/assign-coordinator/{coordinator_id}", headers=as_lead()
    )


def event_service_refusal(status, body=None, text=None):
    request = httpx.Request("PATCH", "http://event.test/events/EVT-001")
    response = httpx.Response(status, json=body, request=request) if text is None else httpx.Response(
        status, text=text, request=request
    )
    return httpx.HTTPStatusError("refused", request=request, response=response)


def test_reassign_when_lead_picks_different_coordinator_saves_new_coordinator(downstream):
    """
    Summary: POST assign-coordinator as the Lead for "user-456" (in the pool) on
        an event already assigned to another coordinator is answered 200 with
        exactly what assign_event_coordinator returned, including the
        previousCoordinatorId, assignedBy and assignedAt Event Service adds on a
        reassignment, and calls it once with ("EVT-001", "user-456").
    AC1 (bullets 1 and 3, pass-through only): the new coordinator replaces the
        previous one, and the Lead, previous coordinator and timestamp reach the
        caller as Event Service reports them. That Event Service really records
        them, and that the previous coordinator loses access, are not proven
        here.
    Double: Stub (get_user returns LEAD; get_available_coordinators returns
        [COORDINATOR, SECOND_COORDINATOR]), Mock (assign_event_coordinator
        returns a reassignment result and is asserted called once)
    """
    # Arrange (Given)
    downstream.get_user.return_value = LEAD
    downstream.coordinators.return_value = [COORDINATOR, SECOND_COORDINATOR]
    reassigned = {
        "eventId": "EVT-001",
        "assignedCoordinatorId": "user-456",
        "previousCoordinatorId": "user-coordinator",
        "assignedBy": "user-lead",
        "assignedAt": "2030-03-01T09:00:00+08:00",
    }
    downstream.assign.return_value = reassigned

    # Act (When)
    response = reassign("user-456")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json == reassigned
    downstream.assign.assert_called_once_with("EVT-001", "user-456")


@pytest.mark.parametrize("status,message", [
    (409, "That coordinator is already assigned to this event. No change was made."),
    (409, "A Cancelled event can't be reassigned."),
    (404, "Event request not found."),
], ids=["no_change", "cancelled_event", "unknown_event"])
def test_reassign_when_event_service_refuses_returns_its_status_and_message(downstream, status, message):
    """
    Summary: When assign_event_coordinator raises an Event Service 4xx refusal
        (409 no change, 409 Cancelled event, 404 unknown event), the Lead gets
        the same status and {"error": <Event Service's message>}.
    AC2: Given the Lead selects the current coordinator, then the system
        rejects it as no change. (case "no_change")
    AC1: only an event that is not completed or rejected can be reassigned.
        (case "cancelled_event"; "unknown_event" is the same pass-through and
        belongs to no AC)
    Double: Stub (get_user returns LEAD; get_available_coordinators returns
        [COORDINATOR]; assign_event_coordinator raises an httpx.HTTPStatusError
        carrying the parametrised status and {"message": ...})
    """
    # Arrange (Given)
    downstream.get_user.return_value = LEAD
    downstream.coordinators.return_value = [COORDINATOR]
    downstream.assign.side_effect = event_service_refusal(status, {"message": message})

    # Act (When)
    response = reassign()

    # Assert (Then)
    assert response.status_code == status
    assert response.json == {"error": message}


@pytest.mark.parametrize(
    "refusal_body",
    [
        pytest.param({"text": "not json"}, id="not_json"),
        pytest.param({"body": ["nope"]}, id="json_list"),
        pytest.param({"body": {}}, id="no_message_key"),
        pytest.param({"body": {"message": 5}}, id="message_not_a_string"),
        pytest.param({"body": {"message": ""}}, id="message_empty"),
    ],
)
def test_reassign_when_refusal_has_no_message_returns_fallback_message(downstream, refusal_body):
    """
    Summary: When Event Service refuses with 409 and a body that is not JSON, is
        a JSON list, has no "message", or has a "message" that is not a
        non-empty string, the Lead gets 409 and {"error": "Event Service refused
        the assignment."}, never an HTML error page or a non-string error.
    AC2: Given the Lead selects the current coordinator, then the system
        rejects it as no change. (a no-change refusal still reaches the Lead
        when Event Service gives no readable reason)
    Double: Stub (get_user returns LEAD; get_available_coordinators returns
        [COORDINATOR]; assign_event_coordinator raises an httpx.HTTPStatusError
        with status 409 and the parametrised body)
    """
    # Arrange (Given)
    downstream.get_user.return_value = LEAD
    downstream.coordinators.return_value = [COORDINATOR]
    downstream.assign.side_effect = event_service_refusal(409, **refusal_body)

    # Act (When)
    response = reassign()

    # Assert (Then)
    assert response.status_code == 409
    assert response.json == {"error": "Event Service refused the assignment."}


@pytest.mark.parametrize(
    "status, expected_status, expected_error",
    [
        (400, 400, "Refused by Event Service."),
        (499, 499, "Refused by Event Service."),
        (500, 500, "Failed to assign coordinator to event: refused"),
        (503, 500, "Failed to assign coordinator to event: refused"),
    ],
    ids=["lowest_refusal", "highest_refusal", "lowest_outage", "service_unavailable"],
)
def test_reassign_when_event_service_status_near_refusal_range_separates_refusal_from_outage(
    downstream, status, expected_status, expected_error
):
    """
    Summary: An Event Service status of 400 or 499 is passed to the Lead with
        {"error": <Event Service's message>}; a status of 500 or 503 becomes
        {"error": "Failed to assign coordinator to event: refused"} with status
        500 and the Event Service message is not shown. Checks both edges of
        the 4xx range and a typical outage.
    AC2 (mechanism, not the AC itself): the refusal a no-change attempt gets
        from Event Service is a 4xx and is passed through; boundary statuses
        400, 499 and 500.
    AC1 (bullet 1 only; error path, cases "lowest_outage" and
        "service_unavailable"): a reassignment is not reported as done, or as a
        refusal, when Event Service is down.
    Double: Stub (get_user returns LEAD; get_available_coordinators returns
        [COORDINATOR]; assign_event_coordinator raises an httpx.HTTPStatusError
        with the parametrised status and {"message": "Refused by Event
        Service."})
    """
    # Arrange (Given)
    downstream.get_user.return_value = LEAD
    downstream.coordinators.return_value = [COORDINATOR]
    downstream.assign.side_effect = event_service_refusal(status, {"message": "Refused by Event Service."})

    # Act (When)
    response = reassign()

    # Assert (Then)
    assert response.status_code == expected_status
    assert response.json == {"error": expected_error}
