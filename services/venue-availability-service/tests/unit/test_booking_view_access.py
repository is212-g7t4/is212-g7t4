"""SCRUM-9 Role-based viewing control for events: Venue Availability unit tests.

Story:      As a registered user, I want to view only information appropriate to my
            role and relationship to an event, so that I can access the information
            relevant to my responsibilities without viewing restricted information.
Real:       Flask app, GET /events/<id>/venue-bookings, /venue-bookings/<id> and
            /venue-holds routes, token verification and role checks.
Doubled:    the booking queries (patched where app/__init__.py looks them up).
Not proven: that a coordinator is assigned to this event; an atomic cannot ask Event
            Service (the calling composites do). Modification is not covered here (SCRUM-10).

AC1  Given an authenticated user is permitted to view information based on their role and
     relationship to the event, when they access that information, then the information
     is made available to them.
AC2  Given an authenticated user's role does not permit them to view particular information,
     when they attempt to access that information, then access is denied.
AC3  Not covered here: relationship to the event is checked by the calling composites.
AC4  Not covered here: same reason as AC3.
AC5  Given two authenticated users have different roles or relationships to the same event,
     when they access information relating to that event, then each user can only view the
     information permitted by their own role and relationship to the event.
"""
import pytest

from tests.unit.factories import USER_ID, bearer

EVENT_ID = "22222222-2222-4222-8222-222222222222"
BOOKINGS = [{"id": "b1", "status": "Approved"}, {"id": "b2", "status": "Pending"}]


@pytest.fixture
def stubbed(setup, monkeypatch):
    monkeypatch.setattr("app.list_event_bookings", lambda url, event_id: list(BOOKINGS))
    monkeypatch.setattr("app.list_active_holds", lambda url: [])
    monkeypatch.setattr("app.get_booking", lambda url, booking_id: BOOKINGS[0])
    client, _ = setup
    return client


def get(client, path, role):
    return client.get(path, headers=bearer(USER_ID, role))


# AC1 ----

@pytest.mark.parametrize("path", [f"/events/{EVENT_ID}/venue-bookings", "/venue-holds", f"/venue-bookings/{EVENT_ID}"])
def test_ac1_venue_staff_can_read_bookings_and_holds(stubbed, path):
    """Normal: venue staff handle bookings, so they may read them."""
    assert get(stubbed, path, "Venue Staff").status_code == 200


# AC2 ----

@pytest.mark.parametrize("path", ["/venue-holds", f"/venue-bookings/{EVENT_ID}"])
def test_ac2_attendees_cannot_read_holds_or_a_booking_record(stubbed, path):
    """Failure: holds and booking records (with requesters) are internal."""
    assert get(stubbed, path, "Attendee").status_code == 403


# AC5 ----

def test_ac5_attendee_sees_only_the_confirmed_venue_of_an_event(stubbed):
    """Conflict: same event, the Attendee gets the Approved booking, staff get every request."""
    path = f"/events/{EVENT_ID}/venue-bookings"

    attendee = get(stubbed, path, "Attendee").json["bookings"]
    staff = get(stubbed, path, "Venue Staff").json["bookings"]

    assert [b["id"] for b in attendee] == ["b1"]
    assert [b["id"] for b in staff] == ["b1", "b2"]
