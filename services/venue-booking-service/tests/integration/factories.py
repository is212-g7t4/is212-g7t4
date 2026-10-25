"""Downstream response builders for Venue Booking Service's integration tests.

Each builder mirrors the JSON the real atomic returns, so a stub can't drift from the API it
stands in for. The source serialiser is cited on each one.
"""

EVENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER_EVENT_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
VENUE_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
BOOKING_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
STAFF_ID = "33333333-3333-4333-8333-333333333333"


def event(status="Under Review", event_id=EVENT_ID, name="Spring Fair", start="2030-03-01T09:00:00",
          end="2030-03-01T17:00:00"):
    """services/event-service/app/models.py::serialize (GET /events/<id> and GET /events)."""
    return {
        "id": event_id,
        "eventName": name,
        "description": "",
        "purpose": "",
        "preferredStartDate": start,
        "preferredEndDate": end,
        "expectedAttendance": "120",
        "venueRequirements": "Stage",
        "accessibilityNeeds": "",
        "equipmentRequirements": "",
        "registrationNeeds": "",
        "withdrawalDeadline": "",
        "status": status,
        "submittedAt": "2030-01-05T01:00:00+00:00",
        "coordinatorId": COORDINATOR_ID,
        "organiserId": "44444444-4444-4444-8444-444444444444",
        "assignedBy": None,
        "assignedAt": None,
        "previousCoordinatorId": None,
        "decision": None,
        "decisionHistory": [],
        "actionDetails": None,
        "actionHistory": [],
        "clarificationHistory": [],
    }


def venue(capacity=150, status="Available", setup=30, turnaround=45, venue_id=VENUE_ID, name="Grand Ballroom"):
    """services/venue-service/app/models.py::serialize (GET /venues)."""
    return {
        "id": venue_id,
        "name": name,
        "location": "Level 2",
        "capacity": capacity,
        "facilities": ["Projector"],
        "accessibility": "",
        "supportedLayouts": ["Theatre"],
        "status": status,
        "setupTimeMinutes": setup,
        "turnaroundTimeMinutes": turnaround,
    }


def booking(status="Pending Review", booking_id=BOOKING_ID, event_id=EVENT_ID,
            requested_at="2030-02-01T10:00:00+08:00", start="2030-03-01T13:00:00"):
    """services/venue-availability-service/app/models.py::serialize."""
    return {
        "id": booking_id,
        "eventId": event_id,
        "venueId": VENUE_ID,
        "requestedStartTime": start,
        "requestedEndTime": "2030-03-01T15:00:00",
        "requiredCapacity": 120,
        "venueRequirements": "Stage and two microphones",
        "status": status,
        "requestedBy": COORDINATOR_ID,
        "reviewedBy": None,
        "requestedAt": requested_at,
        "conflictReason": None,
        "closureRejection": None,
    }
