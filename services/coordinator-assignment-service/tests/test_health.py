from unittest.mock import patch

from app import create_app

MANAGER = {"user_id": "user-manager", "username": "Alice Tan", "role": "Event Coordinator", "manager_id": None}
COORDINATOR = {"user_id": "user-report", "username": "Marcus Lim", "role": "Event Coordinator", "manager_id": "user-manager"}


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
    """A manager can assign a submitted event to a new Event Coordinator."""
    mock_get_user.return_value = MANAGER
    mock_get_coordinators.return_value = [{"user_id": "user-123", "username": "Alice Tan", "role": "Event Coordinator"}]
    mock_assign.return_value = {"eventId": "EVT-001", "assignedCoordinatorId": "user-123"}

    client = create_app().test_client()
    response = client.post(
        "/events/EVT-001/assign-coordinator/user-123",
        json={"actingUserId": "user-manager"},
    )

    assert response.status_code == 200
    assert response.json == {"eventId": "EVT-001", "assignedCoordinatorId": "user-123"}
    mock_get_user.assert_called_once_with("user-manager")
    mock_assign.assert_called_once_with("EVT-001", "user-123")


@patch("app.routes.assign_event_coordinator")
@patch("app.routes.get_available_coordinators")
@patch("app.routes.get_user")
def test_assign_coordinator_success_for_reassignment(mock_get_user, mock_get_coordinators, mock_assign):
    """A manager can reassign an already-assigned event to a different Event Coordinator."""
    mock_get_user.return_value = MANAGER
    mock_get_coordinators.return_value = [
        {"user_id": "user-123", "username": "Alice Tan", "role": "Event Coordinator"},
        {"user_id": "user-456", "username": "Marcus Lim", "role": "Event Coordinator"},
    ]
    mock_assign.return_value = {"eventId": "EVT-001", "assignedCoordinatorId": "user-456"}

    client = create_app().test_client()
    response = client.post(
        "/events/EVT-001/assign-coordinator/user-456",
        json={"actingUserId": "user-manager"},
    )

    assert response.status_code == 200
    assert response.json == {"eventId": "EVT-001", "assignedCoordinatorId": "user-456"}
    mock_assign.assert_called_once_with("EVT-001", "user-456")


@patch("app.routes.get_available_coordinators")
@patch("app.routes.get_user")
def test_assign_coordinator_rejects_unavailable_coordinator(mock_get_user, mock_get_coordinators):
    """Only known available coordinators can be assigned to an event."""
    mock_get_user.return_value = MANAGER
    mock_get_coordinators.return_value = [{"user_id": "user-123", "username": "Alice Tan", "role": "Event Coordinator"}]

    client = create_app().test_client()
    response = client.post(
        "/events/EVT-001/assign-coordinator/user-999",
        json={"actingUserId": "user-manager"},
    )

    assert response.status_code == 404
    assert "not available" in response.json["error"]


@patch("app.routes.get_available_coordinators")
@patch("app.routes.get_user")
def test_assign_coordinator_handles_validation_error(mock_get_user, mock_get_coordinators):
    """Downstream coordinator validation failures are surfaced as service errors."""
    mock_get_user.return_value = MANAGER
    mock_get_coordinators.side_effect = Exception("User Service error")

    client = create_app().test_client()
    response = client.post(
        "/events/EVT-001/assign-coordinator/user-123",
        json={"actingUserId": "user-manager"},
    )

    assert response.status_code == 500
    assert "Failed to validate coordinator" in response.json["error"]


def test_assign_coordinator_requires_acting_user_id():
    """actingUserId must be supplied so the manager check has something to verify."""
    client = create_app().test_client()
    response = client.post("/events/EVT-001/assign-coordinator/user-123", json={})

    assert response.status_code == 400
    assert "actingUserId" in response.json["error"]


@patch("app.routes.get_user")
def test_assign_coordinator_rejects_non_manager(mock_get_user):
    """An Event Coordinator who reports to a manager cannot assign/reassign."""
    mock_get_user.return_value = COORDINATOR

    client = create_app().test_client()
    response = client.post(
        "/events/EVT-001/assign-coordinator/user-123",
        json={"actingUserId": "user-report"},
    )

    assert response.status_code == 403
    assert "manager" in response.json["error"]


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
        json={"actingUserId": "user-manager"},
    )

    assert response.status_code == 500
    assert "Failed to validate acting user" in response.json["error"]
    mock_get_coordinators.assert_not_called()
