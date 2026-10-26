"""SCRUM-29 Venue Booking Review and Decision: Venue Booking Service integration tests.

Story:      As a Venue Staff member, I want to review and decide on a pending venue booking
            request, so that I can determine whether the requested venue arrangement can be
            accepted and provide the Event Coordinator with the outcome.
Real:       Flask app, GET /booking-requests/<id>, PATCH /booking-requests/<id>/review,
            GET /booking-requests, GET /events/<id>/booking-requests, the role, reason,
            event-status and awaiting-review gates, and the real httpx client code in
            app/clients.py.
Doubled:    Venue Availability (GET /venue-bookings/<id>, PATCH /venue-bookings/<id>/approve|
            reject, GET /events/<id>/venue-bookings), Event Service (GET /events/<id>,
            GET /events) and Venue Service (GET /venues/<id>, GET /venues) with respx, at the
            URLs frozen in app.clients.
Not proven: that the decision is persisted, or the buffered conflict rule (only Venue
            Availability's tests prove them); that the real atomics accept these payloads;
            caller identity (X-Dev-* headers and coordinatorId are whatever the caller sends).

AC1  Given a venue booking request is pending review, when Venue Staff open the request, then
     they can view the relevant event timing and venue requirements needed to assess the
     booking.
AC2  Given Venue Staff determine that a pending venue booking request can be accepted, when
     they approve the request, then the booking decision is recorded as approved and the
     outcome is available to the relevant Event Coordinator.
     Covered here as the forwarding of the decision; the record itself is proven in
     services/venue-availability-service/tests/integration/test_booking_review_decision.py.
AC3  Given Venue Staff determine that a pending venue booking request cannot be accepted, when
     they reject the request, then the booking decision is recorded as rejected and the outcome
     is available to the relevant Event Coordinator.
AC4  Given a venue booking request cannot be accepted, when Venue Staff record their decision,
     then they can provide relevant information or a reason explaining why the booking cannot
     be accepted.
AC5  Given Venue Staff have recorded an approval or rejection for a pending venue booking
     request, when the decision is completed, then the request is no longer presented as
     awaiting a booking decision.
AC6  Given a booking request has been rejected and Venue Staff have provided relevant
     information or a reason, when the Event Coordinator views the booking decision, then they
     can view that information so that they can continue planning the event.
"""

import json

import httpx
import pytest
import respx
from httpx import Response

import app.clients as service_clients
from tests.integration.factories import (
    BOOKING_ID,
    COORDINATOR_ID,
    EVENT_ID,
    STAFF_ID,
    VENUE_ID,
    booking,
    event,
    venue,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

# What the frontend sends (frontend/event-management-ui/src/features/venue/venueBookings.ts).
STAFF_HEADERS = {"X-Dev-User-Id": STAFF_ID, "X-Dev-Role": "Venue Staff"}
REASON = "Hall is too small for the stage"
AVAILABILITY = service_clients.VENUE_AVAILABILITY_SERVICE_URL


def stub_booking(router, payload=None):
    return router.get(f"{AVAILABILITY}/venue-bookings/{BOOKING_ID}").mock(
        return_value=Response(200, json=payload or booking())
    )


def stub_staff_event(router, payload=None, **mock):
    route = router.get(
        f"{service_clients.EVENT_SERVICE_URL}/events/{EVENT_ID}",
        params={"coordinatorId": STAFF_ID, "viewerRole": "Venue Staff"},
    )
    return route.mock(**(mock or {"return_value": Response(200, json=payload or event())}))


def stub_venue(router, payload=None):
    return router.get(f"{service_clients.VENUE_SERVICE_URL}/venues/{VENUE_ID}").mock(
        return_value=Response(200, json={"venue": payload or venue()})
    )


def stub_decide(router, action, status_code=200, payload=None):
    return router.patch(f"{AVAILABILITY}/venue-bookings/{BOOKING_ID}/{action}").mock(
        return_value=Response(status_code, json=payload if payload is not None else booking())
    )


def review(client, status, **extra):
    return client.patch(
        f"/booking-requests/{BOOKING_ID}/review",
        headers=STAFF_HEADERS,
        json={"status": status, "reviewedBy": STAFF_ID, **extra},
    )


# AC1 ----


def test_ac1_opened_request_combines_booking_event_and_venue_details(client):
    """Normal: Venue Staff see the event's timing and needs beside the booking and venue limits."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_booking(router, booking(start="2030-03-01T10:00:00", end="2030-03-01T12:00:00"))
        event_stub = stub_staff_event(router)
        stub_venue(router)

        response = client.get(f"/booking-requests/{BOOKING_ID}", headers=STAFF_HEADERS)

    assert response.status_code == 200
    params = event_stub.calls.last.request.url.params
    assert params["coordinatorId"] == STAFF_ID
    assert params["viewerRole"] == "Venue Staff"
    body = response.json
    assert body["event"] == {
        "id": EVENT_ID,
        "eventName": "Spring Fair",
        "status": "Under Review",
        "coordinatorId": COORDINATOR_ID,
        "preferredStartDate": "2030-03-01T09:00:00",
        "preferredEndDate": "2030-03-01T17:00:00",
        "expectedAttendance": "120",
        "venueRequirements": "Stage",
        "accessibilityNeeds": None,
    }
    assert body["venue"] == {
        "id": VENUE_ID,
        "name": "Grand Ballroom",
        "capacity": 150,
        "status": "Available",
        "setupTimeMinutes": 30,
        "turnaroundTimeMinutes": 45,
    }
    assert body["booking"]["venueRequirements"] == "Stage and two microphones"
    assert body["booking"]["occupiedFrom"] == "2030-03-01T09:30:00"
    assert body["booking"]["occupiedTo"] == "2030-03-01T12:45:00"
    assert body["booking"]["awaitingReview"] is True
    assert body["canDecide"] is True


def test_ac1_request_view_for_non_staff_makes_no_downstream_call(client):
    """Failure: no stub is registered, so any downstream call would fail the test."""
    with respx.mock(assert_all_mocked=True):
        response = client.get(
            f"/booking-requests/{BOOKING_ID}",
            headers={"X-Dev-User-Id": COORDINATOR_ID, "X-Dev-Role": "Event Coordinator"},
        )

    assert response.status_code == 403


def test_ac1_event_service_timeout_is_504(client):
    """Failure: a slow Event Service is reported as a timeout, not a crash."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_booking(router)
        stub_staff_event(router, side_effect=httpx.ConnectTimeout("slow"))
        stub_venue(router)

        response = client.get(f"/booking-requests/{BOOKING_ID}", headers=STAFF_HEADERS)

    assert response.status_code == 504


# AC2 ----


def test_ac2_approve_forwards_reviewer_and_buffers_once(client):
    """Normal: the approval reaches Venue Availability once, with the venue's buffers."""
    decided = booking(status="Approved", reviewed_by=STAFF_ID, reviewed_at="2030-02-02T09:00:00+08:00")
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_booking(router)
        stub_staff_event(router)
        stub_venue(router)
        approve = stub_decide(router, "approve", payload=decided)

        response = review(client, "Approved")

    assert response.status_code == 200
    assert response.json["status"] == "Approved"
    assert response.json["reviewedAt"] == "2030-02-02T09:00:00+08:00"
    assert approve.call_count == 1
    assert json.loads(approve.calls.last.request.content) == {
        "reviewedBy": STAFF_ID,
        "setupTimeMinutes": 30,
        "turnaroundTimeMinutes": 45,
    }


def test_ac2_conflict_on_approval_is_passed_through(client):
    """Conflict: proves the pass-through of Venue Availability's refusal, not the rule."""
    body = {"code": "VENUE_UNAVAILABLE", "conflictTypes": ["TENTATIVE_HOLD"],
            "message": "This venue is unavailable for the requested time."}
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_booking(router)
        stub_staff_event(router)
        stub_venue(router)
        stub_decide(router, "approve", 409, body)

        response = review(client, "Approved")

    assert response.status_code == 409
    assert response.json["code"] == "VENUE_UNAVAILABLE"
    assert response.json["conflictTypes"] == ["TENTATIVE_HOLD"]


def test_ac2_availability_failure_is_502(client):
    """Failure: Venue Availability failing to record the decision is a dependency error."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_booking(router)
        stub_staff_event(router)
        stub_venue(router)
        stub_decide(router, "approve", 500, {"message": "boom"})

        response = review(client, "Approved")

    assert response.status_code == 502


# AC3 ----


def test_ac3_ac4_reject_forwards_the_stripped_reason_once(client):
    """Normal: the rejection and its trimmed reason reach Venue Availability exactly once."""
    decided = booking(status="Rejected", reviewed_by=STAFF_ID, rejection_reason=REASON)
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_booking(router)
        stub_staff_event(router)
        reject = stub_decide(router, "reject", payload=decided)

        response = review(client, "Rejected", rejectionReason=f"  {REASON}\n")

    assert response.status_code == 200
    assert response.json["rejectionReason"] == REASON
    assert reject.call_count == 1
    assert json.loads(reject.calls.last.request.content) == {
        "reviewedBy": STAFF_ID,
        "setupTimeMinutes": 0,
        "turnaroundTimeMinutes": 0,
        "rejectionReason": REASON,
    }


# AC4 ----


def test_ac4_reject_without_reason_is_400_before_any_call(client):
    """Failure: no stub is registered, so the refusal provably happens before any call."""
    with respx.mock(assert_all_mocked=True):
        response = review(client, "Rejected", rejectionReason="   ")

    assert response.status_code == 400
    assert response.json["code"] == "REJECTION_REASON_REQUIRED"


# AC5 ----


def test_ac5_decided_booking_is_409_without_calling_availability_decide(client):
    """Conflict: only the booking and event lookups are registered; no decide call is made."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_booking(router, booking(status="Approved"))
        stub_staff_event(router)

        response = review(client, "Rejected", rejectionReason=REASON)

    assert response.status_code == 409
    assert response.json["code"] == "BOOKING_ALREADY_DECIDED"


def test_ac5_availability_race_409_is_passed_through(client):
    """Conflict: another staff member deciding first keeps its BOOKING_ALREADY_DECIDED code."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_booking(router)
        stub_staff_event(router)
        stub_venue(router)
        stub_decide(
            router, "approve", 409,
            {"code": "BOOKING_ALREADY_DECIDED", "message": "This venue request has already been decided."},
        )

        response = review(client, "Approved")

    assert response.status_code == 409
    assert response.json["code"] == "BOOKING_ALREADY_DECIDED"


def test_event_pending_safety_check_is_not_reviewable(client):
    """Conflict: during the safety check the event is not open to venue decisions."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_booking(router)
        stub_staff_event(router, event(status="Pending Safety Check"))

        response = review(client, "Approved")

    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_REVIEWABLE"
    assert response.json["eventStatus"] == "Pending Safety Check"


def test_ac5_staff_queue_no_longer_lists_decided_request_as_awaiting(client):
    """Normal: one decided and one awaiting booking count as one awaiting decision."""
    awaiting = booking()
    decided = booking(status="Rejected", booking_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
                      reviewed_by=STAFF_ID, reviewed_at="2030-02-02T09:00:00+08:00",
                      rejection_reason=REASON)
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        router.get(
            f"{service_clients.EVENT_SERVICE_URL}/events",
            params={"coordinatorId": STAFF_ID, "viewerRole": "Venue Staff"},
        ).mock(return_value=Response(200, json={"events": [event()]}))
        router.get(f"{service_clients.VENUE_SERVICE_URL}/venues").mock(
            return_value=Response(200, json={"venues": [venue()]})
        )
        router.get(f"{AVAILABILITY}/events/{EVENT_ID}/venue-bookings").mock(
            return_value=Response(200, json={"bookings": [awaiting, decided]})
        )

        every = client.get("/booking-requests", headers=STAFF_HEADERS)
        pending = client.get("/booking-requests?status=Pending", headers=STAFF_HEADERS)

    [group] = every.json["events"]
    assert group["awaitingReviewCount"] == 1
    flags = {item["id"]: item["awaitingReview"] for item in group["bookings"]}
    assert flags == {BOOKING_ID: True, decided["id"]: False}
    assert [item["id"] for item in pending.json["events"][0]["bookings"]] == [BOOKING_ID]


# AC6 ----


def test_ac6_coordinator_sees_rejection_reason_and_decision_time(client):
    """Normal: the assigned coordinator's booking list shows why and when it was rejected."""
    rejected = booking(status="Rejected", reviewed_by=STAFF_ID,
                       reviewed_at="2030-02-02T09:00:00+08:00", rejection_reason=REASON)
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        router.get(
            f"{service_clients.EVENT_SERVICE_URL}/events/{EVENT_ID}",
            params={"coordinatorId": COORDINATOR_ID},
        ).mock(return_value=Response(200, json=event()))
        router.get(f"{AVAILABILITY}/events/{EVENT_ID}/venue-bookings").mock(
            return_value=Response(200, json={"bookings": [rejected]})
        )
        router.get(f"{service_clients.VENUE_SERVICE_URL}/venues").mock(
            return_value=Response(200, json={"venues": [venue()]})
        )

        response = client.get(f"/events/{EVENT_ID}/booking-requests?coordinatorId={COORDINATOR_ID}")

    assert response.status_code == 200
    [item] = response.json["bookings"]
    assert item["status"] == "Rejected"
    assert item["rejectionReason"] == REASON
    assert item["reviewedAt"] == "2030-02-02T09:00:00+08:00"
    assert item["venueName"] == "Grand Ballroom"
