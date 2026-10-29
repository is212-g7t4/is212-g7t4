from unittest.mock import MagicMock, patch

import pytest
import httpx

from app import create_app
from app.clients import (
    BookingConflictError,
    BookingNotFoundError,
    BookingStateError,
    EventNotAssignedError,
    EventNotFoundError,
)
from tests.unit.factories import signed_in, bearer

EVENT = {
    "id": "evt-1",
    "status": "Under Review",
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
    client = signed_in(create_app().test_client())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}


STAFF_ID = "d9e4002b-db91-4939-b87e-50f9cceb5e0a"
STAFF_HEADERS = bearer(STAFF_ID, "Venue Staff")


@patch("app.routes.get_safety_records")
@patch("app.routes.get_event_bookings")
@patch("app.routes.get_venues")
@patch("app.routes.get_staff_events")
def test_staff_queue_includes_targeted_safety_feedback(events, venues, bookings, records):
    events.return_value = [{**EVENT, "eventName": "Workshop", "status": "Safety Changes Requested"}]
    venues.return_value = VENUES
    bookings.return_value = [dict(BOOKING), {**BOOKING, "id": "other", "status": "Approved"}]
    records.return_value = [{"roundNumber": 1, "status": "Changes Requested", "remarks": "Exit blocked.", "flags": [
        {"area": "venue arrangement", "bookingId": "booking-1", "changeRequired": "Move stage."}]}]
    response = signed_in(create_app().test_client()).get("/booking-requests", headers=STAFF_HEADERS)
    assert response.status_code == 200
    rows = response.json["events"][0]["bookings"]
    assert rows[0]["safetyFeedback"] == {"reason": "Exit blocked.", "requestedChanges": ["Move stage."]}
    assert rows[1]["safetyFeedback"] is None
    assert rows[0]["venueName"] == "Grand Ballroom"


# An empty Authorization header overrides the client's default sign-in: no token.
@pytest.mark.parametrize("headers,code", [({"Authorization": ""}, 401), (bearer(STAFF_ID, "Event Coordinator"), 403)])
def test_staff_queue_requires_venue_staff(headers, code):
    client = signed_in(create_app().test_client())
    assert client.get("/booking-requests", headers=headers).status_code == code
    assert client.patch("/booking-requests/b/review", headers=headers, json={}).status_code == code


# Safety revision AC2 (staff API): a reopened booking can receive a new Venue Staff decision during safety revision.
@patch("app.routes.get_event_for_internal_viewer")
@patch("app.routes.get_booking")
@patch("app.routes.decide_booking")
@pytest.mark.parametrize("status", ["Approved", "Rejected"])
def test_staff_can_review_reopened_safety_booking(decide, booking, event, status):
    booking.return_value = BOOKING
    event.return_value = {"status": "Safety Changes Requested"}
    decide.return_value = {**BOOKING, "status": status}
    with patch("app.routes.get_venue", return_value=VENUES[1]):
        response = signed_in(create_app().test_client()).patch("/booking-requests/booking-1/review", headers=STAFF_HEADERS,
            json={"reviewedBy": STAFF_ID, "status": status, "rejectionReason": "Venue unsuitable"})
    assert response.status_code == 200
    assert response.json["status"] == status


@patch("app.routes.get_safety_records")
@patch("app.routes.get_event_bookings")
@patch("app.routes.get_venues")
@patch("app.routes.get_staff_events")
@pytest.mark.parametrize("status,count", [("Pending", 1), ("Approved", 1), ("Rejected", 0)])
def test_staff_queue_filters_and_skips_safety_read_outside_revision(events, venues, bookings, records, status, count):
    events.return_value = [{**EVENT, "eventName": "Workshop", "status": "Under Review"}]
    venues.return_value = VENUES
    bookings.return_value = [dict(BOOKING), {**BOOKING, "id": "approved", "status": "Approved"}]
    response = signed_in(create_app().test_client()).get(f"/booking-requests?status={status}", headers=STAFF_HEADERS)
    assert response.status_code == 200
    assert len(response.json["events"]) == count
    if count:
        assert len(response.json["events"][0]["bookings"]) == 1
    records.assert_not_called()


def test_staff_queue_rejects_invalid_status():
    assert signed_in(create_app().test_client()).get("/booking-requests?status=bad", headers=STAFF_HEADERS).status_code == 400


@patch("app.routes.get_staff_events")
@pytest.mark.parametrize("error,code", [(httpx.ReadTimeout("timeout"), 504), (RuntimeError(), 502)])
def test_staff_queue_reports_downstream_failure(events, error, code):
    events.side_effect = error
    assert signed_in(create_app().test_client()).get("/booking-requests", headers=STAFF_HEADERS).status_code == code


@pytest.mark.parametrize("data", [None, {}, {"status": "Pending"}])
def test_staff_review_validates_decision(data):
    assert signed_in(create_app().test_client()).patch("/booking-requests/b/review", headers=STAFF_HEADERS, json=data).status_code == 400


@patch("app.routes.get_event_for_internal_viewer")
@patch("app.routes.get_booking")
@pytest.mark.parametrize("event_status,booking_status", [("Confirmed", "Pending Review"), ("Under Review", "Approved")])
def test_staff_review_blocks_stale_or_closed_requests(booking, event, event_status, booking_status):
    booking.return_value = {**BOOKING, "status": booking_status}
    event.return_value = {"status": event_status}
    assert signed_in(create_app().test_client()).patch("/booking-requests/b/review", headers=STAFF_HEADERS,
        json={"status": "Approved", "reviewedBy": STAFF_ID}).status_code == 409


@patch("app.routes.get_booking")
@pytest.mark.parametrize("error,code", [(BookingNotFoundError(), 404), (RuntimeError(), 502)])
def test_staff_review_reports_lookup_failure(booking, error, code):
    booking.side_effect = error
    assert signed_in(create_app().test_client()).patch("/booking-requests/b/review", headers=STAFF_HEADERS,
        json={"status": "Approved", "reviewedBy": STAFF_ID}).status_code == code


@patch("app.clients.httpx.get")
def test_staff_queue_clients_use_event_and_safety_owners(get):
    from app import clients
    response = MagicMock()
    response.json.return_value = {"events": [EVENT], "safetyChecks": [{"roundNumber": 1}]}
    get.return_value = response
    assert clients.get_staff_events() == [EVENT]
    assert get.call_args.kwargs["params"] == {"viewerRole": "Venue Staff"}
    assert clients.get_safety_records("evt-1") == [{"roundNumber": 1}]
    assert get.call_args.kwargs["params"] == {"eventId": "evt-1"}


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

    client = signed_in(create_app().test_client())
    response = client.post(
        "/booking-requests",
        json=REQUEST,
    )

    assert response.status_code == 201
    assert response.json == BOOKING
    mock_get_event.assert_called_once_with("evt-1")
    mock_create_booking.assert_called_once_with(
        "evt-1", "ven-2", "2026-10-01T09:00", "2026-10-01T12:00",
        80, "Projector"
    )


def test_booking_request_requires_all_fields():
    client = signed_in(create_app().test_client())
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
    response = signed_in(create_app().test_client()).post(
        "/booking-requests", json=REQUEST | change
    )
    assert response.status_code == 400


@patch("app.routes.get_event")
def test_booking_request_rejects_unknown_event(mock_get_event):
    mock_get_event.side_effect = EventNotFoundError

    client = signed_in(create_app().test_client())
    response = client.post(
        "/booking-requests",
        json=REQUEST | {"eventId": "missing", "venueId": "ven-1"},
    )
    assert response.status_code == 404


@patch("app.routes.get_event")
def test_booking_request_rejects_coordinator_not_assigned_to_event(mock_get_event):
    mock_get_event.side_effect = EventNotAssignedError

    client = signed_in(create_app().test_client())
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

    client = signed_in(create_app().test_client())
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

    client = signed_in(create_app().test_client())
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

    client = signed_in(create_app().test_client())
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

    response = signed_in(create_app().test_client()).post(
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

    client = signed_in(create_app().test_client())
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

    response = signed_in(create_app().test_client()).get(
        "/events/evt-1/booking-requests?coordinatorId=coord-1"
    )

    assert response.status_code == 200
    assert [(item["id"], item["venueName"]) for item in response.json["bookings"]] == [
        ("booking-1", "Grand Ballroom"),
        ("booking-2", "Innovation Lab"),
    ]


# SCRUM-29 D7: the legacy approve/reject routes now run the /review checks,
# so these earlier-story tests send Venue Staff headers and stub the event.
@patch("app.routes.get_event_for_internal_viewer", return_value=EVENT)
@patch("app.routes.get_venue")
@patch("app.routes.get_booking")
@patch("app.routes.decide_booking")
def test_approve_booking_request(mock_decide_booking, mock_get_booking, mock_get_venue, _event):
    mock_decide_booking.return_value = {**BOOKING, "status": "Approved"}
    mock_get_booking.return_value = {**BOOKING, "venueId": "ven-2"}
    mock_get_venue.return_value = {"id": "ven-2", "setupTimeMinutes": 30, "turnaroundTimeMinutes": 45}

    client = signed_in(create_app().test_client())
    response = client.patch(
        "/booking-requests/booking-1/approve", headers=STAFF_HEADERS, json={"reviewedBy": STAFF_ID}
    )

    assert response.status_code == 200
    assert response.json["status"] == "Approved"
    mock_decide_booking.assert_called_once_with("booking-1", "Approved", 30, 45)


@patch("app.routes.decide_booking")
def test_reject_booking_request_requires_reviewer(mock_decide_booking):
    client = signed_in(create_app().test_client())
    response = client.patch("/booking-requests/booking-1/reject", headers=STAFF_HEADERS, json={})
    assert response.status_code == 400
    mock_decide_booking.assert_not_called()


@patch("app.routes.get_booking")
@patch("app.routes.decide_booking")
def test_approve_booking_request_missing_returns_404(mock_decide_booking, mock_get_booking):
    mock_get_booking.side_effect = BookingNotFoundError

    client = signed_in(create_app().test_client())
    response = client.patch(
        "/booking-requests/missing/approve", headers=STAFF_HEADERS, json={"reviewedBy": STAFF_ID}
    )
    assert response.status_code == 404


@patch("app.routes.get_event_for_internal_viewer", return_value=EVENT)
@patch("app.routes.get_venue", return_value=VENUES[1])
@patch("app.routes.get_booking", return_value=BOOKING)
@patch("app.routes.decide_booking")
def test_cancelled_booking_cannot_be_reviewed(mock_decide_booking, *_):
    mock_decide_booking.side_effect = BookingStateError

    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1/approve", headers=STAFF_HEADERS, json={"reviewedBy": STAFF_ID}
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

    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1",
        json=REQUEST | {"requiredCapacity": 50},
    )

    assert response.status_code == 200
    assert response.json["status"] == "Pending Review"
    mock_get_event.assert_called_once_with("evt-1")
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

    response = signed_in(create_app().test_client()).patch(
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

    response = signed_in(create_app().test_client()).patch(
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

    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1", json=REQUEST
    )

    assert response.status_code == 409
    assert "cannot be modified" in response.json["message"]


@patch("app.routes.cancel_booking")
@patch("app.routes.get_event")
def test_cancel_booking_updates_only_selected_booking(mock_get_event, mock_cancel_booking):
    mock_get_event.return_value = EVENT
    mock_cancel_booking.return_value = {**BOOKING, "status": "Cancelled"}

    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1/cancel",
        json={"eventId": "evt-1", "coordinatorId": "coord-1"},
    )

    assert response.status_code == 200
    assert response.json["status"] == "Cancelled"
    mock_get_event.assert_called_once_with("evt-1")
    mock_cancel_booking.assert_called_once_with("booking-1", "evt-1")


@patch("app.routes.cancel_booking")
@patch("app.routes.get_event")
def test_cancel_booking_requires_assigned_coordinator(mock_get_event, mock_cancel_booking):
    mock_get_event.side_effect = EventNotAssignedError

    response = signed_in(create_app().test_client()).patch(
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
    response = signed_in(create_app().test_client()).patch(
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
    response = signed_in(create_app().test_client()).patch(
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
    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1", json=REQUEST | {"venueId": venue_id}
    )
    assert response.status_code == expected_status


@patch("app.routes.get_venues")
@patch("app.routes.get_event")
def test_update_booking_reports_venue_service_failure(mock_get_event, mock_get_venues):
    mock_get_event.return_value = EVENT
    mock_get_venues.side_effect = RuntimeError("down")
    response = signed_in(create_app().test_client()).patch(
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
    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1", json=REQUEST
    )
    assert response.status_code == expected_status


def test_cancel_booking_requires_parent_event_and_coordinator():
    response = signed_in(create_app().test_client()).patch(
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
    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1/cancel",
        json={"eventId": "evt-1", "coordinatorId": "coord-1"},
    )
    assert response.status_code == expected_status
