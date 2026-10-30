"""SCRUM-10 Role-Based Modification Control: Venue Service unit tests.

Story:      As a registered user, I want to modify only information appropriate to my
            role and relationship to an event, so that I can perform my responsibilities
            without changing information outside my permissions.
Real:       Flask app, routes, token verification and role checks.
Doubled:    psycopg2 (mocked cursor).
Not proven: that a refused change leaves the stored row untouched in a real database;
            Supabase issuing the token.

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
from unittest.mock import MagicMock

import pytest

from app import create_app
from tests.unit.factories import VALID_PAYLOAD, VENUE_ID, saved_row, signed_in

STAFF = "Venue Staff"


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), cursor


# AC1 ----

def test_ac1_venue_staff_may_add_a_venue(setup):
    """Normal: the Venue Staff role is permitted to create a venue."""
    client, cursor = setup
    cursor.fetchone.side_effect = [None, saved_row()]

    response = signed_in(client, role=STAFF).post("/venues", json=VALID_PAYLOAD)

    assert response.status_code == 201


def test_ac1_venue_staff_may_edit_a_venue(setup):
    """Normal: the Venue Staff role is permitted to edit a venue profile."""
    client, cursor = setup
    cursor.fetchone.side_effect = [None, saved_row(venue_name="Renamed")]

    response = signed_in(client, role=STAFF).put(f"/venues/{VENUE_ID}", json={**VALID_PAYLOAD, "name": "Renamed"})

    assert response.status_code == 200


# AC2 ----

@pytest.mark.parametrize("role", ["Event Coordinator", "Event Coordinator Lead", "Event Organiser",
                                  "Technical Support", "Safety Officer", "Attendee"])
@pytest.mark.parametrize("method, path", [("post", "/venues"), ("put", f"/venues/{VENUE_ID}")])
def test_ac2_a_role_other_than_venue_staff_cannot_change_a_venue(setup, method, path, role):
    """Failure: every other role is refused before the body is read or the database touched."""
    client, cursor = setup

    response = getattr(signed_in(client, role=role), method)(path, json=VALID_PAYLOAD)

    assert response.status_code == 403
    assert response.json["code"] == "VENUE_STAFF_ONLY"
    cursor.execute.assert_not_called()


# AC4 ----

def test_ac4_a_coordinator_keeps_viewing_venues_when_their_change_is_refused(setup):
    """Conflict: the refused write does not disturb the read access the role still has."""
    client, cursor = setup
    cursor.fetchall.return_value = [saved_row()]
    coordinator = signed_in(client, role="Event Coordinator")

    before = coordinator.get("/venues")
    refused = coordinator.post("/venues", json=VALID_PAYLOAD)
    after = coordinator.get("/venues")

    assert (before.status_code, refused.status_code, after.status_code) == (200, 403, 200)
    assert before.json == after.json
