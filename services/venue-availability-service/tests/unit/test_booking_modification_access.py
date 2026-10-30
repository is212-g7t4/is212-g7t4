"""SCRUM-10 Role-Based Modification Control: Venue Availability Service unit tests.

Story:      As a registered user, I want to modify only information appropriate to my
            role and relationship to an event, so that I can perform my responsibilities
            without changing information outside my permissions.
Real:       Flask app, routes, token verification and role checks.
Doubled:    psycopg2 (mocked cursor).
Not proven: that a refused change leaves the stored row untouched in a real database (see
            tests/integration/test_booking_modification_access.py); that the requester is the
            coordinator assigned to the event (Venue Booking Service checks that before calling
            this service); Supabase issuing the token.

AC1  Given an authenticated user is permitted to modify information based on their role and
     relationship to the event, when they make a valid change to that information, then the
     change is allowed.
AC2  Given an authenticated user's role does not permit them to modify particular information,
     when they attempt to change that information, then the modification is prevented and the
     existing information remains unchanged.
AC3  Not covered here: the event relationship is checked by Venue Booking Service, which calls
     this service; this service only knows the caller's role.
AC4  Given a user is permitted to view particular information but is not permitted to modify it,
     when they attempt to change that information, then the modification is prevented while their
     permitted viewing access remains unaffected.
AC5  Not covered here: see AC3.
"""
import pytest

from tests.unit.factories import BOOKING_ID, EVENT_ID, USER_ID, VENUE_ID, bearer, booking_row

REQUESTER_ROUTES = [
    ("post", "/venue-bookings"),
    ("patch", f"/venue-bookings/{BOOKING_ID}"),
    ("patch", f"/venue-bookings/{BOOKING_ID}/cancel"),
]
REVIEWER_ROUTES = [
    ("patch", f"/venue-bookings/{BOOKING_ID}/approve"),
    ("patch", f"/venue-bookings/{BOOKING_ID}/reject"),
]
RECONCILE = ("post", f"/venues/{VENUE_ID}/legacy-conflicts/reconcile")


def send(client, method, path, role):
    return getattr(client, method)(path, json={}, headers=bearer(USER_ID, role))


# AC1 ----

def test_ac1_venue_staff_approve_a_pending_booking(setup):
    """Normal: the Venue Staff role is permitted to decide a booking."""
    client, cursor = setup
    cursor.fetchone.side_effect = [booking_row(), booking_row(status="Approved", reviewed_by=USER_ID)]

    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}/approve", json={"reviewedBy": USER_ID},
        headers=bearer(USER_ID, "Venue Staff"),
    )

    assert response.status_code == 200
    assert response.json["status"] == "Approved"


@pytest.mark.parametrize("role", ["Event Coordinator", "Event Coordinator Lead"])
def test_ac1_coordinators_cancel_a_booking(setup, role):
    """Normal: both coordinator roles are permitted to cancel a booking."""
    client, cursor = setup
    cursor.fetchone.side_effect = [
        booking_row(status="Approved", reviewed_by=USER_ID), booking_row(status="Cancelled", reviewed_by=USER_ID),
    ]

    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}/cancel", json={"eventId": EVENT_ID}, headers=bearer(USER_ID, role)
    )

    assert response.status_code == 200
    assert response.json["status"] == "Cancelled"


# AC2 ----

@pytest.mark.parametrize("role", ["Venue Staff", "Technical Support", "Safety Officer", "Event Organiser", "Attendee"])
@pytest.mark.parametrize("method, path", REQUESTER_ROUTES)
def test_ac2_only_coordinators_may_create_edit_or_cancel_a_booking(setup, method, path, role):
    """Failure: other roles are refused before the body is read or the database touched."""
    client, cursor = setup

    response = send(client, method, path, role)

    assert response.status_code == 403
    assert response.json["message"] == "Your role cannot change this information."
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    "role", ["Event Coordinator", "Event Coordinator Lead", "Technical Support", "Safety Officer", "Event Organiser", "Attendee"]
)
@pytest.mark.parametrize("method, path", REVIEWER_ROUTES)
def test_ac2_only_venue_staff_may_approve_or_reject_a_booking(setup, method, path, role):
    """Failure: a coordinator cannot approve their own request, nor can any other non-staff role."""
    client, cursor = setup

    response = send(client, method, path, role)

    assert response.status_code == 403
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("role", ["Safety Officer", "Event Organiser", "Attendee"])
def test_ac2_a_role_outside_the_booking_roles_cannot_refresh_legacy_conflicts(setup, role):
    """Failure: reconcile follows the booking-view roles, so roles outside them are refused."""
    client, cursor = setup

    response = send(client, *RECONCILE, role)

    assert response.status_code == 403
    cursor.execute.assert_not_called()


# AC4 ----

def test_ac4_a_coordinator_keeps_viewing_bookings_when_their_approval_is_refused(setup):
    """Conflict: the refused approval does not disturb the booking view the role still has."""
    client, cursor = setup
    cursor.fetchone.return_value = booking_row()
    coordinator = bearer(USER_ID, "Event Coordinator")

    before = client.get(f"/venue-bookings/{BOOKING_ID}", headers=coordinator)
    refused = client.patch(f"/venue-bookings/{BOOKING_ID}/approve", json={"reviewedBy": USER_ID}, headers=coordinator)
    after = client.get(f"/venue-bookings/{BOOKING_ID}", headers=coordinator)

    assert (before.status_code, refused.status_code, after.status_code) == (200, 403, 200)
    assert before.json == after.json


# AC2: safety-reset is called by Safety Check Service with the caller's own token ----

SAFETY_RESET = f"/events/{EVENT_ID}/venue-bookings/safety-reset"


@pytest.mark.parametrize(
    "role", ["Event Coordinator", "Event Coordinator Lead", "Venue Staff", "Technical Support", "Event Organiser", "Attendee"]
)
def test_ac2_only_a_safety_officer_may_reset_bookings_even_with_the_internal_token(setup, role):
    """Failure: the service-to-service token proves the route, not the person; the role must also fit."""
    client, cursor = setup
    client.application.config["INTERNAL_SERVICE_TOKEN"] = "test-token"

    response = client.post(
        SAFETY_RESET, json={"bookingIds": [BOOKING_ID]},
        headers={"X-Internal-Service-Token": "test-token", **bearer(USER_ID, role)},
    )

    assert response.status_code == 403
    assert response.json["message"] == "Your role cannot change this information."
    cursor.execute.assert_not_called()
