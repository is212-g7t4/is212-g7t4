"""SCRUM-29 Venue Booking Review and Decision: Venue Availability integration tests.

Story:      As a Venue Staff member, I want to review and decide on a pending venue booking
            request, so that I can determine whether the requested venue arrangement can be
            accepted and provide the Event Coordinator with the outcome.
Real:       Flask app, PATCH /venue-bookings/<id>/approve|reject, PATCH /venue-bookings/<id>,
            GET /events/<id>/venue-bookings, app/models.py SQL (advisory lock, FOR UPDATE,
            buffered conflict query), postgres:17.6 with the full migration chain.
Doubled:    nothing (Venue Availability makes no outbound calls).
Not proven: who the reviewer is (reviewedBy is whatever is sent); the Venue Staff role and
            event-status gates, which run in Venue Booking Service.

AC1  Given a venue booking request is pending review, when Venue Staff open the request, then
     they can view the relevant event timing and venue requirements needed to assess the
     booking.
     Not covered here: the request view is assembled in Venue Booking Service from Event,
     Venue and this service.
AC2  Given Venue Staff determine that a pending venue booking request can be accepted, when
     they approve the request, then the booking decision is recorded as approved and the
     outcome is available to the relevant Event Coordinator.
AC3  Given Venue Staff determine that a pending venue booking request cannot be accepted, when
     they reject the request, then the booking decision is recorded as rejected and the outcome
     is available to the relevant Event Coordinator.
AC4  Given a venue booking request cannot be accepted, when Venue Staff record their decision,
     then they can provide relevant information or a reason explaining why the booking cannot
     be accepted.
AC5  Given Venue Staff have recorded an approval or rejection for a pending venue booking
     request, when the decision is completed, then the request is no longer presented as
     awaiting a booking decision.
AC6  Given a booking request has been rejected and Venue Staff have provided relevant
     information or a reason, when the Event Coordinator views the booking decision, then they
     can view that information so that they can continue planning the event.


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
SCRUM-47 AC2: approval/rejection retain the original requestedBy and decision.
SCRUM-47 AC1: submission intent is verified in test_booking_request_submission.py.
Not proven here: all-staff fanout, display text, links or inbox delivery; the
three Venue Booking dispatcher unit cases cover content/recipients/links, not delivery.
"""

from datetime import datetime, timedelta

import pytest

from tests.integration.factories import (
    COORDINATOR_ID,
    OTHER_COORDINATOR_ID,
    STAFF_ID,
    at,
    assert_booking_intent,
    make_booking,
    make_event,
    make_user,
    make_venue,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

REASON = "Hall is too small for the stage"


@pytest.fixture(autouse=True)
def users(db):
    make_user(db, COORDINATOR_ID)
    make_user(db, OTHER_COORDINATOR_ID)
    make_user(db, STAFF_ID, role="Venue Staff")


def decide(client, booking_id, action, setup=0, turnaround=0, **extra):
    """What Venue Booking Service sends (services/venue-booking-service/app/clients.py)."""
    return client.patch(
        f"/venue-bookings/{booking_id}/{action}",
        json={
            "reviewedBy": STAFF_ID,
            "setupTimeMinutes": setup,
            "turnaroundTimeMinutes": turnaround,
            **extra,
        },
    )


def assert_recent(db, value):
    now = db.now()
    assert now - timedelta(minutes=1) <= value <= now


def pending(db, start=None, end=None, status="Pending Review", venue_id=None, event_id=None):
    venue_id = venue_id or make_venue(db)
    event_id = event_id or make_event(db)
    booking_id = make_booking(
        db, event_id, venue_id, start or at(1, 13), end or at(1, 15), status=status
    )
    return booking_id, venue_id, event_id


# AC2 ----


def test_ac2_approved_decision_is_persisted_with_reviewer_and_time(client, db):
    """Normal: approval commits an alert intent for the submitter despite reassignment."""
    booking_id, venue_id, event_id = pending(db)
    # Reassignment changes today's coordinator, not the original request owner.
    [event] = db.execute(
        'UPDATE public."Event" SET coordinator_id = %s WHERE event_id = %s RETURNING coordinator_id',
        [OTHER_COORDINATOR_ID, event_id],
    )
    assert str(event["coordinator_id"]) == OTHER_COORDINATOR_ID

    response = decide(client, booking_id, "approve")

    assert response.status_code == 200
    row = db.booking(booking_id)
    assert row["status"] == "Approved"
    assert str(row["reviewed_by"]) == STAFF_ID
    assert_recent(db, row["reviewed_at"])
    assert row["rejection_reason"] is None
    body = response.get_json()
    assert body["status"] == "Approved"
    assert body["reviewedBy"] == STAFF_ID
    assert body["reviewedAt"].endswith("+08:00")
    assert body["rejectionReason"] is None

    assert_booking_intent(db, "venue.booking-decision", {
        "bookingId": booking_id, "eventId": event_id, "venueId": venue_id,
        "requestedBy": COORDINATOR_ID, "startDateTime": "2030-03-01T13:00:00+08:00",
        "endDateTime": "2030-03-01T15:00:00+08:00", "decision": "Approved",
    }, row["reviewed_at"])

def test_ac2_approval_overlapping_an_approved_booking_within_buffer_is_refused(client, db):
    """Conflict: setup/turnaround padding makes a 13:14 start clash with a 12:00 finish."""
    venue_id = make_venue(db, setup_time_minutes=30, turnaround_time_minutes=45)
    make_booking(db, make_event(db, OTHER_COORDINATOR_ID), venue_id, at(1, 10), at(1, 12))
    booking_id, _, _ = pending(db, at(1, 13, 14), at(1, 15), venue_id=venue_id)

    response = decide(client, booking_id, "approve", setup=30, turnaround=45)

    assert response.status_code == 409
    assert response.get_json()["code"] == "VENUE_UNAVAILABLE"
    assert response.get_json()["conflictTypes"] == ["APPROVED_BOOKING"]
    row = db.booking(booking_id)
    assert row["status"] == "Pending Review"
    assert row["reviewed_at"] is None


def test_ac2_approval_back_to_back_including_buffers_is_accepted(client, db):
    """Boundary: a 13:15 start meets the other booking's padded end exactly, so it is free."""
    venue_id = make_venue(db, setup_time_minutes=30, turnaround_time_minutes=45)
    make_booking(db, make_event(db, OTHER_COORDINATOR_ID), venue_id, at(1, 10), at(1, 12))
    booking_id, _, _ = pending(db, at(1, 13, 15), at(1, 15), venue_id=venue_id)

    response = decide(client, booking_id, "approve", setup=30, turnaround=45)

    assert response.status_code == 200
    assert db.booking(booking_id)["status"] == "Approved"


def test_ac2_two_pending_requests_for_same_slot_only_first_approval_wins(client, db):
    """Conflict: once A is approved, B for the same slot cannot be, but can be rejected."""
    venue_id = make_venue(db)
    first, _, _ = pending(db, venue_id=venue_id)
    second, _, _ = pending(db, venue_id=venue_id, event_id=make_event(db, OTHER_COORDINATOR_ID))

    assert decide(client, first, "approve").status_code == 200
    refused = decide(client, second, "approve")
    assert refused.status_code == 409
    assert refused.get_json()["code"] == "VENUE_UNAVAILABLE"
    assert db.booking(second)["status"] == "Pending Review"

    rejected = decide(client, second, "reject", rejectionReason=REASON)
    assert rejected.status_code == 200
    assert db.booking(second)["status"] == "Rejected"


# AC3 ----


def test_ac3_rejected_decision_is_persisted_with_reason(client, db):
    """Normal: rejection commits an alert intent for the submitter despite reassignment."""
    booking_id, venue_id, event_id = pending(db)
    # Reassignment changes today's coordinator, not the original request owner.
    [event] = db.execute(
        'UPDATE public."Event" SET coordinator_id = %s WHERE event_id = %s RETURNING coordinator_id',
        [OTHER_COORDINATOR_ID, event_id],
    )
    assert str(event["coordinator_id"]) == OTHER_COORDINATOR_ID

    response = decide(client, booking_id, "reject", rejectionReason=f"  {REASON}  ")

    assert response.status_code == 200
    row = db.booking(booking_id)
    assert row["status"] == "Rejected"
    assert row["rejection_reason"] == REASON
    assert str(row["reviewed_by"]) == STAFF_ID
    assert_recent(db, row["reviewed_at"])
    assert response.get_json()["rejectionReason"] == REASON

    assert_booking_intent(db, "venue.booking-decision", {
        "bookingId": booking_id, "eventId": event_id, "venueId": venue_id,
        "requestedBy": COORDINATOR_ID, "startDateTime": "2030-03-01T13:00:00+08:00",
        "endDateTime": "2030-03-01T15:00:00+08:00", "decision": "Rejected",
    }, row["reviewed_at"])

# AC4 ----


@pytest.mark.parametrize(
    "extra",
    [{}, {"rejectionReason": "   "}, {"rejectionReason": "x" * 501}],
    ids=["missing", "blank", "501-chars"],
)
def test_ac4_reject_without_reason_changes_nothing(client, db, extra):
    """Failure: without a usable reason the booking stays awaiting review."""
    booking_id, _, _ = pending(db)

    response = decide(client, booking_id, "reject", **extra)

    assert response.status_code == 400
    assert response.get_json()["code"] == "REJECTION_REASON_REQUIRED"
    row = db.booking(booking_id)
    assert row["status"] == "Pending Review"
    assert row["reviewed_by"] is None
    assert row["reviewed_at"] is None


# AC5 ----


def test_ac5_second_decision_on_approved_booking_is_refused(client, db):
    """Conflict: an approved booking is final; a later reject changes nothing."""
    booking_id, _, _ = pending(db)
    assert decide(client, booking_id, "approve").status_code == 200
    before = db.booking(booking_id)

    response = decide(client, booking_id, "reject", rejectionReason=REASON)

    assert response.status_code == 409
    assert response.get_json()["code"] == "BOOKING_ALREADY_DECIDED"
    assert db.booking(booking_id) == before


def test_ac5_rejected_booking_cannot_be_approved(client, db):
    """Conflict: a rejected booking is immutable; approving it changes nothing."""
    booking_id, _, _ = pending(db)
    assert decide(client, booking_id, "reject", rejectionReason=REASON).status_code == 200
    before = db.booking(booking_id)

    response = decide(client, booking_id, "approve")

    assert response.status_code == 409
    assert response.get_json()["code"] == "BOOKING_IMMUTABLE"
    assert db.booking(booking_id) == before


def test_ac5_legacy_pending_row_can_be_decided(client, db):
    """Normal: legacy seed rows spelled 'Pending' are still awaiting a decision."""
    booking_id, _, _ = pending(db, status="Pending")

    response = decide(client, booking_id, "approve")

    assert response.status_code == 200
    assert db.booking(booking_id)["status"] == "Approved"


def test_ac5_editing_an_approved_booking_clears_the_old_decision(client, db):
    """Normal: an edited booking rejoins the queue with no stale decision attached."""
    venue_id = make_venue(db)
    event_id = make_event(db)
    booking_id = make_booking(
        db,
        event_id,
        venue_id,
        at(1, 13),
        at(1, 15),
        status="Approved",
        reviewed_by=STAFF_ID,
        reviewed_at=at(1, 9),
    )

    response = client.patch(
        f"/venue-bookings/{booking_id}",
        json={
            "eventId": event_id,
            "venueId": venue_id,
            "requestedStartTime": "2030-03-02T13:00",
            "requestedEndTime": "2030-03-02T15:00",
            "requiredCapacity": 50,
            "venueRequirements": "",
        },
    )

    assert response.status_code == 200
    row = db.booking(booking_id)
    assert row["status"] == "Pending Review"
    assert row["reviewed_by"] is None
    assert row["reviewed_at"] is None
    assert row["rejection_reason"] is None
    assert response.get_json()["reviewedAt"] is None


# AC6 ----


def test_ac6_decision_and_reason_are_returned_with_the_events_bookings(client, db):
    """Normal: the coordinator's booking list carries the reason and Singapore decision time."""
    booking_id, _, event_id = pending(db)
    assert decide(client, booking_id, "reject", rejectionReason=REASON).status_code == 200
    stored = db.booking(booking_id)["reviewed_at"]

    response = client.get(f"/events/{event_id}/venue-bookings")

    assert response.status_code == 200
    [booking] = response.get_json()["bookings"]
    assert booking["status"] == "Rejected"
    assert booking["rejectionReason"] == REASON
    assert booking["reviewedAt"].endswith("+08:00")
    assert datetime.fromisoformat(booking["reviewedAt"]) == stored
