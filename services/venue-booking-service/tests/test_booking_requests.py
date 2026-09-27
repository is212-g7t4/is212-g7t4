from unittest.mock import patch

from app import create_app
from app.clients import EventNotAssignedError, EventNotFoundError

EVENT = {"id": "evt-1", "expectedAttendance": "150"}
VENUES = [
    {"id": "ven-1", "name": "Innovation Lab", "capacity": 60, "status": "Operational"},
    {"id": "ven-2", "name": "Grand Ballroom", "capacity": 500, "status": "Operational"},
    {
        "id": "ven-3",
        "name": "Rooftop Terrace",
        "capacity": 150,
        "status": "Under Maintenance",
    },
]


def test_health():
    client = create_app().test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}


@patch("app.routes.get_venues")
@patch("app.routes.get_event")
def test_booking_request_succeeds_for_catalogued_operational_venue(
    mock_get_event, mock_get_venues
):
    """A venue from the catalogue with enough capacity passes validation."""
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES

    client = create_app().test_client()
    response = client.post(
        "/booking-requests",
        json={"eventId": "evt-1", "venueId": "ven-2", "coordinatorId": "coord-1"},
    )

    assert response.status_code == 201
    assert response.json == {
        "eventId": "evt-1",
        "venueId": "ven-2",
        "venueName": "Grand Ballroom",
        "status": "validated",
    }
    mock_get_event.assert_called_once_with("evt-1", "coord-1")


def test_booking_request_requires_all_fields():
    client = create_app().test_client()
    response = client.post("/booking-requests", json={"eventId": "evt-1"})
    assert response.status_code == 400


@patch("app.routes.get_event")
def test_booking_request_rejects_unknown_event(mock_get_event):
    mock_get_event.side_effect = EventNotFoundError

    client = create_app().test_client()
    response = client.post(
        "/booking-requests",
        json={"eventId": "missing", "venueId": "ven-1", "coordinatorId": "coord-1"},
    )
    assert response.status_code == 404


@patch("app.routes.get_event")
def test_booking_request_rejects_coordinator_not_assigned_to_event(mock_get_event):
    mock_get_event.side_effect = EventNotAssignedError

    client = create_app().test_client()
    response = client.post(
        "/booking-requests",
        json={"eventId": "evt-1", "venueId": "ven-1", "coordinatorId": "someone-else"},
    )
    assert response.status_code == 403


@patch("app.routes.get_venues")
@patch("app.routes.get_event")
def test_booking_request_rejects_venue_not_in_catalogue(
    mock_get_event, mock_get_venues
):
    """A venueId that doesn't exist in Venue Service's catalogue is rejected."""
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES

    client = create_app().test_client()
    response = client.post(
        "/booking-requests",
        json={
            "eventId": "evt-1",
            "venueId": "not-a-real-venue",
            "coordinatorId": "coord-1",
        },
    )
    assert response.status_code == 404


@patch("app.routes.get_venues")
@patch("app.routes.get_event")
def test_booking_request_rejects_non_operational_venue(mock_get_event, mock_get_venues):
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES

    client = create_app().test_client()
    response = client.post(
        "/booking-requests",
        json={"eventId": "evt-1", "venueId": "ven-3", "coordinatorId": "coord-1"},
    )
    assert response.status_code == 409


@patch("app.routes.get_venues")
@patch("app.routes.get_event")
def test_booking_request_rejects_insufficient_capacity(mock_get_event, mock_get_venues):
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES

    client = create_app().test_client()
    response = client.post(
        "/booking-requests",
        json={"eventId": "evt-1", "venueId": "ven-1", "coordinatorId": "coord-1"},
    )
    assert response.status_code == 422
