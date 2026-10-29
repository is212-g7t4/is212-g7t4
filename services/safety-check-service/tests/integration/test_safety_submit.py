"""SCRUM-149 Submit Event for Operational Safety Check: Safety Check Service integration tests.

Story:      As an Event Coordinator, I want to submit my event for an Operational Safety
            Check once its venue and technical arrangements are confirmed, so that the
            Safety Officer can review it before preparation begins.
Real:       Flask app, POST /safety-checks and GET /safety-checks/readiness, the
            event-status check, the ThreadPoolExecutor read of both arrangements, the
            readiness rule in app/readiness.py, and the real httpx code in app/clients.py.
Doubled:    with respx: Event Service (GET /events/<id>, PATCH /events/<id>/safety-status),
            Venue Availability (GET /events/<id>/venue-bookings), Equipment Request
            (GET /equipment-requests, read as the coordinator), Safety Check Record
            (POST /safety-check-records).
Not proven: that the live Equipment Request Service spells the status "Rejected" (its
            STATUSES in app/__init__.py does today); Supabase sign-in itself (the coordinator
            is a token signed with a test key, SCRUM-8); the full journey on the real stack.

AC1  Given an event assigned to the Event Coordinator has at least one approved venue
     booking, and none of its venue bookings or equipment requests is still pending, when
     the Event Coordinator submits it for a safety check, then its status changes to
     'Pending Safety Check' and the submission time is recorded. Rejected, cancelled or
     expired venue bookings and rejected equipment requests are no longer part of the
     event's arrangements and do not block submission.
AC2  Given any venue booking or equipment request for the event is still pending, or the
     event has no approved venue booking, when the Event Coordinator tries to submit, then
     submission is blocked and the outstanding arrangements are listed.
AC3  Given the Event Coordinator is submitting, when they enter equipment placement and
     expected crowd movement notes, then the notes are saved with the safety check.
     Not covered here: unchanged by the rejected-requests fix; tests/unit/test_safety_submit.py
     covers the notes reaching the record service, and the record service stores them.
AC4  Given the event is already 'Pending Safety Check', when the Event Coordinator submits
     it again, then no duplicate safety check is created.
     Not covered here: unchanged by the rejected-requests fix; the duplicate guard is the
     record service's, and tests/unit/test_safety_submit.py covers this service's 409.
AC5  Given the Event Coordinator is not the assigned coordinator, then the submit action is
     not available and an API call is rejected.
     Not covered here: unchanged by the rejected-requests fix; Event Service makes the
     assignment check, and tests/unit/test_safety_submit.py covers this service's 403.
"""

import json

import pytest
from httpx import Response

import app.clients as service_clients
from tests.integration.factories import (
    COORDINATOR_ID,
    EVENT_ID,
    HALL_ID,
    ROUND_ID,
    booking,
    equipment_request,
    event,
    safety_round,
)
from tests.unit.factories import signed_in

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

BOOKING_ID = "44444444-4444-4444-8444-444444444444"
REJECTED_REQUEST_ID = "66666666-6666-4666-8666-666666666666"
PENDING_REQUEST_ID = "67676767-6767-4767-8767-676767676767"


def stub_reads(router, bookings, requests):
    """Every read a submit or readiness call makes, with the URLs and queries app/clients.py sends."""
    router.get(
        f"{service_clients.EVENT_SERVICE_URL}/events/{EVENT_ID}",
    ).mock(return_value=Response(200, json=event("Approved")))
    router.get(
        f"{service_clients.VENUE_AVAILABILITY_SERVICE_URL}/events/{EVENT_ID}/venue-bookings"
    ).mock(return_value=Response(200, json={"bookings": bookings}))
    router.get(
        f"{service_clients.EQUIPMENT_REQUEST_SERVICE_URL}/equipment-requests",
        params={"eventId": EVENT_ID},
    ).mock(return_value=Response(200, json={"requests": requests}))


def stub_writes(router):
    """The record POST and event PATCH a successful submit makes, in that order."""
    created = router.post(
        f"{service_clients.SAFETY_CHECK_RECORD_SERVICE_URL}/safety-check-records"
    ).mock(return_value=Response(201, json=safety_round()))
    moved = router.patch(
        f"{service_clients.EVENT_SERVICE_URL}/events/{EVENT_ID}/safety-status"
    ).mock(return_value=Response(200, json=event("Pending Safety Check")))
    return created, moved


def sent(route):
    return json.loads(route.calls.last.request.content)


def as_coordinator(client):
    return signed_in(client, COORDINATOR_ID, "Event Coordinator")


def submit(client):
    return as_coordinator(client).post("/safety-checks", json={"eventId": EVENT_ID})


# AC1 ----------------------------------------------------------------------


def test_ac1_rejected_equipment_request_does_not_block_readiness(client, stubs):
    """Normal: the event stuck in the 28 Oct bug report now reads as ready, with nothing written."""
    stub_reads(
        stubs,
        [booking(HALL_ID, BOOKING_ID)],
        [equipment_request("Rejected", REJECTED_REQUEST_ID)],
    )

    response = as_coordinator(client).get(
        "/safety-checks/readiness",
        query_string={"eventId": EVENT_ID},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "ready": True,
        "eventStatus": "Approved",
        "outstanding": [],
        "openSafetyCheck": None,
    }


def test_ac1_rejected_equipment_request_does_not_block_submission(client, stubs):
    """Normal: the round is created, then the event moves to 'Pending Safety Check'."""
    stub_reads(
        stubs,
        [booking(HALL_ID, BOOKING_ID)],
        [equipment_request("Rejected", REJECTED_REQUEST_ID)],
    )
    created, moved = stub_writes(stubs)

    response = submit(client)

    assert response.status_code == 201
    assert response.get_json()["event"]["status"] == "Pending Safety Check"
    assert created.call_count == 1
    assert sent(created) == {
        "eventId": EVENT_ID,
        "equipmentPlacementNotes": None,
        "crowdMovementNotes": None,
    }
    assert moved.call_count == 1
    assert sent(moved) == {
        "status": "Pending Safety Check",
        "safetyCheckId": ROUND_ID,
        "roundNumber": 1,
    }
    # SCRUM-8: the coordinator is identified downstream by their forwarded token.
    assert {call.request.headers["Authorization"] for call in stubs.calls} == {client.environ_base["HTTP_AUTHORIZATION"]}


# AC2 ----------------------------------------------------------------------


def test_ac2_rejected_booking_and_request_still_report_no_venue(client, stubs):
    """Boundary: with every arrangement rejected, only the missing venue blocks and nothing is written."""
    # No write stubs are registered, so a record POST or event PATCH fails the test.
    stub_reads(
        stubs,
        [booking(HALL_ID, BOOKING_ID, "Rejected")],
        [equipment_request("Rejected", REJECTED_REQUEST_ID)],
    )

    response = submit(client)

    assert response.status_code == 422
    assert response.get_json()["code"] == "ARRANGEMENTS_OUTSTANDING"
    assert [item["label"] for item in response.get_json()["outstanding"]] == [
        "No venue booking"
    ]


def test_ac2_pending_equipment_request_beside_a_rejected_one_still_blocks(client, stubs):
    """Conflict: only rejections stop blocking, so the pending request is listed and nothing is written."""
    # No write stubs are registered, so a record POST or event PATCH fails the test.
    stub_reads(
        stubs,
        [booking(HALL_ID, BOOKING_ID)],
        [
            equipment_request("Rejected", REJECTED_REQUEST_ID),
            equipment_request("Pending", PENDING_REQUEST_ID),
        ],
    )

    response = submit(client)

    assert response.status_code == 422
    assert response.get_json()["code"] == "ARRANGEMENTS_OUTSTANDING"
    assert response.get_json()["outstanding"] == [
        {
            "type": "equipment",
            "id": PENDING_REQUEST_ID,
            "status": "Pending",
            "label": "Equipment request × 100",
            "reason": "Waiting for Technical Support approval.",
        }
    ]
