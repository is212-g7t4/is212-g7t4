"""SCRUM-112 Assign Event Coordinator to Submitted Event: integration tests.

Story:      As an Event Coordinator Lead, I want to assign an Event Coordinator to a
            submitted event, so that the event has a main internal point of contact.
Real:       Flask app, role checks, assignment orchestration, error translation, and the
            real httpx calls in app/clients.py.
Doubled:    User Service and Event Service at their HTTP boundaries with respx, using the
            URLs frozen in app.clients.
Not proven: User/Event database persistence, Supabase sign-in itself (the Lead is a token
            signed with a test key, SCRUM-8), or the frontend; those belong to the atomic
            integration and browser/e2e tiers.

AC1  The Lead sees submitted requests with event name, organiser, proposed date, and
     Assigned/Unassigned state.
AC2  Assigning an available coordinator records the Lead, coordinator and timestamp.
AC3  Reassignment replaces the coordinator and reflects the newly assigned coordinator.

"""

import json

import httpx
import pytest
import respx
from httpx import Response

import app.clients as service_clients
from tests.unit.factories import bearer
from tests.integration.factories import (
    COORDINATOR_ID,
    EVENT_ID,
    LEAD_ID,
    OTHER_COORDINATOR_ID,
    event,
    lead,
    user,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

ASSIGNED_AT = "2030-02-01T10:05:00+00:00"


def stub_acting_user(router, payload=None, status_code=200):
    return router.get(f"{service_clients.USER_SERVICE_URL}/users/{LEAD_ID}").mock(
        return_value=Response(status_code, json=payload if payload is not None else lead())
    )


def stub_coordinator_pool(router):
    lead_route = router.get(
        f"{service_clients.USER_SERVICE_URL}/users",
        params={"role": "Event Coordinator Lead"},
    ).mock(return_value=Response(200, json={"users": [lead()]}))
    coordinator_route = router.get(
        f"{service_clients.USER_SERVICE_URL}/users",
        params={"role": "Event Coordinator"},
    ).mock(return_value=Response(200, json={
        "users": [
            user(),
            user(OTHER_COORDINATOR_ID, username="Coordinator Two"),
        ]
    }))
    return lead_route, coordinator_route


def stub_assignment(router, coordinator_id, payload=None, status_code=200):
    return router.patch(f"{service_clients.EVENT_SERVICE_URL}/events/{EVENT_ID}").mock(
        return_value=Response(
            status_code,
            json=payload if payload is not None else event(
                status="Under Review",
                coordinatorId=coordinator_id,
                assignedBy=LEAD_ID,
                assignedAt=ASSIGNED_AT,
            ),
        )
    )


# AC1 ---------------------------------------------------------------------


def test_ac1_lead_sees_assigned_and_unassigned_submitted_requests(client):
    """Normal: one worklist preserves every field needed for assignment decisions."""
    unassigned = event()
    assigned = event(
        id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        eventName="Innovation Expo",
        status="Under Review",
        coordinatorId=COORDINATOR_ID,
    )
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        event_route = router.get(
            f"{service_clients.EVENT_SERVICE_URL}/events/submitted",
            params={"viewerRole": "Event Coordinator Lead"},
        ).mock(return_value=Response(200, json={"events": [unassigned, assigned]}))

        response = client.get("/queue")

    assert response.status_code == 200
    assert response.get_json()["events"] == [unassigned, assigned]
    assert event_route.call_count == 1


def test_ac1_non_lead_is_forbidden_before_event_service_is_called(client):
    """Failure: a coordinator cannot read the Manager's assignment worklist."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True):
        # SCRUM-9: the role is the token's; no User Service call is made.
        response = client.get("/queue", headers=bearer(LEAD_ID, "Event Coordinator"))

    assert response.status_code == 403
    assert "Lead" in response.get_json()["error"]


def test_ac1_event_service_outage_is_not_reported_as_an_empty_worklist(client):
    """Failure: a downstream outage produces an error, never a false empty list."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        router.get(
            f"{service_clients.EVENT_SERVICE_URL}/events/submitted",
            params={"viewerRole": "Event Coordinator Lead"},
        ).mock(return_value=Response(503, json={"message": "Event Service unavailable"}))

        response = client.get("/queue")

    assert response.status_code == 500
    assert "Failed to fetch assignment events" in response.get_json()["error"]


# AC2 ---------------------------------------------------------------------


def test_ac2_available_coordinator_and_lead_identity_are_forwarded_once(client):
    """Normal: assignment sends the selected coordinator, and the acting Lead's token for auditing."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_acting_user(router)
        stub_coordinator_pool(router)
        assignment = stub_assignment(router, COORDINATOR_ID)

        response = client.post(
            f"/events/{EVENT_ID}/assign-coordinator/{COORDINATOR_ID}",
        )

    assert response.status_code == 200
    assert response.get_json()["coordinatorId"] == COORDINATOR_ID
    assert response.get_json()["assignedBy"] == LEAD_ID
    assert response.get_json()["assignedAt"] == ASSIGNED_AT
    assert assignment.call_count == 1
    assert json.loads(assignment.calls.last.request.content) == {"assignedCoordinatorId": COORDINATOR_ID}
    # SCRUM-8: the acting Lead reaches Event Service as their forwarded token.
    assert assignment.calls.last.request.headers["Authorization"] == client.environ_base["HTTP_AUTHORIZATION"]


def test_ac2_lead_can_assign_the_event_to_themselves(client):
    """Boundary: the Lead is intentionally part of the available coordinator pool."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_acting_user(router)
        stub_coordinator_pool(router)
        assignment = stub_assignment(router, LEAD_ID)

        response = client.post(
            f"/events/{EVENT_ID}/assign-coordinator/{LEAD_ID}",
        )

    assert response.status_code == 200
    assert response.get_json()["coordinatorId"] == LEAD_ID
    assert json.loads(assignment.calls.last.request.content) == {"assignedCoordinatorId": LEAD_ID}


def test_ac2_unavailable_coordinator_is_refused_before_event_service_is_called(client):
    """Failure: an unknown coordinator cannot be assigned to an event."""
    unavailable_id = "99999999-9999-4999-8999-999999999999"
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_acting_user(router)
        stub_coordinator_pool(router)

        response = client.post(
            f"/events/{EVENT_ID}/assign-coordinator/{unavailable_id}",
        )

    assert response.status_code == 404
    assert "not available" in response.get_json()["error"]


# AC3 ---------------------------------------------------------------------


def test_ac3_reassignment_replaces_the_coordinator_and_returns_the_handover(client):
    """Normal: reassignment returns the new coordinator and latest previous coordinator."""
    reassigned = event(
        status="Under Review",
        coordinatorId=OTHER_COORDINATOR_ID,
        previousCoordinatorId=COORDINATOR_ID,
        assignedBy=LEAD_ID,
        assignedAt=ASSIGNED_AT,
    )
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_acting_user(router)
        stub_coordinator_pool(router)
        assignment = stub_assignment(router, OTHER_COORDINATOR_ID, reassigned)

        response = client.post(
            f"/events/{EVENT_ID}/assign-coordinator/{OTHER_COORDINATOR_ID}",
        )

    assert response.status_code == 200
    assert response.get_json()["coordinatorId"] == OTHER_COORDINATOR_ID
    assert response.get_json()["previousCoordinatorId"] == COORDINATOR_ID
    assert response.get_json()["assignedBy"] == LEAD_ID
    assert json.loads(assignment.calls.last.request.content) == {"assignedCoordinatorId": OTHER_COORDINATOR_ID}


def test_ac3_same_coordinator_conflict_is_passed_back_unchanged(client):
    """Conflict: Event Service's no-change refusal remains a visible 409."""
    message = "That coordinator is already assigned to this event. No change was made."
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_acting_user(router)
        stub_coordinator_pool(router)
        stub_assignment(router, COORDINATOR_ID, {"message": message}, status_code=409)

        response = client.post(
            f"/events/{EVENT_ID}/assign-coordinator/{COORDINATOR_ID}",
        )

    assert response.status_code == 409
    assert response.get_json() == {"error": message}


@pytest.mark.parametrize(
    "outcome",
    [Response(503, json={"message": "Event Service unavailable"}), httpx.ConnectTimeout("timed out")],
    ids=["event-service-503", "event-service-timeout"],
)
def test_ac3_event_service_failure_never_reports_a_successful_reassignment(client, outcome):
    """Failure: a failed handover returns 500 rather than a false reassignment."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_acting_user(router)
        stub_coordinator_pool(router)
        route = router.patch(f"{service_clients.EVENT_SERVICE_URL}/events/{EVENT_ID}")
        if isinstance(outcome, Exception):
            route.mock(side_effect=outcome)
        else:
            route.mock(return_value=outcome)

        response = client.post(
            f"/events/{EVENT_ID}/assign-coordinator/{OTHER_COORDINATOR_ID}",
        )

    assert response.status_code == 500
    assert "Failed to assign coordinator to event" in response.get_json()["error"]
