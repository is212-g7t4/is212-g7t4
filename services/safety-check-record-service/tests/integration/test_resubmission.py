"""SCRUM-164 Revise Arrangements and Resubmit for Safety Check: Safety Check Record Service integration tests.

Story:      As an Event Coordinator, I want to see the Safety Officer's feedback and revise the
            affected arrangements, so that I can resubmit the event for a safety check without
            redoing unaffected planning.
Real:       Flask app and routes, token verification and the role check, app/models.py SQL,
            postgres:17.6 with the full migration chain.
Doubled:    nothing (Safety Check Record Service makes no outbound calls).
Not proven: whether the flagged arrangements were confirmed again and the event's return to
            'Pending Safety Check' (Safety Check Service, Event Service); Supabase sign-in
            itself (SCRUM-8).

AC1  Not covered here: the feedback view is assembled by Safety Check Service.
AC2  Not covered here: venue re-review runs in Venue Availability and Venue Booking.
AC3  Not covered here: equipment resets run in Equipment Request Service.
AC4  Not covered here: unflagged arrangements are held by the other atomics.
AC5  Given all flagged arrangements are confirmed again, when I resubmit, then the status returns
     to 'Pending Safety Check' as a new review round, and earlier rounds remain in the history.
     Covered here: the new round and the preserved history. The event status is Event Service's.
"""

import pytest

from tests.integration.factories import COORDINATOR_ID, as_user, make_event, make_flag, make_people, make_round

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

COORDINATOR = as_user(COORDINATOR_ID)


@pytest.fixture(autouse=True)
def people(db):
    make_people(db)


# AC5 ----

def test_ac5_resubmitting_opens_a_new_round_and_keeps_the_earlier_one(client, db):
    """Normal: round 2 is Pending, while round 1 keeps its decision, reason and flagged area."""
    event_id = make_event(db, status="Safety Changes Requested")
    first = make_round(db, event_id, status="Changes Requested", remarks="Move the stage.")
    make_flag(db, first, area="venue arrangement", change_required="Move the stage away from the exit.")
    before = db.round(first)

    response = client.post("/safety-check-records", json={"eventId": event_id}, **COORDINATOR)

    assert response.status_code == 201
    assert response.get_json()["roundNumber"] == 2
    assert [(row["round_number"], row["status"]) for row in db.rounds(event_id)] == [
        (1, "Changes Requested"),
        (2, "Pending"),
    ]
    assert db.round(first) == before
    assert [flag["change_required"] for flag in db.flags(first)] == ["Move the stage away from the exit."]
