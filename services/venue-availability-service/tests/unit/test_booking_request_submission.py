"""SCRUM-28 Venue Booking Request Submission: Venue Availability unit tests.

Story: As an Event Coordinator, I want to submit a venue booking request for an
event, so that Venue Staff can assess whether the requested venue arrangement
can be accepted.

This atomic owns the stored request and the overlap rule. The event-status gate
(AC2) and the staff queue (AC3, AC4) run in Venue Booking Service; the real-SQL
behaviour of AC1, AC2, AC5 and AC6 is proven in
tests/integration/test_booking_request_submission.py.
"""

from datetime import datetime, timezone

from app.calendar import SINGAPORE
from app.models import _conflict_types, serialize
from tests.unit.factories import EVENT_ID, USER_ID, VENUE_ID, booking_row

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
    """Normal: the request is stored against the event it was submitted for."""
    client, cursor = setup
    cursor.fetchone.return_value = booking_row()
    cursor.fetchall.return_value = []

    response = client.post("/venue-bookings", json=PAYLOAD)

    _, params = _insert(cursor)
    assert str(params[1]) == EVENT_ID
    assert params[6] == "Projector"
    assert response.json["eventId"] == EVENT_ID


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
