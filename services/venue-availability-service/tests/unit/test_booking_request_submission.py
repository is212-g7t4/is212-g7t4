"""SCRUM-28 Venue Booking Request Submission: Venue Availability unit tests.

Story: As an Event Coordinator, I want to submit a venue booking request for an
event, so that Venue Staff can assess whether the requested venue arrangement
can be accepted.

This atomic owns the stored request and the overlap rule. The event-status gate
(AC2) and the staff queue (AC3, AC4) run in Venue Booking Service; the real-SQL
behaviour of AC1, AC2, AC5 and AC6 is proven in
tests/integration/test_booking_request_submission.py.


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
Real: Flask routes, validation and model transaction/SQL construction.
Doubled: psycopg2 connection/cursor; SQL ordering is not durable-commit proof.
SCRUM-47 AC1: successful submission retains the exact original source snapshot.
SCRUM-47 AC2: decision intent is verified in test_booking_review_decision.py.
Not proven here: all-staff fanout, display text, links or inbox delivery; the
three Venue Booking dispatcher unit cases cover content/recipients/links, not delivery.
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


def test_ac2_insert_stamps_requested_at_with_database_now(setup):
    """Normal: the database clock records when the request was submitted."""
    client, cursor = setup
    cursor.fetchone.return_value = booking_row(requested_at=datetime(2026, 9, 1, 10))
    cursor.fetchall.return_value = []

    response = client.post("/venue-bookings", json=PAYLOAD)

    assert response.status_code == 201
    query, params = _insert(cursor)
    assert "status, requested_by, requested_at)" in query
    assert "'Pending Review', %s, now())" in query
    # now() is SQL, so no Python timestamp is sent as a parameter.
    assert len(params) == 8


def test_ac2_response_includes_requested_at_in_singapore_time():
    """Normal: staff and coordinators see the submission time in local time."""
    row = booking_row(requested_at=datetime(2026, 9, 1, 2, 30, tzinfo=timezone.utc))

    assert serialize(row)["requestedAt"] == "2026-09-01T10:30:00+08:00"


def test_ac2_naive_requested_at_is_read_as_singapore_time():
    """Boundary: a localised row keeps its wall-clock submission time."""
    row = booking_row(requested_at=datetime(2026, 9, 1, 10, 30))

    assert serialize(row)["requestedAt"] == datetime(
        2026, 9, 1, 10, 30, tzinfo=SINGAPORE
    ).isoformat()


def test_ac2_legacy_row_without_requested_at_serialises_as_null():
    """Boundary: rows recorded before SCRUM-28 have no submission time."""
    assert serialize(booking_row(requested_at=None))["requestedAt"] is None
    assert serialize(booking_row())["requestedAt"] is None


# AC5 ----


def test_ac5_created_row_keeps_the_submitted_event_id(setup):
    """Normal: the request keeps its event and queues the exact SCRUM-47 submission intent."""
    client, cursor = setup
    cursor.fetchone.return_value = booking_row()
    cursor.fetchall.return_value = []

    response = client.post("/venue-bookings", json=PAYLOAD)

    _, params = _insert(cursor)
    assert str(params[1]) == EVENT_ID
    assert params[6] == "Projector"
    assert response.json["eventId"] == EVENT_ID
    assert_booking_intent(cursor, "venue.booking-submission-fanout", {
        "bookingId": BOOKING_ID, "eventId": EVENT_ID, "venueId": VENUE_ID,
        "requestedBy": USER_ID, "startDateTime": "2026-10-01T09:00:00+08:00",
        "endDateTime": "2026-10-01T12:00:00+08:00",
    })


# AC6 ----


def test_ac6_pending_request_of_other_event_does_not_block(setup):
    """Normal: only approvals and holds block a slot, never another request."""
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
