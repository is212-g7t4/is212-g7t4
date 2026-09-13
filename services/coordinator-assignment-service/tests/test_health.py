from unittest.mock import patch

from app import create_app


def test_health():
    """Test health check endpoint."""
    client = create_app().test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}


@patch("app.routes.get_available_coordinators")
def test_get_coordinators(mock_get_coordinators):
    """Test fetching available coordinators."""
    mock_coordinators = [
        {"id": "user-123", "name": "John Doe", "role": "EventCoordinator"},
        {"id": "user-456", "name": "Jane Smith", "role": "EventCoordinator"},
    ]
    mock_get_coordinators.return_value = mock_coordinators
    
    client = create_app().test_client()
    response = client.get("/coordinators")
    
    assert response.status_code == 200
    assert response.json == {"coordinators": mock_coordinators}
    mock_get_coordinators.assert_called_once()


@patch("app.routes.assign_event_coordinator")
@patch("app.routes.get_available_coordinators")
def test_assign_coordinator_success(mock_get_coordinators, mock_assign):
    """Test successfully assigning a coordinator to an event."""
    mock_coordinators = [
        {"id": "user-123", "name": "John Doe", "role": "EventCoordinator"},
    ]
    mock_get_coordinators.return_value = mock_coordinators
    
    mock_assign.return_value = {"eventId": "EVT-001", "assignedCoordinatorId": "user-123"}
    
    client = create_app().test_client()
    response = client.post("/events/EVT-001/assign-coordinator/user-123")
    
    assert response.status_code == 200
    assert response.json == {"eventId": "EVT-001", "assignedCoordinatorId": "user-123"}
    mock_get_coordinators.assert_called_once()
    mock_assign.assert_called_once_with("EVT-001", "user-123")


@patch("app.routes.get_available_coordinators")
def test_assign_coordinator_not_available(mock_get_coordinators):
    """Test assigning a coordinator that is not available."""
    mock_coordinators = [
        {"id": "user-123", "name": "John Doe", "role": "EventCoordinator"},
    ]
    mock_get_coordinators.return_value = mock_coordinators
    
    client = create_app().test_client()
    response = client.post("/events/EVT-001/assign-coordinator/user-999")
    
    assert response.status_code == 404
    assert "not available" in response.json["error"]


@patch("app.routes.get_available_coordinators")
def test_assign_coordinator_validation_error(mock_get_coordinators):
    """Test assigning coordinator when User Service fails."""
    mock_get_coordinators.side_effect = Exception("User Service error")
    
    client = create_app().test_client()
    response = client.post("/events/EVT-001/assign-coordinator/user-123")
    
    assert response.status_code == 500
    assert "Failed to validate coordinator" in response.json["error"]

