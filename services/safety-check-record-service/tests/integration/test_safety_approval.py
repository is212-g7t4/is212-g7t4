"""SCRUM-150 Approve Operational Safety Check: Safety Check Record Service integration tests.

Story:      As a Safety Officer, I want to approve an event's operational safety arrangements,
            so that the event can proceed to preparation.
Real:       Flask app and routes, token verification and the role check, validation,
            app/models.py SQL (FOR UPDATE race guard, latest-round check), postgres:17.6 with
            the full migration chain.
Doubled:    nothing (Safety Check Record Service makes no outbound calls).
Not proven: the event's move to 'Confirmed' and whether the event was 'Pending Safety Check'
            (Event Service, driven by Safety Check Service); Supabase sign-in itself (the caller
            is a token signed with a test key, SCRUM-8).

AC1  Not covered here: the event's status changes in Event Service.
AC2  Given I approve an event, then the safety check is recorded with the status 'Safety
     Approved', together with my identity, the approval timestamp and any optional remarks, in
     the event's history.
AC3  Given an event is not 'Pending Safety Check', then the approve action is not available and
     an API call is rejected without changing the event.
     Covered here: the round-level half. A round that is no longer Pending, or no longer the
     latest, can't be approved and is left unchanged. The event's own status is checked in
     Safety Check Service.
AC4  Not covered here: what registered Attendees see is decided in Event Service.
"""

from datetime import timedelta

import pytest

from tests.integration.factories import (
    OFFICER_ID,
    OTHER_OFFICER_ID,
    as_user,
    make_event,
    make_people,
    make_round,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

OFFICER = as_user(OFFICER_ID)
APPROVE = {"status": "Safety Approved", "remarks": "Exits are clear."}


@pytest.fixture(autouse=True)
def people(db):
    make_people(db)


def decide(client, safety_check_id, body=APPROVE, user=OFFICER):
    return client.patch(f"/safety-check-records/{safety_check_id}/decision", json=body, **user)


# AC2 ----

def test_ac2_approval_records_status_officer_timestamp_and_remarks(client, db):
    """Normal: every field AC2 lists is persisted, with the time stamped by the database clock."""
    pending = make_round(db, make_event(db, status="Pending Safety Check"))

    response = decide(client, pending)

    assert response.status_code == 200
    stored = db.round(pending)
    assert (stored["status"], str(stored["decided_by"]), stored["remarks"]) == (
        "Safety Approved", OFFICER_ID, "Exits are clear.",
    )
    assert timedelta(0) <= db.now() - stored["decided_at"] < timedelta(minutes=1)
    assert response.get_json()["decidedAt"] is not None


def test_ac2_remarks_are_optional_and_blank_remarks_are_stored_as_empty(client, db):
    """Boundary: "any optional remarks" means none at all is a valid approval, stored as NULL."""
    pending = make_round(db, make_event(db, status="Pending Safety Check"))

    response = decide(client, pending, {"status": "Safety Approved", "remarks": "   "})

    assert response.status_code == 200
    assert (db.round(pending)["status"], db.round(pending)["remarks"]) == ("Safety Approved", None)


def test_ac2_an_approval_is_undone_only_by_the_request_that_made_it(client, db):
    """Normal: the composite's compensation, passing back the exact decidedAt, returns the round to Pending."""
    pending = make_round(db, make_event(db, status="Pending Safety Check"))
    decided_at = decide(client, pending).get_json()["decidedAt"]

    response = client.post(f"/safety-check-records/{pending}/reopen", json={"decidedAt": decided_at}, **OFFICER)

    stored = db.round(pending)
    assert response.status_code == 200
    assert (stored["status"], stored["decided_by"], stored["decided_at"], stored["remarks"]) == (
        "Pending", None, None, None,
    )


def test_ac2_an_older_approval_cannot_be_undone(client, db):
    """Conflict: a decidedAt that doesn't match the stored one is refused, so history stays as recorded."""
    approved = make_round(db, make_event(db, status="Confirmed"), status="Safety Approved")
    before = db.round(approved)

    response = client.post(
        f"/safety-check-records/{approved}/reopen", json={"decidedAt": "2030-01-01T00:00:00+00:00"}, **OFFICER
    )

    assert response.status_code == 409
    assert db.round(approved) == before


# AC3 ----

def test_ac3_a_round_already_decided_cannot_be_approved(client, db):
    """Conflict: approving a round that was sent back for changes is refused and the row is unchanged."""
    decided = make_round(db, make_event(db), status="Changes Requested", remarks="Move the stage.")
    before = db.round(decided)

    response = decide(client, decided)

    assert response.status_code == 409
    assert response.get_json()["code"] == "SAFETY_CHECK_ALREADY_DECIDED"
    assert db.round(decided) == before


def test_ac3_an_earlier_round_cannot_be_approved_once_a_later_one_exists(client, db):
    """Conflict: only the latest round is the one awaiting a decision, even if an older row still reads Pending."""
    event_id = make_event(db, status="Pending Safety Check")
    stale = make_round(db, event_id, round_number=1)
    make_round(db, event_id, round_number=2)
    before = db.round(stale)

    response = decide(client, stale)

    assert response.status_code == 409
    assert response.get_json()["code"] == "NOT_LATEST_ROUND"
    assert db.round(stale) == before


def test_ac3_two_officers_approving_at_once_record_exactly_one_decision(at_once, db):
    """Conflict: FOR UPDATE makes the second decision wait, then find the round decided and lose."""
    pending = make_round(db, make_event(db, status="Pending Safety Check"))
    path = f"/safety-check-records/{pending}/decision"

    responses = at_once(
        ("patch", path, {"json": APPROVE, **as_user(OFFICER_ID)}),
        ("patch", path, {"json": {"status": "Safety Rejected", "remarks": "Unsafe."}, **as_user(OTHER_OFFICER_ID)}),
    )

    statuses = sorted(response.status_code for response in responses)
    winner = next(response.get_json() for response in responses if response.status_code == 200)
    stored = db.round(pending)
    assert statuses == [200, 409]
    assert (stored["status"], str(stored["decided_by"])) == (winner["status"], winner["decidedBy"])
