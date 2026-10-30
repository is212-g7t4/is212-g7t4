"""SCRUM-10 Role-Based Modification Control: Venue Service integration tests.

Story:      As a registered user, I want to modify only information appropriate to my
            role and relationship to an event, so that I can perform my responsibilities
            without changing information outside my permissions.
Real:       Flask app and routes, token verification and the role check, validation,
            app/models.py SQL, postgres:17.6 with the full migration chain.
Doubled:    nothing (Venue Service makes no outbound calls).
Not proven: Supabase sign-in itself (the caller is a token signed with a test key, SCRUM-8).

AC1  Given an authenticated user is permitted to modify information based on their role and
     relationship to the event, when they make a valid change to that information, then the
     change is allowed.
AC2  Given an authenticated user's role does not permit them to modify particular information,
     when they attempt to change that information, then the modification is prevented and the
     existing information remains unchanged.
AC3  Not covered here: venues have no per-record owner, so only the role decides (see AC2).
AC4  Given a user is permitted to view particular information but is not permitted to modify it,
     when they attempt to change that information, then the modification is prevented while their
     permitted viewing access remains unaffected.
AC5  Not covered here: venues have no per-record owner, so there is no event-by-event difference.
"""

import pytest

from tests.integration.factories import PROFILE, make_venue
from tests.unit.factories import bearer

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
STAFF_ID = "55555555-5555-4555-8555-555555555555"


def as_user(user_id, role):
    return {"headers": bearer(user_id, role)}


# AC1 ----

def test_ac1_venue_staff_add_and_edit_a_venue(client, db):
    """Normal: the Venue Staff role may create a venue and then rename it, and both are stored."""
    created = client.post("/venues", json=PROFILE, **as_user(STAFF_ID, "Venue Staff"))
    venue_id = created.get_json()["venue"]["id"]

    edited = client.put(
        f"/venues/{venue_id}", json={**PROFILE, "name": "Harbour Hall East"}, **as_user(STAFF_ID, "Venue Staff")
    )

    assert (created.status_code, edited.status_code) == (201, 200)
    assert db.venue(venue_id)["venue_name"] == "Harbour Hall East"


# AC2 ----

def test_ac2_a_coordinator_cannot_edit_a_venue(client, db):
    """Failure: the profile route was open to any signed-in caller; the stored venue must not change."""
    venue_id = make_venue(db)
    before = db.venue(venue_id)

    response = client.put(
        f"/venues/{venue_id}", json={**PROFILE, "name": "Hijacked"}, **as_user(COORDINATOR_ID, "Event Coordinator")
    )

    assert response.status_code == 403
    assert db.venue(venue_id) == before


def test_ac2_a_coordinator_cannot_add_a_venue(client, db):
    """Failure: no venue row is created by a role that may not create one."""
    response = client.post("/venues", json=PROFILE, **as_user(COORDINATOR_ID, "Event Coordinator"))

    assert response.status_code == 403
    assert db.venue_count() == 0


# AC4 ----

def test_ac4_a_coordinator_keeps_viewing_the_venue_when_their_change_is_refused(client, db):
    """Conflict: the refused PUT leaves both the row and the read access the role still has."""
    venue_id = make_venue(db)
    coordinator = as_user(COORDINATOR_ID, "Event Coordinator")

    before = client.get(f"/venues/{venue_id}", **coordinator)
    refused = client.put(f"/venues/{venue_id}", json={**PROFILE, "name": "Hijacked"}, **coordinator)
    after = client.get(f"/venues/{venue_id}", **coordinator)

    assert (before.status_code, refused.status_code, after.status_code) == (200, 403, 200)
    assert before.get_json() == after.get_json()
