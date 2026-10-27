"""SCRUM-28 Venue Booking Request Submission: Venue Availability integration tests.

Story:      As an Event Coordinator, I want to submit a venue booking request for an event,
            so that Venue Staff can assess whether the requested venue arrangement can be
            accepted.
Real:       Flask app, POST /venue-bookings and GET /events/<id>/venue-bookings, validation,
            app/models.py SQL (advisory lock, venue row lock, buffered overlap query),
            postgres:17.6 with the full migration chain.
Doubled:    nothing (Venue Availability makes no outbound calls).
Not proven: who the caller is (requestedBy is whatever is sent); the event-status gate and
            the venue catalogue/capacity checks, which run in Venue Booking Service.

AC1  Given an Event Coordinator is preparing a venue booking request for an event, when they
     enter the booking information, then they can provide the relevant event timing and venue
     requirements needed for Venue Staff to assess the booking.
AC2  Given the relevant event timing and venue requirements have been provided, when the Event
     Coordinator submits the venue booking request, then the request is recorded and made
     available to Venue Staff for review.
AC3  Not covered here: the Venue Staff queue is built in Venue Booking Service.
AC4  Not covered here: the "awaiting review" flag is computed in Venue Booking Service; this
     file proves the stored status it is computed from (AC2).
AC5  Given an Event Coordinator submits a venue booking request for an event, when the request
     is recorded, then it remains associated with that event so that the booking can be
     assessed in the context of the corresponding event requirements.
AC6  Given an Event Coordinator submits a venue booking request for a venue and time slot, when
     the same venue has already been requested or booked for another event, and the requested
     event timing does not overlap with that other event's timing, then the request is accepted
     for Venue Staff review as normal, so the same venue can be booked for multiple events
     across non-overlapping time slots.


SCRUM-47 Venue booking notification and decision alerts (additional assertions only).
Story: As an Event Coordinator and Venue Staff, I want to receive notifications
about venue booking requests and decisions, so that I can coordinate venue
arrangements efficiently.
AC1 Given an Event Coordinator submits a venue booking request, system sends
an in-app notification to Venue Staff with event name, requested venue,
date/time and link to review.
AC2 Given booking approved/rejected, sends an in-app notification to Event
Coordinator with event name, venue, decision.
AC means acceptance criterion; DR means supporting design rule. Original story
AC numbering below is unchanged; SCRUM-47 has only AC1 and AC2.
Real: Flask/mutation SQL and fixture-owned PostgreSQL with full migrations.
Doubled: nothing; independent connections read the persisted intent.
SCRUM-47 AC1: successful submission retains the exact original source snapshot.
SCRUM-47 AC2: decision intent is verified in test_booking_review_decision.py.
Not proven here: all-staff fanout, display text, links or inbox delivery; the
three Venue Booking dispatcher unit cases cover content/recipients/links, not delivery.
"""

from datetime import datetime, timedelta

import pytest

from tests.integration.factories import (
    COORDINATOR_ID,
    OTHER_COORDINATOR_ID,
    SINGAPORE,
    STAFF_ID,
    at,
    assert_booking_intent,
    make_booking,
    make_closure,
    make_event,
    make_hold,
    make_user,
    make_venue,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


@pytest.fixture(autouse=True)
def users(db):
    make_user(db, COORDINATOR_ID)
    make_user(db, OTHER_COORDINATOR_ID)
    make_user(db, STAFF_ID, role="Venue Staff")


def request_body(event_id, venue_id, start="2030-03-01T13:00", end="2030-03-01T15:00", **overrides):
    """What Venue Booking Service sends (services/venue-booking-service/app/clients.py)."""
    body = {
        "eventId": event_id,
        "venueId": venue_id,
        "requestedBy": COORDINATOR_ID,
        "requestedStartTime": start,
        "requestedEndTime": end,
        "requiredCapacity": 60,
        "venueRequirements": "Stage and two microphones",
        "setupTimeMinutes": 0,
        "turnaroundTimeMinutes": 0,
    }
    body.update(overrides)
    return body


# AC1 ----


def test_ac1_booking_timing_capacity_and_requirements_are_stored_as_sent(client, db):
    """Normal: Venue Staff assess exactly the timing and requirements the coordinator entered."""
    venue_id = make_venue(db, capacity=100)
    event_id = make_event(db)

    response = client.post(
        "/venue-bookings",
        json=request_body(
            event_id, venue_id, requiredCapacity=75, venueRequirements="  Wheelchair ramp  "
        ),
    )

    assert response.status_code == 201
    [row] = db.bookings()
    assert row["requested_start_time"] == at(1, 13)
    assert row["requested_end_time"] == at(1, 15)
    assert row["required_capacity"] == 75
    assert row["venue_requirements"] == "Wheelchair ramp"
    assert str(row["requested_by"]) == COORDINATOR_ID
    assert response.get_json()["requestedStartTime"] == "2030-03-01T13:00:00"
    assert response.get_json()["venueRequirements"] == "Wheelchair ramp"


# AC2 ----


def test_ac2_valid_request_is_stored_as_pending_review_with_submission_time(client, db):
    """Normal: the pending request and exact submission intent commit together."""
    venue_id = make_venue(db)
    event_id = make_event(db)

    response = client.post("/venue-bookings", json=request_body(event_id, venue_id))

    assert response.status_code == 201
    [row] = db.bookings()
    assert row["status"] == "Pending Review"
    now = db.now()
    assert now - timedelta(minutes=1) <= row["requested_at"] <= now
    body = response.get_json()
    assert body["id"] == str(row["booking_id"])
    assert body["status"] == "Pending Review"
    assert datetime.fromisoformat(body["requestedAt"]) == row["requested_at"]
    assert body["requestedAt"].endswith("+08:00")
    assert_booking_intent(db, "venue.booking-submission-fanout", {
        "bookingId": body["id"], "eventId": event_id, "venueId": venue_id,
        "requestedBy": COORDINATOR_ID, "startDateTime": "2030-03-01T13:00:00+08:00",
        "endDateTime": "2030-03-01T15:00:00+08:00",
    }, row["requested_at"])


@pytest.mark.parametrize(
    "overrides",
    [
        {"requestedEndTime": "2030-03-01T13:00"},
        {"requiredCapacity": 0},
        {"eventId": None},
        {"venueId": "not-a-uuid"},
    ],
    ids=["end-not-after-start", "zero-capacity", "missing-event", "invalid-venue-id"],
)
def test_ac2_invalid_request_stores_nothing(client, db, overrides):
    """Failure: an incomplete request is refused and never reaches the staff queue."""
    venue_id = make_venue(db)
    event_id = make_event(db)

    response = client.post("/venue-bookings", json=request_body(event_id, venue_id, **overrides))

    assert response.status_code == 400
    assert db.bookings() == []


# AC5 ----


def test_ac5_request_is_returned_with_its_event(client, db):
    """Normal: the request stays linked to the event it was submitted for, and only that one."""
    venue_id = make_venue(db)
    event_id = make_event(db, name="Spring Fair")
    other_event_id = make_event(db, name="Autumn Gala", coordinator_id=OTHER_COORDINATOR_ID)

    created = client.post("/venue-bookings", json=request_body(event_id, venue_id)).get_json()

    [row] = db.bookings()
    assert str(row["event_id"]) == event_id
    listed = client.get(f"/events/{event_id}/venue-bookings").get_json()["bookings"]
    assert [booking["id"] for booking in listed] == [created["id"]]
    assert listed[0]["eventId"] == event_id
    assert client.get(f"/events/{other_event_id}/venue-bookings").get_json()["bookings"] == []


# AC6 ----


def test_ac6_same_venue_other_event_non_overlapping_slot_is_accepted(client, db):
    """Normal: one venue can serve two events on the same day at different times."""
    venue_id = make_venue(db)
    event_a = make_event(db, name="Morning Talk", coordinator_id=OTHER_COORDINATOR_ID)
    event_b = make_event(db, name="Afternoon Workshop")
    make_booking(db, event_a, venue_id, at(1, 9), at(1, 11), requested_by=OTHER_COORDINATOR_ID)

    response = client.post(
        "/venue-bookings",
        json=request_body(event_b, venue_id, "2030-03-01T13:00", "2030-03-01T15:00"),
    )

    assert response.status_code == 201
    assert response.get_json()["status"] == "Pending Review"
    assert [(str(r["event_id"]), r["status"]) for r in db.bookings(venue_id)] == [
        (event_a, "Approved"),
        (event_b, "Pending Review"),
    ]


def test_ac6_same_venue_back_to_back_with_no_buffers_is_accepted(client, db):
    """Boundary: starting exactly when the other event ends is not an overlap (half-open)."""
    venue_id = make_venue(db)
    event_a = make_event(db, coordinator_id=OTHER_COORDINATOR_ID)
    event_b = make_event(db)
    make_booking(db, event_a, venue_id, at(1, 9), at(1, 11), requested_by=OTHER_COORDINATOR_ID)

    response = client.post(
        "/venue-bookings",
        json=request_body(event_b, venue_id, "2030-03-01T11:00", "2030-03-01T13:00"),
    )

    assert response.status_code == 201
    assert len(db.bookings(venue_id)) == 2


def test_ac6_back_to_back_including_buffer_minutes_is_accepted(client, db):
    """Boundary: 12:00 end + 45 min turnaround + 30 min setup lets the next event start at 13:15."""
    venue_id = make_venue(db, setup_time_minutes=30, turnaround_time_minutes=45)
    event_a = make_event(db, coordinator_id=OTHER_COORDINATOR_ID)
    event_b = make_event(db)
    make_booking(db, event_a, venue_id, at(1, 10), at(1, 12), requested_by=OTHER_COORDINATOR_ID)

    response = client.post(
        "/venue-bookings",
        json=request_body(
            event_b,
            venue_id,
            "2030-03-01T13:15",
            "2030-03-01T15:00",
            setupTimeMinutes=30,
            turnaroundTimeMinutes=45,
        ),
    )

    assert response.status_code == 201
    assert len(db.bookings(venue_id)) == 2


def test_ac6_one_minute_inside_the_buffer_conflicts(client, db):
    """Conflict: starting at 13:14 eats one minute of the venue's turnaround and setup time."""
    venue_id = make_venue(db, setup_time_minutes=30, turnaround_time_minutes=45)
    event_a = make_event(db, coordinator_id=OTHER_COORDINATOR_ID)
    event_b = make_event(db)
    make_booking(db, event_a, venue_id, at(1, 10), at(1, 12), requested_by=OTHER_COORDINATOR_ID)

    response = client.post(
        "/venue-bookings",
        json=request_body(
            event_b,
            venue_id,
            "2030-03-01T13:14",
            "2030-03-01T15:00",
            setupTimeMinutes=30,
            turnaroundTimeMinutes=45,
        ),
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "VENUE_UNAVAILABLE"
    assert response.get_json()["conflictTypes"] == ["APPROVED_BOOKING"]
    assert len(db.bookings(venue_id)) == 1


def test_ac6_pending_request_of_another_event_does_not_block(client, db):
    """Normal: a slot that is only requested (not approved) by another event stays open."""
    venue_id = make_venue(db)
    event_a = make_event(db, coordinator_id=OTHER_COORDINATOR_ID)
    event_b = make_event(db)
    make_booking(
        db, event_a, venue_id, at(1, 13), at(1, 15), status="Pending Review",
        requested_by=OTHER_COORDINATOR_ID,
    )

    response = client.post("/venue-bookings", json=request_body(event_b, venue_id))

    assert response.status_code == 201
    assert [r["status"] for r in db.bookings(venue_id)] == ["Pending Review", "Pending Review"]


def test_ac6_overlapping_approved_booking_is_refused(client, db):
    """Conflict: the same venue at an overlapping time for another event is a double-booking."""
    venue_id = make_venue(db)
    event_a = make_event(db, coordinator_id=OTHER_COORDINATOR_ID)
    event_b = make_event(db)
    make_booking(db, event_a, venue_id, at(1, 14), at(1, 16), requested_by=OTHER_COORDINATOR_ID)

    response = client.post("/venue-bookings", json=request_body(event_b, venue_id))

    assert response.status_code == 409
    assert response.get_json()["conflictTypes"] == ["APPROVED_BOOKING"]
    assert [str(r["event_id"]) for r in db.bookings(venue_id)] == [event_a]


@pytest.mark.parametrize("status", ["Cancelled", "Rejected"])
def test_ac6_cancelled_or_rejected_booking_does_not_block(client, db, status):
    """Normal: a booking that no longer stands frees its slot for another event."""
    venue_id = make_venue(db)
    event_a = make_event(db, coordinator_id=OTHER_COORDINATOR_ID)
    event_b = make_event(db)
    make_booking(
        db, event_a, venue_id, at(1, 13), at(1, 15), status=status,
        requested_by=OTHER_COORDINATOR_ID,
    )

    response = client.post("/venue-bookings", json=request_body(event_b, venue_id))

    assert response.status_code == 201
    assert len(db.bookings(venue_id)) == 2


@pytest.mark.parametrize(
    "expires_in, expected",
    [(timedelta(days=1), 409), (timedelta(hours=-1), 201)],
    ids=["active-hold-blocks", "expired-hold-does-not"],
)
def test_ac6_active_hold_blocks_but_expired_hold_does_not(client, db, expires_in, expected):
    """Conflict/Boundary: a tentative hold blocks only until it expires (expiry relative to now)."""
    venue_id = make_venue(db)
    event_id = make_event(db)
    make_hold(db, venue_id, at(1, 12), at(1, 16), expires_at=datetime.now(SINGAPORE) + expires_in)

    response = client.post("/venue-bookings", json=request_body(event_id, venue_id))

    assert response.status_code == expected
    stored = [r["status"] for r in db.bookings(venue_id)]
    if expected == 409:
        assert response.get_json()["conflictTypes"] == ["TENTATIVE_HOLD"]
        assert stored == ["On Hold"]
    else:
        assert sorted(stored) == ["On Hold", "Pending Review"]


def test_ac6_closure_overlapping_the_slot_is_refused(client, db):
    """Conflict: a venue closed for repairs cannot take a request for that time."""
    venue_id = make_venue(db)
    event_id = make_event(db)
    make_closure(db, venue_id, at(1, 14), at(1, 18))

    response = client.post("/venue-bookings", json=request_body(event_id, venue_id))

    assert response.status_code == 409
    assert response.get_json()["conflictTypes"] == ["VENUE_CLOSURE"]
    assert db.bookings(venue_id) == []
