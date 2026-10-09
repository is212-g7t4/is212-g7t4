from unittest.mock import patch

import pytest

from app import create_app
from app.clients import (
    BookingConflictError,
    BookingNotFoundError,
    EventNotAssignedError,
    EventNotFoundError,
)

EVENT = {
    "id": "evt-1",
    "expectedAttendance": "150",
    "preferredStartDate": "2026-10-01T09:00",
    "preferredEndDate": "2026-10-01T12:00",
}
# Statuses match the ones Venue Service actually stores: Available,
# Under Maintenance or Booked. Only Available is bookable.
VENUES = [
    {"id": "ven-1", "name": "Innovation Lab", "capacity": 60, "status": "Available"},
    {"id": "ven-2", "name": "Grand Ballroom", "capacity": 500, "status": "Available"},
    {
        "id": "ven-3",
        "name": "Rooftop Terrace",
        "capacity": 150,
        "status": "Under Maintenance",
    },
    {"id": "ven-4", "name": "Conference Room A", "capacity": 400, "status": "Booked"},
]
BOOKING = {
    "id": "booking-1",
    "eventId": "evt-1",
    "venueId": "ven-2",
    "requestedStartTime": "2026-10-01T09:00:00",
    "requestedEndTime": "2026-10-01T12:00:00",
    "status": "Pending Review",
    "requestedBy": "coord-1",
    "reviewedBy": None,
}


def test_health():
    client = create_app().test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}


@patch("app.routes.create_booking")
@patch("app.routes.get_venues")
@patch("app.routes.get_event")
def test_booking_request_succeeds_for_catalogued_available_venue(
    mock_get_event, mock_get_venues, mock_create_booking
):
    """A venue from the catalogue with enough capacity is booked."""
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES
    mock_create_booking.return_value = BOOKING

    client = create_app().test_client()
    response = client.post(
        "/booking-requests",
        json={"eventId": "evt-1", "venueId": "ven-2", "coordinatorId": "coord-1"},
    )

    assert response.status_code == 201
    assert response.json == BOOKING
    mock_get_event.assert_called_once_with("evt-1", "coord-1")
    mock_create_booking.assert_called_once_with(
        "evt-1", "ven-2", "2026-10-01T09:00", "2026-10-01T12:00", "coord-1"
    )


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


@pytest.mark.parametrize("venue_id", ["ven-3", "ven-4"])
@patch("app.routes.get_venues")
@patch("app.routes.get_event")
def test_booking_request_rejects_venue_that_is_not_available(
    mock_get_event, mock_get_venues, venue_id
):
    """Under Maintenance and Booked venues are both refused with a 409."""
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES

    client = create_app().test_client()
    response = client.post(
        "/booking-requests",
        json={"eventId": "evt-1", "venueId": venue_id, "coordinatorId": "coord-1"},
    )
    assert response.status_code == 409
    assert "not currently available for booking" in response.json["message"]


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


@patch("app.routes.create_booking")
@patch("app.routes.get_venues")
@patch("app.routes.get_event")
def test_booking_request_rejects_double_booking(
    mock_get_event, mock_get_venues, mock_create_booking
):
    """A conflicting time slot from Venue Availability Service surfaces as 409."""
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES
    mock_create_booking.side_effect = BookingConflictError

    client = create_app().test_client()
    response = client.post(
        "/booking-requests",
        json={"eventId": "evt-1", "venueId": "ven-2", "coordinatorId": "coord-1"},
    )
    assert response.status_code == 409


@patch("app.routes.decide_booking")
def test_approve_booking_request(mock_decide_booking):
    mock_decide_booking.return_value = {**BOOKING, "status": "Approved"}

    client = create_app().test_client()
    response = client.patch(
        "/booking-requests/booking-1/approve", json={"reviewedBy": "staff-1"}
    )

    assert response.status_code == 200
    assert response.json["status"] == "Approved"
    mock_decide_booking.assert_called_once_with("booking-1", "staff-1", "Approved")


@patch("app.routes.decide_booking")
def test_reject_booking_request_requires_reviewer(mock_decide_booking):
    client = create_app().test_client()
    response = client.patch("/booking-requests/booking-1/reject", json={})
    assert response.status_code == 400
    mock_decide_booking.assert_not_called()


@patch("app.routes.decide_booking")
def test_approve_booking_request_missing_returns_404(mock_decide_booking):
    mock_decide_booking.side_effect = BookingNotFoundError

    client = create_app().test_client()
    response = client.patch(
        "/booking-requests/missing/approve", json={"reviewedBy": "staff-1"}
    )
    assert response.status_code == 404
