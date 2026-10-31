"""SCRUM-153 Re-check Safety After High-Impact Changes: Safety Check Record Service integration tests.

Story:      As an Event Coordinator, I want a safety approval to be withdrawn when a high-impact
            detail changes afterwards, so that the event is never prepared on the basis of an
            outdated safety review.
Real:       Flask app and routes, token verification and the role check, validation,
            app/models.py SQL (withdraw round N and open round N+1 in one transaction, FOR
            UPDATE race guard, restore), postgres:17.6 with the full migration chain.
Doubled:    nothing (Safety Check Record Service makes no outbound calls).
Not proven: which fields are high-impact and the event's move back to 'Pending Safety Check'
            (Safety Check Service, Event Service); what Attendees see (Event Service); Supabase
            sign-in itself (SCRUM-8).

AC1  Given an event is 'Confirmed', when its date/time, expected attendance, venue requirements,
     equipment requirements or accessibility needs change, then its status returns to 'Pending
     Safety Check' and the coordinator is told why.
     Covered here: the record side. The approval is withdrawn with its reason and a new Pending
     round is opened, together.
AC2  Not covered here: which fields are low-impact is decided in Safety Check Service.
AC3  Given a safety approval is withdrawn, then it stays visible in the event's safety history.
AC4  Not covered here: the attendee view is built in Event Service.
AC5  Not covered here: the attendee view is built in Event Service.
"""

from datetime import timedelta

import pytest

from tests.integration.factories import (
    COORDINATOR_ID,
    OFFICER_ID,
    as_user,
    make_event,
    make_people,
    make_round,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

COORDINATOR = as_user(COORDINATOR_ID)
REASON = "Date/time changed after safety approval."


@pytest.fixture(autouse=True)
def people(db):
    make_people(db)


def approved_round(db, **fields):
    event_id = make_event(db, status="Confirmed")
    return event_id, make_round(
        db, event_id, status="Safety Approved", remarks="Exits are clear.",
        equipment_placement_notes="Speakers at the back.", crowd_movement_notes="Gate 1 in, Gate 3 out.",
        **fields,
    )


def withdraw(client, safety_check_id, **body):
    return client.post(
        f"/safety-check-records/{safety_check_id}/withdraw", json={"reason": REASON, **body}, **COORDINATOR
    )


# AC1 ----

def test_ac1_withdrawing_an_approval_opens_the_next_round_with_the_reason(client, db):
    """Normal: round 1 is withdrawn (who, when, why) and round 2 is Pending with round 1's notes, in one go."""
    event_id, approved = approved_round(db)

    response = withdraw(client, approved)

    assert response.status_code == 201
    first, second = db.rounds(event_id)
    assert (first["status"], str(first["withdrawn_by"]), first["withdrawal_reason"]) == (
        "Approval Withdrawn", COORDINATOR_ID, REASON,
    )
    assert timedelta(0) <= db.now() - first["withdrawn_at"] < timedelta(minutes=1)
    assert (second["round_number"], second["status"], str(second["submitted_by"])) == (2, "Pending", COORDINATOR_ID)
    assert (second["equipment_placement_notes"], second["crowd_movement_notes"]) == (
        "Speakers at the back.", "Gate 1 in, Gate 3 out.",
    )
    assert response.get_json()["opened"]["id"] == str(second["safety_check_id"])


def test_ac1_only_an_approved_round_can_have_its_approval_withdrawn(client, db):
    """Conflict: a Pending round has no approval to withdraw; nothing changes and no round opens."""
    event_id = make_event(db, status="Pending Safety Check")
    pending = make_round(db, event_id)
    before = db.round(pending)

    response = withdraw(client, pending)

    assert response.status_code == 409
    assert response.get_json()["code"] == "ROUND_NOT_APPROVED"
    assert db.rounds(event_id) == [before]


def test_ac1_a_superseded_approval_cannot_be_withdrawn_again(client, db):
    """Conflict: once round 2 exists, round 1's approval is no longer the one in force."""
    event_id, approved = approved_round(db)
    make_round(db, event_id, round_number=2)
    before = db.rounds(event_id)

    response = withdraw(client, approved)

    assert response.status_code == 409
    assert response.get_json()["code"] == "NOT_LATEST_ROUND"
    assert db.rounds(event_id) == before


def test_ac1_two_simultaneous_withdrawals_open_one_next_round(at_once, db):
    """Conflict: FOR UPDATE on round 1 makes the second re-check wait, then find it already withdrawn."""
    event_id, approved = approved_round(db)
    request = ("post", f"/safety-check-records/{approved}/withdraw", {"json": {"reason": REASON}, **COORDINATOR})

    responses = at_once(request, request)

    assert sorted(response.status_code for response in responses) == [201, 409]
    assert [(row["round_number"], row["status"]) for row in db.rounds(event_id)] == [
        (1, "Approval Withdrawn"),
        (2, "Pending"),
    ]


def test_ac1_a_withdrawal_whose_edit_failed_is_undone(client, db):
    """Normal: the composite's compensation deletes round 2 and puts round 1 back to Safety Approved."""
    event_id, approved = approved_round(db)
    opened = withdraw(client, approved).get_json()["opened"]

    response = client.post(
        f"/safety-check-records/{approved}/restore", json={"openedSafetyCheckId": opened["id"]}, **COORDINATOR
    )

    assert response.status_code == 200
    (only,) = db.rounds(event_id)
    assert (only["status"], only["withdrawn_at"], only["withdrawn_by"], only["withdrawal_reason"]) == (
        "Safety Approved", None, None, None,
    )


def test_ac1_undoing_a_withdrawal_twice_changes_nothing_the_second_time(client, db):
    """Boundary: the composite may retry, so a second restore returns round 1 unchanged."""
    event_id, approved = approved_round(db)
    opened = withdraw(client, approved).get_json()["opened"]
    body = {"openedSafetyCheckId": opened["id"]}
    client.post(f"/safety-check-records/{approved}/restore", json=body, **COORDINATOR)
    before = db.rounds(event_id)

    response = client.post(f"/safety-check-records/{approved}/restore", json=body, **COORDINATOR)

    assert response.status_code == 200
    assert db.rounds(event_id) == before


def test_ac1_a_withdrawal_cannot_be_undone_once_the_new_round_is_decided(client, db):
    """Conflict: round 2 now holds a Safety Officer's decision, so it must be kept."""
    event_id, approved = approved_round(db)
    opened = withdraw(client, approved).get_json()["opened"]
    db.execute(
        """UPDATE public."SafetyCheck" SET status = 'Safety Approved', decided_by = %s, decided_at = now()
           WHERE safety_check_id = %s""",
        [OFFICER_ID, opened["id"]],
    )
    before = db.rounds(event_id)

    response = client.post(
        f"/safety-check-records/{approved}/restore", json={"openedSafetyCheckId": opened["id"]}, **COORDINATOR
    )

    assert response.status_code == 409
    assert db.rounds(event_id) == before


# AC3 ----

def test_ac3_the_withdrawn_approval_keeps_its_original_decision_in_the_history(client, db):
    """Normal: who approved, when and with what remarks survive the withdrawal, and the list shows both rounds."""
    event_id, approved = approved_round(db)
    original = db.round(approved)

    withdraw(client, approved)
    history = client.get(f"/safety-check-records?eventId={event_id}", **COORDINATOR).get_json()["safetyChecks"]

    stored = db.round(approved)
    assert (stored["decided_by"], stored["decided_at"], stored["remarks"]) == (
        original["decided_by"], original["decided_at"], original["remarks"],
    )
    assert [(entry["roundNumber"], entry["status"]) for entry in history] == [
        (2, "Pending"),
        (1, "Approval Withdrawn"),
    ]
    assert (history[1]["decidedBy"], history[1]["remarks"], history[1]["withdrawalReason"]) == (
        OFFICER_ID, "Exits are clear.", REASON,
    )
