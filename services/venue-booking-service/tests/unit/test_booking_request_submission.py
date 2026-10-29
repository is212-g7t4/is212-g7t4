"""SCRUM-28 Venue Booking Request Submission: Venue Booking Service unit tests.

Story: As an Event Coordinator, I want to submit a venue booking request for an
event, so that Venue Staff can assess whether the requested venue arrangement
can be accepted.

This composite owns the event-status gate (AC2), the forwarding of the request
(AC1, AC2) and the Venue Staff queue (AC3, AC4, AC5). The overlap rule behind
AC6 runs in Venue Availability Service; here AC6 only proves its answer is
passed through. Every downstream call is patched where app.routes looks it up.
"""

from unittest.mock import patch

import pytest

from app import create_app
from app.clients import BookingConflictError
from app.routes import REVIEWABLE_EVENT_STATUSES, SUBMITTABLE_EVENT_STATUSES
from tests.unit.factories import signed_in, bearer

STAFF_ID = "d9e4002b-db91-4939-b87e-50f9cceb5e0a"
STAFF_HEADERS = bearer(STAFF_ID, "Venue Staff")
VENUES = [{"id": "ven-1", "name": "Grand Ballroom", "capacity": 200, "status": "Available"}]
EVENT = {
    "id": "evt-1",
    "eventName": "Spring Fair",
    "status": "Under Review",
    "coordinatorId": "coord-1",
    "preferredStartDate": "2030-03-01T09:00:00",
    "preferredEndDate": "2030-03-01T17:00:00",
}
REQUEST = {
    "eventId": "evt-1",
    "venueId": "ven-1",
    "coordinatorId": "coord-1",
    "requestedStartTime": "2030-03-01T13:00",
    "requestedEndTime": "2030-03-01T15:00",
    "requiredCapacity": 120,
    "venueRequirements": "  Stage and two microphones  ",
}
BOOKING = {
    "id": "booking-1",
    "eventId": "evt-1",
    "venueId": "ven-1",
    "requestedStartTime": "2030-03-01T13:00:00",
    "requestedEndTime": "2030-03-01T15:00:00",
    "requiredCapacity": 120,
    "venueRequirements": "Stage and two microphones",
    "status": "Pending Review",
    "requestedBy": "coord-1",
    "reviewedBy": None,
    "requestedAt": "2030-02-01T10:00:00+08:00",
}
NOT_SUBMITTABLE = ["Clarification Requested", "Rejected", "Pending Safety Check", "Confirmed", "Cancelled"]


def submit(event, create_result=BOOKING):
    with (
        patch("app.routes.get_event", return_value=event) as get_event,
        patch("app.routes.get_venues", return_value=VENUES) as get_venues,
        patch("app.routes.create_booking") as create_booking,
    ):
        if isinstance(create_result, Exception):
            create_booking.side_effect = create_result
        else:
            create_booking.return_value = create_result
        response = signed_in(create_app().test_client()).post("/booking-requests", json=REQUEST)
    return response, get_event, get_venues, create_booking


def staff_queue(events, bookings_by_event, query=""):
    with (
        patch("app.routes.get_staff_events", return_value=events),
        patch("app.routes.get_venues", return_value=VENUES),
        patch("app.routes.get_event_bookings", side_effect=lambda event_id: bookings_by_event[event_id]),
        patch("app.routes.get_safety_records", return_value=[]),
    ):
        return signed_in(create_app().test_client()).get(f"/booking-requests{query}", headers=STAFF_HEADERS)


# AC1 ----


def test_ac1_submission_forwards_booking_timing_capacity_and_requirements():
    """Normal: the booking's own timing, capacity and trimmed requirements reach Venue Availability."""
    response, get_event, _, create_booking = submit(EVENT)

    assert response.status_code == 201
    get_event.assert_called_once_with("evt-1")
    create_booking.assert_called_once_with(
        "evt-1", "ven-1", "2030-03-01T13:00", "2030-03-01T15:00",
        120, "Stage and two microphones",
    )


# AC2 ----


@pytest.mark.parametrize("status", SUBMITTABLE_EVENT_STATUSES)
def test_ac2_request_for_submittable_event_is_recorded_as_pending_review(status):
    """Normal: before, during and after review the request is recorded for Venue Staff."""
    response, _, _, create_booking = submit({**EVENT, "status": status})

    assert response.status_code == 201
    assert response.json["status"] == "Pending Review"
    assert response.json["requestedAt"] == "2030-02-01T10:00:00+08:00"
    create_booking.assert_called_once()


def test_ac2_submittable_statuses_are_exactly_the_agreed_four():
    """Normal: the gate matches the statuses agreed for SCRUM-28 (Clarice, 25 Oct)."""
    assert SUBMITTABLE_EVENT_STATUSES == (
        "Submitted", "Under Review", "Approved", "Safety Changes Requested",
    )


@pytest.mark.parametrize("status", NOT_SUBMITTABLE)
def test_ac2_request_for_event_not_under_review_is_refused(status):
    """Conflict: a request Venue Staff could never review is not recorded, and nothing else is called."""
    response, _, get_venues, create_booking = submit({**EVENT, "status": status})

    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_ACCEPTING_VENUE_REQUESTS"
    assert response.json["eventStatus"] == status
    get_venues.assert_not_called()
    create_booking.assert_not_called()


def test_ac2_event_without_status_is_refused():
    """Failure: an event whose status is unknown fails closed."""
    event = {key: value for key, value in EVENT.items() if key != "status"}

    response, _, get_venues, create_booking = submit(event)

    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_ACCEPTING_VENUE_REQUESTS"
    assert response.json["eventStatus"] is None
    get_venues.assert_not_called()
    create_booking.assert_not_called()


# AC3 ----


def test_ac3_staff_queue_shows_event_timing_with_each_request():
    """Normal: Venue Staff see the event's dates next to the booking's own schedule and needs."""
    response = staff_queue([EVENT], {"evt-1": [dict(BOOKING)]})

    assert response.status_code == 200
    [event] = response.json["events"]
    assert event["eventName"] == "Spring Fair"
    assert event["eventStart"] == "2030-03-01T09:00:00"
    assert event["eventEnd"] == "2030-03-01T17:00:00"
    [booking] = event["bookings"]
    assert booking["venueName"] == "Grand Ballroom"
    assert booking["requestedStartTime"] == "2030-03-01T13:00:00"
    assert booking["requestedEndTime"] == "2030-03-01T15:00:00"
    assert booking["requiredCapacity"] == 120
    assert booking["venueRequirements"] == "Stage and two microphones"
    assert booking["requestedAt"] == "2030-02-01T10:00:00+08:00"


@pytest.mark.parametrize("missing", ["", None], ids=["event-service-blank", "absent"])
def test_ac3_staff_queue_tolerates_event_without_dates(missing):
    """Boundary: an event with no preferred dates still lists its requests, with null timing."""
    if missing is None:
        event = {key: value for key, value in EVENT.items() if not key.startswith("preferred")}
    else:
        # Event Service's serialize() sends "" for an unset date.
        event = {**EVENT, "preferredStartDate": "", "preferredEndDate": ""}
    legacy = {key: value for key, value in BOOKING.items() if key != "requestedAt"}

    response = staff_queue([event], {"evt-1": [legacy]})

    assert response.status_code == 200
    [listed] = response.json["events"]
    assert listed["eventStart"] is None
    assert listed["eventEnd"] is None
    assert listed["bookings"][0]["requestedAt"] is None


# AC4 ----


def test_ac4_pending_and_pending_review_are_both_awaiting_review():
    """Normal: both spellings need a decision; decided or withdrawn requests do not."""
    bookings = [
        {**BOOKING, "id": "new", "status": "Pending Review"},
        {**BOOKING, "id": "legacy", "status": "Pending"},
        {**BOOKING, "id": "approved", "status": "Approved"},
        {**BOOKING, "id": "rejected", "status": "Rejected"},
        {**BOOKING, "id": "cancelled", "status": "Cancelled"},
    ]

    response = staff_queue([EVENT], {"evt-1": bookings})

    [event] = response.json["events"]
    flags = {booking["id"]: booking["awaitingReview"] for booking in event["bookings"]}
    assert flags == {
        "new": True, "legacy": True, "approved": False, "rejected": False, "cancelled": False,
    }
    assert event["awaitingReviewCount"] == 2


def test_ac4_awaiting_filter_counts_only_awaiting_requests():
    """Normal: the "Pending" filter returns both spellings and counts them."""
    bookings = [
        {**BOOKING, "id": "new", "status": "Pending Review"},
        {**BOOKING, "id": "legacy", "status": "Pending"},
        {**BOOKING, "id": "approved", "status": "Approved"},
    ]

    response = staff_queue([EVENT], {"evt-1": bookings}, "?status=Pending")

    [event] = response.json["events"]
    assert sorted(booking["id"] for booking in event["bookings"]) == ["legacy", "new"]
    assert event["awaitingReviewCount"] == 2


def test_ac4_awaiting_requests_are_listed_first_oldest_first():
    """Normal: staff work the queue in submission order; legacy rows without a time go last."""
    bookings = [
        {**BOOKING, "id": "approved", "status": "Approved", "requestedAt": "2030-01-01T09:00:00+08:00"},
        {**BOOKING, "id": "legacy-late", "status": "Pending", "requestedAt": None,
         "requestedStartTime": "2030-03-02T09:00:00"},
        {**BOOKING, "id": "newer", "requestedAt": "2030-02-03T09:00:00+08:00"},
        {**BOOKING, "id": "legacy-early", "status": "Pending", "requestedAt": None,
         "requestedStartTime": "2030-03-01T09:00:00"},
        {**BOOKING, "id": "older", "requestedAt": "2030-02-01T09:00:00+08:00"},
    ]

    response = staff_queue([EVENT], {"evt-1": bookings})

    order = [booking["id"] for booking in response.json["events"][0]["bookings"]]
    assert order == ["older", "newer", "legacy-early", "legacy-late", "approved"]


# AC5 ----


def test_ac5_request_is_listed_under_its_own_event():
    """Normal: each request appears only under the event it was submitted for."""
    other = {**EVENT, "id": "evt-2", "eventName": "Autumn Gala"}
    response = staff_queue(
        [EVENT, other],
        {
            "evt-1": [{**BOOKING, "id": "for-spring"}],
            "evt-2": [{**BOOKING, "id": "for-autumn", "eventId": "evt-2"}],
        },
    )

    grouped = {
        event["eventId"]: [booking["id"] for booking in event["bookings"]]
        for event in response.json["events"]
    }
    assert grouped == {"evt-1": ["for-spring"], "evt-2": ["for-autumn"]}


# AC6 ----


def test_ac6_venue_booked_by_another_event_at_other_time_is_accepted():
    """Normal: when Venue Availability accepts the slot, so does the composite.

    This only proves the composite passes the atomic's answer through. The
    non-overlap rule itself is proven in Venue Availability's integration tests.
    """
    response, _, _, create_booking = submit(EVENT)

    assert response.status_code == 201
    assert response.json == BOOKING
    create_booking.assert_called_once()


def test_ac6_overlap_reported_by_availability_is_a_409():
    """Conflict: an overlap found by Venue Availability is reported with its conflict types."""
    response, _, _, _ = submit(EVENT, BookingConflictError(["APPROVED_BOOKING"]))

    assert response.status_code == 409
    assert response.json["code"] == "VENUE_UNAVAILABLE"
    assert response.json["conflictTypes"] == ["APPROVED_BOOKING"]


# Regression: the staff review route now reads the same named statuses ----


@pytest.mark.parametrize(
    "event_status, expected",
    [(status, 200) for status in REVIEWABLE_EVENT_STATUSES]
    + [("Submitted", 409), ("Pending Safety Check", 409), ("Confirmed", 409)],
)
def test_staff_review_uses_the_same_reviewable_statuses(event_status, expected):
    """Boundary: a Submitted event accepts new requests but staff can't decide until Under Review."""
    with (
        patch("app.routes.get_booking", return_value=BOOKING),
        patch("app.routes.get_event_for_internal_viewer", return_value={"status": event_status}),
        patch("app.routes.get_venue", return_value=VENUES[0]),
        patch("app.routes.decide_booking", return_value={**BOOKING, "status": "Approved"}),
    ):
        response = signed_in(create_app().test_client()).patch(
            "/booking-requests/booking-1/review",
            headers=STAFF_HEADERS,
            json={"reviewedBy": STAFF_ID, "status": "Approved"},
        )

    assert response.status_code == expected
    assert REVIEWABLE_EVENT_STATUSES == ("Under Review", "Approved", "Safety Changes Requested")
