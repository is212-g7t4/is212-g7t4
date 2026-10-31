"""
SCRUM-29: Venue Booking Review and Decision

User Story
----------
As a Venue Staff member, I want to review and decide on a pending venue booking
request, so that I can determine whether the requested venue arrangement can be
accepted and provide the Event Coordinator with the outcome.

Acceptance Criteria
-------------------
AC1: Given a venue booking request is pending review, when Venue Staff open the
     request, then they can view the relevant event timing and venue
     requirements needed to assess the booking.
AC2: Given Venue Staff determine that a pending venue booking request can be
     accepted, when they approve the request, then the booking decision is
     recorded as approved and the outcome is available to the relevant Event
     Coordinator.
AC3: Given Venue Staff determine that a pending venue booking request cannot be
     accepted, when they reject the request, then the booking decision is
     recorded as rejected and the outcome is available to the relevant Event
     Coordinator.
AC4: Given a venue booking request cannot be accepted, when Venue Staff record
     their decision, then they can provide relevant information or a reason
     explaining why the booking cannot be accepted.
AC5: Given Venue Staff have recorded an approval or rejection for a pending
     venue booking request, when the decision is completed, then the request is
     no longer presented as awaiting a booking decision.
AC6: Given a booking request has been rejected and Venue Staff have provided
     relevant information or a reason, when the Event Coordinator views the
     booking decision, then they can view that information so that they can
     continue planning the event.

Real
----
- GET /booking-requests/<id> (one view of booking, event needs and venue, with
  the buffered occupied window and whether it can be decided) and PATCH
  .../review, .../approve, .../reject: the Venue Staff check, the event-status
  gate, reason rules and the mapping of Venue Availability's typed refusals.
- Assertions are on the status, codes and the view returned.

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


def test_ac1_open_request_shows_booking_event_needs_and_venue(client):
    """
    Summary: Opening a request shows the booking with the event's timing and requirements.
    AC1: Given a venue booking request is pending review, when Venue Staff open
        the request, then they can view the relevant event timing and venue
        requirements needed to assess the booking.
    Double: Stub (booking, event, venue)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response, _, get_event, get_venue = open_request(client)

    # Assert (Then)
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


def test_ac1_open_request_shows_occupied_window_with_buffers(client):
    """
    Summary: The view shows the venue's full occupied time, setup and turnaround included.
    AC1: Given a venue booking request is pending review, when Venue Staff open
        the request, then they can view the relevant event timing and venue
        requirements needed to assess the booking.
    Double: Stub (venue with buffers)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response, *_ = open_request(client)

    # Assert (Then)
    assert response.json["booking"]["occupiedFrom"] == "2030-03-01T09:30:00"
    assert response.json["booking"]["occupiedTo"] == "2030-03-01T12:45:00"


def test_ac1_open_request_with_unreadable_times_shows_no_occupied_window(client):
    """
    Summary: A booking with unreadable times shows no occupied window.
    AC1: Given a venue booking request is pending review, when Venue Staff open
        the request, then they can view the relevant event timing and venue
        requirements needed to assess the booking.
    Double: Stub (booking without times)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response, *_ = open_request(client, booking={**BOOKING, "requestedStartTime": None})

    # Assert (Then)
    assert response.json["booking"]["occupiedFrom"] is None
    assert response.json["booking"]["occupiedTo"] == "2030-03-01T12:45:00"


def test_ac1_open_request_shows_unset_event_fields_as_null(client):
    """
    Summary: Unset event fields are shown as nothing, not empty text.
    AC1: Given a venue booking request is pending review, when Venue Staff open
        the request, then they can view the relevant event timing and venue
        requirements needed to assess the booking.
    Double: Stub (event with empty fields)
    """
    # Arrange (Given)
    event = {**EVENT, "preferredStartDate": "", "expectedAttendance": "", "accessibilityNeeds": ""}

    # Act (When)
    response, *_ = open_request(client, event=event)

    # Assert (Then)
    assert response.json["event"]["preferredStartDate"] is None
    assert response.json["event"]["expectedAttendance"] is None
    assert response.json["event"]["accessibilityNeeds"] is None


def test_ac1_open_request_labels_unnamed_venue(client):
    """
    Summary: A venue without a name is labelled rather than left blank.
    AC1: Given a venue booking request is pending review, when Venue Staff open
        the request, then they can view the relevant event timing and venue
        requirements needed to assess the booking.
    Double: Stub (venue without name)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response, *_ = open_request(client, venue={**VENUE, "name": ""})

    # Assert (Then)
    assert response.json["booking"]["venueName"] == "Unknown venue"


@pytest.mark.parametrize(
    "headers,code",
    # An empty Authorization header overrides the client's default sign-in: no token.
    [({"Authorization": ""}, 401), (bearer(STAFF_ID, "Event Coordinator"), 403)],
    ids=["blank_token", "coordinator"],
)
def test_ac1_open_request_when_not_venue_staff_is_refused(client, headers, code):
    """
    Summary: Only Venue Staff can open a request.
    AC1: Given a venue booking request is pending review, when Venue Staff open
        the request, then they can view the relevant event timing and venue
        requirements needed to assess the booking.
    Double: Mock (no downstream calls)
    """
    # Arrange (Given): client, headers, code, from fixtures

    # Act (When)
    response, get_booking, get_event, get_venue = open_request(client, headers=headers)

    # Assert (Then)
    assert response.status_code == code
    get_booking.assert_not_called()
    get_event.assert_not_called()
    get_venue.assert_not_called()


def test_ac1_open_unknown_request_returns_404(client, mocker):
    """
    Summary: A booking that does not exist is reported as not found.
    AC1: Given a venue booking request is pending review, when Venue Staff open
        the request, then they can view the relevant event timing and venue
        requirements needed to assess the booking.
    Double: Stub (booking not found)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    mocker.patch("app.routes.get_booking", side_effect=BookingNotFoundError)
    response = client.get("/booking-requests/missing", headers=STAFF_HEADERS)

    # Assert (Then)
    assert response.status_code == 404


@pytest.mark.parametrize(
    "error,code", [(RuntimeError("down"), 502), (httpx.ConnectTimeout("slow"), 504)],
    ids=["failure", "timeout"],
)
def test_ac1_open_request_when_downstream_fails_returns_502_or_504(client, error, code, mocker):
    """
    Summary: A downstream failure or timeout never leaks its error text.
    AC1: Given a venue booking request is pending review, when Venue Staff open
        the request, then they can view the relevant event timing and venue
        requirements needed to assess the booking.
    Double: Stub (downstream raises)
    """
    # Arrange (Given): client, error, code, from fixtures

    # Act (When)
    mocker.patch("app.routes.get_booking", return_value=BOOKING)
    mocker.patch("app.routes.get_event_for_internal_viewer", side_effect=error)
    mocker.patch("app.routes.get_venue", return_value=VENUE)
    response = client.get("/booking-requests/booking-1", headers=STAFF_HEADERS)

    # Assert (Then)
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
    ids=["approved_pending_none", "safety_changes_requested_pending_review_none", "submitted_pending_review_opens_for_review_when_t", "pending_safety_check_pending_review_not_open_for", "under_review_approved_already_decided", "under_review_rejected_already_decided"],
)
def test_ac1_ac5_open_request_says_whether_and_why_it_can_be_decided(
    client, event_status, booking_status, reason
):
    """
    Summary: The view says whether a decision is possible, and why not.
    AC1: Given a venue booking request is pending review, when Venue Staff open
        the request, then they can view the relevant event timing and venue
        requirements needed to assess the booking.
    AC5: Given Venue Staff have recorded an approval or rejection for a pending
        venue booking request, when the decision is completed, then the request
        is no longer presented as awaiting a booking decision.
    Double: Stub (event and booking statuses)
    """
    # Arrange (Given): client, event_status, booking_status, reason, from fixtures

    # Act (When)
    response, *_ = open_request(
        client,
        booking={**BOOKING, "status": booking_status},
        event={**EVENT, "status": event_status},
    )

    # Assert (Then)
    assert response.json["canDecide"] is (reason is None)
    assert response.json["decisionBlockedReason"] == reason
    assert response.json["booking"]["awaitingReview"] is (
        booking_status in ("Pending", "Pending Review")
    )


# AC2 ------------------------------------------------------------------------


def test_ac2_approve_request_is_recorded_with_venue_buffers(client):
    """
    Summary: An approval is recorded, checked with the venue's buffers, and returned.
    AC2: Given Venue Staff determine that a pending venue booking request can
        be accepted, when they approve the request, then the booking decision
        is recorded as approved and the outcome is available to the relevant
        Event Coordinator.
    Double: Mock (decide_booking inspected)
    """
    # Arrange (Given)
    decided = {**BOOKING, "status": "Approved", "reviewedBy": STAFF_ID,
               "reviewedAt": "2030-02-02T09:00:00+08:00"}

    # Act (When)
    response, _, decide = review(client, "Approved", decided=decided)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Approved"
    assert response.json["reviewedAt"] == "2030-02-02T09:00:00+08:00"
    decide.assert_called_once_with("booking-1", "Approved", 30, 45)


def test_ac2_approve_request_with_buffered_conflict_returns_409(client):
    """
    Summary: A conflict found when approving reaches Venue Staff.
    AC2: Given Venue Staff determine that a pending venue booking request can
        be accepted, when they approve the request, then the booking decision
        is recorded as approved and the outcome is available to the relevant
        Event Coordinator.
    Double: Stub (decide_booking raises conflict)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response, *_ = review(
        client, "Approved", decided=BookingConflictError(["APPROVED_BOOKING", "TENTATIVE_HOLD"])
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "VENUE_UNAVAILABLE"
    assert response.json["conflictTypes"] == ["APPROVED_BOOKING", "TENTATIVE_HOLD"]


def test_ac2_approve_request_when_availability_fails_returns_502(client):
    """
    Summary: A failure recording the decision is a dependency failure.
    AC2: Given Venue Staff determine that a pending venue booking request can
        be accepted, when they approve the request, then the booking decision
        is recorded as approved and the outcome is available to the relevant
        Event Coordinator.
    Double: Stub (decide_booking raises)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response, *_ = review(client, "Approved", decided=RuntimeError("down"))

    # Assert (Then)
    assert response.status_code == 502


# AC3 ------------------------------------------------------------------------


def test_ac3_ac4_reject_request_with_reason_records_trimmed_reason(client):
    """
    Summary: A rejection is recorded with its trimmed reason.
    AC3: Given Venue Staff determine that a pending venue booking request
        cannot be accepted, when they reject the request, then the booking
        decision is recorded as rejected and the outcome is available to the
        relevant Event Coordinator.
    AC4: Given a venue booking request cannot be accepted, when Venue Staff
        record their decision, then they can provide relevant information or a
        reason explaining why the booking cannot be accepted.
    Double: Mock (decide_booking inspected)
    """
    # Arrange (Given)
    decided = {**BOOKING, "status": "Rejected", "rejectionReason": REASON}

    # Act (When)
    response, _, decide = review(
        client, "Rejected", decided=decided, rejectionReason=f"\n  {REASON}  "
    )

    # Assert (Then)
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
def test_ac4_reject_request_without_reason_returns_400_before_any_call(client, body):
    """
    Summary: A rejection without a reason is refused before anything is looked up.
    AC4: Given a venue booking request cannot be accepted, when Venue Staff
        record their decision, then they can provide relevant information or a
        reason explaining why the booking cannot be accepted.
    Double: Mock (no downstream calls)
    """
    # Arrange (Given): client, body, from fixtures

    # Act (When)
    response, get_booking, decide = review(client, "Rejected", **body)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["code"] == "REJECTION_REASON_REQUIRED"
    get_booking.assert_not_called()
    decide.assert_not_called()


def test_ac4_reject_request_with_500_character_reason_is_accepted(client):
    """
    Summary: A reason of up to 500 characters is forwarded.
    AC4: (boundary: reason length = 500)
    Double: Mock (decide_booking inspected)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response, _, decide = review(client, "Rejected", rejectionReason="x" * 500)

    # Assert (Then)
    assert response.status_code == 200
    assert decide.call_args.kwargs["rejection_reason"] == "x" * 500


def test_ac4_reject_request_when_availability_refuses_reason_returns_400(client):
    """
    Summary: If Venue Availability still refuses the reason, the UI gets a 400 it can show.
    AC4: Given a venue booking request cannot be accepted, when Venue Staff
        record their decision, then they can provide relevant information or a
        reason explaining why the booking cannot be accepted.
    Double: Stub (decide_booking raises reason error)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response, *_ = review(
        client, "Rejected", decided=clients.RejectionReasonRequiredError(), rejectionReason=REASON
    )

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["code"] == "REJECTION_REASON_REQUIRED"


# AC5 ------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["Approved", "Rejected", "Cancelled"], ids=["approved", "rejected", "cancelled"])
def test_ac5_decide_already_decided_request_returns_409(client, status):
    """
    Summary: A booking no longer awaiting review is never sent to be decided.
    AC5: Given Venue Staff have recorded an approval or rejection for a pending
        venue booking request, when the decision is completed, then the request
        is no longer presented as awaiting a booking decision.
    Double: Stub (booking status), Mock (no decide call)
    """
    # Arrange (Given): client, status, from fixtures

    # Act (When)
    response, _, decide = review(
        client, "Rejected", booking={**BOOKING, "status": status}, rejectionReason=REASON
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "BOOKING_ALREADY_DECIDED"
    assert response.json["message"] == "This venue request is not awaiting staff review."
    decide.assert_not_called()


def test_ac5_decide_when_other_staff_decided_first_returns_409(client):
    """
    Summary: Another staff member deciding first is reported as already decided.
    AC5: Given Venue Staff have recorded an approval or rejection for a pending
        venue booking request, when the decision is completed, then the request
        is no longer presented as awaiting a booking decision.
    Double: Stub (decide_booking raises already decided)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response, *_ = review(client, "Approved", decided=BookingAlreadyDecidedError())

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "BOOKING_ALREADY_DECIDED"


@pytest.mark.parametrize("event_status", ["Submitted", "Pending Safety Check", "Confirmed", "Cancelled"])
def test_ac5_decide_request_for_event_not_reviewable_returns_409(client, event_status):
    """
    Summary: An event outside review gets its own refusal code.
    AC5: Given Venue Staff have recorded an approval or rejection for a pending
        venue booking request, when the decision is completed, then the request
        is no longer presented as awaiting a booking decision.
    Double: Stub (event status)
    """
    # Arrange (Given): client, event_status, from fixtures

    # Act (When)
    response, _, decide = review(client, "Approved", event={**EVENT, "status": event_status})

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_REVIEWABLE"
    assert response.json["eventStatus"] == event_status
    assert response.json["message"] == "This venue request is not awaiting staff review."
    decide.assert_not_called()


def test_ac5_staff_queue_marks_decided_booking_not_awaiting(client, mocker):
    """
    Summary: A decided booking is no longer shown as awaiting.
    AC5: Given Venue Staff have recorded an approval or rejection for a pending
        venue booking request, when the decision is completed, then the request
        is no longer presented as awaiting a booking decision.
    Double: Stub (decided booking)
    """
    # Arrange (Given)
    events = mocker.patch("app.routes.get_staff_events")
    venues = mocker.patch("app.routes.get_venues")
    bookings = mocker.patch("app.routes.get_event_bookings")
    _records = mocker.patch("app.routes.get_safety_records")
    events.return_value = [EVENT]
    venues.return_value = [VENUE]
    decided = {**BOOKING, "id": "booking-2", "status": "Rejected",
               "reviewedAt": "2030-02-02T09:00:00+08:00", "rejectionReason": REASON}
    bookings.side_effect = lambda *_: [dict(BOOKING), dict(decided)]

    every = client.get("/booking-requests", headers=STAFF_HEADERS).json["events"][0]

    # Act (When)
    pending = client.get("/booking-requests?status=Pending", headers=STAFF_HEADERS).json["events"][0]

    # Assert (Then)
    assert every["awaitingReviewCount"] == 1
    rejected = next(b for b in every["bookings"] if b["id"] == "booking-2")
    assert rejected["awaitingReview"] is False
    assert rejected["rejectionReason"] == REASON
    assert rejected["reviewedAt"] == "2030-02-02T09:00:00+08:00"
    assert [b["id"] for b in pending["bookings"]] == ["booking-1"]


# AC6 ------------------------------------------------------------------------


def test_ac6_event_requests_show_coordinator_decision_and_reason(client, mocker):
    """
    Summary: The coordinator's list carries the decision and rejection reason.
    AC6: Given a booking request has been rejected and Venue Staff have
        provided relevant information or a reason, when the Event Coordinator
        views the booking decision, then they can view that information so that
        they can continue planning the event.
    Double: Stub (rejected booking)
    """
    # Arrange (Given)
    _event = mocker.patch("app.routes.get_event", return_value=EVENT)
    bookings = mocker.patch("app.routes.get_event_bookings")
    _venues = mocker.patch("app.routes.get_venues", return_value=[VENUE])
    bookings.return_value = [
        {**BOOKING, "status": "Rejected", "reviewedAt": "2030-02-02T09:00:00+08:00",
         "rejectionReason": REASON}
    ]

    response = client.get("/events/evt-1/booking-requests?coordinatorId=coord-1")

    [booking] = response.json["bookings"]

    # Act + Assert (When / Then)
    assert booking["status"] == "Rejected"
    assert booking["rejectionReason"] == REASON
    assert booking["reviewedAt"] == "2030-02-02T09:00:00+08:00"


# D7: legacy routes ----------------------------------------------------------


def test_ac4_legacy_reject_route_requires_staff_and_reason(client):
    """
    Summary: The older reject route still needs Venue Staff and a reason.
    AC4: Given a venue booking request cannot be accepted, when Venue Staff
        record their decision, then they can provide relevant information or a
        reason explaining why the booking cannot be accepted.
    Double: None
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
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


def test_ac5_legacy_approve_route_checks_event_status(client):
    """
    Summary: The older approve route still refuses an event outside review.
    AC5: Given Venue Staff have recorded an approval or rejection for a pending
        venue booking request, when the decision is completed, then the request
        is no longer presented as awaiting a booking decision.
    Double: Stub (event status)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response, _, decide = review(
        client, "Approved", path="approve", event={**EVENT, "status": "Pending Safety Check"}
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_REVIEWABLE"
    decide.assert_not_called()


# Client ---------------------------------------------------------------------


def _reply(status, body):
    return httpx.Response(status, json=body, request=httpx.Request("PATCH", "http://test"))


@pytest.mark.parametrize("status,sends_reason", [("Approved", False), ("Rejected", True)], ids=["approve", "reject"])
def test_ac4_decide_client_sends_reason_only_for_rejection(monkeypatch, status, sends_reason):
    """
    Summary: The reason is sent with a rejection and not with an approval.
    AC4: Given a venue booking request cannot be accepted, when Venue Staff
        record their decision, then they can provide relevant information or a
        reason explaining why the booking cannot be accepted.
    Double: Stub (respx; request inspected)
    """
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
    ids=["already_decided", "reason_required", "other_error"],
)
def test_ac5_decide_client_maps_typed_refusals(monkeypatch, status, code, error):
    """
    Summary: Venue Availability's typed refusals become typed errors.
    AC5: Given Venue Staff have recorded an approval or rejection for a pending
        venue booking request, when the decision is completed, then the request
        is no longer presented as awaiting a booking decision.
    Double: Stub (respx answers the refusal)
    """
    monkeypatch.setattr(clients.httpx, "patch", lambda *a, **k: _reply(status, {"code": code}))

    with pytest.raises(error):
        clients.decide_booking("booking-1", "Rejected", rejection_reason=REASON)


def test_ac5_decide_request_for_event_without_status_returns_409(client):
    """
    Summary: A malformed event answer is refused, never a crash.
    AC5: Given Venue Staff have recorded an approval or rejection for a pending
        venue booking request, when the decision is completed, then the request
        is no longer presented as awaiting a booking decision.
    Double: Stub (event without status)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response, _, decide = review(client, "Approved", event={k: v for k, v in EVENT.items() if k != "status"})

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_REVIEWABLE"
    decide.assert_not_called()
