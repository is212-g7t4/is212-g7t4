"""
SCRUM-153: Re-check Safety After High-Impact Changes

User Story
----------
As an Event Coordinator, I want a safety approval to be withdrawn when a
high-impact detail changes afterwards, so that the event is never prepared on
the basis of an outdated safety review.

Acceptance Criteria
-------------------
AC1: Given an event is 'Confirmed', when its date/time, expected attendance,
     venue requirements, equipment requirements or accessibility needs change,
     then its status returns to 'Pending Safety Check' and the coordinator is
     told why.
AC2: Given only a low-impact field changes (name, description, purpose,
     registration needs), then the event stays 'Confirmed'.
AC3: Given a safety approval is withdrawn, then it stays visible in the event's
     safety history.
AC4: Given a high-impact change to a 'Confirmed' event is waiting for its new
     safety check, when a registered Attendee views the event, then they still
     see the previously approved details, and the changed details are shown to
     them only after the Safety Officer approves the new safety check.
AC5: Given the new safety check ends without approval (changes requested or the
     event is cancelled), then registered Attendees are never shown the
     unapproved change, and they continue to see the last approved details or
     the cancellation.

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
AC7: Given an event is 'Confirmed' after passing its Operational Safety Check,
     when the Event Coordinator edits or cancels one of its venue bookings,
     then the event's safety approval is withdrawn without opening a new safety
     check round, the event returns to 'Approved', and an edited booking
     returns to awaiting Venue Staff review, so the event must be submitted for
     a safety check again. If the booking change cannot be saved, the safety
     approval is restored and the event stays 'Confirmed'. While the event is
     'Pending Safety Check', its venue bookings cannot be edited or cancelled.

Real
----
- POST /safety-checks/booking-change-withdrawal and .../restore: withdraw the
  approval without opening a round, move the event back to Approved, compensate
  on failure, and the restore in reverse order.
- Assertions are on the status and the order of downstream calls.

Doubled
-------
- Event, Safety Check Record, Venue Availability, Venue, Equipment Request,
  Equipment and User Services: Stub (monkeypatched app.clients functions, or
  respx for client tests) - canned answers or raised client errors; calls
  recorded so tests assert the order and what was (or was not) called.

Not proven
----------
- The whole chain across Venue Booking, Safety Check, Safety Check Record and
  Event Services (-> docs/test-scripts/scrum-28-venue-booking-request-
  submission.md, Part B, run by hand against the stack).
"""
import logging

import httpx
import pytest
from flask import g

from app import clients, create_app
from tests.unit.factories import (
    signed_in,
    BOOKING_ID,
    COORDINATOR_ID,
    EVENT_ID,
    OFFICER_ID,
    OTHER_COORDINATOR_ID,
    RECORD_ID,
    event,
    record,
)

REASON = "Venue booking for Grand Hall was edited after safety approval."


class Downstream:
    """Recorded stand-ins for the atomics these two routes call."""

    def __init__(self):
        self.event = event("Confirmed")
        self.rounds = [record(round_number=2, status="Safety Approved", decidedBy=OFFICER_ID)]
        self.withdrawn = record(round_number=2, status="Approval Withdrawn", decidedBy=OFFICER_ID)
        self.restored = record(round_number=2, status="Safety Approved", decidedBy=OFFICER_ID)
        self.calls = []
        self.fail = {}

    def _record(self, *call):
        self.calls.append(call)
        if call[0] in self.fail:
            raise self.fail[call[0]]

    def get_event(self, event_id, viewer_role=None):
        viewer_id = g.user_id  # The downstream service reads this from the forwarded token.
        self._record("get_event", event_id, viewer_id)
        return self.event

    def list_safety_check_records(self, event_id, status=None):
        self._record("list_records", event_id)
        return self.rounds

    def withdraw_approval_without_next_round(self, round_id, reason):
        withdrawn_by = g.user_id  # The downstream service reads this from the forwarded token.
        self._record("withdraw", round_id, withdrawn_by, reason)
        return self.withdrawn

    def restore_approval_without_next_round(self, round_id):
        self._record("restore", round_id)
        return self.restored

    def set_event_venue_change_status(self, event_id, round_id, round_number, withdraw, reason=None):
        coordinator_id = g.user_id  # The downstream service reads this from the forwarded token.
        self._record("move_event", event_id, coordinator_id, round_id, round_number, withdraw, reason)
        return event("Approved" if withdraw else "Confirmed")

    def names(self):
        return [call[0] for call in self.calls]


@pytest.fixture
def downstream(monkeypatch):
    stub = Downstream()
    for name in (
        "get_event",
        "list_safety_check_records",
        "withdraw_approval_without_next_round",
        "restore_approval_without_next_round",
        "set_event_venue_change_status",
    ):
        monkeypatch.setattr(f"app.clients.{name}", getattr(stub, name))
    return stub


@pytest.fixture
def client():
    return signed_in(create_app().test_client())


def withdraw(client, **overrides):
    body = {"eventId": EVENT_ID, "coordinatorId": COORDINATOR_ID, "bookingId": BOOKING_ID, "reason": REASON, **overrides}
    return client.post("/safety-checks/withdraw-for-venue-change", json=body)


def restore(client, **overrides):
    body = {"eventId": EVENT_ID, "coordinatorId": COORDINATOR_ID, "withdrawnSafetyCheckId": RECORD_ID, **overrides}
    return client.post("/safety-checks/restore-after-venue-change", json=body)


# --- withdraw-for-venue-change -----------------------------------------------


def test_booking_change_withdrawal_withdraws_round_then_returns_event_to_approved(client, downstream):
    """
    Summary: A booking change withdraws the approval and returns the event to Approved, without a new round.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given): client, downstream, from fixtures

    # Act (When)
    response = withdraw(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["event"]["status"] == "Approved"
    assert response.json["withdrawnSafetyCheck"]["status"] == "Approval Withdrawn"
    assert response.json["bookingId"] == BOOKING_ID
    assert downstream.names() == ["get_event", "list_records", "withdraw", "move_event"]
    assert downstream.calls[2] == ("withdraw", RECORD_ID, COORDINATOR_ID, REASON)
    assert downstream.calls[3] == ("move_event", EVENT_ID, COORDINATOR_ID, RECORD_ID, 2, True, REASON)


@pytest.mark.parametrize("status", ["Approved", "Pending Safety Check", "Safety Changes Requested", "Cancelled"])
def test_booking_change_withdrawal_for_unconfirmed_event_returns_409(client, downstream, status):
    """
    Summary: Only a Confirmed event has an approval to withdraw.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.event = event(status)

    # Act (When)
    response = withdraw(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_CONFIRMED"
    assert response.json["currentStatus"] == status
    assert downstream.names() == ["get_event"]


@pytest.mark.parametrize("rounds", [[], [record(round_number=2, status="Approval Withdrawn")]], ids=["none", "withdrawn"])
def test_booking_change_withdrawal_without_approved_latest_round_returns_409(client, downstream, rounds):
    """
    Summary: The latest round must be the approval in force.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.rounds = rounds

    # Act (When)
    response = withdraw(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "NO_APPROVED_SAFETY_CHECK"
    assert "withdraw" not in downstream.names()


def test_booking_change_withdrawal_by_other_coordinator_returns_403(client, downstream):
    """
    Summary: Another coordinator cannot withdraw the approval.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.fail["get_event"] = clients.EventNotAssignedError()

    # Act (When)
    response = withdraw(client, coordinatorId=OTHER_COORDINATOR_ID)

    # Assert (Then)
    assert response.status_code == 403
    assert downstream.names() == ["get_event"]


def test_booking_change_withdrawal_when_rounds_unreadable_withdraws_nothing(client, downstream):
    """
    Summary: If the rounds cannot be read, nothing is withdrawn.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.fail["list_records"] = clients.DownstreamError()

    # Act + Assert (When / Then)
    assert withdraw(client).status_code == 502
    assert "withdraw" not in downstream.names()


@pytest.mark.parametrize(
    "error, status, code",
    [
        (clients.RoundNotApprovedError("ROUND_NOT_APPROVED", {}), 409, "ROUND_NOT_APPROVED"),
        (clients.RoundNotApprovedError(None, {"message": "Taken."}), 409, "ROUND_NOT_APPROVED"),
        (clients.RecordNotFoundError(), 409, "NO_APPROVED_SAFETY_CHECK"),
        (clients.DownstreamTimeout(), 504, None),
        (clients.DownstreamError(), 502, None),
    ],
    ids=["clients_roundnotapprovederror_round_not_approved", "clients_roundnotapprovederror_none_message_taken", "clients_recordnotfounderror_409_no_approved_safe", "clients_downstreamtimeout_504_none", "clients_downstreamerror_502_none"],
)
def test_booking_change_withdrawal_when_record_fails_never_moves_event(client, downstream, error, status, code):
    """
    Summary: A lost race or record failure leaves the event as it was.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.fail["withdraw"] = error

    # Act (When)
    response = withdraw(client)

    # Assert (Then)
    assert response.status_code == status
    assert response.json.get("code") == code
    assert "move_event" not in downstream.names()


@pytest.mark.parametrize(
    "error, status",
    [
        (clients.EventTransitionError("STALE_SAFETY_CHECK", {"code": "STALE_SAFETY_CHECK"}), 409),
        (clients.EventNotAssignedError(), 403),
        (clients.EventNotFoundError(), 404),
        (clients.ServiceCredentialsError(), 502),
        (clients.DownstreamTimeout(), 504),
        (clients.DownstreamError(), 502),
    ],
    ids=["clients_eventtransitionerror_stale_safety_check", "clients_eventnotassignederror_403", "clients_eventnotfounderror_404", "clients_servicecredentialserror_502", "clients_downstreamtimeout_504", "clients_downstreamerror_502"],
)
def test_booking_change_withdrawal_when_event_move_fails_restores_approval(client, downstream, error, status):
    """
    Summary: If the event cannot be moved, the withdrawal is undone.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.fail["move_event"] = error

    # Act (When)
    response = withdraw(client)

    # Assert (Then)
    assert response.status_code == status
    assert downstream.names()[-1] == "restore"
    assert downstream.calls[-1] == ("restore", RECORD_ID)


def test_booking_change_withdrawal_when_undo_fails_logs_for_repair(client, downstream, caplog):
    """
    Summary: When the undo fails too, the original error is returned and the repair logged.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.fail["move_event"] = clients.DownstreamError()
    downstream.fail["restore"] = clients.DownstreamError()

    # Act (When)
    with caplog.at_level(logging.ERROR):
        response = withdraw(client)

    # Assert (Then)
    assert response.status_code == 502
    assert RECORD_ID in caplog.text
    assert EVENT_ID in caplog.text


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"eventId": "x"}, "eventId and bookingId must be valid UUIDs."),
        ({"bookingId": None}, "eventId and bookingId must be valid UUIDs."),
        ({"reason": " "}, "reason is required."),
    ],
    ids=["bad_event_id", "missing_booking_id", "blank_reason"],
)
def test_booking_change_withdrawal_with_bad_body_returns_400(client, downstream, overrides, message):
    """
    Summary: A malformed request makes no downstream call.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given): client, downstream, overrides, message, from fixtures

    # Act (When)
    response = withdraw(client, **overrides)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == message
    assert downstream.calls == []


def test_booking_change_withdrawal_with_non_object_body_returns_400(client, downstream):
    """
    Summary: A request that is not a withdrawal is refused.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: None
    """
    # Arrange (Given): client, downstream, from fixtures

    # Act (When)
    response = client.post("/safety-checks/withdraw-for-venue-change", json=[])

    # Assert (Then)
    assert response.status_code == 400
    assert downstream.calls == []


# --- restore-after-venue-change ----------------------------------------------


def test_booking_change_restore_reinstates_round_then_confirms_event(client, downstream):
    """
    Summary: Restoring puts the approval back first, then confirms the event.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.event = event("Approved")

    # Act (When)
    response = restore(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["event"]["status"] == "Confirmed"
    assert response.json["safetyCheck"]["status"] == "Safety Approved"
    assert downstream.names() == ["get_event", "restore", "move_event"]
    assert downstream.calls[2] == ("move_event", EVENT_ID, COORDINATOR_ID, RECORD_ID, 2, False, None)


def test_booking_change_restore_for_event_not_approved_returns_409(client, downstream):
    """
    Summary: Only an event the withdrawal sent back to Approved can be restored.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given): client, downstream, from fixtures

    # Act (When)
    response = restore(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_WITHDRAWN"
    assert downstream.names() == ["get_event"]


@pytest.mark.parametrize(
    "error, status, code",
    [
        (clients.RecordNotFoundError(), 404, None),
        (clients.RoundNotApprovedError("NOT_RESTORABLE", {}), 409, "NOT_RESTORABLE"),
        (clients.RoundNotApprovedError(None, {}), 409, "NOT_RESTORABLE"),
        (clients.DownstreamTimeout(), 504, None),
        (clients.DownstreamError(), 502, None),
    ],
    ids=["clients_recordnotfounderror_404_none", "clients_roundnotapprovederror_not_restorable_409", "clients_roundnotapprovederror_none_409_not_resto", "clients_downstreamtimeout_504_none", "clients_downstreamerror_502_none"],
)
def test_booking_change_restore_when_record_fails_leaves_event_alone(client, downstream, error, status, code):
    """
    Summary: If the round cannot be restored, the event is not confirmed.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.event = event("Approved")
    downstream.fail["restore"] = error

    # Act (When)
    response = restore(client)

    # Assert (Then)
    assert response.status_code == status
    assert response.json.get("code") == code
    assert "move_event" not in downstream.names()


def test_booking_change_restore_when_event_move_fails_logs(client, downstream, caplog):
    """
    Summary: If the event cannot be confirmed again, it stays Approved and this is logged.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.event = event("Approved")
    downstream.fail["move_event"] = clients.EventTransitionError("STALE_SAFETY_CHECK", {"code": "STALE_SAFETY_CHECK"})

    # Act (When)
    with caplog.at_level(logging.ERROR):
        response = restore(client)

    # Assert (Then)
    assert response.status_code == 409
    assert "left Approved" in caplog.text


def test_booking_change_restore_when_event_unreadable_reports_failure(client, downstream):
    """
    Summary: A failure reading the event is reported.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given)
    downstream.fail["get_event"] = clients.EventNotFoundError()

    # Act + Assert (When / Then)
    assert restore(client).status_code == 404


@pytest.mark.parametrize("body", [[], {"eventId": EVENT_ID, "coordinatorId": COORDINATOR_ID}], ids=["list_body", "bad_round_id"])
def test_booking_change_restore_with_bad_body_returns_400(client, downstream, body):
    """
    Summary: A malformed restore makes no downstream call.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (downstream clients), Mock (call order recorded)
    """
    # Arrange (Given): client, downstream, body, from fixtures

    # Act (When)
    response = client.post("/safety-checks/restore-after-venue-change", json=body)

    # Assert (Then)
    assert response.status_code == 400
    assert downstream.calls == []


# --- The three HTTP wrappers --------------------------------------------------


class Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    @property
    def is_success(self):
        return 200 <= self.status_code < 300

    def json(self):
        if self._payload is None:
            raise ValueError("not JSON")
        return self._payload


@pytest.fixture
def sent(monkeypatch):
    # SCRUM-46: these legacy wrapper cases isolate request/error mapping. The
    # actual venue HTTP lookup is exercised in test_attendee_notifications.py.
    monkeypatch.setattr(clients, "attendee_venue_name", lambda event_id: "Hall A")
    calls, queue = [], []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return queue.pop(0)

    monkeypatch.setattr("app.clients.httpx.request", fake_request)
    return calls, queue


def test_withdraw_client_asks_for_no_next_round(sent):
    """
    Summary: The withdrawal asks the record service not to open a round.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(201, {"withdrawn": record(status="Approval Withdrawn"), "opened": None}))

    assert clients.withdraw_approval_without_next_round(RECORD_ID, REASON)["status"] == "Approval Withdrawn"
    assert calls[0]["url"].endswith(f"/safety-check-records/{RECORD_ID}/withdraw")
    assert calls[0]["json"] == {"reason": REASON, "openNextRound": False}


def test_restore_client_names_no_opened_round(sent):
    """
    Summary: The restore tells the record service no round was opened.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, record(status="Safety Approved")))

    assert clients.restore_approval_without_next_round(RECORD_ID)["status"] == "Safety Approved"
    assert calls[0]["url"].endswith(f"/safety-check-records/{RECORD_ID}/restore")
    assert calls[0]["json"] == {"nextRoundOpened": False}


@pytest.mark.parametrize("wrapper", ["withdraw", "restore"])
@pytest.mark.parametrize(
    "status_code, error",
    [(404, clients.RecordNotFoundError), (409, clients.RoundNotApprovedError), (503, clients.DownstreamError)],
)
def test_record_clients_map_failures(sent, wrapper, status_code, error):
    """
    Summary: Record service failures are mapped to typed errors.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (respx answers the error)
    """
    _, queue = sent
    queue.append(Response(status_code, {"code": "X"}))

    with pytest.raises(error):
        if wrapper == "withdraw":
            clients.withdraw_approval_without_next_round(RECORD_ID, REASON)
        else:
            clients.restore_approval_without_next_round(RECORD_ID)


@pytest.mark.parametrize("withdraw_move", [True, False])
def test_event_client_marks_withdrawal_and_restore_moves(sent, monkeypatch, withdraw_move):
    """
    Summary: The event move says whether it is a withdrawal or a restore.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", "secret")
    queue.append(Response(200, event("Approved" if withdraw_move else "Confirmed")))

    clients.set_event_venue_change_status(EVENT_ID, RECORD_ID, 2, withdraw_move, REASON if withdraw_move else None)

    assert calls[0]["method"] == "PATCH"
    assert calls[0]["url"].endswith(f"/events/{EVENT_ID}/safety-status")
    assert calls[0]["headers"] == {"X-Internal-Token": "secret"}
    expected = {"safetyCheckId": RECORD_ID, "roundNumber": 2}
    # SCRUM-46 adds the mocked actual venue only to withdrawal; restoration
    # continues to follow the existing wrapper contract in these inherited cases.
    if withdraw_move:
        expected |= {"status": "Approved", "withdrawnSafetyCheckId": RECORD_ID, "reason": REASON, "venueBefore": "Hall A"}
    else:
        expected |= {"status": "Confirmed", "restoredSafetyCheckId": RECORD_ID}
    assert calls[0]["json"] == expected


@pytest.mark.parametrize(
    "status_code, payload, error",
    [
        (404, {}, clients.EventNotFoundError),
        (403, {"code": "INTERNAL_ONLY"}, clients.ServiceCredentialsError),
        (403, {}, clients.EventNotAssignedError),
        (409, {"code": "STALE_SAFETY_CHECK"}, clients.EventTransitionError),
        (500, {}, clients.DownstreamError),
    ],
    ids=["404_clients_eventnotfounderror", "403_code_internal_only_clients_servicecredential", "403_clients_eventnotassignederror", "409_code_stale_safety_check_clients_eventtransit", "500_clients_downstreamerror"],
)
def test_event_client_maps_failures(sent, status_code, payload, error):
    """
    Summary: Event Service refusals are mapped to typed errors.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (respx answers the error)
    """
    _, queue = sent
    queue.append(Response(status_code, payload))

    with pytest.raises(error):
        clients.set_event_venue_change_status(EVENT_ID, RECORD_ID, 2, True, REASON)


def test_clients_hide_transport_error_details(monkeypatch):
    """
    Summary: Transport errors become downstream errors without leaking details.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (respx raises)
    """
    def boom(*args, **kwargs):
        raise httpx.ConnectTimeout("slow")

    monkeypatch.setattr("app.clients.httpx.request", boom)
    with pytest.raises(clients.DownstreamTimeout):
        clients.set_event_venue_change_status(EVENT_ID, RECORD_ID, 2, True, REASON)
