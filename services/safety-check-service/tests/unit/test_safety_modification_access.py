"""SCRUM-10 Role-Based Modification Control: Safety Check Service unit tests.

Story:      As a registered user, I want to modify only information appropriate to my
            role and relationship to an event, so that I can perform my responsibilities
            without changing information outside my permissions.
Real:       Flask app, routes, token verification and role checks.
Doubled:    every downstream service (Event, Venue Availability, Equipment Request, Safety Check
            Record, User, Venue, Equipment); the unit tier's socket block fails any call that is
            not stubbed, so a refused change is also proven to send nothing downstream.
Not proven: that the caller is the event's assigned coordinator (the existing submit and
            re-check tests); that a refused change leaves the stored event and round unchanged
            (Event Service and Safety Check Record Service tests); Supabase issuing the token.
            Approve, request-changes and reject are Safety Officer-only through a User Service
            lookup and keep their own tests (test_safety_approve.py, test_safety_reject_changes.py).

AC1  Given an authenticated user is permitted to modify information based on their role and
     relationship to the event, when they make a valid change to that information, then the
     change is allowed.
AC2  Given an authenticated user's role does not permit them to modify particular information,
     when they attempt to change that information, then the modification is prevented and the
     existing information remains unchanged.
AC3  Not covered here: the assignment check is covered by test_safety_submit.py and
     test_safety_recheck.py.
AC4  Given a user is permitted to view particular information but is not permitted to modify it,
     when they attempt to change that information, then the modification is prevented while their
     permitted viewing access remains unaffected.
AC5  Not covered here: see AC3.
"""
import pytest

from app import clients, create_app
from tests.unit.factories import OFFICER_ID, bearer, signed_in

COORDINATOR_ROUTES = [
    "/safety-checks",
    "/safety-checks/resubmit",
    "/safety-checks/recheck",
    "/safety-checks/withdraw-for-venue-change",
    "/safety-checks/restore-after-venue-change",
]


# AC1 ----

@pytest.mark.parametrize("role", ["Event Coordinator", "Event Coordinator Lead"])
@pytest.mark.parametrize("path", COORDINATOR_ROUTES)
def test_ac1_coordinator_roles_get_past_the_gate_to_the_handler_checks(path, role):
    """Normal: both coordinator roles reach the handler, which then asks for a valid eventId."""
    client = signed_in(create_app().test_client(), role=role)

    response = client.post(path, json={})

    assert response.status_code == 400
    assert "eventId" in response.json["message"]


# AC2 ----

@pytest.mark.parametrize("role", ["Safety Officer", "Venue Staff", "Technical Support", "Event Organiser", "Attendee"])
@pytest.mark.parametrize("path", COORDINATOR_ROUTES)
def test_ac2_only_coordinators_may_submit_recheck_or_withdraw_a_safety_check(path, role):
    """Failure: other roles are refused before anything is read, and nothing is sent downstream."""
    client = create_app().test_client()

    response = client.post(path, json={}, headers=bearer(OFFICER_ID, role))

    assert response.status_code == 403
    assert response.json["message"] == "Your role cannot change this information."


# AC4 ----

def test_ac4_a_safety_officer_keeps_their_queue_when_a_submission_is_refused(monkeypatch):
    """Conflict: the refused submit does not disturb the queue the Safety Officer role still has."""
    monkeypatch.setattr(clients, "list_events_by_status", lambda status, viewer_role: [])
    monkeypatch.setattr(clients, "list_venues", lambda: [])
    officer = signed_in(create_app().test_client(), OFFICER_ID, "Safety Officer")

    before = officer.get("/safety-checks/queue")
    refused = officer.post("/safety-checks", json={})
    after = officer.get("/safety-checks/queue")

    assert (before.status_code, refused.status_code, after.status_code) == (200, 403, 200)
    assert before.json == after.json
