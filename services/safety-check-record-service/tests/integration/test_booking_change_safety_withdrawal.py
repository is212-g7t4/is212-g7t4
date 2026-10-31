"""SCRUM-28 Venue Booking Request Submission: Safety Check Record Service integration tests.

Story:      As an Event Coordinator, I want to submit a venue booking request for an event, so
            that Venue Staff can assess whether the requested venue arrangement can be accepted.
Real:       Flask app and routes, token verification and the role check, validation,
            app/models.py SQL (withdraw without opening a round, restore), postgres:17.6 with
            the full migration chain.
Doubled:    nothing (Safety Check Record Service makes no outbound calls).
Not proven: the booking edit or cancellation itself (Venue Availability), the event's move back
            to 'Approved' (Event Service) and the order of those calls (Venue Booking); Supabase
            sign-in itself (SCRUM-8).

AC1  Not covered here: booking information is captured by Venue Booking and Venue Availability.
AC2  Not covered here: the request is recorded by Venue Availability.
AC3  Not covered here: Venue Staff's view is served by Venue Booking.
AC4  Not covered here: the awaiting-review state is held by Venue Availability.
AC5  Not covered here: the booking-to-event link is held by Venue Availability.
AC6  Not covered here: the overlap rule runs in Venue Availability.
AC7  Given an event is 'Confirmed' after passing its Operational Safety Check, when the Event
     Coordinator edits or cancels one of its venue bookings, then the event's safety approval is
     withdrawn without opening a new safety check round, the event returns to 'Approved', and an
     edited booking returns to awaiting Venue Staff review, so the event must be submitted for a
     safety check again. If the booking change cannot be saved, the safety approval is restored
     and the event stays 'Confirmed'. While the event is 'Pending Safety Check', its venue
     bookings cannot be edited or cancelled.
     Covered here: the safety record side (withdraw with no new round; restore on failure).
"""

import pytest

from tests.integration.factories import COORDINATOR_ID, as_user, make_event, make_people, make_round

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

COORDINATOR = as_user(COORDINATOR_ID)
REASON = "Venue booking changed after safety approval."


@pytest.fixture(autouse=True)
def people(db):
    make_people(db)


# AC7 ----

def test_ac7_a_booking_change_withdraws_the_approval_without_opening_a_round(client, db):
    """Normal: round 1 is withdrawn with the reason, and no round 2 exists until the coordinator resubmits."""
    event_id = make_event(db, status="Confirmed")
    approved = make_round(db, event_id, status="Safety Approved")

    response = client.post(
        f"/safety-check-records/{approved}/withdraw", json={"reason": REASON, "openNextRound": False}, **COORDINATOR
    )

    assert response.status_code == 201
    assert response.get_json()["opened"] is None
    (only,) = db.rounds(event_id)
    assert (only["status"], str(only["withdrawn_by"]), only["withdrawal_reason"]) == (
        "Approval Withdrawn", COORDINATOR_ID, REASON,
    )


def test_ac7_the_approval_is_restored_when_the_booking_change_cannot_be_saved(client, db):
    """Normal: the compensation puts round 1 back to Safety Approved with the withdrawal cleared."""
    event_id = make_event(db, status="Confirmed")
    approved = make_round(db, event_id, status="Safety Approved")
    client.post(
        f"/safety-check-records/{approved}/withdraw", json={"reason": REASON, "openNextRound": False}, **COORDINATOR
    )

    response = client.post(
        f"/safety-check-records/{approved}/restore", json={"nextRoundOpened": False}, **COORDINATOR
    )

    assert response.status_code == 200
    (only,) = db.rounds(event_id)
    assert (only["status"], only["withdrawn_at"], only["withdrawn_by"], only["withdrawal_reason"]) == (
        "Safety Approved", None, None, None,
    )


def test_ac7_the_approval_is_not_restored_once_the_event_has_been_resubmitted(client, db):
    """Conflict: a newer round now exists, so the old approval must stay withdrawn."""
    event_id = make_event(db, status="Pending Safety Check")
    withdrawn = make_round(
        db, event_id, status="Approval Withdrawn", withdrawn_by=COORDINATOR_ID, withdrawal_reason=REASON
    )
    make_round(db, event_id, round_number=2)
    before = db.rounds(event_id)

    response = client.post(
        f"/safety-check-records/{withdrawn}/restore", json={"nextRoundOpened": False}, **COORDINATOR
    )

    assert response.status_code == 409
    assert db.rounds(event_id) == before
