"""SCRUM-30: HTTP boundary mocked; real composite route and client exercised."""

import httpx
import pytest

from app import clients, create_app

PAYLOAD = dict(
    eventId="event-1",
    venueId="venue-1",
    coordinatorId="coordinator-1",
    requestedStartTime="2026-10-01T09:00",
    requestedEndTime="2026-10-01T12:00",
    requiredCapacity=80,
    venueRequirements="Projector",
)


def prepare(monkeypatch, status, body):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        data = (
            {
                "venues": [
                    {
                        "id": "venue-1",
                        "name": "Hall",
                        "capacity": 100,
                        "status": "Available",
                    }
                ]
            }
            if url.endswith("/venues")
            else {"venue": {"id": "venue-1", "setupTimeMinutes": 30, "turnaroundTimeMinutes": 45}}
            if url.endswith("/venues/venue-1")
            else {"id": "booking-1", "venueId": "venue-1"}
            if url.endswith("/venue-bookings/booking-1")
            else {"id": "event-1"}
        )
        return httpx.Response(200, json=data, request=httpx.Request("GET", url))

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(clients.httpx, "get", get)
    monkeypatch.setattr(clients.httpx, "post", post)
    return create_app().test_client(), calls


def test_approved_conflict_survives_client_and_route(monkeypatch):
    body = {
        "code": "VENUE_UNAVAILABLE",
        "conflictTypes": ["APPROVED_BOOKING"],
        "message": "This venue is unavailable for the requested time.",
    }
    client, calls = prepare(monkeypatch, 409, body)
    response = client.post("/booking-requests", json=PAYLOAD)
    assert response.status_code == 409
    assert response.json["code"] == body["code"]
    assert response.json["conflictTypes"] == body["conflictTypes"]
    assert calls[0][1]["params"] == {"coordinatorId": "coordinator-1"}
    assert calls[-1][1]["json"]["requestedBy"] == "coordinator-1"


@pytest.mark.parametrize("action", ["edit", "approve"])
def test_edit_and_approval_preserve_typed_conflicts(monkeypatch, action):
    body = {
        "code": "VENUE_UNAVAILABLE",
        "conflictTypes": ["TENTATIVE_HOLD", "VENUE_CLOSURE"],
    }
    client, _ = prepare(monkeypatch, 409, body)
    monkeypatch.setattr(
        clients.httpx,
        "patch",
        lambda url, **k: httpx.Response(
            409, json=body, request=httpx.Request("PATCH", url)
        ),
    )
    path = "/booking-requests/booking-1" + ("/approve" if action == "approve" else "")
    response = client.patch(
        path, json={"reviewedBy": "staff-1"} if action == "approve" else PAYLOAD
    )
    assert response.status_code == 409
    assert response.json["code"] == "VENUE_UNAVAILABLE"
    assert response.json["conflictTypes"] == body["conflictTypes"]


@pytest.mark.parametrize("types", ["VENUE_CLOSURE", ["UNKNOWN"], [None], None, {}])
def test_malformed_conflict_metadata_is_dependency_failure(monkeypatch, types):
    client, _ = prepare(
        monkeypatch, 409, {"code": "VENUE_UNAVAILABLE", "conflictTypes": types}
    )
    response = client.post("/booking-requests", json=PAYLOAD)
    assert response.status_code == 502
    assert "conflictTypes" not in response.json


@pytest.mark.parametrize(
    "types",
    [
        ["TENTATIVE_HOLD"],
        ["VENUE_CLOSURE"],
        ["APPROVED_BOOKING", "TENTATIVE_HOLD", "VENUE_CLOSURE"],
    ],
)
def test_all_submission_conflict_types_survive_http_boundary(monkeypatch, types):
    client, _ = prepare(
        monkeypatch, 409, {"code": "VENUE_UNAVAILABLE", "conflictTypes": types}
    )
    response = client.post("/booking-requests", json=PAYLOAD)
    assert response.status_code == 409
    assert response.json["conflictTypes"] == types


def test_submission_success_preserves_201_and_pending_record(monkeypatch):
    booking = {"id": "booking-1", "status": "Pending Review", "eventId": "event-1"}
    client, calls = prepare(monkeypatch, 201, booking)
    response = client.post("/booking-requests", json=PAYLOAD)
    assert response.status_code == 201
    assert response.json == booking
    assert calls[-1][1]["json"] == {
        key: value
        for key, value in (PAYLOAD | {"requestedBy": "coordinator-1"}).items()
        if key != "coordinatorId"
    }


def test_legacy_submission_409_remains_generic_conflict(monkeypatch):
    client, _ = prepare(monkeypatch, 409, {"message": "conflict"})
    response = client.post("/booking-requests", json=PAYLOAD)
    assert response.status_code == 409
    assert response.json["conflictTypes"] == []


@pytest.mark.parametrize("body", [[], None, "not-an-object"])
def test_invalid_conflict_envelope_is_not_availability(monkeypatch, body):
    client, _ = prepare(monkeypatch, 409, body)
    assert client.post("/booking-requests", json=PAYLOAD).status_code == 502


@pytest.mark.parametrize("status", [400, 500, 503])
def test_downstream_failure_is_not_a_success_or_conflict(monkeypatch, status):
    client, _ = prepare(monkeypatch, status, {"message": "down"})
    response = client.post("/booking-requests", json=PAYLOAD)
    assert response.status_code == 502
    assert "conflictTypes" not in response.json


@pytest.mark.parametrize(
    "failure", [httpx.ReadTimeout("timeout"), httpx.ConnectError("connection failed")]
)
def test_downstream_transport_failure_is_not_availability(monkeypatch, failure):
    client, _ = prepare(monkeypatch, 201, {})

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(clients.httpx, "post", fail)
    assert client.post("/booking-requests", json=PAYLOAD).status_code == 502


@pytest.mark.parametrize(
    "stage,status,expected",
    [
        ("event", 404, 404),
        ("event", 403, 403),
        ("event", 503, 502),
        ("venue", 503, 502),
    ],
)
def test_assignment_and_catalogue_errors_prevent_submission(
    monkeypatch, stage, status, expected
):
    client, calls = prepare(monkeypatch, 201, {})
    get = clients.httpx.get

    def fail_get(url, **kwargs):
        if (stage == "event" and "/events/" in url) or (
            stage == "venue" and url.endswith("/venues")
        ):
            return httpx.Response(status, json={}, request=httpx.Request("GET", url))
        return get(url, **kwargs)

    monkeypatch.setattr(clients.httpx, "get", fail_get)
    assert client.post("/booking-requests", json=PAYLOAD).status_code == expected
    assert not any("json" in kwargs for _, kwargs in calls)


def test_create_non_object_payload_is_rejected():
    assert (
        create_app().test_client().post("/booking-requests", json=[]).status_code == 400
    )


@pytest.mark.parametrize("action", ["approve", "reject"])
@pytest.mark.parametrize("status,expected", [(200, 200), (404, 404), (503, 502)])
def test_review_client_success_not_found_and_failure(
    monkeypatch, action, status, expected
):
    client = create_app().test_client()
    monkeypatch.setattr(
        clients.httpx,
        "get",
        lambda url, **kwargs: httpx.Response(
            200,
            json=(
                {"id": "booking-1", "venueId": "venue-1"}
                if "/venue-bookings/" in url
                else {"venue": {"id": "venue-1", "setupTimeMinutes": 30, "turnaroundTimeMinutes": 45}}
            ),
            request=httpx.Request("GET", url),
        ),
    )
    monkeypatch.setattr(
        clients.httpx,
        "patch",
        lambda url, **kwargs: httpx.Response(
            status, json={"id": "booking-1"}, request=httpx.Request("PATCH", url)
        ),
    )
    response = client.patch(
        f"/booking-requests/booking-1/{action}", json={"reviewedBy": "staff-1"}
    )
    assert response.status_code == expected


def test_update_legacy_conflict_has_empty_types(monkeypatch):
    monkeypatch.setattr(
        clients.httpx,
        "patch",
        lambda url, **kwargs: httpx.Response(
            409, json={"message": "conflict"}, request=httpx.Request("PATCH", url)
        ),
    )
    with pytest.raises(clients.BookingConflictError) as error:
        clients.update_booking(
            "booking-1", "event-1", "venue-1", "start", "end", 80, ""
        )
    assert error.value.conflict_types == []


@pytest.mark.parametrize("status,expected", [(404, 404), (403, 403), (503, 502)])
def test_listing_parent_access_errors(monkeypatch, status, expected):
    monkeypatch.setattr(
        clients.httpx,
        "get",
        lambda url, **kwargs: httpx.Response(
            status, json={}, request=httpx.Request("GET", url)
        ),
    )
    assert (
        create_app()
        .test_client()
        .get("/events/event-1/booking-requests?coordinatorId=coord-1")
        .status_code
        == expected
    )


def test_listing_requires_coordinator():
    assert (
        create_app().test_client().get("/events/event-1/booking-requests").status_code
        == 400
    )


@pytest.mark.parametrize("status,expected", [(200, 200), (503, 502)])
def test_listing_calls_real_booking_client(monkeypatch, status, expected):
    client, _ = prepare(monkeypatch, 201, {})
    get = clients.httpx.get

    def booking_get(url, **kwargs):
        if url.endswith("/venue-bookings"):
            return httpx.Response(
                status, json={"bookings": []}, request=httpx.Request("GET", url)
            )
        return get(url, **kwargs)

    monkeypatch.setattr(clients.httpx, "get", booking_get)
    assert (
        client.get("/events/event-1/booking-requests?coordinatorId=coord-1").status_code
        == expected
    )


@pytest.mark.parametrize("status,expected", [(404, 404), (503, 502)])
def test_cancellation_parent_lookup_errors(monkeypatch, status, expected):
    monkeypatch.setattr(
        clients.httpx,
        "get",
        lambda url, **kwargs: httpx.Response(
            status, json={}, request=httpx.Request("GET", url)
        ),
    )
    response = (
        create_app()
        .test_client()
        .patch(
            "/booking-requests/booking-1/cancel",
            json={"eventId": "event-1", "coordinatorId": "coord-1"},
        )
    )
    assert response.status_code == expected


def test_edit_rejects_offset_times():
    response = (
        create_app()
        .test_client()
        .patch(
            "/booking-requests/booking-1",
            json=PAYLOAD | {"requestedStartTime": "2026-10-01T09:00+08:00"},
        )
    )
    assert response.status_code == 400


def test_preflight_and_unconfigured_origin(monkeypatch):
    monkeypatch.setenv("FRONTEND_ORIGIN", "")
    response = create_app().test_client().options("/booking-requests")
    assert response.status_code == 200
