"""
SCRUM-10: Role-Based Modification Control for Events

User Story
----------
As a registered user, I want to modify only information appropriate to my role
and relationship to an event, so that I can perform my responsibilities without
changing information outside my permissions.

Acceptance Criteria
-------------------
AC1: Given an authenticated user is permitted to modify information based on
     their role and relationship to the event, when they make a valid change to
     that information, then the change is allowed.
AC2: Given an authenticated user's role does not permit them to modify
     particular information, when they attempt to change that information, then
     the modification is prevented and the existing information remains
     unchanged.
AC3: Given an authenticated user's relationship to an event does not permit
     them to modify that event's information, when they attempt to make a
     change, then the modification is prevented and the existing information
     remains unchanged.
AC4: Given a user is permitted to view particular information but is not
     permitted to modify it, when they attempt to change that information, then
     the modification is prevented while their permitted viewing access remains
     unaffected.
AC5: Given a user is permitted to modify information for one event but does not
     have the required access to another event, when they attempt to modify
     information for both events, then only modifications to information for
     which they have the required access are allowed.

Real
----
- The booking write routes: token verification and the role checks
  (coordinators create, edit and cancel; Venue Staff approve and reject; Safety
  Officers reset) run for real.
- Assertions are on the status and the database not being touched.

Doubled
-------
- psycopg2.connect: Stub (`setup`/`client` fixtures) - fresh MagicMock
  connection; the cursor returns canned VenueBooking / VenueClosure rows (or
  raises); executed SQL, parameters and locks are inspected.

Not proven
----------
- That the coordinator is the event's assigned one (AC3): checked by Venue
  Booking Service (-> its test_booking_request_modification_access.py).
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

def test_approve_booking_when_venue_staff_is_allowed(setup):
    """
    Summary: Venue Staff may decide a booking.
    AC1: Given an authenticated user is permitted to modify information based
        on their role and relationship to the event, when they make a valid
        change to that information, then the change is allowed.
    Double: Stub (cursor returns the pending booking)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [booking_row(), booking_row(status="Approved", reviewed_by=USER_ID)]

    # Act (When)
    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}/approve", json={"reviewedBy": USER_ID},
        headers=bearer(USER_ID, "Venue Staff"),
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Approved"


@pytest.mark.parametrize("role", ["Event Coordinator", "Event Coordinator Lead"], ids=["event_coordinator", "event_coordinator_lead"])
def test_cancel_booking_when_coordinator_role_is_allowed(setup, role):
    """
    Summary: Coordinators and the Lead may cancel a booking.
    AC1: Given an authenticated user is permitted to modify information based
        on their role and relationship to the event, when they make a valid
        change to that information, then the change is allowed.
    Double: Stub (cursor returns the booking)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [
        booking_row(status="Approved", reviewed_by=USER_ID), booking_row(status="Cancelled", reviewed_by=USER_ID),
    ]

    # Act (When)
    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}/cancel", json={"eventId": EVENT_ID}, headers=bearer(USER_ID, role)
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Cancelled"


# AC2 ----

@pytest.mark.parametrize("role", ["Venue Staff", "Technical Support", "Safety Officer", "Event Organiser", "Attendee"], ids=["venue_staff", "technical_support", "safety_officer", "event_organiser", "attendee"])
@pytest.mark.parametrize("method, path", REQUESTER_ROUTES, ids=["create", "edit", "cancel"])
def test_requester_booking_actions_when_other_role_return_403(setup, method, path, role):
    """
    Summary: Only coordinators may create, edit or cancel bookings.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Mock (cursor not executed)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = send(client, method, path, role)

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["message"] == "Your role cannot change this information."
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    "role", ["Event Coordinator", "Event Coordinator Lead", "Technical Support", "Safety Officer", "Event Organiser", "Attendee"],
    ids=["event_coordinator", "event_coordinator_lead", "technical_support", "safety_officer", "event_organiser", "attendee"],
)
@pytest.mark.parametrize("method, path", REVIEWER_ROUTES, ids=["approve", "reject"])
def test_reviewer_booking_actions_when_not_venue_staff_return_403(setup, method, path, role):
    """
    Summary: Only Venue Staff may approve or reject a booking; a coordinator cannot approve their own.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Mock (cursor not executed)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = send(client, method, path, role)

    # Assert (Then)
    assert response.status_code == 403
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("role", ["Safety Officer", "Event Organiser", "Attendee"], ids=["safety_officer", "event_organiser", "attendee"])
def test_reconcile_legacy_conflicts_when_role_outside_booking_roles_returns_403(setup, role):
    """
    Summary: Roles outside the booking roles cannot refresh legacy conflicts.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Mock (cursor not executed)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = send(client, *RECONCILE, role)

    # Assert (Then)
    assert response.status_code == 403
    cursor.execute.assert_not_called()


# AC4 ----

def test_event_bookings_after_refused_approval_still_viewable_by_coordinator(setup):
    """
    Summary: A coordinator refused an approval can still view the bookings.
    AC4: Given a user is permitted to view particular information but is not
        permitted to modify it, when they attempt to change that information,
        then the modification is prevented while their permitted viewing access
        remains unaffected.
    Double: Stub (cursor returns bookings)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = booking_row()
    coordinator = bearer(USER_ID, "Event Coordinator")

    before = client.get(f"/venue-bookings/{BOOKING_ID}", headers=coordinator)
    refused = client.patch(f"/venue-bookings/{BOOKING_ID}/approve", json={"reviewedBy": USER_ID}, headers=coordinator)

    # Act (When)
    after = client.get(f"/venue-bookings/{BOOKING_ID}", headers=coordinator)

    # Assert (Then)
    assert (before.status_code, refused.status_code, after.status_code) == (200, 403, 200)
    assert before.json == after.json


# AC2: safety-reset is called by Safety Check Service with the caller's own token ----

SAFETY_RESET = f"/events/{EVENT_ID}/venue-bookings/safety-reset"


@pytest.mark.parametrize(
    "role", ["Event Coordinator", "Event Coordinator Lead", "Venue Staff", "Technical Support", "Event Organiser", "Attendee"],
    ids=["event_coordinator", "event_coordinator_lead", "venue_staff", "technical_support", "event_organiser", "attendee"],
)
def test_safety_reset_when_not_safety_officer_returns_403_even_with_service_token(setup, role):
    """
    Summary: The service token proves the route, not the person: only a Safety Officer may reset bookings.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Mock (cursor not executed)
    """
    # Arrange (Given)
    client, cursor = setup
    client.application.config["INTERNAL_SERVICE_TOKEN"] = "test-token"

    # Act (When)
    response = client.post(
        SAFETY_RESET, json={"bookingIds": [BOOKING_ID]},
        headers={"X-Internal-Token": "test-token", **bearer(USER_ID, role)},
    )

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["message"] == "Your role cannot change this information."
    cursor.execute.assert_not_called()
