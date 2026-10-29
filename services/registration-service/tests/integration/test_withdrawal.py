"""SCRUM-39 Withdraw Registration: Registration Service integration tests.

Story:      As an Attendee, I want to withdraw my registration for an event,
            so that I can free up my place for someone else if I can no longer attend.
Real:       Flask app and routes, app/models.py SQL, and postgres:17.6 with
            the full migration chain.
Doubled:    nothing (Registration Service makes no outbound calls).
Not proven: Supabase sign-in itself; the attendee is a token signed with a test key (SCRUM-8).

AC1  The Attendee can access a "Withdraw" option from their registered event details page.
     Not covered here: button visibility belongs to the frontend component suite.
AC2  Given the Attendee confirms withdrawal, the system changes the registration status
     to 'Withdrawn' and displays a confirmation message.
AC3  The withdrawal is recorded with timestamp for auditability.
AC4  Given the Attendee attempts to withdraw after the registration withdrawal deadline
     (if applicable), the system displays a message to contact the organisers and the
     withdrawal does not go through.
     Not covered here: deadline orchestration belongs to Attendee Registration Service.
"""

from datetime import datetime, timezone

import pytest

from tests.integration.factories import (
    OTHER_ATTENDEE_ID,
    make_withdrawal_world,
)
from tests.unit.factories import bearer

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


# AC2 and AC3 -----------------------------------------------------------------


def test_ac2_confirmed_registration_becomes_withdrawn_and_frees_capacity(client, db):
    """Normal: a successful status change immediately releases the attendee's place."""
    event_id, registration_id = make_withdrawal_world(db)
    before = datetime.now(timezone.utc)

    response = client.patch(
        f"/registrations/{registration_id}/withdraw",
        json={},
    )
    after = datetime.now(timezone.utc)

    assert response.status_code == 200
    assert response.json["registration"]["status"] == "Withdrawn"
    row = db.registration(registration_id)
    assert row["status"] == "Withdrawn"
    assert before <= row["withdrawn_at"] <= after
    assert db.counts(event_id) == {"total": 1, "confirmed": 0}


def test_ac3_already_withdrawn_registration_keeps_original_audit_timestamp(client, db):
    """Conflict: retrying withdrawal must not rewrite its historical timestamp."""
    original = datetime(2029, 12, 2, 10, tzinfo=timezone.utc)
    _, registration_id = make_withdrawal_world(db, status="Withdrawn", withdrawn_at=original)

    response = client.patch(
        f"/registrations/{registration_id}/withdraw",
        json={},
    )

    assert response.status_code == 409
    assert response.json["code"] == "REGISTRATION_ALREADY_WITHDRAWN"
    row = db.registration(registration_id)
    assert row["status"] == "Withdrawn"
    assert row["withdrawn_at"] == original


def test_ac2_another_attendee_cannot_withdraw_the_registration(client, db):
    """Failure: an attendee identifier cannot be used to withdraw another person's place."""
    _, registration_id = make_withdrawal_world(db)

    response = client.patch(
        f"/registrations/{registration_id}/withdraw",
        json={},
        headers=bearer(OTHER_ATTENDEE_ID, "Attendee"),
    )

    assert response.status_code == 403
    assert response.json["code"] == "REGISTRATION_NOT_OWNED"
    row = db.registration(registration_id)
    assert row["status"] == "Confirmed"
    assert row["withdrawn_at"] is None
