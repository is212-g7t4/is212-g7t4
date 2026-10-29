"""SCRUM-28 Venue Booking Request Submission: Venue Booking Service integration tests.

Story:      As an Event Coordinator, I want to submit a venue booking request for an event,
            so that Venue Staff can assess whether the requested venue arrangement can be
            accepted.
Real:       Flask app, POST /booking-requests and GET /booking-requests routes, validation,
            the event-status gate, the staff-queue grouping, and the real httpx client code
            in app/clients.py.
Doubled:    Event Service (GET /events/<id>, GET /events), Venue Service (GET /venues) and
            Venue Availability (POST /venue-bookings, GET /events/<id>/venue-bookings) with
            respx, at the URLs frozen in app.clients.
Not proven: the overlap rule (only Venue Availability's tests prove it); that the real
            atomics accept these payloads; Supabase sign-in itself (callers are tokens signed
            with a test key, SCRUM-8).

AC1  Given an Event Coordinator is preparing a venue booking request for an event, when they
     enter the booking information, then they can provide the relevant event timing and venue
     requirements needed for Venue Staff to assess the booking.
AC2  Given the relevant event timing and venue requirements have been provided, when the Event
     Coordinator submits the venue booking request, then the request is recorded and made
     available to Venue Staff for review.
AC3  Given a venue booking request has been submitted, when Venue Staff access the request,
     then they can view the event to which the request relates together with the relevant
     event timing and venue requirements.
AC4  Given a venue booking request has been submitted and has not yet received a booking
     decision, when Venue Staff view requests requiring action, then the request can be
     identified as awaiting Venue Staff review.
AC5  Given an Event Coordinator submits a venue booking request for an event, when the request
     is recorded, then it remains associated with that event so that the booking can be
     assessed in the context of the corresponding event requirements.
AC6  Given an Event Coordinator submits a venue booking request for a venue and time slot, when
     the same venue has already been requested or booked for another event, and the requested
     event timing does not overlap with that other event's timing, then the request is accepted
     for Venue Staff review as normal, so the same venue can be booked for multiple events
     across non-overlapping time slots.
     Covered here only as a pass-through of Venue Availability's answer; the rule is proven in
     services/venue-availability-service/tests/integration/test_booking_request_submission.py.
"""

import json

import httpx
import pytest
import respx
from httpx import Response

import app.clients as service_clients
from tests.integration.factories import (
    BOOKING_ID,
    EVENT_ID,
    OTHER_EVENT_ID,
    STAFF_ID,
    VENUE_ID,
    booking,
    event,
    venue,
)
from tests.unit.factories import bearer

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

# What the frontend sends (frontend/event-management-ui/src/features/venue/venueBookings.ts).
REQUEST = {
    "eventId": EVENT_ID,
    "venueId": VENUE_ID,
    "requestedStartTime": "2030-03-01T13:00",
    "requestedEndTime": "2030-03-01T15:00",
    "requiredCapacity": 120,
    "venueRequirements": "  Stage and two microphones  ",
}
STAFF_HEADERS = bearer(STAFF_ID, "Venue Staff")
NOT_SUBMITTABLE = ["Clarification Requested", "Rejected", "Pending Safety Check", "Confirmed", "Cancelled"]


def stub_event(router, payload=None, status_code=200):
    return router.get(
        f"{service_clients.EVENT_SERVICE_URL}/events/{EVENT_ID}",
    ).mock(return_value=Response(status_code, json=payload if payload is not None else event()))


def stub_venues(router, *venues):
    return router.get(f"{service_clients.VENUE_SERVICE_URL}/venues").mock(
        return_value=Response(200, json={"venues": list(venues) or [venue()]})
    )


def stub_create(router, status_code=201, payload=None):
    return router.post(f"{service_clients.VENUE_AVAILABILITY_SERVICE_URL}/venue-bookings").mock(
        return_value=Response(status_code, json=payload if payload is not None else booking())
    )


def stub_staff_events(router, *events):
    return router.get(
        f"{service_clients.EVENT_SERVICE_URL}/events",
        params={"viewerRole": "Venue Staff"},
    ).mock(return_value=Response(200, json={"events": list(events)}))


def stub_event_bookings(router, event_id, *bookings):
    return router.get(
        f"{service_clients.VENUE_AVAILABILITY_SERVICE_URL}/events/{event_id}/venue-bookings"
    ).mock(return_value=Response(200, json={"bookings": list(bookings)}))


# AC2 ----


def test_ac2_valid_request_is_forwarded_once_and_returned_as_pending_review(client):
    """Normal: the request reaches Venue Availability once, with the booking's timing and needs (AC1)."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        event_stub = stub_event(router)
        stub_venues(router)
        create = stub_create(router)

        response = client.post("/booking-requests", json=REQUEST)

    assert response.status_code == 201
    assert response.json["status"] == "Pending Review"
    assert response.json["requestedAt"] == "2030-02-01T10:00:00+08:00"
    # SCRUM-8: the coordinator reaches Event Service as their forwarded token, not an ID.
    assert event_stub.calls.last.request.headers["Authorization"] == client.environ_base["HTTP_AUTHORIZATION"]
    assert "coordinatorId" not in event_stub.calls.last.request.url.params
    assert create.call_count == 1
    assert json.loads(create.calls.last.request.content) == {
        "eventId": EVENT_ID,
        "venueId": VENUE_ID,
        "requestedStartTime": "2030-03-01T13:00",
        "requestedEndTime": "2030-03-01T15:00",
        "requiredCapacity": 120,
        "venueRequirements": "Stage and two microphones",
        "setupTimeMinutes": 30,
        "turnaroundTimeMinutes": 45,
    }


@pytest.mark.parametrize("status", NOT_SUBMITTABLE)
def test_ac2_request_for_event_pending_safety_check_is_refused_before_any_booking_call(client, status):
    """Conflict: only Event Service is registered, so any later call would fail the test."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_event(router, event(status=status))

        response = client.post("/booking-requests", json=REQUEST)

    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_ACCEPTING_VENUE_REQUESTS"
    assert response.json["eventStatus"] == status


def test_ac2_capacity_exactly_equal_to_venue_capacity_is_accepted(client):
    """Boundary: a venue that seats exactly the booking's attendance is big enough."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_event(router)
        stub_venues(router, venue(capacity=120))
        create = stub_create(router)

        response = client.post("/booking-requests", json=REQUEST)

    assert response.status_code == 201
    assert json.loads(create.calls.last.request.content)["requiredCapacity"] == 120


def test_ac2_capacity_one_above_venue_capacity_is_refused(client):
    """Conflict: an over-capacity venue is refused and nothing is recorded."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_event(router)
        stub_venues(router, venue(capacity=119))

        response = client.post("/booking-requests", json=REQUEST)

    assert response.status_code == 422
    assert "capacity (119)" in response.json["message"]


def test_ac2_unassigned_coordinator_is_refused(client):
    """Failure: only the event's assigned coordinator may request a venue for it."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_event(router, {"message": "Not assigned."}, status_code=403)

        response = client.post("/booking-requests", json=REQUEST)

    assert response.status_code == 403


def test_ac2_unknown_event_is_404(client):
    """Failure: a request can't be recorded against an event that doesn't exist."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_event(router, {"message": "Event not found."}, status_code=404)

        response = client.post("/booking-requests", json=REQUEST)

    assert response.status_code == 404


def test_ac2_venue_not_in_catalogue_is_404(client):
    """Failure: the venue must come from the catalogue."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_event(router)
        stub_venues(router, venue(venue_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"))

        response = client.post("/booking-requests", json=REQUEST)

    assert response.status_code == 404


def test_ac2_venue_under_maintenance_is_refused(client):
    """Conflict: a venue that isn't Available can't take requests."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_event(router)
        stub_venues(router, venue(status="Under Maintenance"))

        response = client.post("/booking-requests", json=REQUEST)

    assert response.status_code == 409
    assert "code" not in response.json


@pytest.mark.parametrize(
    "outcome",
    [Response(500, json={"message": "boom"}), httpx.ConnectTimeout("timed out")],
    ids=["event-service-500", "event-service-timeout"],
)
def test_ac2_event_service_failure_or_timeout_is_502(client, outcome):
    """Failure: if the event can't be checked, nothing is recorded."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        route = router.get(
            f"{service_clients.EVENT_SERVICE_URL}/events/{EVENT_ID}",
        )
        if isinstance(outcome, Exception):
            route.mock(side_effect=outcome)
        else:
            route.mock(return_value=outcome)

        response = client.post("/booking-requests", json=REQUEST)

    assert response.status_code == 502


# AC3 ----


def test_ac3_staff_queue_shows_event_timing_and_request_details(client):
    """Normal: staff see the event, its dates and the booking's own schedule and needs (AC5)."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_staff_events(router, event())
        stub_venues(router)
        stub_event_bookings(router, EVENT_ID, booking())

        response = client.get("/booking-requests", headers=STAFF_HEADERS)

    assert response.status_code == 200
    [listed] = response.json["events"]
    assert listed["eventId"] == EVENT_ID
    assert listed["eventName"] == "Spring Fair"
    assert listed["eventStart"] == "2030-03-01T09:00:00"
    assert listed["eventEnd"] == "2030-03-01T17:00:00"
    [request] = listed["bookings"]
    assert request["eventId"] == EVENT_ID
    assert request["venueName"] == "Grand Ballroom"
    assert request["requestedStartTime"] == "2030-03-01T13:00:00"
    assert request["requestedEndTime"] == "2030-03-01T15:00:00"
    assert request["venueRequirements"] == "Stage and two microphones"


# AC4 ----


def test_ac4_new_request_is_flagged_awaiting_review(client):
    """Normal: new and legacy pending spellings are both awaiting review; the filter returns both."""
    legacy_id = "ffffffff-ffff-4fff-8fff-ffffffffffff"
    approved_id = "99999999-9999-4999-8999-999999999999"
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_staff_events(router, event(), event(event_id=OTHER_EVENT_ID, name="Autumn Gala"))
        stub_venues(router)
        stub_event_bookings(
            router, EVENT_ID,
            booking(), booking(status="Pending", booking_id=legacy_id, requested_at=None),
        )
        stub_event_bookings(
            router, OTHER_EVENT_ID,
            booking(status="Approved", booking_id=approved_id, event_id=OTHER_EVENT_ID),
        )

        everything = client.get("/booking-requests", headers=STAFF_HEADERS)
        awaiting = client.get("/booking-requests?status=Pending", headers=STAFF_HEADERS)

    by_event = {e["eventId"]: e for e in everything.json["events"]}
    assert by_event[EVENT_ID]["awaitingReviewCount"] == 2
    assert [b["awaitingReview"] for b in by_event[EVENT_ID]["bookings"]] == [True, True]
    assert by_event[OTHER_EVENT_ID]["awaitingReviewCount"] == 0
    assert by_event[OTHER_EVENT_ID]["bookings"][0]["awaitingReview"] is False
    [only] = awaiting.json["events"]
    assert only["eventId"] == EVENT_ID
    assert [b["id"] for b in only["bookings"]] == [BOOKING_ID, legacy_id]


def test_ac4_staff_queue_requires_venue_staff_role(client):
    """Failure: a coordinator can't open the staff queue; no downstream call is made."""
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        response = client.get(
            "/booking-requests",
            headers=bearer(STAFF_ID, "Event Coordinator"),
        )

    assert response.status_code == 403
    assert router.calls.call_count == 0


# AC6 ----


def test_ac6_conflict_from_availability_is_passed_through(client):
    """Conflict: Venue Availability's overlap answer reaches the coordinator unchanged.

    This proves the pass-through, not the rule: the 409 is the stub's canned answer.
    """
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_event(router)
        stub_venues(router)
        stub_create(
            router,
            status_code=409,
            payload={
                "message": "This venue is unavailable for the requested time.",
                "code": "VENUE_UNAVAILABLE",
                "conflictTypes": ["APPROVED_BOOKING"],
            },
        )

        response = client.post("/booking-requests", json=REQUEST)

    assert response.status_code == 409
    assert response.json["code"] == "VENUE_UNAVAILABLE"
    assert response.json["conflictTypes"] == ["APPROVED_BOOKING"]
