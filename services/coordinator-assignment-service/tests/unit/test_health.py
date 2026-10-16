from unittest.mock import patch

import httpx
import pytest

from app import create_app

LEAD = {"user_id": "user-lead", "username": "Alice Tan", "role": "Event Coordinator Lead"}
COORDINATOR = {"user_id": "user-coordinator", "username": "Marcus Lim", "role": "Event Coordinator"}


@patch("app.routes.get_available_coordinators")
def test_get_coordinators_returns_available_event_coordinators(mock_get_coordinators):
    """The service exposes the coordinator pool for assignment decisions."""
    mock_coordinators = [
        {"user_id": "user-123", "username": "Alice Tan", "role": "Event Coordinator"},
        {"user_id": "user-456", "username": "Marcus Lim", "role": "Event Coordinator"},
    ]
    mock_get_coordinators.return_value = mock_coordinators

    client = create_app().test_client()
    response = client.get("/coordinators")

    assert response.status_code == 200
    assert response.json == {"coordinators": mock_coordinators}
    mock_get_coordinators.assert_called_once()


@patch("app.routes.assign_event_coordinator")
@patch("app.routes.get_available_coordinators")
@patch("app.routes.get_user")
def test_assign_coordinator_success_for_new_assignment(mock_get_user, mock_get_coordinators, mock_assign):
    """The Event Coordinator Lead can assign a submitted event to a new Event Coordinator."""
    mock_get_user.return_value = LEAD
    mock_get_coordinators.return_value = [{"user_id": "user-123", "username": "Alice Tan", "role": "Event Coordinator"}]
    mock_assign.return_value = {"eventId": "EVT-001", "assignedCoordinatorId": "user-123"}

    client = create_app().test_client()
    response = client.post(
        "/events/EVT-001/assign-coordinator/user-123",
        json={"actingUserId": "user-lead"},
    )

    assert response.status_code == 200
    assert response.json == {"eventId": "EVT-001", "assignedCoordinatorId": "user-123"}
    mock_get_user.assert_called_once_with("user-lead")
    mock_assign.assert_called_once_with("EVT-001", "user-123", "user-lead")


@patch("app.routes.assign_event_coordinator")
@patch("app.routes.get_available_coordinators")
@patch("app.routes.get_user")
def test_assign_coordinator_success_for_reassignment(mock_get_user, mock_get_coordinators, mock_assign):
    """The Event Coordinator Lead can reassign an already-assigned event to a different Event Coordinator."""
    mock_get_user.return_value = LEAD
    mock_get_coordinators.return_value = [
        {"user_id": "user-123", "username": "Alice Tan", "role": "Event Coordinator"},
        {"user_id": "user-456", "username": "Marcus Lim", "role": "Event Coordinator"},
    ]
    mock_assign.return_value = {"eventId": "EVT-001", "assignedCoordinatorId": "user-456"}

    client = create_app().test_client()
    response = client.post(
        "/events/EVT-001/assign-coordinator/user-456",
        json={"actingUserId": "user-lead"},
    )

    assert response.status_code == 200
    assert response.json == {"eventId": "EVT-001", "assignedCoordinatorId": "user-456"}
    mock_assign.assert_called_once_with("EVT-001", "user-456", "user-lead")


@patch("app.routes.get_available_coordinators")
@patch("app.routes.get_user")
def test_assign_coordinator_rejects_unavailable_coordinator(mock_get_user, mock_get_coordinators):
    """Only known available coordinators can be assigned to an event."""
    mock_get_user.return_value = LEAD
    mock_get_coordinators.return_value = [{"user_id": "user-123", "username": "Alice Tan", "role": "Event Coordinator"}]

    client = create_app().test_client()
    response = client.post(
        "/events/EVT-001/assign-coordinator/user-999",
        json={"actingUserId": "user-lead"},
    )

    assert response.status_code == 404
    assert "not available" in response.json["error"]


@patch("app.routes.get_available_coordinators")
@patch("app.routes.get_user")
def test_assign_coordinator_handles_validation_error(mock_get_user, mock_get_coordinators):
    """Downstream coordinator validation failures are surfaced as service errors."""
    mock_get_user.return_value = LEAD
    mock_get_coordinators.side_effect = Exception("User Service error")

    client = create_app().test_client()
    response = client.post(
        "/events/EVT-001/assign-coordinator/user-123",
        json={"actingUserId": "user-lead"},
    )

    assert response.status_code == 500
    assert "Failed to validate coordinator" in response.json["error"]


def test_assign_coordinator_requires_acting_user_id():
    """actingUserId must be supplied so the Lead check has something to verify."""
    client = create_app().test_client()
    response = client.post("/events/EVT-001/assign-coordinator/user-123", json={})

    assert response.status_code == 400
    assert "actingUserId" in response.json["error"]


@patch("app.routes.get_user")
def test_assign_coordinator_rejects_non_lead(mock_get_user):
    """An Event Coordinator (not the Lead) cannot assign/reassign."""
    mock_get_user.return_value = COORDINATOR

    client = create_app().test_client()
    response = client.post(
        "/events/EVT-001/assign-coordinator/user-123",
        json={"actingUserId": "user-coordinator"},
    )

    assert response.status_code == 403
    assert "Lead" in response.json["error"]


@patch("app.routes.get_user")
def test_assign_coordinator_rejects_unknown_acting_user(mock_get_user):
    """An actingUserId that doesn't resolve to a real user is rejected."""
    mock_get_user.return_value = None

    client = create_app().test_client()
    response = client.post(
        "/events/EVT-001/assign-coordinator/user-123",
        json={"actingUserId": "does-not-exist"},
    )

    assert response.status_code == 403


@patch("app.routes.get_available_coordinators")
@patch("app.routes.get_user")
def test_assign_coordinator_handles_acting_user_lookup_error(mock_get_user, mock_get_coordinators):
    """Downstream acting-user validation failures are surfaced as service errors."""
    mock_get_user.side_effect = Exception("User Service unreachable")

    client = create_app().test_client()
    response = client.post(
        "/events/EVT-001/assign-coordinator/user-123",
        json={"actingUserId": "user-lead"},
    )

    assert response.status_code == 500
    assert "Failed to validate acting user" in response.json["error"]
    mock_get_coordinators.assert_not_called()


@patch("app.routes.assign_event_coordinator")
@patch("app.routes.get_available_coordinators")
@patch("app.routes.get_user")
def test_lead_can_assign_an_event_to_themselves(mock_get_user, mock_get_coordinators, mock_assign):
    """The Lead appears in the assignable pool, so self-assignment succeeds."""
    mock_get_user.return_value = LEAD
    mock_get_coordinators.return_value = [LEAD, COORDINATOR]
    mock_assign.return_value = {"eventId": "EVT-001", "assignedCoordinatorId": "user-lead"}

    client = create_app().test_client()
    response = client.post(
        "/events/EVT-001/assign-coordinator/user-lead",
        json={"actingUserId": "user-lead"},
    )

    assert response.status_code == 200
    mock_assign.assert_called_once_with("EVT-001", "user-lead", "user-lead")


ORGANISER = {"user_id": "user-organiser", "username": "Priya Nair", "role": "Event Organiser"}


@patch("app.routes.get_unassigned_events")
@patch("app.routes.get_user")
def test_lead_sees_the_unassigned_queue(mock_get_user, mock_get_unassigned):
    """The Lead gets the submitted events that still need a coordinator."""
    mock_get_user.return_value = LEAD
    mock_get_unassigned.return_value = [{"id": "EVT-001", "coordinatorId": None}]

    client = create_app().test_client()
    response = client.get("/queue?actingUserId=user-lead")

    assert response.status_code == 200
    assert response.json == {"events": [{"id": "EVT-001", "coordinatorId": None}]}
    mock_get_user.assert_called_once_with("user-lead")


@pytest.mark.parametrize("acting_user", [COORDINATOR, ORGANISER, None])
@patch("app.routes.get_unassigned_events")
@patch("app.routes.get_user")
def test_only_the_lead_can_see_the_queue(mock_get_user, mock_get_unassigned, acting_user):
    """Event Coordinators, other roles and unknown users get 403 and no events."""
    mock_get_user.return_value = acting_user

    client = create_app().test_client()
    response = client.get("/queue?actingUserId=someone")

    assert response.status_code == 403
    mock_get_unassigned.assert_not_called()


def test_queue_requires_acting_user_id():
    response = create_app().test_client().get("/queue")
    assert response.status_code == 400
    assert "actingUserId" in response.json["error"]


@patch("app.routes.get_user")
def test_queue_handles_acting_user_lookup_error(mock_get_user):
    mock_get_user.side_effect = Exception("User Service unreachable")
    response = create_app().test_client().get("/queue?actingUserId=user-lead")
    assert response.status_code == 500
    assert "Failed to validate acting user" in response.json["error"]


@patch("app.routes.get_unassigned_events")
@patch("app.routes.get_user")
def test_queue_handles_event_service_error(mock_get_user, mock_get_unassigned):
    mock_get_user.return_value = LEAD
    mock_get_unassigned.side_effect = Exception("Event Service down")
    response = create_app().test_client().get("/queue?actingUserId=user-lead")
    assert response.status_code == 500
    assert "Failed to fetch unassigned events" in response.json["error"]


@patch("app.routes.get_active_events")
@patch("app.routes.get_available_coordinators")
@patch("app.routes.get_user")
def test_lead_sees_every_coordinator_with_their_active_events(mock_get_user, mock_get_coordinators, mock_get_active):
    """Workload AC1/AC3: every coordinator (the Lead too, and those with no
    events) is listed with their active events; unassigned events are kept
    apart so they're clearly marked."""
    mock_get_user.return_value = LEAD
    mock_get_coordinators.return_value = [LEAD, COORDINATOR]
    assigned = {"id": "EVT-001", "coordinatorId": "user-coordinator", "status": "Under Review"}
    unassigned = {"id": "EVT-002", "coordinatorId": None, "status": "Submitted"}
    mock_get_active.return_value = [assigned, unassigned]

    response = create_app().test_client().get("/workload?actingUserId=user-lead")

    assert response.status_code == 200
    assert response.json == {
        "coordinators": [{**LEAD, "events": []}, {**COORDINATOR, "events": [assigned]}],
        "unassigned": [unassigned],
        "otherAssigned": [],
    }
    mock_get_user.assert_called_once_with("user-lead")


@patch("app.routes.get_active_events")
@patch("app.routes.get_available_coordinators")
@patch("app.routes.get_user")
def test_workload_keeps_events_whose_coordinator_is_no_longer_listed(mock_get_user, mock_get_coordinators, mock_get_active):
    """An event assigned to someone who's no longer an Event Coordinator still shows up."""
    mock_get_user.return_value = LEAD
    mock_get_coordinators.return_value = [COORDINATOR]
    orphan = {"id": "EVT-003", "coordinatorId": "user-gone", "status": "Approved"}
    mock_get_active.return_value = [orphan]

    response = create_app().test_client().get("/workload?actingUserId=user-lead")

    assert response.status_code == 200
    assert response.json["otherAssigned"] == [orphan]
    assert response.json["coordinators"] == [{**COORDINATOR, "events": []}]


@pytest.mark.parametrize("acting_user", [COORDINATOR, ORGANISER, None])
@patch("app.routes.get_active_events")
@patch("app.routes.get_user")
def test_only_the_lead_can_see_the_workload(mock_get_user, mock_get_active, acting_user):
    """Workload AC6: Event Coordinators, other roles and unknown users get 403 and no events."""
    mock_get_user.return_value = acting_user
    response = create_app().test_client().get("/workload?actingUserId=someone")
    assert response.status_code == 403
    mock_get_active.assert_not_called()


def test_workload_requires_acting_user_id():
    response = create_app().test_client().get("/workload")
    assert response.status_code == 400
    assert "actingUserId" in response.json["error"]


@patch("app.routes.get_user")
def test_workload_handles_acting_user_lookup_error(mock_get_user):
    mock_get_user.side_effect = Exception("User Service unreachable")
    response = create_app().test_client().get("/workload?actingUserId=user-lead")
    assert response.status_code == 500
    assert "Failed to validate acting user" in response.json["error"]


@patch("app.routes.get_active_events")
@patch("app.routes.get_available_coordinators")
@patch("app.routes.get_user")
def test_workload_handles_downstream_error(mock_get_user, mock_get_coordinators, mock_get_active):
    mock_get_user.return_value = LEAD
    mock_get_coordinators.return_value = [COORDINATOR]
    mock_get_active.side_effect = Exception("Event Service down")
    response = create_app().test_client().get("/workload?actingUserId=user-lead")
    assert response.status_code == 500
    assert "Failed to fetch coordinator workload" in response.json["error"]


@patch("app.routes.assign_event_coordinator")
@patch("app.routes.get_available_coordinators")
@patch("app.routes.get_user")
def test_assign_coordinator_handles_event_service_error(mock_get_user, mock_get_coordinators, mock_assign):
    """If Event Service can't save the assignment, the Lead gets an error, not a false success."""
    mock_get_user.return_value = LEAD
    mock_get_coordinators.return_value = [COORDINATOR]
    mock_assign.side_effect = Exception("Event Service down")

    response = create_app().test_client().post(
        "/events/EVT-001/assign-coordinator/user-coordinator",
        json={"actingUserId": "user-lead"},
    )

    assert response.status_code == 500
    assert "Failed to assign coordinator to event" in response.json["error"]


def event_service_refusal(status, body):
    request = httpx.Request("PATCH", "http://event.test/events/EVT-001")
    response = httpx.Response(status, json=body, request=request)
    return httpx.HTTPStatusError("refused", request=request, response=response)


@pytest.mark.parametrize("status,message", [
    (409, "That coordinator is already assigned to this event. No change was made."),
    (409, "A Cancelled event can't be reassigned."),
    (404, "Event request not found."),
])
@patch("app.routes.assign_event_coordinator")
@patch("app.routes.get_available_coordinators")
@patch("app.routes.get_user")
def test_reassign_passes_event_service_refusals_to_the_lead(
    mock_get_user, mock_get_coordinators, mock_assign, status, message
):
    """Reassignment: no-change and closed-event refusals keep their status and message."""
    mock_get_user.return_value = LEAD
    mock_get_coordinators.return_value = [COORDINATOR]
    mock_assign.side_effect = event_service_refusal(status, {"message": message})

    response = create_app().test_client().post(
        "/events/EVT-001/assign-coordinator/user-coordinator",
        json={"actingUserId": "user-lead"},
    )

    assert response.status_code == status
    assert response.json == {"error": message}


@patch("app.routes.assign_event_coordinator")
@patch("app.routes.get_available_coordinators")
@patch("app.routes.get_user")
def test_reassign_refusal_without_a_message_gets_a_fallback(mock_get_user, mock_get_coordinators, mock_assign):
    mock_get_user.return_value = LEAD
    mock_get_coordinators.return_value = [COORDINATOR]
    request = httpx.Request("PATCH", "http://event.test/events/EVT-001")
    mock_assign.side_effect = httpx.HTTPStatusError(
        "refused", request=request, response=httpx.Response(409, text="not json", request=request))

    response = create_app().test_client().post(
        "/events/EVT-001/assign-coordinator/user-coordinator",
        json={"actingUserId": "user-lead"},
    )

    assert response.status_code == 409
    assert response.json == {"error": "Event Service refused the assignment."}


@patch("app.routes.assign_event_coordinator")
@patch("app.routes.get_available_coordinators")
@patch("app.routes.get_user")
def test_reassign_event_service_outage_is_a_500(mock_get_user, mock_get_coordinators, mock_assign):
    mock_get_user.return_value = LEAD
    mock_get_coordinators.return_value = [COORDINATOR]
    mock_assign.side_effect = event_service_refusal(503, {"message": "db down"})

    response = create_app().test_client().post(
        "/events/EVT-001/assign-coordinator/user-coordinator",
        json={"actingUserId": "user-lead"},
    )

    assert response.status_code == 500
    assert "Failed to assign coordinator to event" in response.json["error"]
