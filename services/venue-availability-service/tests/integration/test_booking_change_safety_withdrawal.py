"""SCRUM-28 Venue Booking Request Submission (Part B): Venue Availability integration tests.

Story:      As an Event Coordinator, I want to submit a venue booking request for an event,
            so that Venue Staff can assess whether the requested venue arrangement can be
            accepted.
            Part B (Clarice, 25 Oct): an edited booking goes back to Venue Staff for review
            and, for a Confirmed event, its safety approval is withdrawn.
Real:       Flask app, PATCH /venue-bookings/<id>, app/models.py SQL, postgres:17.6 with the
            full migration chain.
Doubled:    nothing (Venue Availability makes no outbound calls).
Not proven: the safety withdrawal and the event-status gate, which run in Safety Check
            Service and Venue Booking Service.

AC1-AC6  Not covered here: Part B goes beyond the six SCRUM-28 ACs. This file proves that
         an edited request rejoins the staff queue as a fresh submission, at the time the
         coordinator entered.
"""

from datetime import timedelta

import pytest

from tests.integration.factories import (
    COORDINATOR_ID,
    STAFF_ID,
    at,
    make_booking,
    make_event,
    make_user,
    make_venue,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


def test_edit_resets_review_and_restamps_the_submission_time(client, db):
    """Normal: the edited request is Pending Review again, unreviewed, stamped with now()."""
    make_user(db, COORDINATOR_ID)
    make_user(db, STAFF_ID, role="Venue Staff")
    venue_id = make_venue(db)
    event_id = make_event(db, status="Confirmed")
    booking_id = make_booking(db, event_id, venue_id, at(1, 9), at(1, 11))
    db.execute(
        """UPDATE public."VenueBooking" SET reviewed_by = %s, requested_at = now() - interval '30 days'
           WHERE booking_id = %s""",
        [STAFF_ID, booking_id],
    )

    response = client.patch(
        f"/venue-bookings/{booking_id}",
        json={
            "eventId": event_id,
            "venueId": venue_id,
            "requestedStartTime": "2030-03-01T10:00",
            "requestedEndTime": "2030-03-01T12:00",
            "requiredCapacity": 40,
            "venueRequirements": "Moved one hour later",
        },
    )

    assert response.status_code == 200
    row = db.booking(booking_id)
    assert row["status"] == "Pending Review"
    assert row["reviewed_by"] is None
    assert row["requested_start_time"] == at(1, 10)
    assert row["requested_end_time"] == at(1, 12)
    now = db.now()
    assert now - timedelta(minutes=1) <= row["requested_at"] <= now
    assert response.get_json()["requestedAt"] is not None
    # Same shape as POST /venue-bookings: naive Singapore local time.
    assert response.get_json()["requestedStartTime"] == "2030-03-01T10:00:00"
    assert response.get_json()["requestedEndTime"] == "2030-03-01T12:00:00"


def test_edit_keeps_the_singapore_wall_clock_time(client, db):
    """Boundary: an edit to 10:00 is stored as 10:00 SGT, not 10:00 UTC (18:00 SGT)."""
    make_user(db, COORDINATOR_ID)
    venue_id = make_venue(db)
    event_id = make_event(db)
    booking_id = make_booking(db, event_id, venue_id, at(1, 9), at(1, 11), status="Pending Review")

    response = client.patch(
        f"/venue-bookings/{booking_id}",
        json={
            "eventId": event_id,
            "venueId": venue_id,
            "requestedStartTime": "2030-03-01T10:00",
            "requestedEndTime": "2030-03-01T12:00",
            "requiredCapacity": 40,
            "venueRequirements": "",
        },
    )

    assert response.status_code == 200
    stored = db.booking(booking_id)
    assert stored["requested_start_time"] == at(1, 10)
    listed = client.get(f"/events/{event_id}/venue-bookings").get_json()["bookings"]
    assert listed[0]["requestedStartTime"] == "2030-03-01T10:00:00"
