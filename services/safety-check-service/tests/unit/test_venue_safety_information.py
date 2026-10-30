"""
SCRUM-167: Record Venue Safety Information

User Story
----------
As a Venue Staff member, I want to record a venue's emergency access details
and known operational restrictions, so that the Safety Officer can take them
into account when reviewing events at that venue.

Acceptance Criteria
-------------------
AC1: Given authorised Venue Staff edit a venue, when they enter emergency
     access details (e.g. exits, assembly point, emergency vehicle access) and
     known restrictions (e.g. noise curfew, no open flames, floor load limit),
     then the details are saved with the venue and shown on its details page.
AC2: Given a venue has no safety information recorded, when it is viewed, then
     the fields show "Not provided" rather than appearing blank.
AC3: Given safety information is updated, when it is saved, then the editor and
     timestamp are recorded.
AC4: Given a user who is not Venue Staff, when they attempt to edit venue
     safety information through the UI or API, then the change is rejected and
     the existing values are unchanged.

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
- GET /safety-checks/review: each booked venue's emergency access details and
  known restrictions in the review.
- Assertions are on the venue fields returned.

Doubled
-------
- Event, Safety Check Record, Venue Availability, Venue, Equipment Request,
  Equipment and User Services: Stub (monkeypatched app.clients functions) -
  canned answers or raised client errors; calls recorded so tests assert the
  order and what was (or was not) called.

Not proven
----------
- That the atomic services behave as stubbed, and that a compensation really
  restores state in the database (-> each atomic service's unit and integration
  tests, and tests/integration/ here with respx).
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
    AC1: Given authorised Venue Staff edit a venue, when they enter emergency
        access details (e.g. exits, assembly point, emergency vehicle access)
        and known restrictions (e.g. noise curfew, no open flames, floor load
        limit), then the details are saved with the venue and shown on its
        details page.
    SCRUM-163 AC1: Given a pending safety check, when I open it, then I see
        expected attendance against each venue's capacity, venue layout,
        emergency access details, accessibility requirements, equipment list
        with placement notes, crowd movement notes and known venue
        restrictions.
    Double: Stub (event, bookings, venues)
    """
    # Arrange (Given)
    stub_review(monkeypatch, [booking(venueId=HALL_ID)], [venue(
        HALL_ID,
        emergencyAccessDetails="Exits on north wall; assembly at front lawn",
        knownRestrictions="Noise curfew 10pm; no open flames",
    )])

    # Act (When)
    response = get_review(client)

    # Assert (Then)
    assert response.status_code == 200
    reviewed = response.get_json()["venues"][0]
    assert reviewed["emergencyAccess"] == "Exits on north wall; assembly at front lawn"
    assert reviewed["restrictions"] == "Noise curfew 10pm; no open flames"


def test_review_passes_null_when_venue_has_no_safety_information(client, monkeypatch):
    """
    Summary: Nothing recorded stays empty so the review shows "Not provided".
    AC2: Given a venue has no safety information recorded, when it is viewed,
        then the fields show "Not provided" rather than appearing blank.
    SCRUM-163 AC3: Given any of these items is not recorded, then it is shown
        as "Not provided".
    Double: Stub (event, bookings, venues)
    """
    # Arrange (Given)
    stub_review(monkeypatch, [booking(venueId=HALL_ID)], [venue(HALL_ID)])

    # Act (When)
    reviewed = get_review(client).get_json()["venues"][0]

    # Assert (Then)
    assert reviewed["emergencyAccess"] is None
    assert reviewed["restrictions"] is None


def test_review_shows_each_venues_own_safety_information(client, monkeypatch):
    """
    Summary: Each booked venue's safety information is shown separately.
    AC1: Given authorised Venue Staff edit a venue, when they enter emergency
        access details (e.g. exits, assembly point, emergency vehicle access)
        and known restrictions (e.g. noise curfew, no open flames, floor load
        limit), then the details are saved with the venue and shown on its
        details page.
    Double: Stub (event, bookings, venues)
    """
    # Arrange (Given)
    stub_review(
        monkeypatch,
        [booking(venueId=HALL_ID), booking(venueId=ROOM_ID, booking_id="booking-2")],
        [
            venue(ROOM_ID, name="Meeting Room", emergencyAccessDetails="Room exits",
                  knownRestrictions="Room limits"),
            venue(HALL_ID, emergencyAccessDetails="Hall exits", knownRestrictions="Hall limits"),
        ],
    )

    # Act (When)
    venues = get_review(client).get_json()["venues"]

    # Assert (Then)
    assert [(v["venueId"], v["emergencyAccess"], v["restrictions"]) for v in venues] == [
        (HALL_ID, "Hall exits", "Hall limits"),
        (ROOM_ID, "Room exits", "Room limits"),
    ]
