"""
SCRUM-163: Review Event Safety Information

User Story
----------
As a Safety Officer, I want to see all of an event's safety-relevant
information in one place, so that I can assess its operational safety without
chasing other staff for details.

Acceptance Criteria
-------------------
AC1: Given a pending safety check, when I open it, then I see expected
     attendance against each venue's capacity, venue layout, emergency access
     details, accessibility requirements, equipment list with placement notes,
     crowd movement notes and known venue restrictions.
AC2: Given expected attendance exceeds a venue's capacity, then this is visibly
     flagged.
AC3: Given any of these items is not recorded, then it is shown as "Not
     provided".
AC4: Given the event has earlier safety decisions, then I can see each previous
     decision, its reason and the requested changes.
AC5: The review page is read-only: I cannot edit event, venue or equipment
     information from it.

Real
----
- The venue safety details in the Safety Officer's review: each booked venue's
  emergency access details and known restrictions, as recorded by Venue Staff,
  or empty when none were recorded.
- We check the venue details in the review.

Doubled
-------
- Event, Safety Check Record, Venue Availability, Venue, Equipment Request and
  User Services: answer as each test needs, fail, or do not answer in time
  [Stub]; we check which were asked, in what order, and what they were sent
  [Mock].
- Sign-in: a test key signs the caller's token (tests/conftest.py) [Stub].

Not proven
----------
- That Venue Staff can record these details (SCRUM-167) (-> venue-service
  tests).
"""
import pytest

from app import clients, create_app
from tests.unit.factories import (
    signed_in,
    EVENT_ID,
    OFFICER_ID,
    booking,
    event,
    record,
    user,
    venue,
)

HALL_ID = "88888888-8888-4888-8888-888888888888"
ROOM_ID = "89898989-8989-4989-8989-898989898989"


@pytest.fixture
def client():
    return signed_in(create_app().test_client())


def stub_review(monkeypatch, bookings, venues):
    monkeypatch.setattr(clients, "get_user", lambda _id: user())
    monkeypatch.setattr(clients, "get_event", lambda *_args, **_kwargs: event("Pending Safety Check"))
    monkeypatch.setattr(clients, "get_event_venue_bookings", lambda _id: bookings)
    monkeypatch.setattr(clients, "get_event_equipment_requests", lambda *_args: [])
    monkeypatch.setattr(clients, "list_safety_check_records", lambda _id, status=None: [record()])
    monkeypatch.setattr(clients, "list_venues", lambda: venues)
    monkeypatch.setattr(clients, "list_equipment", lambda: [])


def get_review(client):
    return client.get(
        f"/safety-checks/{EVENT_ID}/review",
        query_string={"safetyOfficerId": OFFICER_ID},
    )


def test_review_shows_venue_emergency_access_and_restrictions(client, monkeypatch):
    """
    Summary: What Venue Staff recorded is what the Safety Officer sees.
    AC1: Given a pending safety check, when I open it, then I see expected
        attendance against each venue's capacity, venue layout, emergency
        access details, accessibility requirements, equipment list with
        placement notes, crowd movement notes and known venue restrictions.
    Double: Event Service, Venue Availability and Venue hold the event, its
        bookings and the venues [Stub].
    """
    stub_review(monkeypatch, [booking(venueId=HALL_ID)], [venue(
        HALL_ID,
        emergencyAccessDetails="Exits on north wall; assembly at front lawn",
        knownRestrictions="Noise curfew 10pm; no open flames",
    )])

    response = get_review(client)

    assert response.status_code == 200
    reviewed = response.get_json()["venues"][0]
    assert reviewed["emergencyAccess"] == "Exits on north wall; assembly at front lawn"
    assert reviewed["restrictions"] == "Noise curfew 10pm; no open flames"


def test_review_passes_null_when_venue_has_no_safety_information(client, monkeypatch):
    """
    Summary: Nothing recorded stays empty so the review shows "Not provided".
    AC3: Given any of these items is not recorded, then it is shown as "Not
        provided".
    Double: Event Service, Venue Availability and Venue hold the event, its
        bookings and the venues [Stub].
    """
    stub_review(monkeypatch, [booking(venueId=HALL_ID)], [venue(HALL_ID)])

    reviewed = get_review(client).get_json()["venues"][0]

    assert reviewed["emergencyAccess"] is None
    assert reviewed["restrictions"] is None


def test_review_shows_each_venues_own_safety_information(client, monkeypatch):
    """
    Summary: Each booked venue's safety information is shown separately.
    AC1: Given a pending safety check, when I open it, then I see expected
        attendance against each venue's capacity, venue layout, emergency
        access details, accessibility requirements, equipment list with
        placement notes, crowd movement notes and known venue restrictions.
    Double: Event Service, Venue Availability and Venue hold the event, its
        bookings and the venues [Stub].
    """
    stub_review(
        monkeypatch,
        [booking(venueId=HALL_ID), booking(venueId=ROOM_ID, booking_id="booking-2")],
        [
            venue(ROOM_ID, name="Meeting Room", emergencyAccessDetails="Room exits",
                  knownRestrictions="Room limits"),
            venue(HALL_ID, emergencyAccessDetails="Hall exits", knownRestrictions="Hall limits"),
        ],
    )

    venues = get_review(client).get_json()["venues"]

    assert [(v["venueId"], v["emergencyAccess"], v["restrictions"]) for v in venues] == [
        (HALL_ID, "Hall exits", "Hall limits"),
        (ROOM_ID, "Room exits", "Room limits"),
    ]
