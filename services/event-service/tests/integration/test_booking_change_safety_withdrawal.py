"""SCRUM-28 Venue Booking Request Submission (Part B): Event Service integration tests.

Story:      As an Event Coordinator, I want to submit a venue booking request for an event,
            so that Venue Staff can assess whether the requested venue arrangement can be
            accepted.
            Part B (Clarice, 25 Oct): editing or cancelling a venue booking of a 'Confirmed'
            event withdraws its safety approval and sends the event back to 'Approved'.
Real:       Flask app, PATCH /events/<id>/safety-status, validation, app/models.py SQL under
            the row lock, postgres:17.6 with the full migration chain.
Doubled:    nothing (Event Service makes no outbound calls).
Not proven: that Safety Check Service sends these calls in the right order, or that the
            SafetyCheck round itself is withdrawn (Safety Check Record Service owns it);
            caller identity (coordinatorId is whatever is sent; the internal token is not
            configured in this tier).

AC1-AC6  Not covered here: Part B goes beyond the six SCRUM-28 ACs. These tests prove the
         event-side lifecycle move Part B needs.
"""

import json

import pytest

from tests.integration.factories import COORDINATOR_ID, ORGANISER_ID, make_event, make_user

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


@pytest.fixture
def client(locked_client):
    """These routes are only for other services, which always send the shared token (SCRUM-10)."""
    locked_client.environ_base["HTTP_X_INTERNAL_TOKEN"] = "synthetic"
    return locked_client

ROUND_ID = "55555555-5555-4555-8555-555555555555"
OFFICER_ID = "22222222-2222-4222-8222-222222222222"
APPROVAL = {
    "status": "Confirmed",
    "details": "Operational Safety Check approved (round 1).",
    "decidedBy": OFFICER_ID,
    "safetyCheckId": ROUND_ID,
    "remarks": None,
    "recordedAt": "2030-02-01T02:00:00+00:00",
}


@pytest.fixture
def confirmed_event(db):
    make_user(db, ORGANISER_ID)
    make_user(db, COORDINATOR_ID, role="Event Coordinator")
    event_id = make_event(db, status="Confirmed", coordinator_id=COORDINATOR_ID)
    set_history(db, event_id, [APPROVAL])
    return event_id


def set_history(db, event_id, history):
    db.execute(
        """UPDATE public."Event"
           SET description = jsonb_set(description::jsonb, '{actionHistory}', %s::jsonb)::text
           WHERE event_id = %s""",
        [json.dumps(history), event_id],
    )


def history(db, event_id):
    return json.loads(db.event(event_id)["description"])["actionHistory"]


def withdraw(client, event_id, **overrides):
    body = {
        "status": "Approved",
        "safetyCheckId": ROUND_ID,
        "roundNumber": 1,
        "coordinatorId": COORDINATOR_ID,
        "withdrawnSafetyCheckId": ROUND_ID,
        # SCRUM-46: caller supplies the original actual venue before booking edits.
        "venueBefore": "Grand Hall",
        "reason": "The Grand Hall booking changed after safety approval.",
        **overrides,
    }
    return client.patch(f"/events/{event_id}/safety-status", json=body)


def test_withdrawal_with_the_round_id_moves_confirmed_to_approved(client, db, confirmed_event):
    """Normal: the move and its history entry are committed together."""
    response = withdraw(client, confirmed_event)

    assert response.status_code == 200
    assert db.event(confirmed_event)["status"] == "Approved"
    entry = history(db, confirmed_event)[-1]
    assert entry["status"] == "Approved"
    assert entry["withdrawnSafetyCheckId"] == ROUND_ID
    assert "Grand Hall booking changed" in entry["details"]


def test_withdrawal_without_the_round_id_changes_nothing(client, db, confirmed_event):
    """Failure: plain 'Approved' is refused and the event stays Confirmed."""
    response = withdraw(client, confirmed_event, withdrawnSafetyCheckId=None)

    assert response.status_code == 400
    assert db.event(confirmed_event)["status"] == "Confirmed"
    assert history(db, confirmed_event) == [APPROVAL]


def test_withdrawal_of_a_round_the_event_does_not_hold_changes_nothing(client, db, confirmed_event):
    """Conflict: a stale round id is refused under the lock."""
    other = "66666666-6666-4666-8666-666666666666"

    response = withdraw(client, confirmed_event, safetyCheckId=other, withdrawnSafetyCheckId=other)

    assert response.status_code == 409
    assert response.json["code"] == "STALE_SAFETY_CHECK"
    assert db.event(confirmed_event)["status"] == "Confirmed"


def test_restore_returns_the_event_to_confirmed_only_through_safety_status(client, db, confirmed_event):
    """Normal: the undo restores Confirmed; /progress still can't reach it (SCRUM-152)."""
    assert withdraw(client, confirmed_event).status_code == 200

    blocked = client.patch(
        f"/events/{confirmed_event}/progress",
        json={"coordinatorId": COORDINATOR_ID, "status": "Confirmed", "actionDetails": "Try."},
    )
    assert blocked.status_code == 409
    assert db.event(confirmed_event)["status"] == "Approved"

    restored = client.patch(
        f"/events/{confirmed_event}/safety-status",
        json={
            "status": "Confirmed",
            "safetyCheckId": ROUND_ID,
            "roundNumber": 1,
            "coordinatorId": COORDINATOR_ID,
            "restoredSafetyCheckId": ROUND_ID,
            # Restoration supplies final venue facts for the saved comparison baseline.
            "attendeeVenue": "Grand Hall",
        },
    )

    assert restored.status_code == 200
    assert db.event(confirmed_event)["status"] == "Confirmed"
    entry = history(db, confirmed_event)[-1]
    assert entry["restoredSafetyCheckId"] == ROUND_ID
    assert entry["safetyCheckId"] == ROUND_ID
