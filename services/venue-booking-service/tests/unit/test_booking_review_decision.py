"""SCRUM-29 Venue Booking Review and Decision — Venue Booking unit tests.

As a Venue Staff member, I want to review and decide on a pending venue
booking request, so that I can determine whether the requested venue
arrangement can be accepted and provide the Event Coordinator with the outcome.

This composite opens a request with the event's and venue's details (AC1),
gates the decision on the Venue Staff role, event status and booking status,
validates the rejection reason (AC4) and passes the decision to Venue
Availability, which stores it. Every downstream call is mocked.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app import clients, create_app
from app.clients import BookingAlreadyDecidedError, BookingConflictError, BookingNotFoundError
from tests.unit.factories import signed_in, bearer

STAFF_ID = "d9e4002b-db91-4939-b87e-50f9cceb5e0a"
STAFF_HEADERS = bearer(STAFF_ID, "Venue Staff")
REASON = "Hall is too small for the stage"

BOOKING = {
    "id": "booking-1",
    "eventId": "evt-1",
    "venueId": "ven-1",
    "requestedStartTime": "2030-03-01T10:00:00",
    "requestedEndTime": "2030-03-01T12:00:00",
    "requiredCapacity": 120,
    "venueRequirements": "Stage and two microphones",
    "status": "Pending Review",
    "requestedBy": "coord-1",
    "reviewedBy": None,
    "requestedAt": "2030-02-01T10:00:00+08:00",
    "reviewedAt": None,
    "rejectionReason": None,
    "conflictReason": None,
    "closureRejection": None,
}
EVENT = {
    "id": "evt-1",
    "eventName": "Spring Fair",
    "status": "Under Review",
    "coordinatorId": "coord-1",
    "preferredStartDate": "2030-03-01T09:00:00",
    "preferredEndDate": "2030-03-01T17:00:00",
    "expectedAttendance": "120",
    "venueRequirements": "Stage",
    "accessibilityNeeds": "Wheelchair ramp",
    "description": "Not for Venue Staff",
    "decisionHistory": [{"status": "Under Review"}],
}
VENUE = {
    "id": "ven-1",
    "name": "Grand Ballroom",
    "location": "Level 2",
    "capacity": 150,
    "status": "Available",
    "setupTimeMinutes": 30,
    "turnaroundTimeMinutes": 45,
}


@pytest.fixture
def client():
    return signed_in(create_app().test_client())


def open_request(client, booking=BOOKING, event=EVENT, venue=VENUE, headers=STAFF_HEADERS):
    with (
        patch("app.routes.get_booking", return_value=booking) as get_booking,
        patch("app.routes.get_event_for_internal_viewer", return_value=event) as get_event,
        patch("app.routes.get_venue", return_value=venue) as get_venue,
    ):
        response = client.get("/booking-requests/booking-1", headers=headers)
    return response, get_booking, get_event, get_venue


def review(client, status, booking=BOOKING, event=EVENT, decided=None, path="review", **body):
    payload = {"reviewedBy": STAFF_ID, **body}
    if path == "review":
        payload["status"] = status
    with (
        patch("app.routes.get_booking", return_value=booking) as get_booking,
        patch("app.routes.get_event_for_internal_viewer", return_value=event),
        patch("app.routes.get_venue", return_value=VENUE),
        patch("app.routes.decide_booking") as decide,
    ):
        if isinstance(decided, Exception):
            decide.side_effect = decided
        else:
            decide.return_value = decided or {**booking, "status": status}
        response = client.patch(
            f"/booking-requests/booking-1/{path}", headers=STAFF_HEADERS, json=payload
        )
    return response, get_booking, decide


# AC1 ------------------------------------------------------------------------


def test_ac1_opening_a_request_shows_event_timing_and_requirements(client):
    """Normal: one view combines the booking, the event's needs and the venue's limits."""
    response, _, get_event, get_venue = open_request(client)

    assert response.status_code == 200
    body = response.json
    assert body["event"] == {
        "id": "evt-1",
        "eventName": "Spring Fair",
        "status": "Under Review",
        "coordinatorId": "coord-1",
        "preferredStartDate": "2030-03-01T09:00:00",
        "preferredEndDate": "2030-03-01T17:00:00",
        "expectedAttendance": "120",
        "venueRequirements": "Stage",
        "accessibilityNeeds": "Wheelchair ramp",
    }
    assert body["venue"] == {
        "id": "ven-1",
        "name": "Grand Ballroom",
        "capacity": 150,
        "status": "Available",
        "setupTimeMinutes": 30,
        "turnaroundTimeMinutes": 45,
    }
    assert body["booking"]["venueRequirements"] == "Stage and two microphones"
    assert body["booking"]["requiredCapacity"] == 120
    assert body["booking"]["venueName"] == "Grand Ballroom"
    assert body["booking"]["awaitingReview"] is True
    assert body["canDecide"] is True
    assert body["decisionBlockedReason"] is None
    get_event.assert_called_once_with("evt-1", "Venue Staff")
    get_venue.assert_called_once_with("ven-1")


def test_ac1_occupied_window_includes_setup_and_turnaround(client):
    """Boundary: 10:00-12:00 with 30 min setup and 45 min turnaround occupies 09:30-12:45."""
    response, *_ = open_request(client)

    assert response.json["booking"]["occupiedFrom"] == "2030-03-01T09:30:00"
    assert response.json["booking"]["occupiedTo"] == "2030-03-01T12:45:00"


def test_ac1_occupied_window_is_null_when_booking_times_are_unreadable(client):
    """Boundary: a booking with no readable time shows no occupied window."""
    response, *_ = open_request(client, booking={**BOOKING, "requestedStartTime": None})

    assert response.json["booking"]["occupiedFrom"] is None
    assert response.json["booking"]["occupiedTo"] == "2030-03-01T12:45:00"


def test_ac1_unset_event_fields_are_null_not_empty_strings(client):
    """Boundary: Event Service's "" for unset fields reaches the UI as null."""
    event = {**EVENT, "preferredStartDate": "", "expectedAttendance": "", "accessibilityNeeds": ""}

    response, *_ = open_request(client, event=event)

    assert response.json["event"]["preferredStartDate"] is None
    assert response.json["event"]["expectedAttendance"] is None
    assert response.json["event"]["accessibilityNeeds"] is None


def test_ac1_venue_without_a_name_is_labelled_unknown(client):
    """Boundary: a nameless venue is labelled rather than left blank."""
    response, *_ = open_request(client, venue={**VENUE, "name": ""})

    assert response.json["booking"]["venueName"] == "Unknown venue"


@pytest.mark.parametrize(
    "headers,code",
    # An empty Authorization header overrides the client's default sign-in: no token.
    [({"Authorization": ""}, 401), (bearer(STAFF_ID, "Event Coordinator"), 403)],
)
def test_ac1_request_view_requires_venue_staff(client, headers, code):
    """Failure: only Venue Staff can open a request, and nothing is fetched otherwise."""
    response, get_booking, get_event, get_venue = open_request(client, headers=headers)

    assert response.status_code == code
    get_booking.assert_not_called()
    get_event.assert_not_called()
    get_venue.assert_not_called()


def test_ac1_unknown_booking_is_404(client):
    """Failure: a booking Venue Availability doesn't know is reported as not found."""
    with patch("app.routes.get_booking", side_effect=BookingNotFoundError):
        response = client.get("/booking-requests/missing", headers=STAFF_HEADERS)
    assert response.status_code == 404


@pytest.mark.parametrize(
    "error,code", [(RuntimeError("down"), 502), (httpx.ConnectTimeout("slow"), 504)]
)
def test_ac1_downstream_failure_is_502_and_timeout_504(client, error, code):
    """Failure: Event or Venue Service failing never leaks its error text."""
    with (
        patch("app.routes.get_booking", return_value=BOOKING),
        patch("app.routes.get_event_for_internal_viewer", side_effect=error),
        patch("app.routes.get_venue", return_value=VENUE),
    ):
        response = client.get("/booking-requests/booking-1", headers=STAFF_HEADERS)
    assert response.status_code == code
    assert "down" not in response.json["message"]


@pytest.mark.parametrize(
    "event_status,booking_status,reason",
    [
        ("Approved", "Pending", None),
        ("Safety Changes Requested", "Pending Review", None),
        ("Submitted", "Pending Review", "Opens for review when the event is Under Review"),
        ("Pending Safety Check", "Pending Review", "Not open for review while the event is Pending Safety Check"),
        ("Under Review", "Approved", "Already decided"),
        ("Under Review", "Rejected", "Already decided"),
    ],
)
def test_ac1_can_decide_only_when_awaiting_and_event_reviewable(
    client, event_status, booking_status, reason
):
    """Normal/Conflict: the view says whether a decision is possible, and why not."""
    response, *_ = open_request(
        client,
        booking={**BOOKING, "status": booking_status},
        event={**EVENT, "status": event_status},
    )

    assert response.json["canDecide"] is (reason is None)
    assert response.json["decisionBlockedReason"] == reason
    assert response.json["booking"]["awaitingReview"] is (
        booking_status in ("Pending", "Pending Review")
    )


# AC2 ------------------------------------------------------------------------


def test_ac2_approval_is_recorded_and_returned(client):
    """Normal: approval is forwarded with the venue's buffers and returns the decision time."""
    decided = {**BOOKING, "status": "Approved", "reviewedBy": STAFF_ID,
               "reviewedAt": "2030-02-02T09:00:00+08:00"}

    response, _, decide = review(client, "Approved", decided=decided)

    assert response.status_code == 200
    assert response.json["status"] == "Approved"
    assert response.json["reviewedAt"] == "2030-02-02T09:00:00+08:00"
    decide.assert_called_once_with("booking-1", "Approved", 30, 45)


def test_ac2_approval_conflict_is_passed_through(client):
    """Conflict: Venue Availability's buffered-overlap refusal reaches the UI unchanged."""
    response, *_ = review(
        client, "Approved", decided=BookingConflictError(["APPROVED_BOOKING", "TENTATIVE_HOLD"])
    )

    assert response.status_code == 409
    assert response.json["code"] == "VENUE_UNAVAILABLE"
    assert response.json["conflictTypes"] == ["APPROVED_BOOKING", "TENTATIVE_HOLD"]


def test_ac2_availability_failure_is_502(client):
    """Failure: Venue Availability failing to record the decision is a dependency error."""
    response, *_ = review(client, "Approved", decided=RuntimeError("down"))

    assert response.status_code == 502


# AC3 ------------------------------------------------------------------------


def test_ac3_rejection_with_reason_is_recorded(client):
    """Normal: the trimmed reason is forwarded and comes back on the booking."""
    decided = {**BOOKING, "status": "Rejected", "rejectionReason": REASON}

    response, _, decide = review(
        client, "Rejected", decided=decided, rejectionReason=f"\n  {REASON}  "
    )

    assert response.status_code == 200
    assert response.json["rejectionReason"] == REASON
    decide.assert_called_once_with("booking-1", "Rejected", rejection_reason=REASON)


# AC4 ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [{}, {"rejectionReason": ""}, {"rejectionReason": "  "}, {"rejectionReason": None},
     {"rejectionReason": ["x"]}, {"rejectionReason": "x" * 501}],
    ids=["missing", "empty", "blank", "null", "list", "501-chars"],
)
def test_ac4_rejection_without_reason_is_refused_before_any_call(client, body):
    """Failure: no usable reason means 400 before any downstream lookup."""
    response, get_booking, decide = review(client, "Rejected", **body)

    assert response.status_code == 400
    assert response.json["code"] == "REJECTION_REASON_REQUIRED"
    get_booking.assert_not_called()
    decide.assert_not_called()


def test_ac4_reason_of_exactly_500_characters_is_accepted(client):
    """Boundary: 500 characters is the longest reason forwarded."""
    response, _, decide = review(client, "Rejected", rejectionReason="x" * 500)

    assert response.status_code == 200
    assert decide.call_args.kwargs["rejection_reason"] == "x" * 500


def test_ac4_availability_refusing_the_reason_is_400_not_502(client):
    """Failure: if Venue Availability still refuses the reason, the UI gets a 400."""
    response, *_ = review(
        client, "Rejected", decided=clients.RejectionReasonRequiredError(), rejectionReason=REASON
    )

    assert response.status_code == 400
    assert response.json["code"] == "REJECTION_REASON_REQUIRED"


# AC5 ------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["Approved", "Rejected", "Cancelled"])
def test_ac5_decided_booking_is_refused_with_booking_already_decided(client, status):
    """Conflict: a booking no longer awaiting review is never sent to be decided."""
    response, _, decide = review(
        client, "Rejected", booking={**BOOKING, "status": status}, rejectionReason=REASON
    )

    assert response.status_code == 409
    assert response.json["code"] == "BOOKING_ALREADY_DECIDED"
    assert response.json["message"] == "This venue request is not awaiting staff review."
    decide.assert_not_called()


def test_ac5_race_at_availability_is_reported_as_already_decided(client):
    """Conflict: another staff member deciding first is reported, not a 502."""
    response, *_ = review(client, "Approved", decided=BookingAlreadyDecidedError())

    assert response.status_code == 409
    assert response.json["code"] == "BOOKING_ALREADY_DECIDED"


@pytest.mark.parametrize("event_status", ["Submitted", "Pending Safety Check", "Confirmed", "Cancelled"])
def test_event_not_reviewable_has_its_own_code(client, event_status):
    """Conflict: an event outside review gets EVENT_NOT_REVIEWABLE, with its status."""
    response, _, decide = review(client, "Approved", event={**EVENT, "status": event_status})

    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_REVIEWABLE"
    assert response.json["eventStatus"] == event_status
    assert response.json["message"] == "This venue request is not awaiting staff review."
    decide.assert_not_called()


@patch("app.routes.get_safety_records")
@patch("app.routes.get_event_bookings")
@patch("app.routes.get_venues")
@patch("app.routes.get_staff_events")
def test_ac5_staff_queue_marks_decided_booking_not_awaiting(events, venues, bookings, _records, client):
    """Normal: a decided booking is no longer counted or filtered as awaiting."""
    events.return_value = [EVENT]
    venues.return_value = [VENUE]
    decided = {**BOOKING, "id": "booking-2", "status": "Rejected",
               "reviewedAt": "2030-02-02T09:00:00+08:00", "rejectionReason": REASON}
    bookings.side_effect = lambda *_: [dict(BOOKING), dict(decided)]

    every = client.get("/booking-requests", headers=STAFF_HEADERS).json["events"][0]
    pending = client.get("/booking-requests?status=Pending", headers=STAFF_HEADERS).json["events"][0]

    assert every["awaitingReviewCount"] == 1
    rejected = next(b for b in every["bookings"] if b["id"] == "booking-2")
    assert rejected["awaitingReview"] is False
    assert rejected["rejectionReason"] == REASON
    assert rejected["reviewedAt"] == "2030-02-02T09:00:00+08:00"
    assert [b["id"] for b in pending["bookings"]] == ["booking-1"]


# AC6 ------------------------------------------------------------------------


@patch("app.routes.get_venues", return_value=[VENUE])
@patch("app.routes.get_event_bookings")
@patch("app.routes.get_event", return_value=EVENT)
def test_ac6_coordinator_list_returns_decision_and_reason(_event, bookings, _venues, client):
    """Normal: the coordinator's booking list carries the rejection reason and its time."""
    bookings.return_value = [
        {**BOOKING, "status": "Rejected", "reviewedAt": "2030-02-02T09:00:00+08:00",
         "rejectionReason": REASON}
    ]

    response = client.get("/events/evt-1/booking-requests?coordinatorId=coord-1")

    [booking] = response.json["bookings"]
    assert booking["status"] == "Rejected"
    assert booking["rejectionReason"] == REASON
    assert booking["reviewedAt"] == "2030-02-02T09:00:00+08:00"


# D7: legacy routes ----------------------------------------------------------


def test_legacy_reject_route_requires_staff_and_reason(client):
    """Failure: /reject can no longer bypass the role check or the reason."""
    assert client.patch(
        "/booking-requests/booking-1/reject",
        json={"rejectionReason": REASON},
        headers={"Authorization": ""},  # no token
    ).status_code == 401

    response, get_booking, decide = review(client, "Rejected", path="reject")
    assert response.status_code == 400
    assert response.json["code"] == "REJECTION_REASON_REQUIRED"
    get_booking.assert_not_called()

    response, _, decide = review(client, "Rejected", path="reject", rejectionReason=REASON)
    assert response.status_code == 200
    decide.assert_called_once_with("booking-1", "Rejected", rejection_reason=REASON)


def test_legacy_approve_route_runs_the_event_status_gate(client):
    """Conflict: /approve refuses an event outside review, like /review."""
    response, _, decide = review(
        client, "Approved", path="approve", event={**EVENT, "status": "Pending Safety Check"}
    )
    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_REVIEWABLE"
    decide.assert_not_called()


# Client ---------------------------------------------------------------------


def _reply(status, body):
    return httpx.Response(status, json=body, request=httpx.Request("PATCH", "http://test"))


@pytest.mark.parametrize("status,sends_reason", [("Approved", False), ("Rejected", True)])
def test_decide_booking_sends_reason_only_when_rejecting(monkeypatch, status, sends_reason):
    """Normal: the reason is part of a reject's body and absent from an approval's."""
    sent = MagicMock(return_value=_reply(200, {"id": "booking-1"}))
    monkeypatch.setattr(clients.httpx, "patch", sent)

    clients.decide_booking("booking-1", status, 30, 45, REASON)

    url = sent.call_args.args[0]
    body = sent.call_args.kwargs["json"]
    assert url.endswith("/venue-bookings/booking-1/" + ("reject" if sends_reason else "approve"))
    assert ("rejectionReason" in body) is sends_reason
    if sends_reason:
        assert body["rejectionReason"] == REASON


@pytest.mark.parametrize(
    "status,code,error",
    [
        (409, "BOOKING_ALREADY_DECIDED", clients.BookingAlreadyDecidedError),
        (400, "REJECTION_REASON_REQUIRED", clients.RejectionReasonRequiredError),
        (400, "SOMETHING_ELSE", httpx.HTTPStatusError),
    ],
)
def test_decide_booking_maps_already_decided_and_reason_required(monkeypatch, status, code, error):
    """Failure: Venue Availability's typed refusals become typed client errors."""
    monkeypatch.setattr(clients.httpx, "patch", lambda *a, **k: _reply(status, {"code": code}))

    with pytest.raises(error):
        clients.decide_booking("booking-1", "Rejected", rejection_reason=REASON)


def test_event_without_a_status_is_refused_not_a_crash(client):
    """Failure: a malformed Event Service answer is a 409, never a 500."""
    response, _, decide = review(client, "Approved", event={k: v for k, v in EVENT.items() if k != "status"})

    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_REVIEWABLE"
    decide.assert_not_called()
