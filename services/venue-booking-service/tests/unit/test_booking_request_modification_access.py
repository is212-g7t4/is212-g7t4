"""SCRUM-10 Role-Based Modification Control: Venue Booking Service unit tests.

Story:      As a registered user, I want to modify only information appropriate to my
            role and relationship to an event, so that I can perform my responsibilities
            without changing information outside my permissions.
Real:       Flask app, routes, token verification and role checks.
Doubled:    every downstream service (Event, Venue, Venue Availability, Safety Check); the
            unit tier's socket block fails any call that is not stubbed, so a refused
            change is also proven to send nothing downstream.
Not proven: that the requester is the coordinator assigned to the event (Event Service's own
            tests); that a refused change leaves the stored booking unchanged (Venue
            Availability Service's tests); Supabase issuing the token.

AC1  Given an authenticated user is permitted to modify information based on their role and
     relationship to the event, when they make a valid change to that information, then the
     change is allowed.
AC2  Given an authenticated user's role does not permit them to modify particular information,
     when they attempt to change that information, then the modification is prevented and the
     existing information remains unchanged.
AC3  Not covered here: the event relationship is decided by Event Service, which this service asks.
AC4  Given a user is permitted to view particular information but is not permitted to modify it,
     when they attempt to change that information, then the modification is prevented while their
     permitted viewing access remains unaffected.
AC5  Not covered here: see AC3.
"""
import pytest

from app import create_app, routes
from tests.unit.factories import bearer, signed_in

VENUE_ID = "8381b11e-aaae-4d58-bdba-2607e9e2bde2"
USER = "00000000-0000-4000-8000-000000000001"
VENUE = {"id": VENUE_ID, "setupTimeMinutes": 0, "turnaroundTimeMinutes": 0}

REQUESTER_ROUTES = [
    ("post", "/booking-requests"),
    ("patch", "/booking-requests/booking-1"),
    ("patch", "/booking-requests/booking-1/cancel"),
]


# AC1 ----

@pytest.mark.parametrize("role", ["Event Coordinator", "Event Coordinator Lead"])
def test_ac1_coordinator_roles_get_past_the_gate_to_the_cancel_checks(role):
    """Normal: both coordinator roles reach the handler's own validation (eventId is required)."""
    client = signed_in(create_app().test_client(), role=role)

    response = client.patch("/booking-requests/booking-1/cancel", json={})

    assert response.status_code == 400
    assert response.json["message"] == "eventId is required."


def test_ac1_venue_staff_edit_a_venue_profile(monkeypatch):
    """Normal: the Venue Staff role is permitted to save a venue profile."""
    monkeypatch.setattr(routes, "update_venue_profile", lambda venue_id, data: VENUE)
    monkeypatch.setattr(
        routes, "reconcile_legacy_conflicts", lambda venue: {"venueId": VENUE_ID, "conflictCount": 0, "conflicts": []}
    )

    response = signed_in(create_app().test_client(), role="Venue Staff").put(f"/venues/{VENUE_ID}", json={"name": "X"})

    assert response.status_code == 200


# AC2 ----

@pytest.mark.parametrize("role", ["Venue Staff", "Technical Support", "Safety Officer", "Event Organiser", "Attendee"])
@pytest.mark.parametrize("method, path", REQUESTER_ROUTES)
def test_ac2_only_coordinators_may_create_edit_or_cancel_a_booking_request(method, path, role):
    """Failure: other roles are refused before anything is read, and nothing is sent downstream."""
    client = create_app().test_client()

    response = getattr(client, method)(path, json={}, headers=bearer(USER, role))

    assert response.status_code == 403
    assert response.json["message"] == "Your role cannot change this information."


@pytest.mark.parametrize("role", ["Event Coordinator", "Event Coordinator Lead", "Technical Support", "Safety Officer",
                                  "Event Organiser", "Attendee"])
def test_ac2_only_venue_staff_may_edit_a_venue_profile(role):
    """Failure: the venue profile is Venue Staff's; no other role reaches Venue Service."""
    client = create_app().test_client()

    response = client.put(f"/venues/{VENUE_ID}", json={"name": "X"}, headers=bearer(USER, role))

    assert response.status_code == 403


# AC4 ----

def test_ac4_a_coordinator_keeps_viewing_legacy_conflicts_when_their_venue_edit_is_refused(monkeypatch):
    """Conflict: the refused PUT does not disturb the conflict view the coordinator role still has."""
    monkeypatch.setattr(routes, "get_venue", lambda venue_id: VENUE)
    monkeypatch.setattr(
        routes, "reconcile_legacy_conflicts", lambda venue: {"venueId": VENUE_ID, "conflictCount": 0, "conflicts": []}
    )
    coordinator = signed_in(create_app().test_client(), role="Event Coordinator")

    before = coordinator.get(f"/venues/{VENUE_ID}/legacy-conflicts")
    refused = coordinator.put(f"/venues/{VENUE_ID}", json={"name": "X"})
    after = coordinator.get(f"/venues/{VENUE_ID}/legacy-conflicts")

    assert (before.status_code, refused.status_code, after.status_code) == (200, 403, 200)
    assert before.json == after.json
