"""Shared helpers for Safety Check Service's unit tests."""

EVENT_ID = "00000000-0000-0000-0000-000000000001"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OTHER_COORDINATOR_ID = "22222222-2222-4222-8222-222222222222"
BOOKING_ID = "66666666-6666-4666-8666-666666666666"
REQUEST_ID = "77777777-7777-4777-8777-777777777777"
RECORD_ID = "55555555-5555-4555-8555-555555555555"


def booking(status="Approved", booking_id=BOOKING_ID, **overrides):
    """A booking as `venue-availability-service` serialises it."""
    return {
        "id": booking_id,
        "eventId": EVENT_ID,
        "venueId": "88888888-8888-4888-8888-888888888888",
        "requestedStartTime": "2026-11-12T09:00:00",
        "requestedEndTime": "2026-11-12T17:00:00",
        "requiredCapacity": 120,
        "venueRequirements": "Stage and projector",
        "status": status,
        "requestedBy": COORDINATOR_ID,
        "reviewedBy": None,
        **overrides,
    }


def equipment_request(status="Approved", request_id=REQUEST_ID, **overrides):
    """An equipment request as `equipment-request-service` serialises it."""
    return {
        "id": request_id,
        "eventId": EVENT_ID,
        "equipmentId": "99999999-9999-4999-8999-999999999999",
        "quantityRequested": 2,
        "technicalRequirements": "Two wireless mics",
        "status": status,
        "reviewedBy": None,
        **overrides,
    }


def event(status="Approved"):
    """Only the fields this composite reads from Event Service."""
    return {
        "id": EVENT_ID,
        "eventName": "Community Workshop",
        "status": status,
        "coordinatorId": COORDINATOR_ID,
        "actionHistory": [],
    }


def record(round_number=1, status="Pending", **overrides):
    """A round as `safety-check-record-service` serialises it."""
    return {
        "id": RECORD_ID,
        "eventId": EVENT_ID,
        "roundNumber": round_number,
        "submittedBy": COORDINATOR_ID,
        "submittedAt": "2026-11-01T02:30:00+00:00",
        "equipmentPlacementNotes": None,
        "crowdMovementNotes": None,
        "status": status,
        "decidedBy": None,
        "decidedAt": None,
        "remarks": None,
        **overrides,
    }
