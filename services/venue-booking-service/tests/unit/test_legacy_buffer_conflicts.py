"""SCRUM-155 composite orchestration for venue buffer changes."""

import httpx
import pytest

from app import create_app
from app import clients, routes
from app.search import _shift, availability_for, shortlist
from datetime import datetime
from tests.unit.factories import signed_in, bearer


VENUE_ID = "00000000-0000-0000-0000-000000000001"
VENUE = {
    "id": VENUE_ID,
    "name": "Grand Ballroom",
    "setupTimeMinutes": 30,
    "turnaroundTimeMinutes": 45,
}


def test_venue_edit_saves_then_reconciles_without_changing_bookings(monkeypatch):
    calls = []
    monkeypatch.setattr(
        routes,
        "update_venue_profile",
        lambda venue_id, details: calls.append(("save", venue_id, details)) or VENUE,
    )
    monkeypatch.setattr(
        routes,
        "reconcile_legacy_conflicts",
        lambda venue: calls.append(("reconcile", venue))
        or {"venueId": VENUE_ID, "conflictCount": 1, "conflicts": []},
    )

    response = signed_in(create_app().test_client()).put(
        f"/venues/{VENUE_ID}", json={"setupTimeMinutes": 30, "turnaroundTimeMinutes": 45}
    )

    assert response.status_code == 200
    assert response.json["legacyConflicts"]["conflictCount"] == 1
    assert [call[0] for call in calls] == ["save", "reconcile"]


def test_conflict_read_uses_current_venue_buffers(monkeypatch):
    monkeypatch.setattr(routes, "get_venue", lambda venue_id: VENUE)
    monkeypatch.setattr(
        routes,
        "reconcile_legacy_conflicts",
        lambda venue: {"venueId": venue["id"], "conflictCount": 0, "conflicts": []},
    )

    response = signed_in(create_app().test_client()).get(
        f"/venues/{VENUE_ID}/legacy-conflicts"
    )

    assert response.status_code == 200
    assert response.json == {
        "venueId": VENUE_ID,
        "conflictCount": 0,
        "conflicts": [],
    }


def test_conflict_read_enriches_event_names_for_venue_staff(monkeypatch):
    conflicts = {
        "venueId": VENUE_ID,
        "conflictCount": 2,
        "conflicts": [
            {
                "firstBooking": {"eventId": "event-1"},
                "secondBooking": {"eventId": "event-2"},
            },
            {
                "firstBooking": {"eventId": "event-1"},
                "secondBooking": {"eventId": None},
            },
        ],
    }
    calls = []
    monkeypatch.setattr(routes, "get_venue", lambda venue_id: VENUE)
    monkeypatch.setattr(routes, "reconcile_legacy_conflicts", lambda venue: conflicts)
    monkeypatch.setattr(
        routes,
        "get_event_for_internal_viewer",
        lambda event_id, role: calls.append((event_id, role))
        or {"eventName": {"event-1": "Workshop", "event-2": "Summit"}[event_id]},
    )

    response = signed_in(create_app().test_client()).get(
        f"/venues/{VENUE_ID}/legacy-conflicts",
        headers=bearer("staff-1", "Venue Staff"),
    )

    assert response.status_code == 200
    assert response.json["conflicts"][0]["firstBooking"]["eventName"] == "Workshop"
    assert response.json["conflicts"][0]["secondBooking"]["eventName"] == "Summit"
    assert [call[0] for call in calls] == ["event-1", "event-2"]


def test_event_name_failure_keeps_conflict_response_usable(monkeypatch):
    conflict = {
        "venueId": VENUE_ID,
        "conflictCount": 1,
        "conflicts": [{
            "firstBooking": {"eventId": "event-1"},
            "secondBooking": {"eventId": "event-2"},
        }],
    }
    monkeypatch.setattr(routes, "get_venue", lambda venue_id: VENUE)
    monkeypatch.setattr(routes, "reconcile_legacy_conflicts", lambda venue: conflict)

    def event(event_id, *_):
        if event_id == "event-1":
            raise RuntimeError("event service offline")
        return {"eventName": ""}

    monkeypatch.setattr(routes, "get_event_for_internal_viewer", event)
    response = signed_in(create_app().test_client()).get(
        f"/venues/{VENUE_ID}/legacy-conflicts",
        headers=bearer("staff-1", "Venue Staff"),
    )

    assert response.status_code == 200
    assert "eventName" not in response.json["conflicts"][0]["firstBooking"]
    assert "eventName" not in response.json["conflicts"][0]["secondBooking"]


def test_downstream_validation_error_is_preserved(monkeypatch):
    request = httpx.Request("PUT", f"http://venue/venues/{VENUE_ID}")
    response = httpx.Response(
        400,
        json={"message": "Please correct the venue details.", "errors": ["Bad buffer"]},
        request=request,
    )
    monkeypatch.setattr(
        routes,
        "update_venue_profile",
        lambda *args: (_ for _ in ()).throw(
            httpx.HTTPStatusError("bad", request=request, response=response)
        ),
    )

    result = signed_in(create_app().test_client()).put(f"/venues/{VENUE_ID}", json={})

    assert result.status_code == 400
    assert result.json["errors"] == ["Bad buffer"]


def test_new_composite_clients_forward_current_venue_buffers(monkeypatch):
    calls = []

    def response(method, url, body):
        calls.append((method, url, body))
        return httpx.Response(200, json=body, request=httpx.Request(method, url))

    monkeypatch.setattr(
        clients.httpx,
        "get",
        lambda url, **kwargs: response(
            "GET",
            url,
            {"venue": VENUE} if "/venues/" in url else {"id": "booking-1", "venueId": VENUE_ID},
        ),
    )
    monkeypatch.setattr(
        clients.httpx,
        "put",
        lambda url, json, headers: response("PUT", url, {"venue": VENUE}),
    )
    monkeypatch.setattr(
        clients.httpx,
        "post",
        lambda url, json, headers: response("POST", url, {"conflictCount": 0}),
    )

    assert clients.get_venue(VENUE_ID) == VENUE
    assert clients.update_venue_profile(VENUE_ID, {"name": "Hall"}) == VENUE
    assert clients.reconcile_legacy_conflicts(VENUE) == {"conflictCount": 0}
    assert clients.get_booking("booking-1")["venueId"] == VENUE_ID
    assert calls[-2][2] == {"conflictCount": 0}
    assert calls[-2][1].endswith("/legacy-conflicts/reconcile")


def test_internal_event_client_requests_venue_staff_view(monkeypatch):
    seen = {}

    def get(url, **kwargs):
        seen.update(url=url, kwargs=kwargs)
        return httpx.Response(
            200,
            json={"eventName": "Workshop"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(clients.httpx, "get", get)
    assert clients.get_event_for_internal_viewer("event-1", "Venue Staff") == {
        "eventName": "Workshop"
    }
    assert seen["kwargs"]["params"] == {"viewerRole": "Venue Staff"}


def test_get_booking_client_translates_not_found(monkeypatch):
    monkeypatch.setattr(
        clients.httpx,
        "get",
        lambda url, headers: httpx.Response(404, request=httpx.Request("GET", url)),
    )
    with pytest.raises(clients.BookingNotFoundError):
        clients.get_booking("missing")


def test_buffered_search_widens_read_and_applies_exact_window(monkeypatch):
    calls = []
    venue = {
        **VENUE,
        "capacity": 100,
        "status": "Available",
        "location": "SG",
        "facilities": [],
        "accessibility": "",
        "supportedLayouts": [],
    }
    monkeypatch.setattr(routes, "search_venues", lambda filters: [venue])

    def window(start, end, padding=0):
        calls.append(padding)
        return {"bookings": [], "closures": []}

    monkeypatch.setattr(routes, "get_bookings_between", window)
    response = signed_in(create_app().test_client()).get(
        "/venue-search",
        query_string={
            "start": "2090-10-01T10:00:00",
            "end": "2090-10-01T12:00:00",
            "expectedAttendance": "20",
        },
    )

    assert response.status_code == 200
    assert calls == [0, 75]


def test_booking_create_and_edit_forward_catalogue_buffers(monkeypatch):
    venue = {
        **VENUE,
        "capacity": 100,
        "status": "Available",
    }
    monkeypatch.setattr(routes, "get_event", lambda *args: {"status": "Under Review"})
    monkeypatch.setattr(routes, "get_venues", lambda: [venue])
    create_calls, update_calls = [], []
    monkeypatch.setattr(
        routes, "create_booking", lambda *args: create_calls.append(args) or {"id": "booking-1"}
    )
    monkeypatch.setattr(
        routes, "update_booking", lambda *args: update_calls.append(args) or {"id": "booking-1"}
    )
    payload = {
        "eventId": "event-1",
        "venueId": VENUE_ID,
        "coordinatorId": "coordinator-1",
        "requestedStartTime": "2090-10-01T10:00",
        "requestedEndTime": "2090-10-01T12:00",
        "requiredCapacity": 20,
        "venueRequirements": "Stage",
    }
    client = signed_in(create_app().test_client())

    assert client.post("/booking-requests", json=payload).status_code == 201
    assert client.patch("/booking-requests/booking-1", json=payload).status_code == 200
    assert create_calls[0][-2:] == (30, 45)
    assert update_calls[0][-2:] == (30, 45)


def test_venue_edit_failure_paths_are_explicit(monkeypatch):
    client = signed_in(create_app().test_client())
    path = f"/venues/{VENUE_ID}"
    assert client.put(path, json=[]).status_code == 400

    request = httpx.Request("PUT", "http://venue")
    response = httpx.Response(503, content=b"not-json", request=request)
    monkeypatch.setattr(
        routes,
        "update_venue_profile",
        lambda *args: (_ for _ in ()).throw(
            httpx.HTTPStatusError("bad", request=request, response=response)
        ),
    )
    assert client.put(path, json={}).json["message"] == "Unable to save the venue."

    monkeypatch.setattr(
        routes,
        "update_venue_profile",
        lambda *args: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert client.put(path, json={}).status_code == 502

    monkeypatch.setattr(routes, "update_venue_profile", lambda *args: VENUE)
    monkeypatch.setattr(
        routes,
        "reconcile_legacy_conflicts",
        lambda *args: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    result = client.put(path, json={})
    assert result.status_code == 502
    assert result.json["venueSaved"] is True


def test_conflict_read_failure_paths(monkeypatch):
    path = f"/venues/{VENUE_ID}/legacy-conflicts"
    client = signed_in(create_app().test_client())
    request = httpx.Request("GET", "http://venue")

    for status, expected in [(404, 404), (503, 502)]:
        response = httpx.Response(status, request=request)
        monkeypatch.setattr(
            routes,
            "get_venue",
            lambda *args, response=response: (_ for _ in ()).throw(
                httpx.HTTPStatusError("bad", request=request, response=response)
            ),
        )
        assert client.get(path).status_code == expected

    monkeypatch.setattr(
        routes,
        "get_venue",
        lambda *args: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert client.get(path).status_code == 502


def test_search_buffer_helpers_cover_boundaries_and_legacy_call_shape():
    assert _shift(datetime.max, 1) == datetime.max
    assert _shift(datetime.min, -1) == datetime.min
    venue = {"id": VENUE_ID, "status": "Available", "setupTimeMinutes": 30, "turnaroundTimeMinutes": 45}
    outside = [{
        "venueId": VENUE_ID,
        "status": "Approved",
        "requestedStartTime": "2090-10-01T14:00:00",
        "requestedEndTime": "2090-10-01T15:00:00",
    }, {
        "venueId": VENUE_ID,
        "status": "Pending",
        "requestedStartTime": "2090-10-01T16:00:00",
        "requestedEndTime": "2090-10-01T17:00:00",
    }]
    assert availability_for(venue, outside, "2090-10-01T10:00:00", "2090-10-01T12:00:00") == "Available"
    assert availability_for(venue, [{"venueId": VENUE_ID, "status": "Pending"}]) == "Pending request"
    assert shortlist([venue], [], [{"venueId": VENUE_ID}], None, None) == []
