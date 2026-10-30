"""SCRUM-10 Role-Based Modification Control: Venue Availability Service integration tests.

Story:      As a registered user, I want to modify only information appropriate to my
            role and relationship to an event, so that I can perform my responsibilities
            without changing information outside my permissions.
Real:       Flask app and routes, token verification and role checks, app/models.py SQL,
            postgres:17.6 with the full migration chain.
Doubled:    nothing (Venue Availability Service makes no outbound calls).
Not proven: Supabase sign-in itself (the caller is a token signed with a test key, SCRUM-8);
            that the requester is the coordinator assigned to the event (Venue Booking Service
            checks that before calling this service).

AC1  Given an authenticated user is permitted to modify information based on their role and
     relationship to the event, when they make a valid change to that information, then the
     change is allowed.
AC2  Given an authenticated user's role does not permit them to modify particular information,
     when they attempt to change that information, then the modification is prevented and the
     existing information remains unchanged.
AC3  Not covered here: the event relationship is checked by Venue Booking Service.
AC4  Given a user is permitted to view particular information but is not permitted to modify it,
     when they attempt to change that information, then the modification is prevented while their
     permitted viewing access remains unaffected.
AC5  Not covered here: see AC3.
"""

import pytest

from tests.integration.factories import (
    COORDINATOR_ID,
    STAFF_ID,
    at,
    make_booking,
    make_event,
    make_user,
    make_venue,
)
from tests.unit.factories import bearer

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


@pytest.fixture(autouse=True)
def users(db):
    make_user(db, COORDINATOR_ID)
    make_user(db, STAFF_ID, role="Venue Staff")


def pending_booking(db):
    venue_id = make_venue(db)
    return make_booking(db, make_event(db), venue_id, at(1, 10), at(1, 12), status="Pending Review")


# AC1 ----

def test_ac1_venue_staff_approve_a_pending_booking(client, db):
    """Normal: the Venue Staff role may decide a booking, and the decision and reviewer are stored."""
    booking_id = pending_booking(db)

    response = client.patch(
        f"/venue-bookings/{booking_id}/approve",
        json={"setupTimeMinutes": 0, "turnaroundTimeMinutes": 0},
        headers=bearer(STAFF_ID, "Venue Staff"),
    )

    assert response.status_code == 200
    stored = db.booking(booking_id)
    assert (stored["status"], str(stored["reviewed_by"])) == ("Approved", STAFF_ID)


# AC2 ----

def test_ac2_a_coordinator_cannot_approve_their_own_booking(client, db):
    """Failure: the requester holds the relationship but not the reviewer role, so nothing changes."""
    booking_id = pending_booking(db)
    before = db.booking(booking_id)

    response = client.patch(
        f"/venue-bookings/{booking_id}/approve",
        json={"setupTimeMinutes": 0, "turnaroundTimeMinutes": 0},
        headers=bearer(COORDINATOR_ID, "Event Coordinator"),
    )

    assert response.status_code == 403
    assert db.booking(booking_id) == before


def test_ac2_venue_staff_cannot_cancel_a_coordinators_booking(client, db):
    """Failure: cancelling is the requester side; the reviewer role may not do it."""
    booking_id = pending_booking(db)
    before = db.booking(booking_id)
    event_id = str(before["event_id"])

    response = client.patch(
        f"/venue-bookings/{booking_id}/cancel", json={"eventId": event_id}, headers=bearer(STAFF_ID, "Venue Staff")
    )

    assert response.status_code == 403
    assert db.booking(booking_id) == before


# AC4 ----

def test_ac4_a_coordinator_keeps_viewing_the_booking_when_their_approval_is_refused(client, db):
    """Conflict: the refused approval leaves the booking and the view the role still has unchanged."""
    booking_id = pending_booking(db)
    coordinator = bearer(COORDINATOR_ID, "Event Coordinator")

    before = client.get(f"/venue-bookings/{booking_id}", headers=coordinator)
    refused = client.patch(
        f"/venue-bookings/{booking_id}/approve",
        json={"setupTimeMinutes": 0, "turnaroundTimeMinutes": 0},
        headers=coordinator,
    )
    after = client.get(f"/venue-bookings/{booking_id}", headers=coordinator)

    assert (before.status_code, refused.status_code, after.status_code) == (200, 403, 200)
    assert before.get_json() == after.get_json()
    assert db.booking(booking_id)["status"] == "Pending Review"
