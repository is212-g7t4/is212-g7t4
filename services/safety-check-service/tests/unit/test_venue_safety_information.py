"""SCRUM-167 Record Venue Safety Information: Safety Check Service.

As a Venue Staff member, I want to record a venue's emergency access details
and known operational restrictions, so that the Safety Officer can take them
into account when reviewing events at that venue.

The Safety Officer's review (SCRUM-163) shows each booked venue's emergency
access and restrictions. They come from Venue Service's
`emergencyAccessDetails` and `knownRestrictions`; the review's outward keys
(`emergencyAccess`, `restrictions`) are unchanged so the UI needs no change.
"""
import pytest

from app import clients, create_app
from tests.unit.factories import (
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
    return create_app().test_client()


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


def test_ac1_review_shows_venue_emergency_access_and_restrictions(client, monkeypatch):
    """Normal: what Venue Staff recorded is what the Safety Officer sees."""
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


def test_ac2_review_passes_null_when_venue_has_no_safety_information(client, monkeypatch):
    """Boundary: nothing recorded stays null, so the review shows "Not provided"."""
    stub_review(monkeypatch, [booking(venueId=HALL_ID)], [venue(HALL_ID)])

    reviewed = get_review(client).get_json()["venues"][0]

    assert reviewed["emergencyAccess"] is None
    assert reviewed["restrictions"] is None


def test_ac1_each_booked_venue_gets_its_own_safety_information(client, monkeypatch):
    """Normal: two venues' safety information is never mixed up."""
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
