"""SCRUM-156: Book Multiple Venues for an Event

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

SCRUM-157: Manage Individual Venue Arrangements

User Story
----------
As an Event Coordinator, I want to modify or cancel a specific venue booking
for an event, so that I can adjust one venue arrangement without affecting the
event's other venue arrangements.

Acceptance Criteria
-------------------
AC1: Given an event has one or more venue bookings, when the Event Coordinator
     modifies a specific booking, then only that selected booking is updated.
AC2: If a modification changes the venue, date/time, required capacity, or
     other suitability requirements, then suitability, availability, and
     conflict checks are performed again for that booking only.
AC3: Given an event has multiple venue bookings, when the Event Coordinator
     cancels one booking, then only the selected booking is cancelled and the
     other bookings remain unchanged.
AC4: Cancelling or modifying one venue booking does not automatically change
     the status of the event's other venue bookings.
AC5: A cancelled booking remains associated with the event with a Cancelled
     status for record keeping.

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

SCRUM-164: Revise Arrangements and Resubmit for Safety Check

Agreed revision from this conversation; pending confirmation that Jira has been updated

User Story
----------
As an Event Coordinator, I want to see the Safety Officer's feedback and revise
the affected arrangements, so that I can resubmit the event for a safety check
without redoing unaffected planning.

Acceptance Criteria
-------------------
AC1: Given my event is 'Safety Changes Requested', when I open it, then I see
     the decision, reason, requested changes and affected areas.
AC2: Given the venue arrangement is flagged, then the affected venue booking
     must be reviewed again by Venue Staff (revised booking or replacement
     request) before the event can be resubmitted.
AC3: Given the technical arrangement is flagged, then the affected equipment requests that were previously 'Approved' return to 'Pending' and must be approved again by Technical Support Staff before the event can be resubmitted. The safety-change action does not reopen existing 'Rejected' requests or clear their rejection reasons, and requests already 'Pending' remain 'Pending'.
AC4: Given an arrangement was not flagged, then it stays confirmed and does not
     need to be reviewed again.
AC5: Given all flagged arrangements are confirmed again, when I resubmit, then
     the status returns to 'Pending Safety Check' as a new review round, and
     earlier rounds remain in the history.

Real
----
- The composite booking routes: the Venue Staff queue (with targeted safety
  feedback), create (catalogue, status, capacity of the booking itself,
  assignment, double-booking), list, approve/reject, edit (re-validated and
  resubmitted, only that booking) and cancel.
- Assertions are on the status, the bookings returned and the calls made.

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

import pytest
import httpx

from app import create_app
from app.clients import (
    BookingConflictError,
    BookingNotFoundError,
    BookingStateError,
    EventNotAssignedError,
    EventNotFoundError,
)
from tests.unit.factories import signed_in, bearer

EVENT = {
    "id": "evt-1",
    "status": "Under Review",
    "expectedAttendance": "150",
    "preferredStartDate": "2030-10-01T09:00",
    "preferredEndDate": "2030-10-01T12:00",
}
# Statuses match the ones Venue Service actually stores: Available,
# Under Maintenance or Booked. Only Available is bookable.
VENUES = [
    {"id": "ven-1", "name": "Innovation Lab", "capacity": 60, "status": "Available"},
    {"id": "ven-2", "name": "Grand Ballroom", "capacity": 500, "status": "Available"},
    {
        "id": "ven-3",
        "name": "Rooftop Terrace",
        "capacity": 150,
        "status": "Under Maintenance",
    },
    {"id": "ven-4", "name": "Conference Room A", "capacity": 400, "status": "Booked"},
]
BOOKING = {
    "id": "booking-1",
    "eventId": "evt-1",
    "venueId": "ven-2",
    "requestedStartTime": "2030-10-01T09:00:00",
    "requestedEndTime": "2030-10-01T12:00:00",
    "requiredCapacity": 80,
    "venueRequirements": "Projector",
    "status": "Pending Review",
    "requestedBy": "coord-1",
    "reviewedBy": None,
}

REQUEST = {
    "eventId": "evt-1",
    "venueId": "ven-2",
    "coordinatorId": "coord-1",
    "requestedStartTime": "2030-10-01T09:00",
    "requestedEndTime": "2030-10-01T12:00",
    "requiredCapacity": 80,
    "venueRequirements": "Projector",
}


STAFF_ID = "d9e4002b-db91-4939-b87e-50f9cceb5e0a"
STAFF_HEADERS = bearer(STAFF_ID, "Venue Staff")


def test_staff_queue_shows_safety_feedback_on_flagged_bookings(mocker):
    """
    Summary: Venue Staff see the Safety Officer's feedback on bookings flagged for change.
    SCRUM-164 AC2: Given the venue arrangement is flagged, then the affected
        venue booking must be reviewed again by Venue Staff (revised booking or
        replacement request) before the event can be resubmitted.
    Double: Stub (bookings, events, safety rounds)
    """
    # Arrange (Given)
    events = mocker.patch("app.routes.get_staff_events")
    venues = mocker.patch("app.routes.get_venues")
    bookings = mocker.patch("app.routes.get_event_bookings")
    records = mocker.patch("app.routes.get_safety_records")
    events.return_value = [{**EVENT, "eventName": "Workshop", "status": "Safety Changes Requested"}]
    venues.return_value = VENUES
    bookings.return_value = [dict(BOOKING), {**BOOKING, "id": "other", "status": "Approved"}]
    records.return_value = [{"roundNumber": 1, "status": "Changes Requested", "remarks": "Exit blocked.", "flags": [
        {"area": "venue arrangement", "bookingId": "booking-1", "changeRequired": "Move stage."}]}]

    # Act (When)
    response = signed_in(create_app().test_client()).get("/booking-requests", headers=STAFF_HEADERS)

    # Assert (Then)
    assert response.status_code == 200
    rows = response.json["events"][0]["bookings"]
    assert rows[0]["safetyFeedback"] == {"reason": "Exit blocked.", "requestedChanges": ["Move stage."]}
    assert rows[1]["safetyFeedback"] is None
    assert rows[0]["venueName"] == "Grand Ballroom"


@pytest.mark.parametrize("headers,code", [({"Authorization": ""}, 401), (bearer(STAFF_ID, "Event Coordinator"), 403)], ids=["blank_token", "coordinator"])
def test_staff_queue_when_not_venue_staff_is_refused(headers, code):
    """
    Summary: Only Venue Staff can open the queue.
    SCRUM-28 AC4: Given a venue booking request has been submitted and has not
        yet received a booking decision, when Venue Staff view requests
        requiring action, then the request can be identified as awaiting Venue
        Staff review.
    Double: None
    """
    # Arrange (Given)
    client = signed_in(create_app().test_client())

    # Act + Assert (When / Then)
    assert client.get("/booking-requests", headers=headers).status_code == code
    assert client.patch("/booking-requests/b/review", headers=headers, json={}).status_code == code


@pytest.mark.parametrize("status", ["Approved", "Rejected"], ids=["approve", "reject"])
def test_staff_can_decide_booking_reopened_by_safety_check(status, mocker):
    """
    Summary: A booking sent back by the safety check can be decided again.
    SCRUM-164 AC2: Given the venue arrangement is flagged, then the affected
        venue booking must be reviewed again by Venue Staff (revised booking or
        replacement request) before the event can be resubmitted.
    Double: Stub (event in Safety Changes Requested)
    """
    # Arrange (Given)
    decide = mocker.patch("app.routes.decide_booking")
    booking = mocker.patch("app.routes.get_booking")
    event = mocker.patch("app.routes.get_event_for_internal_viewer")
    booking.return_value = BOOKING
    event.return_value = {"status": "Safety Changes Requested"}
    decide.return_value = {**BOOKING, "status": status}

    # Act (When)
    mocker.patch("app.routes.get_venue", return_value=VENUES[1])
    response = signed_in(create_app().test_client()).patch("/booking-requests/booking-1/review", headers=STAFF_HEADERS,
        json={"reviewedBy": STAFF_ID, "status": status, "rejectionReason": "Venue unsuitable"})

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == status


@pytest.mark.parametrize("status,count", [("Pending", 1), ("Approved", 1), ("Rejected", 0)], ids=["pending", "approved", "rejected"])
def test_staff_queue_filters_and_reads_safety_only_in_revision(status, count, mocker):
    """
    Summary: The queue filters by status and reads safety feedback only for events in revision.
    SCRUM-28 AC4: Given a venue booking request has been submitted and has not
        yet received a booking decision, when Venue Staff view requests
        requiring action, then the request can be identified as awaiting Venue
        Staff review.
    Double: Stub (bookings), Mock (safety read)
    """
    # Arrange (Given)
    events = mocker.patch("app.routes.get_staff_events")
    venues = mocker.patch("app.routes.get_venues")
    bookings = mocker.patch("app.routes.get_event_bookings")
    records = mocker.patch("app.routes.get_safety_records")
    events.return_value = [{**EVENT, "eventName": "Workshop", "status": "Under Review"}]
    venues.return_value = VENUES
    bookings.return_value = [dict(BOOKING), {**BOOKING, "id": "approved", "status": "Approved"}]

    # Act (When)
    response = signed_in(create_app().test_client()).get(f"/booking-requests?status={status}", headers=STAFF_HEADERS)

    # Assert (Then)
    assert response.status_code == 200
    assert len(response.json["events"]) == count
    if count:
        assert len(response.json["events"][0]["bookings"]) == 1
    records.assert_not_called()


def test_staff_queue_with_unknown_status_returns_400():
    """
    Summary: An unknown status filter is refused.
    SCRUM-28 AC4: Given a venue booking request has been submitted and has not
        yet received a booking decision, when Venue Staff view requests
        requiring action, then the request can be identified as awaiting Venue
        Staff review.
    Double: None
    """
    # Act + Assert (When / Then)
    assert signed_in(create_app().test_client()).get("/booking-requests?status=bad", headers=STAFF_HEADERS).status_code == 400


@pytest.mark.parametrize("error,code", [(httpx.ReadTimeout("timeout"), 504), (RuntimeError(), 502)], ids=["timeout", "failure"])
def test_staff_queue_when_downstream_fails_returns_error(error, code, mocker):
    """
    Summary: A downstream failure is reported rather than shown as an empty queue.
    SCRUM-28 AC4: Given a venue booking request has been submitted and has not
        yet received a booking decision, when Venue Staff view requests
        requiring action, then the request can be identified as awaiting Venue
        Staff review.
    Double: Stub (downstream raises)
    """
    # Arrange (Given)
    events = mocker.patch("app.routes.get_staff_events")
    events.side_effect = error

    # Act + Assert (When / Then)
    assert signed_in(create_app().test_client()).get("/booking-requests", headers=STAFF_HEADERS).status_code == code


@pytest.mark.parametrize("data", [None, {}, {"status": "Pending"}], ids=["no_body", "empty_object", "pending"])
def test_staff_review_with_bad_decision_returns_400(data):
    """
    Summary: A review must be Approved or Rejected.
    SCRUM-29 AC2: Given Venue Staff determine that a pending venue booking
        request can be accepted, when they approve the request, then the
        booking decision is recorded as approved and the outcome is available
        to the relevant Event Coordinator.
    Double: None
    """
    # Arrange (Given): data, from fixtures

    # Act + Assert (When / Then)
    assert signed_in(create_app().test_client()).patch("/booking-requests/b/review", headers=STAFF_HEADERS, json=data).status_code == 400


@pytest.mark.parametrize("event_status,booking_status", [("Confirmed", "Pending Review"), ("Under Review", "Approved")], ids=["confirmed_event", "decided_booking"])
def test_staff_review_of_closed_event_or_decided_booking_returns_409(event_status, booking_status, mocker):
    """
    Summary: A booking of a closed event, or already decided, cannot be reviewed.
    SCRUM-29 AC5: Given Venue Staff have recorded an approval or rejection for
        a pending venue booking request, when the decision is completed, then
        the request is no longer presented as awaiting a booking decision.
    Double: Stub (event and booking statuses)
    """
    # Arrange (Given)
    booking = mocker.patch("app.routes.get_booking")
    event = mocker.patch("app.routes.get_event_for_internal_viewer")
    booking.return_value = {**BOOKING, "status": booking_status}
    event.return_value = {"status": event_status}

    # Act + Assert (When / Then)
    assert signed_in(create_app().test_client()).patch("/booking-requests/b/review", headers=STAFF_HEADERS,
        json={"status": "Approved", "reviewedBy": STAFF_ID}).status_code == 409


@pytest.mark.parametrize("error,code", [(BookingNotFoundError(), 404), (RuntimeError(), 502)], ids=["not_found", "failure"])
def test_staff_review_when_lookup_fails_returns_error(error, code, mocker):
    """
    Summary: A failed lookup is reported, not treated as a decision.
    SCRUM-29 AC2: Given Venue Staff determine that a pending venue booking
        request can be accepted, when they approve the request, then the
        booking decision is recorded as approved and the outcome is available
        to the relevant Event Coordinator.
    Double: Stub (lookup raises)
    """
    # Arrange (Given)
    booking = mocker.patch("app.routes.get_booking")
    booking.side_effect = error

    # Act + Assert (When / Then)
    assert signed_in(create_app().test_client()).patch("/booking-requests/b/review", headers=STAFF_HEADERS,
        json={"status": "Approved", "reviewedBy": STAFF_ID}).status_code == code


def test_staff_queue_clients_read_events_and_safety_rounds_from_owners(mocker):
    """
    Summary: Queue details come from Event and Safety Check Record Services.
    SCRUM-28 AC3: Given a venue booking request has been submitted, when Venue
        Staff access the request, then they can view the event to which the
        request relates together with the relevant event timing and venue
        requirements.
    Double: Stub (respx; requests inspected)
    """
    # Arrange (Given)
    get = mocker.patch("app.clients.httpx.get")
    from app import clients
    response = MagicMock()
    response.json.return_value = {"events": [EVENT], "safetyChecks": [{"roundNumber": 1}]}
    get.return_value = response

    # Act + Assert (When / Then)
    assert clients.get_staff_events() == [EVENT]
    assert get.call_args.kwargs["params"] == {"viewerRole": "Venue Staff"}
    assert clients.get_safety_records("evt-1") == [{"roundNumber": 1}]
    assert get.call_args.kwargs["params"] == {"eventId": "evt-1"}


def test_create_request_for_catalogued_available_venue_is_saved(mocker):
    """
    Summary: A request for an available catalogue venue with enough capacity is saved.
    AC1: Given an event exists, when the Event Coordinator creates venue
        booking requests, then more than one venue booking can be associated
        with the same event.
    Double: Stub (event, venues, Venue Availability creates)
    """
    # Arrange (Given)
    mock_get_event = mocker.patch("app.routes.get_event")
    mock_get_venues = mocker.patch("app.routes.get_venues")
    mock_create_booking = mocker.patch("app.routes.create_booking")
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES
    mock_create_booking.return_value = BOOKING

    client = signed_in(create_app().test_client())

    # Act (When)
    response = client.post(
        "/booking-requests",
        json=REQUEST,
    )

    # Assert (Then)
    assert response.status_code == 201
    assert response.json == BOOKING
    mock_get_event.assert_called_once_with("evt-1")
    mock_create_booking.assert_called_once_with(
        "evt-1", "ven-2", "2030-10-01T09:00", "2030-10-01T12:00",
        80, "Projector"
    )


def test_create_request_without_required_fields_returns_400():
    """
    Summary: A request missing required fields is refused.
    AC2: Each venue booking records its own venue, date/time, required
        capacity/expected attendance, venue requirements, and booking status.
    Double: None
    """
    client = signed_in(create_app().test_client())
    response = client.post("/booking-requests", json={"eventId": "evt-1"})
    assert response.status_code == 400


@pytest.mark.parametrize(
    "change",
    [
        {"requestedStartTime": "2030-10-01"},
        {"requestedEndTime": "2030-10-01T08:00"},
        {"requiredCapacity": 0},
        {"requiredCapacity": True},
        {"venueRequirements": None},
    ],
    ids=["requestedstarttime_2030_10_01", "requestedendtime_2030_10_01t08_00", "requiredcapacity_0", "requiredcapacity_true", "venuerequirements_none"],
)
def test_create_request_with_invalid_booking_details_returns_400(change):
    """
    Summary: Each booking's own times, capacity and requirements are validated.
    AC2: Each venue booking records its own venue, date/time, required
        capacity/expected attendance, venue requirements, and booking status.
    Double: None
    """
    response = signed_in(create_app().test_client()).post(
        "/booking-requests", json=REQUEST | change
    )
    assert response.status_code == 400


def test_create_request_for_unknown_event_returns_404(mocker):
    """
    Summary: A request for an unknown event is refused.
    AC1: Given an event exists, when the Event Coordinator creates venue
        booking requests, then more than one venue booking can be associated
        with the same event.
    Double: Stub (event lookup not found)
    """
    # Arrange (Given)
    mock_get_event = mocker.patch("app.routes.get_event")
    mock_get_event.side_effect = EventNotFoundError

    client = signed_in(create_app().test_client())

    # Act (When)
    response = client.post(
        "/booking-requests",
        json=REQUEST | {"eventId": "missing", "venueId": "ven-1"},
    )

    # Assert (Then)
    assert response.status_code == 404


def test_create_request_when_not_assigned_coordinator_returns_403(mocker):
    """
    Summary: Only the event's assigned coordinator can request its bookings.
    AC1: Given an event exists, when the Event Coordinator creates venue
        booking requests, then more than one venue booking can be associated
        with the same event.
    Double: Stub (event assigned to someone else)
    """
    # Arrange (Given)
    mock_get_event = mocker.patch("app.routes.get_event")
    mock_get_event.side_effect = EventNotAssignedError

    client = signed_in(create_app().test_client())

    # Act (When)
    response = client.post(
        "/booking-requests",
        json=REQUEST | {"venueId": "ven-1", "coordinatorId": "someone-else"},
    )

    # Assert (Then)
    assert response.status_code == 403


def test_create_request_for_venue_not_in_catalogue_returns_404(mocker):
    """
    Summary: A venue that does not exist in the catalogue is refused.
    AC4: When a venue booking is submitted, its suitability, availability, and
        booking conflicts are evaluated using the requirements of that specific
        booking.
    Double: Stub (venues without the id)
    """
    mock_get_event = mocker.patch("app.routes.get_event")
    mock_get_venues = mocker.patch("app.routes.get_venues")
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES

    client = signed_in(create_app().test_client())
    response = client.post(
        "/booking-requests",
        json=REQUEST | {"venueId": "not-a-real-venue"},
    )
    assert response.status_code == 404


@pytest.mark.parametrize("venue_id", ["ven-3", "ven-4"], ids=["under_maintenance", "booked"])
def test_create_request_for_venue_not_available_returns_409(venue_id, mocker):
    """
    Summary: Venues under maintenance or booked are refused.
    AC4: When a venue booking is submitted, its suitability, availability, and
        booking conflicts are evaluated using the requirements of that specific
        booking.
    Double: Stub (venue status)
    """
    mock_get_event = mocker.patch("app.routes.get_event")
    mock_get_venues = mocker.patch("app.routes.get_venues")
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES

    client = signed_in(create_app().test_client())
    response = client.post(
        "/booking-requests",
        json=REQUEST | {"venueId": venue_id},
    )
    assert response.status_code == 409
    assert "not currently available for booking" in response.json["message"]


def test_create_request_checks_booking_capacity_not_event_total(mocker):
    """
    Summary: Capacity is checked against that booking's own required capacity.
    AC4: When a venue booking is submitted, its suitability, availability, and
        booking conflicts are evaluated using the requirements of that specific
        booking.
    Double: Stub (venues), Mock (create_booking)
    """
    mock_get_event = mocker.patch("app.routes.get_event")
    mock_get_venues = mocker.patch("app.routes.get_venues")
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES

    client = signed_in(create_app().test_client())
    mock_create = mocker.patch("app.routes.create_booking", return_value=BOOKING)
    response = client.post(
        "/booking-requests",
        json=REQUEST | {"venueId": "ven-1", "requiredCapacity": 50},
    )
    assert response.status_code == 201
    assert EVENT["expectedAttendance"] == "150"
    assert mock_create.call_args.args[4] == 50


def test_create_request_above_venue_capacity_returns_409(mocker):
    """
    Summary: A booking needing more places than the venue has is refused.
    AC4: When a venue booking is submitted, its suitability, availability, and
        booking conflicts are evaluated using the requirements of that specific
        booking.
    Double: Stub (venue capacity)
    """
    mock_get_event = mocker.patch("app.routes.get_event")
    mock_get_venues = mocker.patch("app.routes.get_venues")
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES

    response = signed_in(create_app().test_client()).post(
        "/booking-requests", json=REQUEST | {"venueId": "ven-1", "requiredCapacity": 61}
    )

    assert response.status_code == 422


def test_create_request_for_taken_slot_returns_409(mocker):
    """
    Summary: A slot already taken is reported as a conflict.
    AC4: When a venue booking is submitted, its suitability, availability, and
        booking conflicts are evaluated using the requirements of that specific
        booking.
    Double: Stub (Venue Availability reports a conflict)
    """
    mock_get_event = mocker.patch("app.routes.get_event")
    mock_get_venues = mocker.patch("app.routes.get_venues")
    mock_create_booking = mocker.patch("app.routes.create_booking")
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES
    mock_create_booking.side_effect = BookingConflictError

    client = signed_in(create_app().test_client())
    response = client.post(
        "/booking-requests",
        json=REQUEST,
    )
    assert response.status_code == 409


def test_event_requests_list_each_booking_separately(mocker):
    """
    Summary: An event's bookings are listed separately.
    AC1: Given an event exists, when the Event Coordinator creates venue
        booking requests, then more than one venue booking can be associated
        with the same event.
    AC3: Given multiple venue bookings exist for an event, when the Event
        Coordinator views the event, then each booking is displayed separately
        while remaining associated with the same event.
    Double: Stub (two bookings)
    """
    # Arrange (Given)
    mock_get_event_bookings = mocker.patch("app.routes.get_event_bookings")
    mock_get_event = mocker.patch("app.routes.get_event")
    mock_get_venues = mocker.patch("app.routes.get_venues")
    mock_get_event.return_value = EVENT
    mock_get_event_bookings.return_value = [
        BOOKING,
        BOOKING | {"id": "booking-2", "venueId": "ven-1", "requiredCapacity": 50},
    ]
    mock_get_venues.return_value = VENUES

    # Act (When)
    response = signed_in(create_app().test_client()).get(
        "/events/evt-1/booking-requests?coordinatorId=coord-1"
    )

    # Assert (Then)
    assert response.status_code == 200
    assert [(item["id"], item["venueName"]) for item in response.json["bookings"]] == [
        ("booking-1", "Grand Ballroom"),
        ("booking-2", "Innovation Lab"),
    ]


def test_approve_request_is_recorded(mocker):
    """
    Summary: Venue Staff can approve a request.
    SCRUM-29 AC2: Given Venue Staff determine that a pending venue booking
        request can be accepted, when they approve the request, then the
        booking decision is recorded as approved and the outcome is available
        to the relevant Event Coordinator.
    Double: Stub (Venue Availability approves)
    """
    # Arrange (Given)
    mock_decide_booking = mocker.patch("app.routes.decide_booking")
    mock_get_booking = mocker.patch("app.routes.get_booking")
    mock_get_venue = mocker.patch("app.routes.get_venue")
    _event = mocker.patch("app.routes.get_event_for_internal_viewer", return_value=EVENT)
    mock_decide_booking.return_value = {**BOOKING, "status": "Approved"}
    mock_get_booking.return_value = {**BOOKING, "venueId": "ven-2"}
    mock_get_venue.return_value = {"id": "ven-2", "setupTimeMinutes": 30, "turnaroundTimeMinutes": 45}

    client = signed_in(create_app().test_client())

    # Act (When)
    response = client.patch(
        "/booking-requests/booking-1/approve", headers=STAFF_HEADERS, json={"reviewedBy": STAFF_ID}
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Approved"
    mock_decide_booking.assert_called_once_with("booking-1", "Approved", 30, 45)


def test_reject_request_without_reviewer_is_refused(mocker):
    """
    Summary: A rejection needs a signed-in reviewer.
    SCRUM-29 AC3: Given Venue Staff determine that a pending venue booking
        request cannot be accepted, when they reject the request, then the
        booking decision is recorded as rejected and the outcome is available
        to the relevant Event Coordinator.
    Double: None
    """
    # Arrange (Given)
    mock_decide_booking = mocker.patch("app.routes.decide_booking")
    client = signed_in(create_app().test_client())

    # Act (When)
    response = client.patch("/booking-requests/booking-1/reject", headers=STAFF_HEADERS, json={})

    # Assert (Then)
    assert response.status_code == 400
    mock_decide_booking.assert_not_called()


def test_approve_unknown_request_returns_404(mocker):
    """
    Summary: Approving an unknown request is refused.
    SCRUM-29 AC2: Given Venue Staff determine that a pending venue booking
        request can be accepted, when they approve the request, then the
        booking decision is recorded as approved and the outcome is available
        to the relevant Event Coordinator.
    Double: Stub (Venue Availability not found)
    """
    # Arrange (Given)
    mock_decide_booking = mocker.patch("app.routes.decide_booking")
    mock_get_booking = mocker.patch("app.routes.get_booking")
    mock_get_booking.side_effect = BookingNotFoundError

    client = signed_in(create_app().test_client())

    # Act (When)
    response = client.patch(
        "/booking-requests/missing/approve", headers=STAFF_HEADERS, json={"reviewedBy": STAFF_ID}
    )

    # Assert (Then)
    assert response.status_code == 404


def test_review_cancelled_request_returns_409(mocker):
    """
    Summary: A cancelled request cannot be reviewed.
    SCRUM-29 AC5: Given Venue Staff have recorded an approval or rejection for
        a pending venue booking request, when the decision is completed, then
        the request is no longer presented as awaiting a booking decision.
    Double: Stub (Venue Availability state error)
    """
    # Arrange (Given)
    mock_decide_booking = mocker.patch("app.routes.decide_booking")
    mocker.patch("app.routes.get_booking", return_value=BOOKING)
    mocker.patch("app.routes.get_venue", return_value=VENUES[1])
    mocker.patch("app.routes.get_event_for_internal_viewer", return_value=EVENT)
    mock_decide_booking.side_effect = BookingStateError

    # Act (When)
    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1/approve", headers=STAFF_HEADERS, json={"reviewedBy": STAFF_ID}
    )

    # Assert (Then)
    assert response.status_code == 409
    assert "cannot be reviewed" in response.json["message"]


def test_edit_request_revalidates_and_resubmits_only_that_booking(mocker):
    """
    Summary: An edit is re-validated and only that booking is resubmitted.
    SCRUM-157 AC1: Given an event has one or more venue bookings, when the
        Event Coordinator modifies a specific booking, then only that selected
        booking is updated.
    SCRUM-157 AC2: If a modification changes the venue, date/time, required
        capacity, or other suitability requirements, then suitability,
        availability, and conflict checks are performed again for that booking
        only.
    Double: Mock (update_booking inspected)
    """
    # Arrange (Given)
    mock_get_event = mocker.patch("app.routes.get_event")
    mock_get_venues = mocker.patch("app.routes.get_venues")
    mock_update_booking = mocker.patch("app.routes.update_booking")
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES
    mock_update_booking.return_value = {
        **BOOKING,
        "requiredCapacity": 50,
        "status": "Pending Review",
        "reviewedBy": None,
    }

    # Act (When)
    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1",
        json=REQUEST | {"requiredCapacity": 50},
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Pending Review"
    mock_get_event.assert_called_once_with("evt-1")
    mock_update_booking.assert_called_once_with(
        "booking-1", "evt-1", "ven-2", "2030-10-01T09:00",
        "2030-10-01T12:00", 50, "Projector"
    )


def test_edit_request_rechecks_capacity_before_saving(mocker):
    """
    Summary: An edit re-checks capacity before saving.
    SCRUM-157 AC2: If a modification changes the venue, date/time, required
        capacity, or other suitability requirements, then suitability,
        availability, and conflict checks are performed again for that booking
        only.
    Double: Stub (venue capacity)
    """
    mock_get_event = mocker.patch("app.routes.get_event")
    mock_get_venues = mocker.patch("app.routes.get_venues")
    mock_update_booking = mocker.patch("app.routes.update_booking")
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES

    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1",
        json=REQUEST | {"venueId": "ven-1", "requiredCapacity": 61},
    )

    assert response.status_code == 422
    mock_update_booking.assert_not_called()


def test_edit_request_conflict_leaves_other_bookings_unchanged(mocker):
    """
    Summary: A conflicting edit is reported and the event's other bookings are untouched.
    SCRUM-157 AC4: Cancelling or modifying one venue booking does not
        automatically change the status of the event's other venue bookings.
    Double: Stub (update raises conflict)
    """
    mock_get_event = mocker.patch("app.routes.get_event")
    mock_get_venues = mocker.patch("app.routes.get_venues")
    mock_update_booking = mocker.patch("app.routes.update_booking")
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES
    mock_update_booking.side_effect = BookingConflictError

    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1", json=REQUEST
    )

    assert response.status_code == 409
    assert "Grand Ballroom" in response.json["message"]


def test_edit_cancelled_request_returns_409(mocker):
    """
    Summary: A cancelled request cannot be edited back to life.
    SCRUM-157 AC5: A cancelled booking remains associated with the event with a
        Cancelled status for record keeping.
    Double: Stub (update raises state error)
    """
    mock_get_event = mocker.patch("app.routes.get_event")
    mock_get_venues = mocker.patch("app.routes.get_venues")
    mock_update_booking = mocker.patch("app.routes.update_booking")
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES
    mock_update_booking.side_effect = BookingStateError

    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1", json=REQUEST
    )

    assert response.status_code == 409
    assert "cannot be modified" in response.json["message"]


def test_cancel_request_cancels_only_that_booking(mocker):
    """
    Summary: Cancelling cancels only the selected booking.
    SCRUM-157 AC3: Given an event has multiple venue bookings, when the Event
        Coordinator cancels one booking, then only the selected booking is
        cancelled and the other bookings remain unchanged.
    Double: Mock (cancel_booking inspected)
    """
    # Arrange (Given)
    mock_get_event = mocker.patch("app.routes.get_event")
    mock_cancel_booking = mocker.patch("app.routes.cancel_booking")
    mock_get_event.return_value = EVENT
    mock_cancel_booking.return_value = {**BOOKING, "status": "Cancelled"}

    # Act (When)
    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1/cancel",
        json={"eventId": "evt-1", "coordinatorId": "coord-1"},
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Cancelled"
    mock_get_event.assert_called_once_with("evt-1")
    mock_cancel_booking.assert_called_once_with("booking-1", "evt-1")


def test_cancel_request_when_not_assigned_coordinator_returns_403(mocker):
    """
    Summary: Only the event's assigned coordinator can cancel its bookings.
    SCRUM-157 AC3: Given an event has multiple venue bookings, when the Event
        Coordinator cancels one booking, then only the selected booking is
        cancelled and the other bookings remain unchanged.
    Double: Stub (event assigned to someone else)
    """
    # Arrange (Given)
    mock_get_event = mocker.patch("app.routes.get_event")
    mock_cancel_booking = mocker.patch("app.routes.cancel_booking")
    mock_get_event.side_effect = EventNotAssignedError

    # Act (When)
    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1/cancel",
        json={"eventId": "evt-1", "coordinatorId": "someone-else"},
    )

    # Assert (Then)
    assert response.status_code == 403
    mock_cancel_booking.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"eventId": "evt-1"},
        REQUEST | {"requiredCapacity": 0},
        REQUEST | {"venueRequirements": None},
        REQUEST | {"requestedStartTime": "2030-10-01"},
    ],
    ids=["empty", "eventid_evt_1", "request_requiredcapacity_0", "request_venuerequirements_none", "request_requestedstarttime_2030_10_01"],
)
def test_edit_request_with_invalid_body_returns_400(payload):
    """
    Summary: An edit with an invalid body is refused.
    SCRUM-157 AC2: If a modification changes the venue, date/time, required
        capacity, or other suitability requirements, then suitability,
        availability, and conflict checks are performed again for that booking
        only.
    Double: None
    """
    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1", json=payload
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    ("event_error", "expected_status"),
    [(EventNotFoundError, 404), (EventNotAssignedError, 403), (RuntimeError("down"), 502)],
    ids=["not_found", "not_assigned", "outage"],
)
def test_edit_request_when_event_check_fails_is_refused(event_error, expected_status, mocker):
    """
    Summary: An edit needs access to the booking's event.
    SCRUM-157 AC1: Given an event has one or more venue bookings, when the
        Event Coordinator modifies a specific booking, then only that selected
        booking is updated.
    Double: Stub (event lookup raises)
    """
    # Arrange (Given)
    mock_get_event = mocker.patch("app.routes.get_event")
    mock_get_event.side_effect = event_error

    # Act (When)
    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1", json=REQUEST
    )

    # Assert (Then)
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    ("venue_id", "expected_status"),
    [("missing", 404), ("ven-3", 409)],
    ids=["missing_venue", "unavailable_venue"],
)
def test_edit_request_rechecks_venue_catalogue(venue_id, expected_status, mocker):
    """
    Summary: An edit to an unknown or unavailable venue is refused.
    SCRUM-157 AC2: If a modification changes the venue, date/time, required
        capacity, or other suitability requirements, then suitability,
        availability, and conflict checks are performed again for that booking
        only.
    Double: Stub (venues)
    """
    mock_get_event = mocker.patch("app.routes.get_event")
    mock_get_venues = mocker.patch("app.routes.get_venues")
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES
    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1", json=REQUEST | {"venueId": venue_id}
    )
    assert response.status_code == expected_status


def test_edit_request_when_venue_service_fails_returns_502(mocker):
    """
    Summary: A Venue Service failure during an edit is reported.
    SCRUM-157 AC2: If a modification changes the venue, date/time, required
        capacity, or other suitability requirements, then suitability,
        availability, and conflict checks are performed again for that booking
        only.
    Double: Stub (venue lookup raises)
    """
    mock_get_event = mocker.patch("app.routes.get_event")
    mock_get_venues = mocker.patch("app.routes.get_venues")
    mock_get_event.return_value = EVENT
    mock_get_venues.side_effect = RuntimeError("down")
    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1", json=REQUEST
    )
    assert response.status_code == 502


@pytest.mark.parametrize(
    ("update_error", "expected_status"),
    [(BookingNotFoundError, 404), (RuntimeError("down"), 502)],
    ids=["not_found", "outage"],
)
def test_edit_request_when_save_fails_returns_error(update_error, expected_status, mocker):
    """
    Summary: A failed save is reported.
    SCRUM-157 AC1: Given an event has one or more venue bookings, when the
        Event Coordinator modifies a specific booking, then only that selected
        booking is updated.
    Double: Stub (update raises)
    """
    # Arrange (Given)
    mock_get_event = mocker.patch("app.routes.get_event")
    mock_get_venues = mocker.patch("app.routes.get_venues")
    mock_update_booking = mocker.patch("app.routes.update_booking")
    mock_get_event.return_value = EVENT
    mock_get_venues.return_value = VENUES
    mock_update_booking.side_effect = update_error

    # Act (When)
    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1", json=REQUEST
    )

    # Assert (Then)
    assert response.status_code == expected_status


def test_cancel_request_needs_event_and_coordinator():
    """
    Summary: Cancelling needs the event and its coordinator.
    SCRUM-157 AC3: Given an event has multiple venue bookings, when the Event
        Coordinator cancels one booking, then only the selected booking is
        cancelled and the other bookings remain unchanged.
    Double: None
    """
    # Act (When)
    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1/cancel", json={}
    )

    # Assert (Then)
    assert response.status_code == 400


@pytest.mark.parametrize(
    ("cancel_error", "expected_status"),
    [(BookingNotFoundError, 404), (RuntimeError("down"), 502)],
    ids=["not_found", "outage"],
)
def test_cancel_request_when_save_fails_returns_error(cancel_error, expected_status, mocker):
    """
    Summary: A failed cancel is reported.
    SCRUM-157 AC3: Given an event has multiple venue bookings, when the Event
        Coordinator cancels one booking, then only the selected booking is
        cancelled and the other bookings remain unchanged.
    Double: Stub (cancel raises)
    """
    # Arrange (Given)
    mock_get_event = mocker.patch("app.routes.get_event")
    mock_cancel_booking = mocker.patch("app.routes.cancel_booking")
    mock_get_event.return_value = EVENT
    mock_cancel_booking.side_effect = cancel_error

    # Act (When)
    response = signed_in(create_app().test_client()).patch(
        "/booking-requests/booking-1/cancel",
        json={"eventId": "evt-1", "coordinatorId": "coord-1"},
    )

    # Assert (Then)
    assert response.status_code == expected_status


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_health_when_called_returns_ok():
    """
    Summary: Anyone can check the service is up.
    Supporting design check: /health answers without a token
    Double: None
    """
    client = signed_in(create_app().test_client())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}
