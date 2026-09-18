from unittest.mock import patch

from app import create_app


@patch("app.routes.get_available_coordinators")
def test_get_coordinators_returns_available_event_coordinators(mock_get_coordinators):
    """The service exposes the mock coordinator pool for assignment decisions."""
    mock_coordinators = [
        {"user_id": "user-123", "username": "Alicia Tan", "role": "EventCoordinator"},
        {"user_id": "user-456", "username": "Marcus Lim", "role": "EventCoordinator"},
    ]
    mock_get_coordinators.return_value = mock_coordinators

    client = create_app().test_client()
    response = client.get("/coordinators")

    assert response.status_code == 200
    assert response.json == {"coordinators": mock_coordinators}
    mock_get_coordinators.assert_called_once()


@patch("app.routes.assign_event_coordinator")
@patch("app.routes.get_available_coordinators")
def test_assign_coordinator_success_for_new_assignment(mock_get_coordinators, mock_assign):
    """A submitted event can be assigned to a new Event Coordinator."""
    mock_coordinators = [{"user_id": "user-123", "username": "Alicia Tan", "role": "EventCoordinator"}]
    mock_get_coordinators.return_value = mock_coordinators
    mock_assign.return_value = {"eventId": "EVT-001", "assignedCoordinatorId": "user-123"}

    client = create_app().test_client()
    response = client.post("/events/EVT-001/assign-coordinator/user-123")

    assert response.status_code == 200
    assert response.json == {"eventId": "EVT-001", "assignedCoordinatorId": "user-123"}
    mock_assign.assert_called_once_with("EVT-001", "user-123")


@patch("app.routes.assign_event_coordinator")
@patch("app.routes.get_available_coordinators")
def test_assign_coordinator_success_for_reassignment(mock_get_coordinators, mock_assign):
    """An assigned event can be reassigned to a different Event Coordinator."""
    mock_coordinators = [
        {"user_id": "user-123", "username": "Alicia Tan", "role": "EventCoordinator"},
        {"user_id": "user-456", "username": "Marcus Lim", "role": "EventCoordinator"},
    ]
    mock_get_coordinators.return_value = mock_coordinators
    mock_assign.return_value = {"eventId": "EVT-001", "assignedCoordinatorId": "user-456"}

    client = create_app().test_client()
    response = client.post("/events/EVT-001/assign-coordinator/user-456")

    assert response.status_code == 200
    assert response.json == {"eventId": "EVT-001", "assignedCoordinatorId": "user-456"}
    mock_assign.assert_called_once_with("EVT-001", "user-456")


@patch("app.routes.get_available_coordinators")
def test_assign_coordinator_rejects_unavailable_coordinator(mock_get_coordinators):
    """Only known available coordinators can be assigned to an event."""
    mock_coordinators = [{"user_id": "user-123", "username": "Alicia Tan", "role": "EventCoordinator"}]
    mock_get_coordinators.return_value = mock_coordinators

    client = create_app().test_client()
    response = client.post("/events/EVT-001/assign-coordinator/user-999")

    assert response.status_code == 404
    assert "not available" in response.json["error"]


@patch("app.routes.get_available_coordinators")
def test_assign_coordinator_handles_validation_error(mock_get_coordinators):
    """Downstream coordinator validation failures are surfaced as service errors."""
    mock_get_coordinators.side_effect = Exception("User Service error")

    client = create_app().test_client()
    response = client.post("/events/EVT-001/assign-coordinator/user-123")

    assert response.status_code == 500
    assert "Failed to validate coordinator" in response.json["error"]

