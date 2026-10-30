"""
SCRUM-30: Check Venue Availability

User Story
----------
As an Event Coordinator, I want to check availability for a selected venue and
booking period, so that I can avoid submitting a venue request that conflicts
with an existing event or closure.

Acceptance Criteria
-------------------
AC1: Given no conflicting confirmed bookings exist for the selected valid venue
     and booking start/end times, when the Event Coordinator submits the
     booking request, then the request is created with status Pending Review.
AC2: Given the selected date and time interval overlaps an approved booking,
     applicable tentative hold, or recorded closure for that venue, then the
     system reports the conflict type and indicates that the venue request
     cannot be submitted for that interval.

SCRUM-156: Book Multiple Venues for an Event

User Story
----------
As an Event Coordinator, I want to create multiple venue booking requests for a
single event, so that I can arrange the different spaces required for the event

Acceptance Criteria
-------------------
AC1: Given an event exists, when the Event Coordinator creates venue booking
     requests, then more than one venue booking can be associated with the same
     event.
AC2: Each venue booking records its own venue, date/time, required
     capacity/expected attendance, venue requirements, and booking status.
AC3: Given multiple venue bookings exist for an event, when the Event
     Coordinator views the event, then each booking is displayed separately
     while remaining associated with the same event.
AC4: When a venue booking is submitted, its suitability, availability, and
     booking conflicts are evaluated using the requirements of that specific
     booking.
AC5: If one venue booking fails a suitability, availability, or conflict check,
     other valid venue bookings for the same event can still proceed.
AC6: Different venues requested for the same event during overlapping time
     periods are not considered conflicting solely because they belong to the
     same event.

Real
----
- The composite booking routes and app.clients: typed conflicts from Venue
  Availability passed through on submit, edit and approve; malformed conflict
  data and downstream failures never reported as availability; listing and
  cancellation parent-event checks.
- Assertions are on the status and the conflict types returned.

Doubled
-------
- Event, Venue, Venue Availability, Safety Check Record and Safety Check
  Services: Stub (unittest.mock.patch / monkeypatch on app.routes and
  app.clients, or respx for client tests) - canned answers or raised client
  errors; calls recorded so tests assert what was (or was not) called.

Not proven
----------
- That the atomic services behave as stubbed (-> their own unit and integration
  tests, and tests/integration/ here with respx).
"""

import httpx
import pytest

from app import clients, create_app
from tests.unit.factories import signed_in, bearer

# SCRUM-29 D7: the legacy approve/reject routes now require Venue Staff.
STAFF_ID = "d9e4002b-db91-4939-b87e-50f9cceb5e0a"
STAFF_HEADERS = bearer(STAFF_ID, "Venue Staff")

PAYLOAD = dict(
    eventId="event-1",
    venueId="venue-1",
    coordinatorId="coordinator-1",
    requestedStartTime="2030-10-01T09:00",
    requestedEndTime="2030-10-01T12:00",
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
            else {
                "id": "booking-1",
                "eventId": "event-1",
                "venueId": "venue-1",
                "status": "Pending Review",
            }
            if url.endswith("/venue-bookings/booking-1")
            else {"id": "event-1", "status": "Under Review"}
        )
        return httpx.Response(200, json=data, request=httpx.Request("GET", url))

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(clients.httpx, "get", get)
    monkeypatch.setattr(clients.httpx, "post", post)
    return signed_in(create_app().test_client()), calls


def test_create_request_overlapping_approved_booking_returns_conflict_type(monkeypatch):
    """
    Summary: A request clashing with an approved booking is refused with that conflict type.
    AC2: Given the selected date and time interval overlaps an approved
        booking, applicable tentative hold, or recorded closure for that venue,
        then the system reports the conflict type and indicates that the venue
        request cannot be submitted for that interval.
    Double: Stub (Venue Availability returns an APPROVED_BOOKING conflict)
    """
    # Arrange (Given)
    body = {
        "code": "VENUE_UNAVAILABLE",
        "conflictTypes": ["APPROVED_BOOKING"],
        "message": "This venue is unavailable for the requested time.",
    }
    client, calls = prepare(monkeypatch, 409, body)

    # Act (When)
    response = client.post("/booking-requests", json=PAYLOAD)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == body["code"]
    assert response.json["conflictTypes"] == body["conflictTypes"]
    # SCRUM-8: the coordinator travels as their token, not as request fields.
    assert "params" not in calls[0][1]
    assert "requestedBy" not in calls[-1][1]["json"]
    assert all(call[1]["headers"]["Authorization"].startswith("Bearer ") for call in calls)


@pytest.mark.parametrize("action", ["edit", "approve"], ids=["edit", "approve"])
def test_edit_or_approve_conflict_keeps_its_type(monkeypatch, action):
    """
    Summary: Editing or approving into a conflict reports its type.
    AC2: Given the selected date and time interval overlaps an approved
        booking, applicable tentative hold, or recorded closure for that venue,
        then the system reports the conflict type and indicates that the venue
        request cannot be submitted for that interval.
    Double: Stub (Venue Availability returns a typed conflict)
    """
    # Arrange (Given)
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

    # Act (When)
    response = client.patch(
        path,
        json={"reviewedBy": STAFF_ID} if action == "approve" else PAYLOAD,
        headers=STAFF_HEADERS if action == "approve" else {},
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "VENUE_UNAVAILABLE"
    assert response.json["conflictTypes"] == body["conflictTypes"]


@pytest.mark.parametrize("types", ["VENUE_CLOSURE", ["UNKNOWN"], [None], None, {}], ids=["venue_closure", "unknown", "none", "none_2", "empty"])
def test_create_request_with_malformed_conflict_data_returns_502(monkeypatch, types):
    """
    Summary: Unreadable conflict details are a dependency failure, never "available".
    AC2: Given the selected date and time interval overlaps an approved
        booking, applicable tentative hold, or recorded closure for that venue,
        then the system reports the conflict type and indicates that the venue
        request cannot be submitted for that interval.
    Double: Stub (Venue Availability returns malformed conflict types)
    """
    # Arrange (Given)
    client, _ = prepare(
        monkeypatch, 409, {"code": "VENUE_UNAVAILABLE", "conflictTypes": types}
    )

    # Act (When)
    response = client.post("/booking-requests", json=PAYLOAD)

    # Assert (Then)
    assert response.status_code == 502
    assert "conflictTypes" not in response.json


@pytest.mark.parametrize(
    "types",
    [
        ["TENTATIVE_HOLD"],
        ["VENUE_CLOSURE"],
        ["APPROVED_BOOKING", "TENTATIVE_HOLD", "VENUE_CLOSURE"],
    ],
    ids=["tentative_hold", "venue_closure", "several"],
)
def test_create_request_reports_every_conflict_type(monkeypatch, types):
    """
    Summary: Hold, closure and multiple conflict types all reach the coordinator.
    AC2: Given the selected date and time interval overlaps an approved
        booking, applicable tentative hold, or recorded closure for that venue,
        then the system reports the conflict type and indicates that the venue
        request cannot be submitted for that interval.
    Double: Stub (Venue Availability returns the types)
    """
    # Arrange (Given)
    client, _ = prepare(
        monkeypatch, 409, {"code": "VENUE_UNAVAILABLE", "conflictTypes": types}
    )

    # Act (When)
    response = client.post("/booking-requests", json=PAYLOAD)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["conflictTypes"] == types


def test_create_request_without_conflict_returns_pending_review(monkeypatch):
    """
    Summary: A request with no conflict is created as Pending Review.
    AC1: Given no conflicting confirmed bookings exist for the selected valid
        venue and booking start/end times, when the Event Coordinator submits
        the booking request, then the request is created with status Pending
        Review.
    Double: Stub (Venue Availability creates the booking)
    """
    # Arrange (Given)
    booking = {"id": "booking-1", "status": "Pending Review", "eventId": "event-1"}
    client, calls = prepare(monkeypatch, 201, booking)

    # Act (When)
    response = client.post("/booking-requests", json=PAYLOAD)

    # Assert (Then)
    assert response.status_code == 201
    assert response.json == booking
    assert calls[-1][1]["json"] == {
        key: value
        for key, value in PAYLOAD.items()
        if key != "coordinatorId"
    }


def test_create_request_with_untyped_409_returns_generic_conflict(monkeypatch):
    """
    Summary: An older conflict answer without types still reports a conflict.
    AC2: Given the selected date and time interval overlaps an approved
        booking, applicable tentative hold, or recorded closure for that venue,
        then the system reports the conflict type and indicates that the venue
        request cannot be submitted for that interval.
    Double: Stub (Venue Availability answers a plain 409)
    """
    # Arrange (Given)
    client, _ = prepare(monkeypatch, 409, {"message": "conflict"})

    # Act (When)
    response = client.post("/booking-requests", json=PAYLOAD)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["conflictTypes"] == []


@pytest.mark.parametrize("body", [[], None, "not-an-object"], ids=["list_body", "null_body", "text_body"])
def test_create_request_with_unreadable_conflict_body_returns_502(monkeypatch, body):
    """
    Summary: An unreadable conflict answer is never treated as availability.
    AC2: Given the selected date and time interval overlaps an approved
        booking, applicable tentative hold, or recorded closure for that venue,
        then the system reports the conflict type and indicates that the venue
        request cannot be submitted for that interval.
    Double: Stub (Venue Availability answers 409 with a bad body)
    """
    # Arrange (Given)
    client, _ = prepare(monkeypatch, 409, body)

    # Act + Assert (When / Then)
    assert client.post("/booking-requests", json=PAYLOAD).status_code == 502


@pytest.mark.parametrize("status", [400, 500, 503], ids=["bad_request", "server_error", "unavailable"])
def test_create_request_when_availability_fails_returns_error(monkeypatch, status):
    """
    Summary: A Venue Availability failure is neither a success nor a conflict.
    AC1: Given no conflicting confirmed bookings exist for the selected valid
        venue and booking start/end times, when the Event Coordinator submits
        the booking request, then the request is created with status Pending
        Review.
    Double: Stub (Venue Availability answers the status)
    """
    # Arrange (Given)
    client, _ = prepare(monkeypatch, status, {"message": "down"})

    # Act (When)
    response = client.post("/booking-requests", json=PAYLOAD)

    # Assert (Then)
    assert response.status_code == 502
    assert "conflictTypes" not in response.json


@pytest.mark.parametrize(
    "failure", [httpx.ReadTimeout("timeout"), httpx.ConnectError("connection failed")],
    ids=["timeout", "connect_error"],
)
def test_create_request_when_availability_unreachable_returns_error(monkeypatch, failure):
    """
    Summary: An unreachable Venue Availability is never treated as available.
    AC1: Given no conflicting confirmed bookings exist for the selected valid
        venue and booking start/end times, when the Event Coordinator submits
        the booking request, then the request is created with status Pending
        Review.
    Double: Stub (httpx raises)
    """
    # Arrange (Given)
    client, _ = prepare(monkeypatch, 201, {})

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(clients.httpx, "post", fail)

    # Act + Assert (When / Then)
    assert client.post("/booking-requests", json=PAYLOAD).status_code == 502


@pytest.mark.parametrize(
    "stage,status,expected",
    [
        ("event", 404, 404),
        ("event", 403, 403),
        ("event", 503, 502),
        ("venue", 503, 502),
    ],
    ids=["event_not_found", "event_forbidden", "event_down", "venue_down"],
)
def test_create_request_when_event_or_venue_lookup_fails_is_not_submitted(
    monkeypatch, stage, status, expected
):
    """
    Summary: If the event or venue lookup fails, nothing is submitted.
    AC1: Given no conflicting confirmed bookings exist for the selected valid
        venue and booking start/end times, when the Event Coordinator submits
        the booking request, then the request is created with status Pending
        Review.
    Double: Stub (event or venue lookup fails)
    """
    # Arrange (Given)
    client, calls = prepare(monkeypatch, 201, {})
    get = clients.httpx.get

    def fail_get(url, **kwargs):
        if (stage == "event" and "/events/" in url) or (
            stage == "venue" and url.endswith("/venues")
        ):
            return httpx.Response(status, json={}, request=httpx.Request("GET", url))
        return get(url, **kwargs)

    monkeypatch.setattr(clients.httpx, "get", fail_get)

    # Act + Assert (When / Then)
    assert client.post("/booking-requests", json=PAYLOAD).status_code == expected
    assert not any("json" in kwargs for _, kwargs in calls)


def test_create_request_with_non_object_body_returns_400():
    """
    Summary: A request that is not a booking is refused.
    AC1: Given no conflicting confirmed bookings exist for the selected valid
        venue and booking start/end times, when the Event Coordinator submits
        the booking request, then the request is created with status Pending
        Review.
    Double: None
    """
    # Act + Assert (When / Then)
    assert (
        signed_in(create_app().test_client()).post("/booking-requests", json=[]).status_code == 400
    )


@pytest.mark.parametrize("action", ["approve", "reject"], ids=["approve", "reject"])
@pytest.mark.parametrize("status,expected", [(200, 200), (404, 404), (503, 502)], ids=["success", "not_found", "failure"])
def test_review_client_maps_success_not_found_and_failure(
    monkeypatch, action, status, expected
):
    """
    Summary: Review calls map success, not-found and failure correctly.
    AC1: Given no conflicting confirmed bookings exist for the selected valid
        venue and booking start/end times, when the Event Coordinator submits
        the booking request, then the request is created with status Pending
        Review.
    Double: Stub (respx Venue Availability)
    """
    # Arrange (Given)
    client = signed_in(create_app().test_client())
    monkeypatch.setattr(
        clients.httpx,
        "get",
        lambda url, **kwargs: httpx.Response(
            200,
            json=(
                {
                    "id": "booking-1",
                    "eventId": "event-1",
                    "venueId": "venue-1",
                    "status": "Pending Review",
                }
                if "/venue-bookings/" in url
                else {"id": "event-1", "status": "Under Review"}
                if "/events/" in url
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

    # Act (When)
    response = client.patch(
        f"/booking-requests/booking-1/{action}",
        headers=STAFF_HEADERS,
        json={"reviewedBy": STAFF_ID, "rejectionReason": "Venue unsuitable"},
    )

    # Assert (Then)
    assert response.status_code == expected


def test_update_client_with_untyped_conflict_returns_empty_types(monkeypatch):
    """
    Summary: An edit conflict without types is reported with no types.
    AC2: Given the selected date and time interval overlaps an approved
        booking, applicable tentative hold, or recorded closure for that venue,
        then the system reports the conflict type and indicates that the venue
        request cannot be submitted for that interval.
    Double: Stub (respx answers 409)
    """
    # Arrange (Given)
    monkeypatch.setattr(
        clients.httpx,
        "patch",
        lambda url, **kwargs: httpx.Response(
            409, json={"message": "conflict"}, request=httpx.Request("PATCH", url)
        ),
    )

    # Act + Assert (When / Then)
    with pytest.raises(clients.BookingConflictError) as error:
        clients.update_booking(
            "booking-1", "event-1", "venue-1", "start", "end", 80, ""
        )

    # Assert (Then)
    assert error.value.conflict_types == []


@pytest.mark.parametrize("status,expected", [(404, 404), (403, 403), (503, 502)], ids=["not_found", "forbidden", "unavailable"])
def test_list_event_requests_when_event_check_fails_returns_error(monkeypatch, status, expected):
    """
    Summary: Listing an event's requests fails cleanly when the event check fails.
    SCRUM-156 AC3: Given multiple venue bookings exist for an event, when the
        Event Coordinator views the event, then each booking is displayed
        separately while remaining associated with the same event.
    Double: Stub (event lookup fails)
    """
    # Arrange (Given)
    monkeypatch.setattr(
        clients.httpx,
        "get",
        lambda url, **kwargs: httpx.Response(
            status, json={}, request=httpx.Request("GET", url)
        ),
    )

    # Act + Assert (When / Then)
    assert (
        signed_in(create_app().test_client())
        .get("/events/event-1/booking-requests?coordinatorId=coord-1")
        .status_code
        == expected
    )


def test_list_event_requests_without_signed_in_user_returns_401():
    """
    Summary: Listing needs a signed-in coordinator.
    SCRUM-156 AC3: Given multiple venue bookings exist for an event, when the
        Event Coordinator views the event, then each booking is displayed
        separately while remaining associated with the same event.
    Double: None
    """
    # Act + Assert (When / Then)
    assert create_app().test_client().get("/events/event-1/booking-requests").status_code == 401


@pytest.mark.parametrize("status,expected", [(200, 200), (503, 502)], ids=["success", "unavailable"])
def test_list_event_requests_uses_booking_client(monkeypatch, status, expected):
    """
    Summary: Listing reads the event's bookings from Venue Availability.
    SCRUM-156 AC3: Given multiple venue bookings exist for an event, when the
        Event Coordinator views the event, then each booking is displayed
        separately while remaining associated with the same event.
    Double: Stub (respx Venue Availability)
    """
    # Arrange (Given)
    client, _ = prepare(monkeypatch, 201, {})
    get = clients.httpx.get

    def booking_get(url, **kwargs):
        if url.endswith("/venue-bookings"):
            return httpx.Response(
                status, json={"bookings": []}, request=httpx.Request("GET", url)
            )
        return get(url, **kwargs)

    monkeypatch.setattr(clients.httpx, "get", booking_get)

    # Act + Assert (When / Then)
    assert (
        client.get("/events/event-1/booking-requests?coordinatorId=coord-1").status_code
        == expected
    )


@pytest.mark.parametrize("status,expected", [(404, 404), (503, 502)], ids=["not_found", "unavailable"])
def test_cancel_request_when_event_check_fails_returns_error(monkeypatch, status, expected):
    """
    Summary: Cancelling fails cleanly when the event check fails.
    SCRUM-156 AC3: Given multiple venue bookings exist for an event, when the
        Event Coordinator views the event, then each booking is displayed
        separately while remaining associated with the same event.
    Double: Stub (event lookup fails)
    """
    # Arrange (Given)
    monkeypatch.setattr(
        clients.httpx,
        "get",
        lambda url, **kwargs: httpx.Response(
            status, json={}, request=httpx.Request("GET", url)
        ),
    )

    # Act (When)
    response = (
        signed_in(create_app().test_client())
        .patch(
            "/booking-requests/booking-1/cancel",
            json={"eventId": "event-1", "coordinatorId": "coord-1"},
        )
    )

    # Assert (Then)
    assert response.status_code == expected


def test_edit_request_with_offset_times_returns_400():
    """
    Summary: Edited times must be local Singapore times.
    AC2: Given the selected date and time interval overlaps an approved
        booking, applicable tentative hold, or recorded closure for that venue,
        then the system reports the conflict type and indicates that the venue
        request cannot be submitted for that interval.
    Double: None
    """
    # Act (When)
    response = (
        signed_in(create_app().test_client())
        .patch(
            "/booking-requests/booking-1",
            json=PAYLOAD | {"requestedStartTime": "2030-10-01T09:00+08:00"},
        )
    )

    # Assert (Then)
    assert response.status_code == 400


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_preflight_answers_and_blank_origin_allows_nothing(monkeypatch):
    """
    Summary: Browser preflights are answered, and a blank frontend origin allows no website.
    Supporting design check: CORS for the configured frontend origin
    Double: None
    """
    monkeypatch.setenv("FRONTEND_ORIGIN", "")
    response = signed_in(create_app().test_client()).options("/booking-requests")
    assert response.status_code == 200
