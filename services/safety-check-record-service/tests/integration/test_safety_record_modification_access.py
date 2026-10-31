"""SCRUM-10 Role-Based Modification Control for Events: Safety Check Record Service integration tests.

Story:      As a registered user, I want to modify only information appropriate to my role and
            relationship to an event, so that I can perform my responsibilities without changing
            information outside my permissions.
Real:       Flask app and routes, token verification and the role check, app/models.py SQL,
            postgres:17.6 with the full migration chain.
Doubled:    nothing (Safety Check Record Service makes no outbound calls).
Not proven: Supabase sign-in itself (the caller is a token signed with a test key, SCRUM-8).

AC1  Given an authenticated user is permitted to modify information based on their role and
     relationship to the event, when they make a valid change to that information, then the
     change is allowed.
AC2  Given an authenticated user's role does not permit them to modify particular information,
     when they attempt to change that information, then the modification is prevented and the
     existing information remains unchanged.
AC3  Not covered here: the relationship (the event's assigned coordinator) is checked in Safety
     Check Service; this service checks the role only.
AC4  Given a user is permitted to view particular information but is not permitted to modify it,
     when they attempt to change that information, then the modification is prevented while
     their permitted viewing access remains unaffected.
AC5  Not covered here: there is no per-event relationship check in this service (see AC3).
"""

import pytest

from tests.integration.factories import (
    ATTENDEE_ID,
    COORDINATOR_ID,
    OFFICER_ID,
    as_user,
    make_event,
    make_people,
    make_round,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

COORDINATOR = as_user(COORDINATOR_ID)
OFFICER = as_user(OFFICER_ID)
APPROVE = {"status": "Safety Approved"}


@pytest.fixture(autouse=True)
def people(db):
    make_people(db)


# AC1 ----

def test_ac1_a_coordinator_opens_a_round_and_a_safety_officer_decides_it(client, db):
    """Normal: each role may make the change that belongs to it, and both changes are stored."""
    event_id = make_event(db)

    opened = client.post("/safety-check-records", json={"eventId": event_id}, **COORDINATOR)
    decided = client.patch(f"/safety-check-records/{opened.get_json()['id']}/decision", json=APPROVE, **OFFICER)

    assert (opened.status_code, decided.status_code) == (201, 200)
    assert [row["status"] for row in db.rounds(event_id)] == ["Safety Approved"]


# AC2 ----

def test_ac2_a_safety_officer_cannot_open_a_round(client, db):
    """Failure: submitting is the coordinator's job, so no round is created."""
    event_id = make_event(db)

    response = client.post("/safety-check-records", json={"eventId": event_id}, **OFFICER)

    assert response.status_code == 403
    assert db.round_count() == 0


def test_ac2_a_coordinator_cannot_decide_a_round(client, db):
    """Failure: only a Safety Officer decides; the Pending round is left exactly as it was."""
    pending = make_round(db, make_event(db, status="Pending Safety Check"))
    before = db.round(pending)

    response = client.patch(f"/safety-check-records/{pending}/decision", json=APPROVE, **COORDINATOR)

    assert response.status_code == 403
    assert db.round(pending) == before


def test_ac2_an_attendee_cannot_withdraw_an_approval(client, db):
    """Failure: the approval stays and no new round is opened."""
    event_id = make_event(db, status="Confirmed")
    approved = make_round(db, event_id, status="Safety Approved")
    before = db.rounds(event_id)

    response = client.post(
        f"/safety-check-records/{approved}/withdraw", json={"reason": "Because."}, **as_user(ATTENDEE_ID)
    )

    assert response.status_code == 403
    assert db.rounds(event_id) == before


# AC4 ----

def test_ac4_a_coordinator_keeps_viewing_the_rounds_when_their_decision_is_refused(client, db):
    """Conflict: the refused decision leaves both the round and the coordinator's read access."""
    event_id = make_event(db, status="Pending Safety Check")
    pending = make_round(db, event_id)

    before = client.get(f"/safety-check-records?eventId={event_id}", **COORDINATOR)
    refused = client.patch(f"/safety-check-records/{pending}/decision", json=APPROVE, **COORDINATOR)
    after = client.get(f"/safety-check-records?eventId={event_id}", **COORDINATOR)

    assert (before.status_code, refused.status_code, after.status_code) == (200, 403, 200)
    assert before.get_json() == after.get_json()
