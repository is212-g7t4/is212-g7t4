"""Stub response bodies for Safety Check Service's integration tests.

Each mirrors the real atomic's serialiser (cited per builder), so a stub cannot drift
from the JSON the real service returns. Dates are fixed and in 2030.
"""

EVENT_ID = "00000000-0000-4000-8000-000000000167"
OFFICER_ID = "33333333-3333-4333-8333-333333333333"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
STAFF_ID = "55555555-5555-4555-8555-555555555555"
HALL_ID = "88888888-8888-4888-8888-888888888888"
ROOM_ID = "89898989-8989-4989-8989-898989898989"
ROUND_ID = "77777777-7777-4777-8777-777777777777"


def user(role="Safety Officer", user_id=OFFICER_ID):
    """services/user-service/app/models.py::serialize."""
    return {
        "user_id": user_id,
        "username": "Safety Officer One",
        "email": "safety.officer@example.com",
        "role": role,
        "organization": "",
        "contact_details": "",
    }


def event(status="Pending Safety Check"):
    """services/event-service/app/models.py::serialize."""
    return {
        "eventName": "Harbour Festival",
        "description": "An evening festival.",
        "purpose": "Community",
        "preferredStartDate": "2030-03-01T18:00:00+08:00",
        "preferredEndDate": "2030-03-01T22:00:00+08:00",
        "expectedAttendance": "100",
        "venueRequirements": "Stage",
        "accessibilityNeeds": "",
        "equipmentRequirements": "",
        "registrationNeeds": "",
        "withdrawalDeadline": "",
        "id": EVENT_ID,
        "status": status,
        "submittedAt": "2030-01-10T02:00:00+00:00",
        "coordinatorId": COORDINATOR_ID,
        "organiserId": None,
        "assignedBy": None,
        "assignedAt": None,
        "previousCoordinatorId": None,
        "decision": None,
        "decisionHistory": [],
        "actionDetails": None,
        "actionHistory": [],
        "clarificationHistory": [],
    }


def booking(venue_id, booking_id):
    """services/venue-availability-service/app/models.py::serialize."""
    return {
        "id": booking_id,
        "eventId": EVENT_ID,
        "venueId": venue_id,
        "requestedStartTime": "2030-03-01T18:00:00+08:00",
        "requestedEndTime": "2030-03-01T22:00:00+08:00",
        "requiredCapacity": 100,
        "venueRequirements": "Stage",
        "status": "Approved",
        "requestedBy": COORDINATOR_ID,
        "reviewedBy": STAFF_ID,
        "requestedAt": "2030-01-05T10:00:00+08:00",
        "reviewedAt": "2030-01-06T10:00:00+08:00",
    }


def safety_round():
    """services/safety-check-record-service/app/models.py::serialize."""
    return {
        "id": ROUND_ID,
        "eventId": EVENT_ID,
        "roundNumber": 1,
        "submittedBy": COORDINATOR_ID,
        "submittedAt": "2030-01-12T02:00:00+00:00",
        "equipmentPlacementNotes": None,
        "crowdMovementNotes": None,
        "status": "Pending",
        "decidedBy": None,
        "decidedAt": None,
        "remarks": None,
        "withdrawnAt": None,
        "withdrawnBy": None,
        "withdrawalReason": None,
        "flags": [],
    }


def venue(venue_id, name, emergency=None, restrictions=None):
    """services/venue-service/app/models.py::serialize, with SCRUM-167's four fields."""
    return {
        "id": venue_id,
        "name": name,
        "location": "Harbour Wing",
        "capacity": 200,
        "facilities": ["wifi"],
        "accessibility": "Wheelchair accessible",
        "supportedLayouts": ["theatre"],
        "status": "Available",
        "setupTimeMinutes": 30,
        "turnaroundTimeMinutes": 30,
        "emergencyAccessDetails": emergency,
        "knownRestrictions": restrictions,
        "safetyInfoUpdatedBy": STAFF_ID if emergency or restrictions else None,
        "safetyInfoUpdatedAt": "2030-01-08T10:30:00+08:00" if emergency or restrictions else None,
    }
