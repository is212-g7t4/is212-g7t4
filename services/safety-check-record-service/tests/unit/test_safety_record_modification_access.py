"""SCRUM-10 Role-Based Modification Control: Safety Check Record Service unit tests.

Story:      As a registered user, I want to modify only information appropriate to my
            role and relationship to an event, so that I can perform my responsibilities
            without changing information outside my permissions.
Real:       Flask app, routes, token verification and role checks.
Doubled:    psycopg2 (mocked cursor).
Not proven: that a refused change leaves the stored round untouched in a real database (this
            service has no integration tier yet); that the caller is the event's assigned
            coordinator (Safety Check Service checks that before calling this service);
            Supabase issuing the token.

AC1  Given an authenticated user is permitted to modify information based on their role and
     relationship to the event, when they make a valid change to that information, then the
     change is allowed.
AC2  Given an authenticated user's role does not permit them to modify particular information,
     when they attempt to change that information, then the modification is prevented and the
     existing information remains unchanged.
AC3  Not covered here: the event relationship is checked by Safety Check Service.
AC4  Given a user is permitted to view particular information but is not permitted to modify it,
     when they attempt to change that information, then the modification is prevented while their
     permitted viewing access remains unaffected.
AC5  Not covered here: see AC3.
"""
from unittest.mock import MagicMock

import pytest

from app import create_app
from tests.unit.factories import COORDINATOR_ID, EVENT_ID, OFFICER_ID, RECORD_ID, bearer, record_row, signed_in

COORDINATOR_ROUTES = [
    ("post", "/safety-check-records"),
    ("delete", f"/safety-check-records/{RECORD_ID}"),
    ("post", f"/safety-check-records/{RECORD_ID}/withdraw"),
    ("post", f"/safety-check-records/{RECORD_ID}/restore"),
]
OFFICER_ROUTES = [
    ("patch", f"/safety-check-records/{RECORD_ID}/decision"),
    ("post", f"/safety-check-records/{RECORD_ID}/reopen"),
]


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), cursor


# AC1 ----

@pytest.mark.parametrize("role", ["Event Coordinator", "Event Coordinator Lead"])
def test_ac1_coordinator_roles_open_a_round(setup, role):
    """Normal: both coordinator roles are permitted to submit an event for a safety check."""
    client, cursor = setup
    cursor.fetchone.side_effect = [None, record_row(round_number=1)]

    response = signed_in(client, COORDINATOR_ID, role).post("/safety-check-records", json={"eventId": EVENT_ID})

    assert response.status_code == 201


def test_ac1_a_safety_officer_decides_a_pending_round(setup):
    """Normal: the Safety Officer role is permitted to decide a round."""
    client, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(), record_row(), record_row(status="Safety Approved", decided=True),
    ]

    response = signed_in(client, OFFICER_ID, "Safety Officer").patch(
        f"/safety-check-records/{RECORD_ID}/decision", json={"status": "Safety Approved", "eventId": EVENT_ID}
    )

    assert response.status_code == 200
    assert response.json["status"] == "Safety Approved"


# AC2 ----

@pytest.mark.parametrize("role", ["Safety Officer", "Venue Staff", "Technical Support", "Event Organiser", "Attendee"])
@pytest.mark.parametrize("method, path", COORDINATOR_ROUTES)
def test_ac2_only_coordinators_may_open_withdraw_or_undo_a_round(setup, method, path, role):
    """Failure: other roles are refused before anything is read or written."""
    client, cursor = setup

    response = getattr(client, method)(path, json={}, headers=bearer(OFFICER_ID, role))

    assert response.status_code == 403
    assert response.json["message"] == "Your role cannot change this information."
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    "role", ["Event Coordinator", "Event Coordinator Lead", "Venue Staff", "Technical Support", "Event Organiser", "Attendee"]
)
@pytest.mark.parametrize("method, path", OFFICER_ROUTES)
def test_ac2_only_a_safety_officer_may_decide_or_reopen_a_round(setup, method, path, role):
    """Failure: a coordinator cannot approve their own submission, nor can any other role."""
    client, cursor = setup

    response = getattr(client, method)(path, json={}, headers=bearer(COORDINATOR_ID, role))

    assert response.status_code == 403
    cursor.execute.assert_not_called()


# AC4 ----

def test_ac4_a_coordinator_keeps_viewing_rounds_when_their_decision_is_refused(setup):
    """Conflict: the refused decision does not disturb the round list the role still has."""
    client, cursor = setup
    cursor.fetchall.return_value = []
    coordinator = signed_in(client, COORDINATOR_ID, "Event Coordinator")

    before = coordinator.get(f"/safety-check-records?eventId={EVENT_ID}")
    refused = coordinator.patch(f"/safety-check-records/{RECORD_ID}/decision", json={"status": "Safety Approved"})
    after = coordinator.get(f"/safety-check-records?eventId={EVENT_ID}")

    assert (before.status_code, refused.status_code, after.status_code) == (200, 403, 200)
    assert before.json == after.json
