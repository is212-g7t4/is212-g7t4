from unittest.mock import patch

import pytest

from app import create_app
from app.clients import (
    BookingConflictError,
    BookingNotFoundError,
    BookingStateError,
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
    "requiredCapacity": 80,
    "venueRequirements": "Projector",
    "status": "Pending Review",
    "requestedBy": "coord-1",
    "reviewedBy": None,
}

REQUEST = {
    "eventId": "evt-1",
    "venueId": "ven-2",
    "coordinatorId": "coord-1",
    "requestedStartTime": "2026-10-01T09:00",
    "requestedEndTime": "2026-10-01T12:00",
    "requiredCapacity": 80,
    "venueRequirements": "Projector",
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
        json=REQUEST,
    )

    assert response.status_code == 201
    assert response.json == BOOKING
    mock_get_event.assert_called_once_with("evt-1", "coord-1")
    mock_create_booking.assert_called_once_with(
        "evt-1", "ven-2", "2026-10-01T09:00", "2026-10-01T12:00",
        80, "Projector", "coord-1"
    )


def test_booking_request_requires_all_fields():
    client = create_app().test_client()
    response = client.post("/booking-requests", json={"eventId": "evt-1"})
    assert response.status_code == 400


@pytest.mark.parametrize(
    "change",
    [
        {"requestedStartTime": "2026-10-01"},
        {"requestedEndTime": "2026-10-01T08:00"},
        {"requiredCapacity": 0},
        {"requiredCapacity": True},
        {"venueRequirements": None},
    ],
)
def test_booking_request_validates_booking_specific_details(change):
    response = create_app().test_client().post(
        "/booking-requests", json=REQUEST | change
    )
    assert response.status_code == 400


@patch("app.routes.get_event")
def test_booking_request_rejects_unknown_event(mock_get_event):
    mock_get_event.side_effect = EventNotFoundError

    client = create_app().test_client()
    response = client.post(
        "/booking-requests",
        json=REQUEST | {"eventId": "missing", "venueId": "ven-1"},
    )
    assert response.status_code == 404


@patch("app.routes.get_event")
def test_booking_request_rejects_coordinator_not_assigned_to_event(mock_get_event):
    mock_get_event.side_effect = EventNotAssignedError

    client = create_app().test_client()
    response = client.post(
        "/booking-requests",
        json=REQUEST | {"venueId": "ven-1", "coordinatorId": "someone-else"},
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
        json=REQUEST | {"venueId": "not-a-real-venue"},
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
        json=REQUEST | {"venueId": venue_id},
    )
    assert response.status_code == 409
    assert "not currently available for booking" in response.json["message"]


@patch("app.routes.get_venues")
@patch("app.routes.get_event")
def test_booking_request_uses_booking_capacity_not_event_total(mock_get_event, mock_get_venues):
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES

    client = create_app().test_client()
    with patch("app.routes.create_booking", return_value=BOOKING) as mock_create:
        response = client.post(
            "/booking-requests",
            json=REQUEST | {"venueId": "ven-1", "requiredCapacity": 50},
        )
    assert response.status_code == 201
    assert EVENT["expectedAttendance"] == "150"
    assert mock_create.call_args.args[4] == 50


@patch("app.routes.get_venues")
@patch("app.routes.get_event")
def test_booking_request_rejects_booking_capacity_above_venue_capacity(
    mock_get_event, mock_get_venues
):
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES

    response = create_app().test_client().post(
        "/booking-requests", json=REQUEST | {"venueId": "ven-1", "requiredCapacity": 61}
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
        json=REQUEST,
    )
    assert response.status_code == 409


@patch("app.routes.get_venues")
@patch("app.routes.get_event")
@patch("app.routes.get_event_bookings")
def test_lists_multiple_bookings_for_same_event_separately(
    mock_get_event_bookings, mock_get_event, mock_get_venues
):
    mock_get_event.return_value = EVENT
    mock_get_event_bookings.return_value = [
        BOOKING,
        BOOKING | {"id": "booking-2", "venueId": "ven-1", "requiredCapacity": 50},
    ]
    mock_get_venues.return_value = VENUES

    response = create_app().test_client().get(
        "/events/evt-1/booking-requests?coordinatorId=coord-1"
    )

    assert response.status_code == 200
    assert [(item["id"], item["venueName"]) for item in response.json["bookings"]] == [
        ("booking-1", "Grand Ballroom"),
        ("booking-2", "Innovation Lab"),
    ]


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


@patch("app.routes.decide_booking")
def test_cancelled_booking_cannot_be_reviewed(mock_decide_booking):
    mock_decide_booking.side_effect = BookingStateError

    response = create_app().test_client().patch(
        "/booking-requests/booking-1/approve", json={"reviewedBy": "staff-1"}
    )

    assert response.status_code == 409
    assert "cannot be reviewed" in response.json["message"]


@patch("app.routes.update_booking")
@patch("app.routes.get_venues")
@patch("app.routes.get_event")
def test_update_booking_revalidates_and_resubmits_only_selected_booking(
    mock_get_event, mock_get_venues, mock_update_booking
):
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES
    mock_update_booking.return_value = {
        **BOOKING,
        "requiredCapacity": 50,
        "status": "Pending Review",
        "reviewedBy": None,
    }

    response = create_app().test_client().patch(
        "/booking-requests/booking-1",
        json=REQUEST | {"requiredCapacity": 50},
    )

    assert response.status_code == 200
    assert response.json["status"] == "Pending Review"
    mock_get_event.assert_called_once_with("evt-1", "coord-1")
    mock_update_booking.assert_called_once_with(
        "booking-1", "evt-1", "ven-2", "2026-10-01T09:00",
        "2026-10-01T12:00", 50, "Projector"
    )


@patch("app.routes.update_booking")
@patch("app.routes.get_venues")
@patch("app.routes.get_event")
def test_update_booking_rechecks_capacity_before_saving(
    mock_get_event, mock_get_venues, mock_update_booking
):
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES

    response = create_app().test_client().patch(
        "/booking-requests/booking-1",
        json=REQUEST | {"venueId": "ven-1", "requiredCapacity": 61},
    )

    assert response.status_code == 422
    mock_update_booking.assert_not_called()


@patch("app.routes.update_booking")
@patch("app.routes.get_venues")
@patch("app.routes.get_event")
def test_update_booking_reports_conflict_without_changing_siblings(
    mock_get_event, mock_get_venues, mock_update_booking
):
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES
    mock_update_booking.side_effect = BookingConflictError

    response = create_app().test_client().patch(
        "/booking-requests/booking-1", json=REQUEST
    )

    assert response.status_code == 409
    assert "Grand Ballroom" in response.json["message"]


@patch("app.routes.update_booking")
@patch("app.routes.get_venues")
@patch("app.routes.get_event")
def test_cancelled_booking_cannot_be_resubmitted(
    mock_get_event, mock_get_venues, mock_update_booking
):
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES
    mock_update_booking.side_effect = BookingStateError

    response = create_app().test_client().patch(
        "/booking-requests/booking-1", json=REQUEST
    )

    assert response.status_code == 409
    assert "cannot be modified" in response.json["message"]


@patch("app.routes.cancel_booking")
@patch("app.routes.get_event")
def test_cancel_booking_updates_only_selected_booking(mock_get_event, mock_cancel_booking):
    mock_get_event.return_value = EVENT
    mock_cancel_booking.return_value = {**BOOKING, "status": "Cancelled"}

    response = create_app().test_client().patch(
        "/booking-requests/booking-1/cancel",
        json={"eventId": "evt-1", "coordinatorId": "coord-1"},
    )

    assert response.status_code == 200
    assert response.json["status"] == "Cancelled"
    mock_get_event.assert_called_once_with("evt-1", "coord-1")
    mock_cancel_booking.assert_called_once_with("booking-1", "evt-1")


@patch("app.routes.cancel_booking")
@patch("app.routes.get_event")
def test_cancel_booking_requires_assigned_coordinator(mock_get_event, mock_cancel_booking):
    mock_get_event.side_effect = EventNotAssignedError

    response = create_app().test_client().patch(
        "/booking-requests/booking-1/cancel",
        json={"eventId": "evt-1", "coordinatorId": "someone-else"},
    )

    assert response.status_code == 403
    mock_cancel_booking.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"eventId": "evt-1"},
        REQUEST | {"requiredCapacity": 0},
        REQUEST | {"venueRequirements": None},
        REQUEST | {"requestedStartTime": "2026-10-01"},
    ],
)
def test_update_booking_validates_request(payload):
    response = create_app().test_client().patch(
        "/booking-requests/booking-1", json=payload
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    ("event_error", "expected_status"),
    [(EventNotFoundError, 404), (EventNotAssignedError, 403), (RuntimeError("down"), 502)],
)
@patch("app.routes.get_event")
def test_update_booking_requires_access_to_parent_event(
    mock_get_event, event_error, expected_status
):
    mock_get_event.side_effect = event_error
    response = create_app().test_client().patch(
        "/booking-requests/booking-1", json=REQUEST
    )
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    ("venue_id", "expected_status"),
    [("missing", 404), ("ven-3", 409)],
)
@patch("app.routes.get_venues")
@patch("app.routes.get_event")
def test_update_booking_rechecks_venue_catalogue(
    mock_get_event, mock_get_venues, venue_id, expected_status
):
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES
    response = create_app().test_client().patch(
        "/booking-requests/booking-1", json=REQUEST | {"venueId": venue_id}
    )
    assert response.status_code == expected_status


@patch("app.routes.get_venues")
@patch("app.routes.get_event")
def test_update_booking_reports_venue_service_failure(mock_get_event, mock_get_venues):
    mock_get_event.return_value = EVENT
    mock_get_venues.side_effect = RuntimeError("down")
    response = create_app().test_client().patch(
        "/booking-requests/booking-1", json=REQUEST
    )
    assert response.status_code == 502


@pytest.mark.parametrize(
    ("update_error", "expected_status"),
    [(BookingNotFoundError, 404), (RuntimeError("down"), 502)],
)
@patch("app.routes.update_booking")
@patch("app.routes.get_venues")
@patch("app.routes.get_event")
def test_update_booking_reports_atomic_failure(
    mock_get_event, mock_get_venues, mock_update_booking, update_error, expected_status
):
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES
    mock_update_booking.side_effect = update_error
    response = create_app().test_client().patch(
        "/booking-requests/booking-1", json=REQUEST
    )
    assert response.status_code == expected_status


def test_cancel_booking_requires_parent_event_and_coordinator():
    response = create_app().test_client().patch(
        "/booking-requests/booking-1/cancel", json={}
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    ("cancel_error", "expected_status"),
    [(BookingNotFoundError, 404), (RuntimeError("down"), 502)],
)
@patch("app.routes.cancel_booking")
@patch("app.routes.get_event")
def test_cancel_booking_reports_atomic_failure(
    mock_get_event, mock_cancel_booking, cancel_error, expected_status
):
    mock_get_event.return_value = EVENT
    mock_cancel_booking.side_effect = cancel_error
    response = create_app().test_client().patch(
        "/booking-requests/booking-1/cancel",
        json={"eventId": "evt-1", "coordinatorId": "coord-1"},
    )
    assert response.status_code == expected_status
