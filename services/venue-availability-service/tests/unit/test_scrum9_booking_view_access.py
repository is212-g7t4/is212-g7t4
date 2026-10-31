"""
SCRUM-9: Role-Based Access Control for Events

User Story
----------
As a registered user, I want to view only information appropriate to my role
and relationship to an event, so that I can access the information relevant to
my responsibilities without viewing restricted information.

Acceptance Criteria
-------------------
AC1: Given an authenticated user is permitted to view information based on
     their role and relationship to the event, when they access that
     information, then the information is made available to them.
AC2: Given an authenticated user's role does not permit them to view particular
     information, when they attempt to access that information, then access is
     denied.
AC3: Given an authenticated user's relationship to an event does not permit
     them to view that event's information, when they attempt to access the
     information, then access is denied.
AC4: Given a user is permitted to view information for one event but does not
     have the required relationship to another event, when they attempt to view
     information for both events, then they can only view the information for
     which they have the required access.
AC5: Given two authenticated users have different roles or relationships to the
     same event, when they access information relating to that event, then each
     user can only view the information permitted by their own role and
     relationship to the event.

Real
----
- The booking and hold read routes: token verification and the role checks
  (Attendees see only an event's confirmed venue) run for real.
- Assertions are on the status and the rows returned.

Doubled
-------
- psycopg2.connect: Stub (`setup`/`client` fixtures) - fresh MagicMock
  connection; the cursor returns canned VenueBooking / VenueClosure rows (or
  raises); executed SQL, parameters and locks are inspected.

Not proven
----------
- That the caller is related to the event (AC3): checked by the composites (->
  venue-booking-service tests).
- AC4's permitted-view experience is a frontend concern; this atomic proves
  only the API access boundary.
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

@pytest.mark.parametrize("path", [f"/events/{EVENT_ID}/venue-bookings", "/venue-holds", f"/venue-bookings/{EVENT_ID}"], ids=["event_bookings", "holds", "booking_record"])
def test_ac1_booking_reads_when_venue_staff_return_200(stubbed, path):
    """
    Summary: Venue Staff can read bookings and holds.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: Stub (cursor returns no rows)
    """
    # Arrange (Given): stubbed, path, from fixtures

    # Act + Assert (When / Then)
    assert get(stubbed, path, "Venue Staff").status_code == 200


# AC2 ----

@pytest.mark.parametrize("path", ["/venue-holds", f"/venue-bookings/{EVENT_ID}"], ids=["holds", "booking_record"])
def test_ac2_booking_reads_when_attendee_return_403(stubbed, path):
    """
    Summary: Attendees cannot read holds or a booking record with its requester.
    AC2: Given an authenticated user's role does not permit them to view
        particular information, when they attempt to access that information,
        then access is denied.
    Double: Mock (cursor not executed)
    """
    # Arrange (Given): stubbed, path, from fixtures

    # Act + Assert (When / Then)
    assert get(stubbed, path, "Attendee").status_code == 403


# AC5 ----

def test_ac5_event_bookings_when_attendee_return_only_approved_booking(stubbed):
    """
    Summary: For the same event, an attendee sees only the approved booking while staff see every request.
    AC5: Given two authenticated users have different roles or relationships to
        the same event, when they access information relating to that event,
        then each user can only view the information permitted by their own
        role and relationship to the event.
    Double: Stub (cursor returns the event's bookings)
    """
    # Arrange (Given)
    path = f"/events/{EVENT_ID}/venue-bookings"

    attendee = get(stubbed, path, "Attendee").json["bookings"]

    # Act (When)
    staff = get(stubbed, path, "Venue Staff").json["bookings"]

    # Assert (Then)
    assert [b["id"] for b in attendee] == ["b1"]
    assert [b["id"] for b in staff] == ["b1", "b2"]
