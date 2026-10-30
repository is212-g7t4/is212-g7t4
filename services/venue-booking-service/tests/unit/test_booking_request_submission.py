"""
SCRUM-28: Venue Booking Request Submission

User Story
----------
As an Event Coordinator, I want to submit a venue booking request for an event,
so that Venue Staff can assess whether the requested venue arrangement can be
accepted.

Acceptance Criteria
-------------------
AC1: Given an Event Coordinator is preparing a venue booking request for an
     event, when they enter the booking information, then they can provide the
     relevant event timing and venue requirements needed for Venue Staff to
     assess the booking.
AC2: Given the relevant event timing and venue requirements have been provided,
     when the Event Coordinator submits the venue booking request, then the
     request is recorded and made available to Venue Staff for review.
AC3: Given a venue booking request has been submitted, when Venue Staff access
     the request, then they can view the event to which the request relates
     together with the relevant event timing and venue requirements.
AC4: Given a venue booking request has been submitted and has not yet received
     a booking decision, when Venue Staff view requests requiring action, then
     the request can be identified as awaiting Venue Staff review.
AC5: Given an Event Coordinator submits a venue booking request for an event,
     when the request is recorded, then it remains associated with that event
     so that the booking can be assessed in the context of the corresponding
     event requirements.
AC6: Given an Event Coordinator submits a venue booking request for a venue and
     time slot, when the same venue has already been requested or booked for
     another event, and the requested event timing does not overlap with that
     other event's timing, then the request is accepted for Venue Staff review
     as normal, so the same venue can be booked for multiple events across
     non-overlapping time slots.

Real
----
- POST /booking-requests and the staff queue: forwarding the booking's own
  timing, capacity and requirements, the event-status gate, the time rules (not
  in the past, within the event's dates by day), and the queue order and
  awaiting filter.
- Assertions are on the status, what is sent and the queue returned.

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

from unittest.mock import patch

import pytest

from app import create_app
from app.clients import BookingConflictError
from app.routes import REVIEWABLE_EVENT_STATUSES, SUBMITTABLE_EVENT_STATUSES
from tests.unit.factories import signed_in, bearer

STAFF_ID = "d9e4002b-db91-4939-b87e-50f9cceb5e0a"
STAFF_HEADERS = bearer(STAFF_ID, "Venue Staff")
VENUES = [{"id": "ven-1", "name": "Grand Ballroom", "capacity": 200, "status": "Available"}]
EVENT = {
    "id": "evt-1",
    "eventName": "Spring Fair",
    "status": "Under Review",
    "coordinatorId": "coord-1",
    "preferredStartDate": "2030-03-01T09:00:00",
    "preferredEndDate": "2030-03-01T17:00:00",
}
REQUEST = {
    "eventId": "evt-1",
    "venueId": "ven-1",
    "coordinatorId": "coord-1",
    "requestedStartTime": "2030-03-01T13:00",
    "requestedEndTime": "2030-03-01T15:00",
    "requiredCapacity": 120,
    "venueRequirements": "  Stage and two microphones  ",
}
BOOKING = {
    "id": "booking-1",
    "eventId": "evt-1",
    "venueId": "ven-1",
    "requestedStartTime": "2030-03-01T13:00:00",
    "requestedEndTime": "2030-03-01T15:00:00",
    "requiredCapacity": 120,
    "venueRequirements": "Stage and two microphones",
    "status": "Pending Review",
    "requestedBy": "coord-1",
    "reviewedBy": None,
    "requestedAt": "2030-02-01T10:00:00+08:00",
}
NOT_SUBMITTABLE = ["Clarification Requested", "Rejected", "Pending Safety Check", "Confirmed", "Cancelled"]


def submit(event, create_result=BOOKING):
    with (
        patch("app.routes.get_event", return_value=event) as get_event,
        patch("app.routes.get_venues", return_value=VENUES) as get_venues,
        patch("app.routes.create_booking") as create_booking,
    ):
        if isinstance(create_result, Exception):
            create_booking.side_effect = create_result
        else:
            create_booking.return_value = create_result
        response = signed_in(create_app().test_client()).post("/booking-requests", json=REQUEST)
    return response, get_event, get_venues, create_booking


def staff_queue(events, bookings_by_event, query=""):
    with (
        patch("app.routes.get_staff_events", return_value=events),
        patch("app.routes.get_venues", return_value=VENUES),
        patch("app.routes.get_event_bookings", side_effect=lambda event_id: bookings_by_event[event_id]),
        patch("app.routes.get_safety_records", return_value=[]),
    ):
        return signed_in(create_app().test_client()).get(f"/booking-requests{query}", headers=STAFF_HEADERS)


# AC1 ----


def test_create_request_forwards_booking_timing_capacity_and_requirements():
    """
    Summary: A request carries its own timing, capacity and requirements to Venue Availability.
    AC1: Given an Event Coordinator is preparing a venue booking request for an
        event, when they enter the booking information, then they can provide
        the relevant event timing and venue requirements needed for Venue Staff
        to assess the booking.
    Double: Stub (event, venues), Mock (create_booking inspected)
    """
    # Act (When)
    response, get_event, _, create_booking = submit(EVENT)

    # Assert (Then)
    assert response.status_code == 201
    get_event.assert_called_once_with("evt-1")
    create_booking.assert_called_once_with(
        "evt-1", "ven-1", "2030-03-01T13:00", "2030-03-01T15:00",
        120, "Stage and two microphones",
    )


# AC2 ----


@pytest.mark.parametrize("status", SUBMITTABLE_EVENT_STATUSES)
def test_create_request_for_submittable_event_is_pending_review(status):
    """
    Summary: A request for an event in a submittable status is recorded for Venue Staff review.
    AC2: Given the relevant event timing and venue requirements have been
        provided, when the Event Coordinator submits the venue booking request,
        then the request is recorded and made available to Venue Staff for
        review.
    Double: Stub (event in the status), Mock (create_booking)
    """
    # Arrange (Given): status, from fixtures

    # Act (When)
    response, _, _, create_booking = submit({**EVENT, "status": status})

    # Assert (Then)
    assert response.status_code == 201
    assert response.json["status"] == "Pending Review"
    assert response.json["requestedAt"] == "2030-02-01T10:00:00+08:00"
    create_booking.assert_called_once()


def test_submittable_statuses_are_exactly_the_agreed_four():
    """
    Summary: Requests are accepted for exactly the four statuses agreed for SCRUM-28.
    AC2: Given the relevant event timing and venue requirements have been
        provided, when the Event Coordinator submits the venue booking request,
        then the request is recorded and made available to Venue Staff for
        review.
    Double: None
    """
    # Act + Assert (When / Then)
    assert SUBMITTABLE_EVENT_STATUSES == (
        "Submitted", "Under Review", "Approved", "Safety Changes Requested",
    )


@pytest.mark.parametrize("status", NOT_SUBMITTABLE)
def test_create_request_for_event_not_submittable_returns_409(status):
    """
    Summary: A request Venue Staff could never review is not recorded.
    AC2: Given the relevant event timing and venue requirements have been
        provided, when the Event Coordinator submits the venue booking request,
        then the request is recorded and made available to Venue Staff for
        review.
    Double: Stub (event in the status), Mock (no create)
    """
    # Arrange (Given): status, from fixtures

    # Act (When)
    response, _, get_venues, create_booking = submit({**EVENT, "status": status})

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_ACCEPTING_VENUE_REQUESTS"
    assert response.json["eventStatus"] == status
    get_venues.assert_not_called()
    create_booking.assert_not_called()


def test_create_request_for_event_without_status_returns_409():
    """
    Summary: An event with an unknown status fails closed.
    AC2: Given the relevant event timing and venue requirements have been
        provided, when the Event Coordinator submits the venue booking request,
        then the request is recorded and made available to Venue Staff for
        review.
    Double: Stub (event without status)
    """
    # Arrange (Given)
    event = {key: value for key, value in EVENT.items() if key != "status"}

    # Act (When)
    response, _, get_venues, create_booking = submit(event)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_ACCEPTING_VENUE_REQUESTS"
    assert response.json["eventStatus"] is None
    get_venues.assert_not_called()
    create_booking.assert_not_called()


# AC3 ----


def test_staff_queue_shows_event_dates_with_each_request():
    """
    Summary: Venue Staff see the event's dates next to each request.
    AC3: Given a venue booking request has been submitted, when Venue Staff
        access the request, then they can view the event to which the request
        relates together with the relevant event timing and venue requirements.
    Double: Stub (bookings and events)
    """
    # Act (When)
    response = staff_queue([EVENT], {"evt-1": [dict(BOOKING)]})

    # Assert (Then)
    assert response.status_code == 200
    [event] = response.json["events"]
    assert event["eventName"] == "Spring Fair"
    assert event["eventStart"] == "2030-03-01T09:00:00"
    assert event["eventEnd"] == "2030-03-01T17:00:00"
    [booking] = event["bookings"]
    assert booking["venueName"] == "Grand Ballroom"
    assert booking["requestedStartTime"] == "2030-03-01T13:00:00"
    assert booking["requestedEndTime"] == "2030-03-01T15:00:00"
    assert booking["requiredCapacity"] == 120
    assert booking["venueRequirements"] == "Stage and two microphones"
    assert booking["requestedAt"] == "2030-02-01T10:00:00+08:00"


@pytest.mark.parametrize("missing", ["", None], ids=["event-service-blank", "absent"])
def test_staff_queue_with_event_without_dates_still_lists_requests(missing):
    """
    Summary: An event with no dates still has its requests listed.
    AC3: Given a venue booking request has been submitted, when Venue Staff
        access the request, then they can view the event to which the request
        relates together with the relevant event timing and venue requirements.
    Double: Stub (event without dates)
    """
    # Arrange (Given)
    if missing is None:
        event = {key: value for key, value in EVENT.items() if not key.startswith("preferred")}
    else:
        # Event Service's serialize() sends "" for an unset date.
        event = {**EVENT, "preferredStartDate": "", "preferredEndDate": ""}
    legacy = {key: value for key, value in BOOKING.items() if key != "requestedAt"}

    # Act (When)
    response = staff_queue([event], {"evt-1": [legacy]})

    # Assert (Then)
    assert response.status_code == 200
    [listed] = response.json["events"]
    assert listed["eventStart"] is None
    assert listed["eventEnd"] is None
    assert listed["bookings"][0]["requestedAt"] is None


# AC4 ----


def test_staff_queue_counts_pending_and_pending_review_as_awaiting():
    """
    Summary: Both spellings of pending count as awaiting review.
    AC4: Given a venue booking request has been submitted and has not yet
        received a booking decision, when Venue Staff view requests requiring
        action, then the request can be identified as awaiting Venue Staff
        review.
    Double: Stub (bookings in each status)
    """
    # Arrange (Given)
    bookings = [
        {**BOOKING, "id": "new", "status": "Pending Review"},
        {**BOOKING, "id": "legacy", "status": "Pending"},
        {**BOOKING, "id": "approved", "status": "Approved"},
        {**BOOKING, "id": "rejected", "status": "Rejected"},
        {**BOOKING, "id": "cancelled", "status": "Cancelled"},
    ]

    response = staff_queue([EVENT], {"evt-1": bookings})

    [event] = response.json["events"]
    flags = {booking["id"]: booking["awaitingReview"] for booking in event["bookings"]}

    # Act + Assert (When / Then)
    assert flags == {
        "new": True, "legacy": True, "approved": False, "rejected": False, "cancelled": False,
    }
    assert event["awaitingReviewCount"] == 2


def test_staff_queue_pending_filter_returns_only_awaiting():
    """
    Summary: The Pending filter returns and counts only requests awaiting review.
    AC4: Given a venue booking request has been submitted and has not yet
        received a booking decision, when Venue Staff view requests requiring
        action, then the request can be identified as awaiting Venue Staff
        review.
    Double: Stub (bookings in each status)
    """
    # Arrange (Given)
    bookings = [
        {**BOOKING, "id": "new", "status": "Pending Review"},
        {**BOOKING, "id": "legacy", "status": "Pending"},
        {**BOOKING, "id": "approved", "status": "Approved"},
    ]

    response = staff_queue([EVENT], {"evt-1": bookings}, "?status=Pending")

    [event] = response.json["events"]

    # Act + Assert (When / Then)
    assert sorted(booking["id"] for booking in event["bookings"]) == ["legacy", "new"]
    assert event["awaitingReviewCount"] == 2


def test_staff_queue_lists_awaiting_first_oldest_first():
    """
    Summary: Awaiting requests come first, oldest first.
    AC4: Given a venue booking request has been submitted and has not yet
        received a booking decision, when Venue Staff view requests requiring
        action, then the request can be identified as awaiting Venue Staff
        review.
    Double: Stub (bookings with submission times)
    """
    # Arrange (Given)
    bookings = [
        {**BOOKING, "id": "approved", "status": "Approved", "requestedAt": "2030-01-01T09:00:00+08:00"},
        {**BOOKING, "id": "legacy-late", "status": "Pending", "requestedAt": None,
         "requestedStartTime": "2030-03-02T09:00:00"},
        {**BOOKING, "id": "newer", "requestedAt": "2030-02-03T09:00:00+08:00"},
        {**BOOKING, "id": "legacy-early", "status": "Pending", "requestedAt": None,
         "requestedStartTime": "2030-03-01T09:00:00"},
        {**BOOKING, "id": "older", "requestedAt": "2030-02-01T09:00:00+08:00"},
    ]

    response = staff_queue([EVENT], {"evt-1": bookings})

    order = [booking["id"] for booking in response.json["events"][0]["bookings"]]

    # Act + Assert (When / Then)
    assert order == ["older", "newer", "legacy-early", "legacy-late", "approved"]


# AC5 ----


def test_event_requests_list_only_that_events_requests():
    """
    Summary: Each request appears only under the event it was submitted for.
    AC5: Given an Event Coordinator submits a venue booking request for an
        event, when the request is recorded, then it remains associated with
        that event so that the booking can be assessed in the context of the
        corresponding event requirements.
    Double: Stub (bookings of two events)
    """
    # Arrange (Given)
    other = {**EVENT, "id": "evt-2", "eventName": "Autumn Gala"}
    response = staff_queue(
        [EVENT, other],
        {
            "evt-1": [{**BOOKING, "id": "for-spring"}],
            "evt-2": [{**BOOKING, "id": "for-autumn", "eventId": "evt-2"}],
        },
    )

    grouped = {
        event["eventId"]: [booking["id"] for booking in event["bookings"]]
        for event in response.json["events"]
    }

    # Act + Assert (When / Then)
    assert grouped == {"evt-1": ["for-spring"], "evt-2": ["for-autumn"]}


# AC6 ----


def test_create_request_for_venue_booked_at_other_time_is_accepted():
    """
    Summary: A venue booked by another event at a different time can still be requested.
    AC6: Given an Event Coordinator submits a venue booking request for a venue
        and time slot, when the same venue has already been requested or booked
        for another event, and the requested event timing does not overlap with
        that other event's timing, then the request is accepted for Venue Staff
        review as normal, so the same venue can be booked for multiple events
        across non-overlapping time slots.
    Double: Stub (Venue Availability accepts)
    """
    # Act (When)
    response, _, _, create_booking = submit(EVENT)

    # Assert (Then)
    assert response.status_code == 201
    assert response.json == BOOKING
    create_booking.assert_called_once()


def test_create_request_overlapping_other_booking_returns_409():
    """
    Summary: An overlap found by Venue Availability is reported as a conflict.
    AC6: Given an Event Coordinator submits a venue booking request for a venue
        and time slot, when the same venue has already been requested or booked
        for another event, and the requested event timing does not overlap with
        that other event's timing, then the request is accepted for Venue Staff
        review as normal, so the same venue can be booked for multiple events
        across non-overlapping time slots.
    Double: Stub (Venue Availability reports a conflict)
    """
    # Act (When)
    response, _, _, _ = submit(EVENT, BookingConflictError(["APPROVED_BOOKING"]))

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "VENUE_UNAVAILABLE"
    assert response.json["conflictTypes"] == ["APPROVED_BOOKING"]


# Regression: the staff review route now reads the same named statuses ----


@pytest.mark.parametrize(
    "event_status, expected",
    [(status, 200) for status in REVIEWABLE_EVENT_STATUSES]
    + [("Submitted", 409), ("Pending Safety Check", 409), ("Confirmed", 409)],
)
def test_staff_review_allows_only_reviewable_event_statuses(event_status, expected):
    """
    Summary: Venue Staff can decide only for events in a reviewable status.
    AC4: Given a venue booking request has been submitted and has not yet
        received a booking decision, when Venue Staff view requests requiring
        action, then the request can be identified as awaiting Venue Staff
        review.
    Double: Stub (event in each status)
    """
    # Arrange (Given): event_status, expected, from fixtures

    # Act (When)
    with (
        patch("app.routes.get_booking", return_value=BOOKING),
        patch("app.routes.get_event_for_internal_viewer", return_value={"status": event_status}),
        patch("app.routes.get_venue", return_value=VENUES[0]),
        patch("app.routes.decide_booking", return_value={**BOOKING, "status": "Approved"}),
    ):
        response = signed_in(create_app().test_client()).patch(
            "/booking-requests/booking-1/review",
            headers=STAFF_HEADERS,
            json={"reviewedBy": STAFF_ID, "status": "Approved"},
        )

    # Assert (Then)
    assert response.status_code == expected
    assert REVIEWABLE_EVENT_STATUSES == ("Under Review", "Approved", "Safety Changes Requested")


# Booking window: a request must be in the future and on the event's dates ----


def submit_window(event, **times):
    with (
        patch("app.routes.get_event", return_value=event),
        patch("app.routes.get_venues", return_value=VENUES) as get_venues,
        patch("app.routes.create_booking", return_value=BOOKING) as create_booking,
    ):
        response = signed_in(create_app().test_client()).post(
            "/booking-requests", json=REQUEST | times
        )
    return response, get_venues, create_booking


def update_window(event, **times):
    with (
        patch("app.routes.get_event", return_value=event),
        patch("app.routes.get_venues", return_value=VENUES) as get_venues,
        patch("app.routes.update_booking", return_value=BOOKING) as update_booking,
    ):
        response = signed_in(create_app().test_client()).patch(
            "/booking-requests/booking-1", json=REQUEST | times
        )
    return response, get_venues, update_booking


@pytest.mark.parametrize("send", [submit_window, update_window])
def test_request_starting_in_past_returns_400(send):
    """
    Summary: A slot that has already started cannot be requested or moved to.
    AC1: Given an Event Coordinator is preparing a venue booking request for an
        event, when they enter the booking information, then they can provide
        the relevant event timing and venue requirements needed for Venue Staff
        to assess the booking.
    Double: Stub (event), Mock (no create)
    """
    # Arrange (Given): send, from fixtures

    # Act (When)
    response, get_venues, save = send(
        {**EVENT, "preferredStartDate": "2020-03-01T09:00:00", "preferredEndDate": "2020-03-01T17:00:00"},
        requestedStartTime="2020-03-01T13:00",
        requestedEndTime="2020-03-01T15:00",
    )

    # Assert (Then)
    assert response.status_code == 422
    assert response.json["code"] == "BOOKING_IN_PAST"
    get_venues.assert_not_called()
    save.assert_not_called()


@pytest.mark.parametrize("send", [submit_window, update_window])
@pytest.mark.parametrize(
    "start, end",
    [
        ("2030-02-28T13:00", "2030-02-28T15:00"),  # the day before the event
        ("2030-03-02T09:00", "2030-03-02T11:00"),  # the day after the event
        ("2030-02-28T23:00", "2030-03-01T10:00"),  # starts the day before
        ("2030-03-01T16:00", "2030-03-02T01:00"),  # runs past the last day
    ],
    ids=["2030_02_28t13_00_2030_02_28t15_00", "2030_03_02t09_00_2030_03_02t11_00", "2030_02_28t23_00_2030_03_01t10_00", "2030_03_01t16_00_2030_03_02t01_00"],
)
def test_request_outside_event_dates_returns_400(send, start, end):
    """
    Summary: Any part of a booking outside the event's dates is refused.
    AC1: Given an Event Coordinator is preparing a venue booking request for an
        event, when they enter the booking information, then they can provide
        the relevant event timing and venue requirements needed for Venue Staff
        to assess the booking.
    Double: Stub (event with dates)
    """
    # Arrange (Given): send, start, end, from fixtures

    # Act (When)
    response, get_venues, save = send(EVENT, requestedStartTime=start, requestedEndTime=end)

    # Assert (Then)
    assert response.status_code == 422
    assert response.json["code"] == "BOOKING_OUTSIDE_EVENT_DATES"
    assert "2030-03-01 to 2030-03-01" in response.json["message"]
    get_venues.assert_not_called()
    save.assert_not_called()


@pytest.mark.parametrize(
    "start, end",
    [
        ("2030-03-01T07:00", "2030-03-01T09:00"),  # setup before the event starts, same day
        ("2030-03-01T00:00", "2030-03-01T23:59"),  # the whole of the event's day
    ],
    ids=["2030_03_01t07_00_2030_03_01t09_00", "2030_03_01t00_00_2030_03_01t23_59"],
)
def test_request_on_event_day_outside_event_hours_is_accepted(start, end):
    """
    Summary: Setup or teardown on the event's day outside its hours is allowed.
    AC1: Given an Event Coordinator is preparing a venue booking request for an
        event, when they enter the booking information, then they can provide
        the relevant event timing and venue requirements needed for Venue Staff
        to assess the booking.
    Double: Stub (event with dates), Mock (create_booking)
    """
    # Arrange (Given): start, end, from fixtures

    # Act (When)
    response, _, create_booking = submit_window(EVENT, requestedStartTime=start, requestedEndTime=end)

    # Assert (Then)
    assert response.status_code == 201
    create_booking.assert_called_once()


def test_request_on_later_day_of_multi_day_event_is_accepted():
    """
    Summary: A later day of a multi-day event counts as within its dates.
    AC1: Given an Event Coordinator is preparing a venue booking request for an
        event, when they enter the booking information, then they can provide
        the relevant event timing and venue requirements needed for Venue Staff
        to assess the booking.
    Double: Stub (multi-day event), Mock (create_booking)
    """
    # Act (When)
    response, _, create_booking = submit_window(
        {**EVENT, "preferredEndDate": "2030-03-03T17:00:00"},
        requestedStartTime="2030-03-03T10:00",
        requestedEndTime="2030-03-03T12:00",
    )

    # Assert (Then)
    assert response.status_code == 201
    create_booking.assert_called_once()


@pytest.mark.parametrize("dates", [{"preferredStartDate": "", "preferredEndDate": ""}, {}], ids=["only_start_date", "no_dates"])
def test_request_for_event_without_dates_only_checks_future(dates):
    """
    Summary: With no event dates, only "not in the past" is checked.
    AC1: Given an Event Coordinator is preparing a venue booking request for an
        event, when they enter the booking information, then they can provide
        the relevant event timing and venue requirements needed for Venue Staff
        to assess the booking.
    Double: Stub (event without dates), Mock (create_booking)
    """
    # Arrange (Given)
    event = {key: value for key, value in EVENT.items() if not key.startswith("preferred")}

    # Act (When)
    response, _, create_booking = submit_window(event | dates)

    # Assert (Then)
    assert response.status_code == 201
    create_booking.assert_called_once()


def test_booking_window_check_starting_now_is_in_past():
    """
    Summary: A request starting exactly now is already in the past.
    AC1: (boundary: start = now)
    Double: None
    """
    # Arrange (Given)
    from datetime import datetime

    from app.routes import _booking_window_invalid

    now = datetime(2030, 3, 1, 13, 0)

    # Act (When)
    with create_app().app_context():
        refused = _booking_window_invalid(EVENT, now, datetime(2030, 3, 1, 15, 0), now=now)
        accepted = _booking_window_invalid(
            EVENT, datetime(2030, 3, 1, 13, 1), datetime(2030, 3, 1, 15, 0), now=now
        )

    # Assert (Then)
    assert refused[1] == 422
    assert accepted is None
