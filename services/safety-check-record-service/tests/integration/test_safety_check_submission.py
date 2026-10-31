"""SCRUM-149 Submit Event for Operational Safety Check: Safety Check Record Service integration tests.

Story:      As an Event Coordinator, I want to submit my event for an Operational Safety Check
            once its venue and technical arrangements are confirmed, so that the Safety Officer
            can review it before preparation begins.
Real:       Flask app and routes, token verification and the role check, validation,
            app/models.py SQL (FOR UPDATE, the UNIQUE (event_id, round_number) backstop),
            postgres:17.6 with the full migration chain.
Doubled:    nothing (Safety Check Record Service makes no outbound calls).
Not proven: the event's move to 'Pending Safety Check' (Event Service) and the readiness and
            assigned-coordinator checks (Safety Check Service); Supabase sign-in itself (the
            caller is a token signed with a test key, SCRUM-8).

AC1  Given an event assigned to the Event Coordinator has at least one approved venue booking,
     and none of its venue bookings or equipment requests is still pending, when the Event
     Coordinator submits it for a safety check, then its status changes to 'Pending Safety
     Check' and the submission time is recorded. Rejected, cancelled or expired venue bookings
     and rejected equipment requests are no longer part of the event's arrangements and do not
     block submission.
     Covered here: the round is recorded with its submission time. The status change and the
     readiness rule run in Event Service and Safety Check Service.
AC2  Not covered here: which arrangements block submission is decided in Safety Check Service
     (app/readiness.py), which never reaches this service when it blocks.
AC3  Given the Event Coordinator is submitting, when they enter equipment placement and expected
     crowd movement notes, then the notes are saved with the safety check.
AC4  Given the event is already 'Pending Safety Check', when the Event Coordinator submits it
     again, then no duplicate safety check is created.
AC5  Not covered here: whether the caller is the event's assigned coordinator is checked in
     Safety Check Service; this service only checks the role (see the SCRUM-10 file).
"""

from datetime import timedelta

import pytest

from tests.integration.factories import (
    COORDINATOR_ID,
    OTHER_COORDINATOR_ID,
    UNKNOWN_ID,
    as_user,
    make_event,
    make_people,
    make_round,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

COORDINATOR = as_user(COORDINATOR_ID)


@pytest.fixture(autouse=True)
def people(db):
    make_people(db)


def submit(client, event_id, **notes):
    return client.post("/safety-check-records", json={"eventId": event_id, **notes}, **COORDINATOR)


# AC1 ----

def test_ac1_first_submission_records_round_one_with_its_submission_time(client, db):
    """Normal: the round is stored Pending, by the signed-in coordinator, stamped by the database clock."""
    event_id = make_event(db)

    response = submit(client, event_id)

    assert response.status_code == 201
    body = response.get_json()
    stored = db.round(body["id"])
    assert (stored["round_number"], stored["status"], str(stored["submitted_by"])) == (1, "Pending", COORDINATOR_ID)
    assert timedelta(0) <= db.now() - stored["submitted_at"] < timedelta(minutes=1)
    assert stored["decided_by"] is None and stored["decided_at"] is None
    assert body["roundNumber"] == 1 and body["submittedAt"] is not None


def test_ac1_an_undecided_round_can_be_removed_when_the_submission_cannot_complete(client, db):
    """Normal: the composite's compensation deletes the round it just opened, so no orphan stays Pending."""
    event_id = make_event(db)
    opened = submit(client, event_id).get_json()

    response = client.delete(f"/safety-check-records/{opened['id']}", **COORDINATOR)

    assert response.status_code == 204
    assert db.rounds(event_id) == []


def test_ac1_a_decided_round_cannot_be_removed_and_stays_in_the_history(client, db):
    """Conflict: the compensation route must never delete a decision someone has already made."""
    event_id = make_event(db)
    decided = make_round(db, event_id, status="Safety Approved")
    before = db.round(decided)

    response = client.delete(f"/safety-check-records/{decided}", **COORDINATOR)

    assert response.status_code == 409
    assert db.round(decided) == before


def test_ac1_a_submission_for_an_event_that_does_not_exist_stores_nothing(client, db):
    """Failure: the real Event foreign key refuses the round; only "refused and nothing stored" is asserted (guide §9.4)."""
    response = submit(client, UNKNOWN_ID)

    assert response.status_code >= 400
    assert db.round_count() == 0


# AC3 ----

def test_ac3_both_notes_are_saved_with_the_safety_check(client, db):
    """Normal: what the coordinator typed is what the Safety Officer will read, trimmed."""
    event_id = make_event(db)

    response = submit(
        client,
        event_id,
        equipmentPlacementNotes="  Speakers at the back corners.  ",
        crowdMovementNotes="Enter by Gate 1, leave by Gate 3.",
    )

    stored = db.round(response.get_json()["id"])
    assert response.status_code == 201
    assert stored["equipment_placement_notes"] == "Speakers at the back corners."
    assert stored["crowd_movement_notes"] == "Enter by Gate 1, leave by Gate 3."


def test_ac3_blank_notes_are_stored_as_empty_not_as_whitespace(client, db):
    """Boundary: whitespace-only notes become NULL, so the review shows "Not provided" rather than a blank."""
    event_id = make_event(db)

    response = submit(client, event_id, equipmentPlacementNotes="   ", crowdMovementNotes="")

    stored = db.round(response.get_json()["id"])
    assert (stored["equipment_placement_notes"], stored["crowd_movement_notes"]) == (None, None)


def test_ac3_notes_of_exactly_2000_characters_are_saved_in_full(client, db):
    """Boundary: the limit itself is allowed, and the text column keeps every character."""
    event_id = make_event(db)

    response = submit(client, event_id, crowdMovementNotes="x" * 2000)

    assert response.status_code == 201
    assert db.round(response.get_json()["id"])["crowd_movement_notes"] == "x" * 2000


def test_ac3_notes_over_2000_characters_are_refused_and_nothing_is_stored(client, db):
    """Failure: one character over the limit is refused before any round is opened."""
    event_id = make_event(db)

    response = submit(client, event_id, crowdMovementNotes="x" * 2001)

    assert response.status_code == 400
    assert db.round_count() == 0


# AC4 ----

def test_ac4_submitting_again_while_pending_creates_no_duplicate(client, db):
    """Conflict: the open round comes back in the 409 and the event still has exactly one round."""
    event_id = make_event(db)
    first = submit(client, event_id).get_json()

    again = submit(client, event_id)

    assert again.status_code == 409
    assert again.get_json()["code"] == "SAFETY_CHECK_ALREADY_PENDING"
    assert again.get_json()["safetyCheck"]["id"] == first["id"]
    assert len(db.rounds(event_id)) == 1


def test_ac4_two_simultaneous_first_submissions_create_one_round(at_once, db):
    """Conflict: no earlier row to lock, so only the real UNIQUE (event_id, round_number) can stop a duplicate."""
    event_id = make_event(db)
    request = ("post", "/safety-check-records", {"json": {"eventId": event_id}, **as_user(COORDINATOR_ID)})
    other = ("post", "/safety-check-records", {"json": {"eventId": event_id}, **as_user(OTHER_COORDINATOR_ID)})

    responses = at_once(request, other)

    assert sorted(response.status_code for response in responses) == [201, 409]
    assert [row["round_number"] for row in db.rounds(event_id)] == [1]


def test_ac4_two_simultaneous_resubmissions_open_one_next_round(at_once, db):
    """Conflict: FOR UPDATE on the decided round 1 makes the second submit wait and then lose."""
    event_id = make_event(db)
    make_round(db, event_id, status="Changes Requested", remarks="Move the stage.")
    request = ("post", "/safety-check-records", {"json": {"eventId": event_id}, **COORDINATOR})

    responses = at_once(request, request)

    assert sorted(response.status_code for response in responses) == [201, 409]
    assert [(row["round_number"], row["status"]) for row in db.rounds(event_id)] == [
        (1, "Changes Requested"),
        (2, "Pending"),
    ]
