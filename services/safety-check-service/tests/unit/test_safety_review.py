"""SCRUM-163: the Safety Officer's consolidated, read-only review."""
import pytest

from app import clients, create_app
from tests.unit.factories import (
    EVENT_ID,
    OFFICER_ID,
    booking,
    equipment_request,
    event,
    record,
    user,
)

HALL_ID = "88888888-8888-4888-8888-888888888888"
ROOM_ID = "89898989-8989-4989-8989-898989898989"
EQUIPMENT_ID = "99999999-9999-4999-8999-999999999999"


@pytest.fixture
def client():
    return create_app().test_client()


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


def test_review_aggregates_event_arrangements_and_prior_decisions(client, review_data):
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


@pytest.mark.parametrize("query", [{}, {"safetyOfficerId": "not-a-uuid"}])
def test_review_requires_a_valid_officer_id(client, query):
    response = client.get(f"/safety-checks/{EVENT_ID}/review", query_string=query)

    assert response.status_code == 400


def test_review_requires_a_safety_officer(client, review_data, monkeypatch):
    monkeypatch.setattr(clients, "get_user", lambda _id: user(role="Event Coordinator"))

    response = get_review(client)

    assert response.status_code == 403
    assert response.get_json()["code"] == "NOT_SAFETY_OFFICER"


def test_review_only_loads_events_awaiting_a_decision(client, review_data, monkeypatch):
    monkeypatch.setattr(clients, "get_event", lambda *_args, **_kwargs: event("Confirmed"))

    response = get_review(client)

    assert response.status_code == 409
    assert response.get_json()["code"] == "EVENT_NOT_PENDING_SAFETY_CHECK"


def test_review_returns_not_found_when_event_service_cannot_find_event(client, review_data, monkeypatch):
    def missing_event(*_args, **_kwargs):
        raise clients.EventNotFoundError

    monkeypatch.setattr(clients, "get_event", missing_event)

    response = get_review(client)

    assert response.status_code == 404


def test_review_reports_a_missing_open_round(client, review_data, monkeypatch):
    monkeypatch.setattr(clients, "list_safety_check_records", lambda *_args, **_kwargs: [])

    response = get_review(client)

    assert response.status_code == 409
    assert response.get_json()["code"] == "NO_OPEN_SAFETY_CHECK"


def test_review_does_not_compare_capacity_when_attendance_is_unrecorded(
    client, review_data, monkeypatch,
):
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
)
def test_review_fails_closed_when_an_arrangement_cannot_be_loaded(
    client, review_data, monkeypatch, failure, status,
):
    def fail(_event_id):
        raise failure

    monkeypatch.setattr(clients, "get_event_venue_bookings", fail)

    response = get_review(client)

    assert response.status_code == status
    assert "Unable to check" in response.get_json()["message"]