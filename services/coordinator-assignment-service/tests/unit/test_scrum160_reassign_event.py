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
    Summary: The Lead can move an assigned event to a different coordinator.
    AC1: Given an event with an assigned coordinator that is not completed or
        rejected, when the Lead selects a different coordinator and confirms:
        - the new coordinator replaces the previous one
        - the previous coordinator loses access to manage the event
        - the Lead, previous coordinator, new coordinator, and timestamp are
          recorded in the event's detail page
    Double: Stub (acting Lead; pool of two), Mock (assign_event_coordinator)
    """
    # Arrange (Given)
    downstream.get_user.return_value = LEAD
    downstream.coordinators.return_value = [COORDINATOR, SECOND_COORDINATOR]
    downstream.assign.return_value = {"eventId": "EVT-001", "assignedCoordinatorId": "user-456"}

    # Act (When)
    response = reassign("user-456")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json == {"eventId": "EVT-001", "assignedCoordinatorId": "user-456"}
    downstream.assign.assert_called_once_with("EVT-001", "user-456")


@pytest.mark.parametrize("status,message", [
    (409, "That coordinator is already assigned to this event. No change was made."),
    (409, "A Cancelled event can't be reassigned."),
    (404, "Event request not found."),
], ids=["no_change", "cancelled_event", "unknown_event"])
def test_reassign_when_event_service_refuses_returns_its_status_and_message(downstream, status, message):
    """
    Summary: A no-change, closed-event or unknown-event refusal reaches the Lead with Event Service's status and reason.
    AC2: Given the Lead selects the current coordinator, then the system
        rejects it as no change.
    AC1: only an event that is not completed or rejected can be reassigned
    Double: Stub (assign_event_coordinator raises Event Service's refusal)
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


def test_reassign_when_refusal_has_no_message_returns_fallback_message(downstream):
    """
    Summary: A refusal without a readable reason still tells the Lead it was refused.
    AC2: Given the Lead selects the current coordinator, then the system
        rejects it as no change.
    Double: Stub (Event Service answers 409 with a non-JSON body)
    """
    # Arrange (Given)
    downstream.get_user.return_value = LEAD
    downstream.coordinators.return_value = [COORDINATOR]
    downstream.assign.side_effect = event_service_refusal(409, text="not json")

    # Act (When)
    response = reassign()

    # Assert (Then)
    assert response.status_code == 409
    assert response.json == {"error": "Event Service refused the assignment."}


def test_reassign_when_event_service_has_outage_returns_500(downstream):
    """
    Summary: An Event Service outage is reported as a failure, not as a refusal.
    AC1: Given an event with an assigned coordinator that is not completed or
        rejected, when the Lead selects a different coordinator and confirms:
        - the new coordinator replaces the previous one
        - the previous coordinator loses access to manage the event
        - the Lead, previous coordinator, new coordinator, and timestamp are
          recorded in the event's detail page
    Double: Stub (Event Service answers 503)
    """
    # Arrange (Given)
    downstream.get_user.return_value = LEAD
    downstream.coordinators.return_value = [COORDINATOR]
    downstream.assign.side_effect = event_service_refusal(503, {"message": "db down"})

    # Act (When)
    response = reassign()

    # Assert (Then)
    assert response.status_code == 500
    assert "Failed to assign coordinator to event" in response.json["error"]


@pytest.mark.parametrize(
    "status, expected_status, expected_error",
    [
        (400, 400, "Refused by Event Service."),
        (499, 499, "Refused by Event Service."),
        (500, 500, "Failed to assign coordinator to event: refused"),
    ],
    ids=["lowest_refusal", "highest_refusal", "lowest_outage"],
)
def test_reassign_when_event_service_status_near_refusal_range_separates_refusal_from_outage(
    downstream, status, expected_status, expected_error
):
    """
    Summary: Every 4xx from Event Service reaches the Lead as a refusal with its reason, and a 5xx as a failure.
    AC2: (boundary: Event Service status = 400, 499, 500)
    Double: Stub (assign_event_coordinator raises Event Service's
        HTTPStatusError)
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
