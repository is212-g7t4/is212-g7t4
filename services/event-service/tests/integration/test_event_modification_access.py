"""SCRUM-10 Role-Based Modification Control for Events: Event Service integration tests.

Story:      As a registered user, I want to modify only information appropriate to my
            role and relationship to an event, so that I can perform my responsibilities
            without changing information outside my permissions.
Real:       Flask app and routes, token verification, role and relationship checks,
            app/models.py SQL, postgres:17.6 with the full migration chain.
Doubled:    nothing (Event Service makes no outbound calls).
Not proven: Supabase sign-in itself; the caller is a token signed with a test key (SCRUM-8).
            Composite services (Coordinator Assignment, Event Workflow) that sit in front of
            some of these routes are not exercised.

AC1  Given an authenticated user is permitted to modify information based on their role and
     relationship to the event, when they make a valid change to that information, then the
     change is allowed.
AC2  Given an authenticated user's role does not permit them to modify particular information,
     when they attempt to change that information, then the modification is prevented and the
     existing information remains unchanged.
AC3  Given an authenticated user's relationship to an event does not permit them to modify that
     event's information, when they attempt to make a change, then the modification is prevented
     and the existing information remains unchanged.
AC4  Given a user is permitted to view particular information but is not permitted to modify it,
     when they attempt to change that information, then the modification is prevented while their
     permitted viewing access remains unaffected.
AC5  Given a user is permitted to modify information for one event but does not have the required
     access to another event, when they attempt to modify information for both events, then only
     modifications to information for which they have the required access are allowed.
"""

from datetime import datetime

import pytest

from tests.integration.factories import (
    COORDINATOR_ID,
    LEAD_ID,
    ORGANISER_ID,
    OTHER_ORGANISER_ID,
    SINGAPORE,
    make_event,
    make_user,
)
from tests.unit.factories import bearer

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


@pytest.fixture
def client(locked_client):
    return locked_client

OTHER_COORDINATOR_ID = "55555555-5555-4555-8555-555555555555"
STAFF_ID = "66666666-6666-4666-8666-666666666666"
LEAD = "Event Coordinator Lead"
COORDINATOR = "Event Coordinator"
ORGANISER = "Event Organiser"
PROGRESS = {"status": "Approved", "actionDetails": "Venue held."}
SERVICE = {"X-Internal-Token": "synthetic"}


@pytest.fixture(autouse=True)
def users(db):
    make_user(db, ORGANISER_ID)
    make_user(db, OTHER_ORGANISER_ID)
    make_user(db, COORDINATOR_ID, role=COORDINATOR)
    make_user(db, OTHER_COORDINATOR_ID, role=COORDINATOR)
    make_user(db, LEAD_ID, role=LEAD)
    make_user(db, STAFF_ID, role="Venue Staff")


def as_user(user_id, role):
    return {"headers": bearer(user_id, role)}


def under_review(db, coordinator_id=COORDINATOR_ID, **overrides):
    values = {
        "status": "Under Review",
        "coordinator_id": coordinator_id,
        "event_name": "Community Workshop",
        "description": "A hands-on workshop",
        "purpose": "Learning",
        "start": datetime(2030, 3, 1, 9, tzinfo=SINGAPORE),
        "end": datetime(2030, 3, 1, 17, tzinfo=SINGAPORE),
        "expected_attendance": 25,
        "venue_requirements": "Seminar room",
    }
    values.update(overrides)
    return make_event(db, **values)


# AC1 ----

def test_ac1_organiser_edits_their_own_draft(client, db):
    """Normal: the organiser role plus ownership lets the change through and stores it."""
    draft_id = make_event(db, status="Draft", event_name="Spring Fair")

    response = client.patch(
        f"/events/drafts/{draft_id}", json={"eventName": "Spring Fair v2"}, **as_user(ORGANISER_ID, ORGANISER)
    )

    assert response.status_code == 200
    assert db.event(draft_id)["event_name"] == "Spring Fair v2"


def test_ac1_assigned_coordinator_updates_progress(client, db):
    """Normal: the coordinator role plus the assignment lets the status change be stored."""
    event_id = under_review(db)

    response = client.patch(f"/events/{event_id}/progress", json=PROGRESS, **as_user(COORDINATOR_ID, COORDINATOR))

    assert response.status_code == 200
    assert db.event(event_id)["status"] == "Approved"


def test_ac1_lead_assigns_a_coordinator(client, db):
    """Normal: only the Lead's role may assign, and the assignment is stored."""
    event_id = under_review(db, coordinator_id=None)

    response = client.patch(
        f"/events/{event_id}", json={"assignedCoordinatorId": COORDINATOR_ID}, **as_user(LEAD_ID, LEAD)
    )

    assert response.status_code == 200
    assert str(db.event(event_id)["coordinator_id"]) == COORDINATOR_ID


# AC2 ----

def test_ac2_a_coordinator_cannot_assign_coordinators(client, db):
    """Failure: assignment was open to any signed-in caller; it is now the Lead's alone."""
    event_id = under_review(db, coordinator_id=None)
    before = db.event(event_id)

    response = client.patch(
        f"/events/{event_id}",
        json={"assignedCoordinatorId": OTHER_COORDINATOR_ID},
        headers={**bearer(COORDINATOR_ID, COORDINATOR), **SERVICE},
    )

    assert response.status_code == 403
    assert db.event(event_id) == before


def test_ac2_venue_staff_cannot_update_event_progress(client, db):
    """Failure: even as the named coordinator, a role that only views events cannot move one along."""
    event_id = under_review(db, coordinator_id=STAFF_ID)
    before = db.event(event_id)

    response = client.patch(f"/events/{event_id}/progress", json=PROGRESS, **as_user(STAFF_ID, "Venue Staff"))

    assert response.status_code == 403
    assert db.event(event_id) == before


def test_ac2_a_coordinator_cannot_submit_an_event(client, db):
    """Failure: submitting is the organiser's job; no event row is created."""
    response = client.post(
        "/events",
        json={
            "eventName": "Sneaky", "description": "d", "purpose": "p", "expectedAttendance": "10",
            "preferredStartDate": "2030-03-01T09:00", "preferredEndDate": "2030-03-01T17:00",
        },
        **as_user(COORDINATOR_ID, COORDINATOR),
    )

    assert response.status_code == 403
    assert db.event_count() == 0


# AC3 ----

def test_ac3_another_organiser_cannot_edit_the_draft(client, db):
    """Failure: the organiser role is not enough without owning the draft."""
    draft_id = make_event(db, status="Draft", event_name="Spring Fair")
    before = db.event(draft_id)

    response = client.patch(
        f"/events/drafts/{draft_id}", json={"eventName": "Hijacked"}, **as_user(OTHER_ORGANISER_ID, ORGANISER)
    )

    assert response.status_code == 403
    assert db.event(draft_id) == before


def test_ac3_a_coordinator_not_assigned_to_the_event_cannot_update_it(client, db):
    """Failure: the coordinator role is not enough without the assignment."""
    event_id = under_review(db, coordinator_id=OTHER_COORDINATOR_ID)
    before = db.event(event_id)

    response = client.patch(f"/events/{event_id}/progress", json=PROGRESS, **as_user(COORDINATOR_ID, COORDINATOR))

    assert response.status_code == 403
    assert db.event(event_id) == before


def test_ac3_lead_edits_details_only_while_no_coordinator_is_assigned(client, db):
    """Boundary: unassigned is allowed; assigned to someone else is refused and unchanged."""
    unassigned_id = under_review(db, coordinator_id=None)
    assigned_id = under_review(db, coordinator_id=OTHER_COORDINATOR_ID)
    before = db.event(assigned_id)
    body = {"changes": {"eventName": "Renamed"}, "actorRole": LEAD}

    lead = {"headers": {**bearer(LEAD_ID, LEAD), **SERVICE}}
    allowed = client.patch(f"/events/{unassigned_id}/details", json=body, **lead)
    refused = client.patch(f"/events/{assigned_id}/details", json=body, **lead)

    assert (allowed.status_code, refused.status_code) == (200, 403)
    assert db.event(unassigned_id)["event_name"] == "Renamed"
    assert db.event(assigned_id) == before


# AC4 ----

def test_ac4_venue_staff_keep_their_view_when_their_change_is_refused(client, db):
    """Conflict: the refused PATCH leaves the event and the view the role is allowed unchanged."""
    event_id = under_review(db, coordinator_id=STAFF_ID)
    staff = as_user(STAFF_ID, "Venue Staff")
    url = f"/events/{event_id}?viewerRole=1"

    before = client.get(url, **staff)
    refused = client.patch(f"/events/{event_id}/progress", json=PROGRESS, **staff)
    after = client.get(url, **staff)

    assert (before.status_code, refused.status_code, after.status_code) == (200, 403, 200)
    assert before.get_json() == after.get_json()
    assert db.event(event_id)["status"] == "Under Review"


# AC5 ----

def test_ac5_coordinator_changes_only_the_event_they_are_assigned_to(client, db):
    """Conflict: the same change on two events is stored for one and refused for the other."""
    mine_id = under_review(db)
    theirs_id = under_review(db, coordinator_id=OTHER_COORDINATOR_ID, event_name="Their Event")
    theirs_before = db.event(theirs_id)
    coordinator = as_user(COORDINATOR_ID, COORDINATOR)

    allowed = client.patch(f"/events/{mine_id}/progress", json=PROGRESS, **coordinator)
    refused = client.patch(f"/events/{theirs_id}/progress", json=PROGRESS, **coordinator)

    assert (allowed.status_code, refused.status_code) == (200, 403)
    assert db.event(mine_id)["status"] == "Approved"
    assert db.event(theirs_id) == theirs_before


# AC2: PATCH /safety-status is called by Safety Check Service with the caller's own token ----

SAFETY_ROUND = "77777777-7777-4777-8777-777777777777"
OFFICER_ID = "88888888-8888-4888-8888-888888888888"


def test_ac2_the_assigned_coordinator_cannot_confirm_their_own_event(client, db):
    """Failure: the coordinator holds the assignment but not the Safety Officer role, so nothing changes."""
    event_id = under_review(db, status="Pending Safety Check")
    before = db.event(event_id)

    response = client.patch(
        f"/events/{event_id}/safety-status",
        json={"status": "Confirmed", "safetyCheckId": SAFETY_ROUND, "roundNumber": 1},
        headers={**bearer(COORDINATOR_ID, COORDINATOR), **SERVICE},
    )

    assert response.status_code == 403
    assert db.event(event_id) == before


def test_ac2_a_safety_officer_cannot_submit_an_event_for_a_safety_check(client, db):
    """Failure: even as the named coordinator, the Safety Officer role cannot submit; the event stays Approved."""
    make_user(db, OFFICER_ID, role="Safety Officer")
    event_id = under_review(db, status="Approved", coordinator_id=OFFICER_ID)
    before = db.event(event_id)

    response = client.patch(
        f"/events/{event_id}/safety-status",
        json={"status": "Pending Safety Check", "safetyCheckId": SAFETY_ROUND, "roundNumber": 1},
        headers={**bearer(OFFICER_ID, "Safety Officer"), **SERVICE},
    )

    assert response.status_code == 403
    assert db.event(event_id) == before
