"""SCRUM-28 Venue Booking Request Submission (Part B): Venue Booking Service integration tests.

Story:      As an Event Coordinator, I want to submit a venue booking request for an event,
            so that Venue Staff can assess whether the requested venue arrangement can be
            accepted.
            Part B (Clarice, 25 Oct): editing or cancelling a venue booking is gated by the
            event's status, and on a 'Confirmed' event it first withdraws the safety
            approval (the event goes back to 'Approved').
Real:       Flask app, PATCH /booking-requests/<id>, validation, the edit gate, the
            withdraw-then-change-then-restore orchestration, and the real httpx client code
            in app/clients.py.
Doubled:    Event Service, Venue Service, Safety Check Service and Venue Availability with
            respx, at the URLs frozen in app.clients.
Not proven: that Safety Check Service really withdraws/restores the approval (its own tests,
            and Event Service's integration tests, prove the moves); the end-to-end chain
            across real services, which is in the manual test script.

AC1-AC6  Not covered here: Part B goes beyond the six SCRUM-28 ACs.
"""

import json

import pytest
import respx
from httpx import Response

import app.clients as service_clients
from tests.integration.factories import (
    BOOKING_ID,
    EVENT_ID,
    VENUE_ID,
    booking,
    event,
    venue,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

WITHDRAWN_ID = "77777777-7777-4777-8777-777777777777"
EDIT = {
    "eventId": EVENT_ID,
    "venueId": VENUE_ID,
    "requestedStartTime": "2030-03-01T14:00",
    "requestedEndTime": "2030-03-01T16:00",
    "requiredCapacity": 120,
    "venueRequirements": "Stage moved to the north wall",
}
REASON = "A venue booking (Grand Ballroom) was edited after safety approval."


def stub_event(router, status):
    return router.get(
        f"{service_clients.EVENT_SERVICE_URL}/events/{EVENT_ID}",
    ).mock(return_value=Response(200, json=event(status=status)))


def stub_withdraw(router):
    # services/safety-check-service/app/routes.py::withdraw_for_venue_change
    return router.post(
        f"{service_clients.SAFETY_CHECK_SERVICE_URL}/safety-checks/withdraw-for-venue-change"
    ).mock(return_value=Response(200, json={
        "event": event(status="Approved"),
        "withdrawnSafetyCheck": {"id": WITHDRAWN_ID, "roundNumber": 2, "status": "Approval Withdrawn"},
        "bookingId": BOOKING_ID,
    }))


def stub_update(router, status_code=200, payload=None):
    return router.patch(
        f"{service_clients.VENUE_AVAILABILITY_SERVICE_URL}/venue-bookings/{BOOKING_ID}"
    ).mock(return_value=Response(status_code, json=payload if payload is not None else booking()))


def test_confirmed_edit_withdraws_the_approval_then_updates_the_booking(client):
    """Normal: Event -> Venue -> Safety Check withdraw -> Venue Availability, with exact bodies."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_event(router, "Confirmed")
        router.get(f"{service_clients.VENUE_SERVICE_URL}/venues").mock(
            return_value=Response(200, json={"venues": [venue()]})
        )
        withdraw = stub_withdraw(router)
        update = stub_update(router)

        response = client.patch(f"/booking-requests/{BOOKING_ID}", json=EDIT)
        # respx clears router.calls when the block exits, so read the order here.
        order = [call.request.url.path for call in router.calls]

    assert response.status_code == 200
    assert order == [
        f"/events/{EVENT_ID}",
        "/venues",
        "/safety-checks/withdraw-for-venue-change",
        f"/venue-bookings/{BOOKING_ID}",
    ]
    assert json.loads(withdraw.calls.last.request.content) == {
        "eventId": EVENT_ID, "bookingId": BOOKING_ID, "reason": REASON,
    }
    # SCRUM-8: Safety Check Service learns the coordinator from the forwarded token.
    assert withdraw.calls.last.request.headers["Authorization"] == client.environ_base["HTTP_AUTHORIZATION"]
    assert json.loads(update.calls.last.request.content) == {
        "eventId": EVENT_ID,
        "venueId": VENUE_ID,
        "requestedStartTime": "2030-03-01T14:00",
        "requestedEndTime": "2030-03-01T16:00",
        "requiredCapacity": 120,
        "venueRequirements": "Stage moved to the north wall",
        "setupTimeMinutes": 30,
        "turnaroundTimeMinutes": 45,
    }


def test_conflicting_confirmed_edit_restores_the_approval_once(client):
    """Conflict: a venue conflict after the withdrawal triggers exactly one restore."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_event(router, "Confirmed")
        router.get(f"{service_clients.VENUE_SERVICE_URL}/venues").mock(
            return_value=Response(200, json={"venues": [venue()]})
        )
        stub_withdraw(router)
        stub_update(router, 409, {
            "message": "This venue is unavailable for the requested time.",
            "code": "VENUE_UNAVAILABLE",
            "conflictTypes": ["APPROVED_BOOKING"],
        })
        restore = router.post(
            f"{service_clients.SAFETY_CHECK_SERVICE_URL}/safety-checks/restore-after-venue-change"
        ).mock(return_value=Response(200, json={"event": event(status="Confirmed"), "safetyCheck": {"id": WITHDRAWN_ID}}))

        response = client.patch(f"/booking-requests/{BOOKING_ID}", json=EDIT)

    assert response.status_code == 409
    assert response.json["code"] == "VENUE_UNAVAILABLE"
    assert restore.call_count == 1
    assert json.loads(restore.calls.last.request.content) == {
        "eventId": EVENT_ID, "withdrawnSafetyCheckId": WITHDRAWN_ID,
    }


@pytest.mark.parametrize("path, body", [
    (f"/booking-requests/{BOOKING_ID}", EDIT),
    (f"/booking-requests/{BOOKING_ID}/cancel", {"eventId": EVENT_ID}),
], ids=["edit", "cancel"])
def test_pending_safety_check_event_refuses_changes_with_only_the_event_read(client, path, body):
    """Conflict: only Event Service is registered, so any later call would fail the test."""
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        stub_event(router, "Pending Safety Check")

        response = client.patch(path, json=body)

    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_ACCEPTING_VENUE_CHANGES"
