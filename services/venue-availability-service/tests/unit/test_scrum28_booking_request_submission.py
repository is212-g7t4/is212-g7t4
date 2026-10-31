"""
SCRUM-28: Venue Booking Request Submission

User Story
----------
As an Event Coordinator, I want to submit a venue booking request for an event,
so that Venue Staff can assess whether the requested venue arrangement can be
accepted.

Acceptance Criteria
-------------------
AC1: Given an Event Coordinator is preparing a venue booking request for an
     event, when they enter the booking information, then they can provide the
     relevant event timing and venue requirements needed for Venue Staff to
     assess the booking.
AC2: Given the relevant event timing and venue requirements have been provided,
     when the Event Coordinator submits the venue booking request, then the
     request is recorded and made available to Venue Staff for review.
AC3: Given a venue booking request has been submitted, when Venue Staff access
     the request, then they can view the event to which the request relates
     together with the relevant event timing and venue requirements.
AC4: Given a venue booking request has been submitted and has not yet received
     a booking decision, when Venue Staff view requests requiring action, then
     the request can be identified as awaiting Venue Staff review.
AC5: Given an Event Coordinator submits a venue booking request for an event,
     when the request is recorded, then it remains associated with that event
     so that the booking can be assessed in the context of the corresponding
     event requirements.
AC6: Given an Event Coordinator submits a venue booking request for a venue and
     time slot, when the same venue has already been requested or booked for
     another event, and the requested event timing does not overlap with that
     other event's timing, then the request is accepted for Venue Staff review
     as normal, so the same venue can be booked for multiple events across
     non-overlapping time slots.

Real
----
- POST /venue-bookings and the booking serializer: requested_at from the
  database clock, Singapore-time serialisation, and the event link kept on the
  row run for real.
- Assertions are on the SQL and the returned fields.

Doubled
-------
- psycopg2.connect: Stub (`setup`/`client` fixtures) - fresh MagicMock
  connection; the cursor returns canned VenueBooking / VenueClosure rows (or
  raises); executed SQL, parameters and locks are inspected.

Not proven
----------
- That the overlap SQL, locks and constraints behave the same on real
  PostgreSQL (-> tests/integration/, throwaway postgres:17.6, and the opt-in
  tests/live/test_calendar.py).
- AC1 input validation is covered by `test_scrum28_booking_write_regressions.py`.
  AC3/AC4 Venue Staff presentation and pending-queue behaviour are owned by
  Venue Booking Service.
"""

from datetime import datetime, timezone

from app.calendar import SINGAPORE
from app.models import _conflict_types, serialize
from tests.unit.factories import (
    BOOKING_ID, EVENT_ID, USER_ID, VENUE_ID, assert_booking_intent, booking_row,
)

PAYLOAD = {
    "eventId": EVENT_ID,
    "venueId": VENUE_ID,
    "requestedBy": USER_ID,
    "requestedStartTime": "2026-10-01T09:00",
    "requestedEndTime": "2026-10-01T12:00",
    "requiredCapacity": 80,
    "venueRequirements": "  Projector  ",
}


def _insert(cursor):
    return next(
        call.args
        for call in cursor.execute.call_args_list
        if call.args[0].lstrip().startswith("INSERT")
    )


# AC2 ----


def test_ac2_create_booking_records_submission_time_from_database_clock(setup):
    """
    Summary: The time a request was submitted comes from the database clock.
    AC2: Given the relevant event timing and venue requirements have been
        provided, when the Event Coordinator submits the venue booking request,
        then the request is recorded and made available to Venue Staff for
        review.
    Double: Stub (cursor returns the inserted row; SQL inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = booking_row(requested_at=datetime(2026, 9, 1, 10))
    cursor.fetchall.return_value = []

    # Act (When)
    response = client.post("/venue-bookings", json=PAYLOAD)

    # Assert (Then)
    assert response.status_code == 201
    query, params = _insert(cursor)
    assert "status, requested_by, requested_at)" in query
    assert "'Pending Review', %s, now())" in query
    # now() is SQL, so no Python timestamp is sent as a parameter.
    assert len(params) == 8


def test_ac2_create_booking_returns_submission_time_in_singapore_time():
    """
    Summary: Staff and coordinators see the submission time in Singapore time.
    AC2: Given the relevant event timing and venue requirements have been
        provided, when the Event Coordinator submits the venue booking request,
        then the request is recorded and made available to Venue Staff for
        review.
    Double: Stub (cursor returns a UTC timestamp)
    """
    # Arrange (Given)
    row = booking_row(requested_at=datetime(2026, 9, 1, 2, 30, tzinfo=timezone.utc))

    # Act + Assert (When / Then)
    assert serialize(row)["requestedAt"] == "2026-09-01T10:30:00+08:00"


def test_ac2_booking_with_naive_submission_time_is_read_as_singapore_time():
    """
    Summary: A stored time without a zone keeps its wall-clock value.
    AC2: Given the relevant event timing and venue requirements have been
        provided, when the Event Coordinator submits the venue booking request,
        then the request is recorded and made available to Venue Staff for
        review.
    Double: None
    """
    # Arrange (Given)
    row = booking_row(requested_at=datetime(2026, 9, 1, 10, 30))

    # Act + Assert (When / Then)
    assert serialize(row)["requestedAt"] == datetime(
        2026, 9, 1, 10, 30, tzinfo=SINGAPORE
    ).isoformat()


def test_ac2_booking_without_submission_time_returns_null():
    """
    Summary: Older bookings without a submission time return none.
    AC2: Given the relevant event timing and venue requirements have been
        provided, when the Event Coordinator submits the venue booking request,
        then the request is recorded and made available to Venue Staff for
        review.
    Double: None
    """
    # Act + Assert (When / Then)
    assert serialize(booking_row(requested_at=None))["requestedAt"] is None
    assert serialize(booking_row())["requestedAt"] is None


# AC5 ----


def test_ac5_create_booking_keeps_event_id_and_queues_submission_alert(setup):
    """
    Summary: The request stays linked to its event and queues the submission alert.
    AC5: Given an Event Coordinator submits a venue booking request for an
        event, when the request is recorded, then it remains associated with
        that event so that the booking can be assessed in the context of the
        corresponding event requirements.
    Double: Stub (cursor returns the inserted row), Mock (outbox insert
        inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = booking_row()
    cursor.fetchall.return_value = []

    response = client.post("/venue-bookings", json=PAYLOAD)

    # Act (When)
    _, params = _insert(cursor)

    # Assert (Then)
    assert str(params[1]) == EVENT_ID
    assert params[6] == "Projector"
    assert response.json["eventId"] == EVENT_ID
    assert_booking_intent(cursor, "venue.booking-submission-fanout", {
        "bookingId": BOOKING_ID, "eventId": EVENT_ID, "venueId": VENUE_ID,
        "requestedBy": USER_ID, "startDateTime": "2026-10-01T09:00:00+08:00",
        "endDateTime": "2026-10-01T12:00:00+08:00",
    })


# AC6 ----


def test_ac6_create_booking_with_other_events_pending_request_is_accepted(setup):
    """
    Summary: Another event's pending request for the same slot does not block this one.
    AC6: Given an Event Coordinator submits a venue booking request for a venue
        and time slot, when the same venue has already been requested or booked
        for another event, and the requested event timing does not overlap with
        that other event's timing, then the request is accepted for Venue Staff
        review as normal, so the same venue can be booked for multiple events
        across non-overlapping time slots.
    Double: Stub (overlap query finds only a pending request)
    """
    _, cursor = setup
    cursor.fetchall.return_value = []

    for buffers in ((0, 0), (30, 45)):
        cursor.execute.reset_mock()
        _conflict_types(
            cursor,
            VENUE_ID,
            datetime(2026, 10, 1, 9),
            datetime(2026, 10, 1, 12),
            setup_time_minutes=buffers[0],
            turnaround_time_minutes=buffers[1],
        )
        query = cursor.execute.call_args.args[0]
        assert "status IN ('Approved', 'On Hold')" in query
        assert "Pending" not in query
