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
- The Safety Officer's review of one event: attendance against each venue's
  capacity (flagged when exceeded), venues, equipment with placement notes,
  crowd movement notes, earlier decisions, and "Not provided" for anything
  missing; it fails as a whole if any part cannot be loaded.
- We check the review returned.

Doubled
-------
- Event, Safety Check Record, Venue Availability, Venue, Equipment Request and
  User Services: answer as each test needs, fail, or do not answer in time
  [Stub]; we check which were asked, in what order, and what they were sent
  [Mock].
- Sign-in: a test key signs the caller's token (tests/conftest.py) [Stub].

Not proven
----------
- The review page in the browser, including that nothing can be edited from it
  (AC5) (-> frontend SafetyReview.test.tsx).
"""
import pytest

from app import clients, create_app
from tests.unit.factories import (
    signed_in,
    EVENT_ID,
    OFFICER_ID,
    booking,
    equipment_request,
    event,
    record,
    user,
)
from tests.unit.factories import Response

HALL_ID = "88888888-8888-4888-8888-888888888888"
ROOM_ID = "89898989-8989-4989-8989-898989898989"
EQUIPMENT_ID = "99999999-9999-4999-8999-999999999999"


@pytest.fixture
def client():
    return signed_in(create_app().test_client())


@pytest.fixture
def review_data(monkeypatch):
    current = record(round_number=2, status="Pending", equipmentPlacementNotes=None,
                     crowdMovementNotes="Use the east exit.")
    previous = record(
        id="44444444-4444-4444-8444-444444444444",
        round_number=1,
        status="Changes Requested",
        decidedBy=OFFICER_ID,
        decidedAt="2026-10-01T09:00:00+00:00",
        remarks="The exit route is unclear.",
        flags=[{
            "id": "flag-1", "area": "venue arrangement", "bookingId": None,
            "equipmentRequestId": None, "changeRequired": "Keep the west exit clear.",
        }],
    )
    bookings = [
        booking(venueId=HALL_ID, requiredCapacity=150),
        booking(venueId=ROOM_ID, booking_id="booking-2", requiredCapacity=150),
    ]
    requests = [equipment_request(), equipment_request(
        request_id="request-2", equipmentId="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )]
    monkeypatch.setattr(clients, "get_user", lambda _id: user())
    monkeypatch.setattr(clients, "get_event", lambda *_args, **_kwargs: event("Pending Safety Check"))
    monkeypatch.setattr(clients, "get_event_venue_bookings", lambda _id: bookings)
    monkeypatch.setattr(clients, "get_event_equipment_requests", lambda *_args: requests)
    monkeypatch.setattr(clients, "list_safety_check_records", lambda _id, status=None: [current, previous])
    monkeypatch.setattr(clients, "list_venues", lambda: [
        {"id": HALL_ID, "name": "Main Hall", "capacity": 100,
         "supportedLayouts": ["Theatre"], "accessibility": "Step-free entry"},
        {"id": ROOM_ID, "name": "Meeting Room", "capacity": 200,
         "supportedLayouts": [], "accessibility": ""},
    ])
    monkeypatch.setattr(clients, "list_equipment", lambda: [
        {"id": EQUIPMENT_ID, "type": "Microphone", "description": "Wireless microphone"},
    ])
    return {"current": current, "previous": previous, "bookings": bookings, "requests": requests}


def get_review(client, **params):
    return client.get(
        f"/safety-checks/{EVENT_ID}/review",
        query_string={"safetyOfficerId": OFFICER_ID, **params},
    )


def test_review_shows_arrangements_capacity_and_earlier_decisions(client, review_data):
    """
    Summary: The officer sees attendance against capacity, venues, equipment, notes and earlier decisions in one place.
    AC1: Given a pending safety check, when I open it, then I see expected
        attendance against each venue's capacity, venue layout, emergency
        access details, accessibility requirements, equipment list with
        placement notes, crowd movement notes and known venue restrictions.
    AC2: Given expected attendance exceeds a venue's capacity, then this is
        visibly flagged.
    AC4: Given the event has earlier safety decisions, then I can see each
        previous decision, its reason and the requested changes.
    Double: Event Service, Safety Check Record, Venue Availability, Venue and
        Equipment Request hold the event and everything about it [Stub].
    """
    response = get_review(client)

    assert response.status_code == 200
    body = response.get_json()
    assert body["event"]["id"] == EVENT_ID
    assert body["safetyCheck"]["id"] == review_data["current"]["id"]
    assert body["venues"][0] == {
        "bookingId": review_data["bookings"][0]["id"],
        "venueId": HALL_ID,
        "name": "Main Hall",
        "expectedAttendance": "120",
        "capacity": 100,
        "overCapacity": True,
        "layout": "Theatre",
        "emergencyAccess": None,
        "accessibility": "Step-free entry",
        "restrictions": None,
        "venueRequirements": "Stage and projector",
        "status": "Approved",
    }
    assert body["venues"][1]["overCapacity"] is False
    assert body["venues"][1]["layout"] is None
    assert body["equipment"][0]["name"] == "Microphone"
    assert body["equipment"][1]["name"] is None
    assert [item["roundNumber"] for item in body["history"]] == [1]
    assert body["history"][0]["remarks"] == "The exit route is unclear."


def test_review_for_event_not_pending_returns_409(client, review_data, monkeypatch):
    """
    Summary: Only an event awaiting a decision can be reviewed.
    AC1: Given a pending safety check, when I open it, then I see expected
        attendance against each venue's capacity, venue layout, emergency
        access details, accessibility requirements, equipment list with
        placement notes, crowd movement notes and known venue restrictions.
    Double: Event Service, Safety Check Record, Venue Availability, Venue and
        Equipment Request hold the event and everything about it [Stub].
    """
    monkeypatch.setattr(clients, "get_event", lambda *_args, **_kwargs: event("Confirmed"))

    response = get_review(client)

    assert response.status_code == 409
    assert response.get_json()["code"] == "EVENT_NOT_PENDING_SAFETY_CHECK"


def test_review_unknown_event_returns_404(client, review_data, monkeypatch):
    """
    Summary: Reviewing an unknown event is refused.
    AC1: Given a pending safety check, when I open it, then I see expected
        attendance against each venue's capacity, venue layout, emergency
        access details, accessibility requirements, equipment list with
        placement notes, crowd movement notes and known venue restrictions.
    Double: Event Service, Safety Check Record, Venue Availability, Venue and
        Equipment Request hold the event and everything about it [Stub].
    """
    def missing_event(*_args, **_kwargs):
        raise clients.EventNotFoundError

    monkeypatch.setattr(clients, "get_event", missing_event)

    response = get_review(client)

    assert response.status_code == 404


def test_review_without_open_round_reports_it(client, review_data, monkeypatch):
    """
    Summary: A missing open round is reported.
    AC1: Given a pending safety check, when I open it, then I see expected
        attendance against each venue's capacity, venue layout, emergency
        access details, accessibility requirements, equipment list with
        placement notes, crowd movement notes and known venue restrictions.
    Double: Event Service, Safety Check Record, Venue Availability, Venue and
        Equipment Request hold the event and everything about it [Stub].
    """
    monkeypatch.setattr(clients, "list_safety_check_records", lambda *_args, **_kwargs: [])

    response = get_review(client)

    assert response.status_code == 409
    assert response.get_json()["code"] == "NO_OPEN_SAFETY_CHECK"


def test_review_without_attendance_skips_capacity_comparison(
    client, review_data, monkeypatch,
):
    """
    Summary: Without recorded attendance, capacity is not compared.
    AC3: Given any of these items is not recorded, then it is shown as "Not
        provided".
    Double: Event Service, Safety Check Record, Venue Availability, Venue and
        Equipment Request hold the event and everything about it [Stub].
    """
    monkeypatch.setattr(
        clients, "get_event",
        lambda *_args, **_kwargs: event("Pending Safety Check", expectedAttendance="Not set"),
    )
    monkeypatch.setattr(clients, "list_venues", lambda: [
        {"id": HALL_ID, "name": "Main Hall", "capacity": None},
        {"id": ROOM_ID, "name": "Meeting Room", "capacity": 200},
    ])

    response = get_review(client)

    assert response.status_code == 200
    assert response.get_json()["venues"][0]["overCapacity"] is False
    assert response.get_json()["venues"][1]["overCapacity"] is False


@pytest.mark.parametrize(
    ("failure", "status"),
    [(clients.DownstreamTimeout(), 504), (clients.DownstreamError(), 502)],
    ids=["clients_downstreamtimeout_504", "clients_downstreamerror_502"],
)
def test_review_when_arrangement_unreadable_fails_closed(
    client, review_data, monkeypatch, failure, status,
):
    """
    Summary: If any arrangement cannot be loaded, the review fails rather than showing part of it.
    AC1: Given a pending safety check, when I open it, then I see expected
        attendance against each venue's capacity, venue layout, emergency
        access details, accessibility requirements, equipment list with
        placement notes, crowd movement notes and known venue restrictions.
    Double: Event Service, Safety Check Record, Venue Availability, Venue and
        Equipment Request hold the event and everything about it [Stub].
    """
    def fail(_event_id):
        raise failure

    monkeypatch.setattr(clients, "get_event_venue_bookings", fail)

    response = get_review(client)

    assert response.status_code == status
    assert "Unable to check" in response.get_json()["message"]


def test_equipment_catalogue_client_reads_catalogue(sent):
    """
    Summary: The equipment catalogue is read for the review.
    AC1: Given a pending safety check, when I open it, then I see expected
        attendance against each venue's capacity, venue layout, emergency
        access details, accessibility requirements, equipment list with
        placement notes, crowd movement notes and known venue restrictions.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    calls, queue = sent
    queue.append(Response(200, {"equipment": [{"id": "fixture", "type": "Table"}]}))

    assert clients.list_equipment() == [{"id": "fixture", "type": "Table"}]
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith("/equipment")


def test_equipment_catalogue_client_failure_is_downstream_error(sent):
    """
    Summary: If the equipment catalogue cannot be read, it is reported as a failure of that service.
    AC1: Given a pending safety check, when I open it, then I see expected
        attendance against each venue's capacity, venue layout, emergency
        access details, accessibility requirements, equipment list with
        placement notes, crowd movement notes and known venue restrictions.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    _, queue = sent
    queue.append(Response(503, {"message": "database unavailable"}))

    with pytest.raises(clients.DownstreamError):
        clients.list_equipment()
