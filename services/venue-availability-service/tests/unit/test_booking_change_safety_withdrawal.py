"""
SCRUM-157: Manage Individual Venue Arrangements

User Story
----------
As an Event Coordinator, I want to modify or cancel a specific venue booking
for an event, so that I can adjust one venue arrangement without affecting the
event's other venue arrangements.

Acceptance Criteria
-------------------
AC1: Given an event has one or more venue bookings, when the Event Coordinator
     modifies a specific booking, then only that selected booking is updated.
AC2: If a modification changes the venue, date/time, required capacity, or
     other suitability requirements, then suitability, availability, and
     conflict checks are performed again for that booking only.
AC3: Given an event has multiple venue bookings, when the Event Coordinator
     cancels one booking, then only the selected booking is cancelled and the
     other bookings remain unchanged.
AC4: Cancelling or modifying one venue booking does not automatically change
     the status of the event's other venue bookings.
AC5: A cancelled booking remains associated with the event with a Cancelled
     status for record keeping.

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
AC7: Given an event is 'Confirmed' after passing its Operational Safety Check,
     when the Event Coordinator edits or cancels one of its venue bookings,
     then the event's safety approval is withdrawn without opening a new safety
     check round, the event returns to 'Approved', and an edited booking
     returns to awaiting Venue Staff review, so the event must be submitted for
     a safety check again. If the booking change cannot be saved, the safety
     approval is restored and the event stays 'Confirmed'. While the event is
     'Pending Safety Check', its venue bookings cannot be edited or cancelled.

Real
----
- PATCH /venue-bookings/<id>: the edit resets the booking to Pending Review
  with requested_at = now() and Singapore-aware times.
- Assertions are on the SQL and returned times.

Doubled
-------
- psycopg2.connect: Stub (`setup`/`client` fixtures) - fresh MagicMock
  connection; the cursor returns canned VenueBooking / VenueClosure rows (or
  raises); executed SQL, parameters and locks are inspected.

Not proven
----------
- The whole chain across Venue Booking, Safety Check, Safety Check Record and
  Event Services (-> docs/test-scripts/scrum-28-venue-booking-request-
  submission.md, Part B, run by hand against the stack).
"""

from datetime import datetime

from app.calendar import SINGAPORE
from tests.unit.factories import BOOKING_ID, EVENT_ID, USER_ID, VENUE_ID, booking_row


def test_edit_booking_resets_to_pending_review_with_new_request_time(setup):
    """
    Summary: An edited booking goes back to Venue Staff as Pending Review, queued by the time of the edit.
    AC2: If a modification changes the venue, date/time, required capacity, or
        other suitability requirements, then suitability, availability, and
        conflict checks are performed again for that booking only.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor returns the updated row; SQL inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [booking_row(status="Approved", reviewed_by=USER_ID), booking_row()]
    cursor.fetchall.return_value = []

    # Act (When)
    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}",
        json={
            "eventId": EVENT_ID,
            "venueId": VENUE_ID,
            "requestedStartTime": "2026-10-01T09:00",
            "requestedEndTime": "2026-10-01T12:00",
            "requiredCapacity": 80,
            "venueRequirements": "Projector",
        },
    )

    # Assert (Then)
    assert response.status_code == 200
    update = next(call.args[0] for call in cursor.execute.call_args_list if "UPDATE public" in call.args[0])
    assert "status = 'Pending Review'" in update
    assert "requested_at = now()" in update


def test_edit_booking_sends_and_returns_singapore_times(setup):
    """
    Summary: Edited times are stored and returned in Singapore time, not shifted by 8 hours.
    AC1: Given an event has one or more venue bookings, when the Event
        Coordinator modifies a specific booking, then only that selected
        booking is updated.
    Double: Stub (cursor returns the updated row; parameters inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [booking_row(), booking_row()]
    cursor.fetchall.return_value = []

    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}",
        json={
            "eventId": EVENT_ID,
            "venueId": VENUE_ID,
            "requestedStartTime": "2026-10-01T09:00",
            "requestedEndTime": "2026-10-01T12:00",
            "requiredCapacity": 80,
            "venueRequirements": "Projector",
        },
    )

    # Act (When)
    params = next(call.args[1] for call in cursor.execute.call_args_list if "UPDATE public" in call.args[0])

    # Assert (Then)
    assert params[1] == datetime(2026, 10, 1, 9, tzinfo=SINGAPORE)
    assert params[2] == datetime(2026, 10, 1, 12, tzinfo=SINGAPORE)
    assert response.json["requestedStartTime"] == "2026-10-01T09:00:00"
