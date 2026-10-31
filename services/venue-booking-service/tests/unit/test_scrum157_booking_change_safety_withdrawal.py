"""
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
- PATCH /booking-requests/<id> and .../cancel: the event-status gate (open,
  closed, Confirmed), withdrawing the safety approval before changing a
  Confirmed event's booking, validating before withdrawing, and restoring the
  approval if the booking change fails.
- Assertions are on the status and the order of downstream calls.

Doubled
-------
- Event, Venue, Venue Availability, Safety Check Record and Safety Check
  Services: Stub (unittest.mock.patch / monkeypatch on app.routes and
  app.clients, or respx for client tests) - canned answers or raised client
  errors; calls recorded so tests assert what was (or was not) called.

Not proven
----------
- The whole chain across Venue Booking, Safety Check, Safety Check Record and
  Event Services (-> docs/test-scripts/scrum-28-venue-booking-request-
  submission.md, Part B, run by hand against the stack).
- That Safety Check Service withdraws and restores correctly (->
  safety-check-service and safety-check-record-service tests).
- AC4 and AC5 isolation/record-keeping behaviour is covered by
  `test_scrum156_book_multiple_venues.py` and
  `test_scrum157_booking_management_clients.py`; this module focuses on the
  safety-withdrawal workflow around AC1-AC3.
"""
import logging

import httpx
import pytest

from app import clients, create_app
from app.clients import (
    BookingConflictError,
    BookingNotFoundError,
    BookingStateError,
    SafetyApprovalError,
)
from app.routes import CHANGEABLE_EVENT_STATUSES
from tests.unit.factories import signed_in

EVENT_ID = "evt-1"
BOOKING_ID = "booking-1"
WITHDRAWN_ID = "round-2"
VENUE = {"id": "ven-1", "name": "Grand Ballroom", "capacity": 200, "status": "Available"}
EDIT = {
    "eventId": EVENT_ID,
    "venueId": "ven-1",
    "coordinatorId": "coord-1",
    "requestedStartTime": "2030-03-01T13:00",
    "requestedEndTime": "2030-03-01T15:00",
    "requiredCapacity": 120,
    "venueRequirements": "Stage",
}
CANCEL = {"eventId": EVENT_ID, "coordinatorId": "coord-1"}
OPEN_STATUSES = ["Submitted", "Under Review", "Approved", "Safety Changes Requested"]
CLOSED_STATUSES = ["Pending Safety Check", "Clarification Requested", "Rejected", "Cancelled"]


class Calls:
    """Records the order of every downstream call."""

    def __init__(self, monkeypatch, status):
        self.order = []
        self.fail = {}
        self.event = {"id": EVENT_ID, "status": status}
        for name, result in (
            ("get_event", lambda: self.event),
            ("get_venues", lambda: [VENUE]),
            ("withdraw_safety_for_venue_change", lambda: {"withdrawnSafetyCheck": {"id": WITHDRAWN_ID}}),
            ("update_booking", lambda: {"id": BOOKING_ID, "status": "Pending Review"}),
            ("cancel_booking", lambda: {"id": BOOKING_ID, "status": "Cancelled"}),
            ("restore_safety_after_venue_change", lambda: {}),
        ):
            monkeypatch.setattr(f"app.routes.{name}", self._recorder(name, result))

    def _recorder(self, name, result):
        def call(*args):
            self.order.append((name, args))
            if name in self.fail:
                raise self.fail[name]
            return result()
        return call

    def names(self):
        return [name for name, _ in self.order]

    def args(self, name):
        return next(args for called, args in self.order if called == name)


def edit(client):
    return client.patch(f"/booking-requests/{BOOKING_ID}", json=EDIT)


def cancel(client):
    return client.patch(f"/booking-requests/{BOOKING_ID}/cancel", json=CANCEL)


ACTIONS = {"edit": (edit, "update_booking"), "cancel": (cancel, "cancel_booking")}


@pytest.fixture
def client():
    return signed_in(create_app().test_client())


# --- The gate -----------------------------------------------------------------


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("status", OPEN_STATUSES)
def test_ac1_ac3_change_booking_before_safety_check_needs_no_safety_call(client, monkeypatch, action, status):
    """
    Summary: Before the safety check starts, a booking can be edited or cancelled with no safety step.
    AC1: Given an event has one or more venue bookings, when the Event
        Coordinator modifies a specific booking, then only that selected
        booking is updated.
    AC3: Given an event has multiple venue bookings, when the Event Coordinator
        cancels one booking, then only the selected booking is cancelled and
        the other bookings remain unchanged.
    Double: Stub (event in an open status), Mock (call order recorded)
    """
    # Arrange (Given)
    calls = Calls(monkeypatch, status)
    send, booking_call = ACTIONS[action]

    # Act (When)
    response = send(client)

    # Assert (Then)
    assert response.status_code == 200
    assert booking_call in calls.names()
    assert "withdraw_safety_for_venue_change" not in calls.names()


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("status", CLOSED_STATUSES)
def test_scrum28_ac7_change_booking_during_safety_check_or_after_close_returns_409(client, monkeypatch, action, status):
    """
    Summary: While the safety check is pending or the event is closed, bookings cannot be changed.
    AC1: Given an event has one or more venue bookings, when the Event
        Coordinator modifies a specific booking, then only that selected
        booking is updated.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (event in a closed status), Mock (no other calls)
    """
    # Arrange (Given)
    calls = Calls(monkeypatch, status)
    send, _ = ACTIONS[action]

    # Act (When)
    response = send(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_ACCEPTING_VENUE_CHANGES"
    assert response.json["eventStatus"] == status
    assert calls.names() == ["get_event"]


def test_scrum28_ac7_changeable_statuses_are_submittable_four_plus_confirmed():
    """
    Summary: Bookings can be changed in the four submittable statuses and Confirmed.
    AC1: Given an event has one or more venue bookings, when the Event
        Coordinator modifies a specific booking, then only that selected
        booking is updated.
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
    # Act + Assert (When / Then)
    assert CHANGEABLE_EVENT_STATUSES == (
        "Submitted", "Under Review", "Approved", "Safety Changes Requested", "Confirmed",
    )


# --- Confirmed: withdraw first, then change -----------------------------------


def test_scrum28_ac7_edit_booking_of_confirmed_event_withdraws_approval_first(client, monkeypatch):
    """
    Summary: Editing a Confirmed event's booking first withdraws its safety approval.
    AC1: Given an event has one or more venue bookings, when the Event
        Coordinator modifies a specific booking, then only that selected
        booking is updated.
    AC2: If a modification changes the venue, date/time, required capacity, or
        other suitability requirements, then suitability, availability, and
        conflict checks are performed again for that booking only.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Mock (call order recorded)
    """
    # Arrange (Given)
    calls = Calls(monkeypatch, "Confirmed")

    # Act (When)
    response = edit(client)

    # Assert (Then)
    assert response.status_code == 200
    assert calls.names() == ["get_event", "get_venues", "withdraw_safety_for_venue_change", "update_booking"]
    assert calls.args("withdraw_safety_for_venue_change") == (
        EVENT_ID, BOOKING_ID,
        "A venue booking (Grand Ballroom) was edited after safety approval.",
    )


def test_scrum28_ac7_cancel_booking_of_confirmed_event_withdraws_approval_first(client, monkeypatch):
    """
    Summary: Cancelling a Confirmed event's booking first withdraws its safety approval.
    AC3: Given an event has multiple venue bookings, when the Event Coordinator
        cancels one booking, then only the selected booking is cancelled and
        the other bookings remain unchanged.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Mock (call order recorded)
    """
    # Arrange (Given)
    calls = Calls(monkeypatch, "Confirmed")

    # Act (When)
    response = cancel(client)

    # Assert (Then)
    assert response.status_code == 200
    assert calls.names() == ["get_event", "withdraw_safety_for_venue_change", "cancel_booking"]
    assert calls.args("withdraw_safety_for_venue_change")[2] == "A venue booking was cancelled after safety approval."


def test_scrum28_ac7_edit_booking_failing_validation_never_withdraws_approval(client, monkeypatch):
    """
    Summary: An edit that fails validation never touches the approval.
    AC2: If a modification changes the venue, date/time, required capacity, or
        other suitability requirements, then suitability, availability, and
        conflict checks are performed again for that booking only.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Mock (no withdraw call)
    """
    # Arrange (Given)
    calls = Calls(monkeypatch, "Confirmed")
    monkeypatch.setattr("app.routes.get_venues", lambda: [{**VENUE, "capacity": 10}])

    # Act + Assert (When / Then)
    assert edit(client).status_code == 422
    assert "withdraw_safety_for_venue_change" not in calls.names()


@pytest.mark.parametrize(
    "error, status",
    [
        (BookingConflictError(["APPROVED_BOOKING"]), 409),
        (BookingStateError(), 409),
        (BookingNotFoundError(), 404),
        (RuntimeError("down"), 502),
    ],
    ids=["conflict", "state_error", "not_found", "outage"],
)
def test_scrum28_ac7_edit_booking_failure_restores_approval_and_returns_booking_error(client, monkeypatch, error, status):
    """
    Summary: If the edit fails, the approval is put back and the booking error is shown.
    AC1: Given an event has one or more venue bookings, when the Event
        Coordinator modifies a specific booking, then only that selected
        booking is updated.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (update raises), Mock (restore called)
    """
    # Arrange (Given)
    calls = Calls(monkeypatch, "Confirmed")
    calls.fail["update_booking"] = error

    # Act (When)
    response = edit(client)

    # Assert (Then)
    assert response.status_code == status
    assert calls.names()[-1] == "restore_safety_after_venue_change"
    assert calls.args("restore_safety_after_venue_change") == (EVENT_ID, WITHDRAWN_ID)


def test_ac2_edit_booking_conflict_reports_conflict_types(client, monkeypatch):
    """
    Summary: A conflicting edit shows the venue conflict, not a safety message.
    AC2: If a modification changes the venue, date/time, required capacity, or
        other suitability requirements, then suitability, availability, and
        conflict checks are performed again for that booking only.
    Double: Stub (update raises BookingConflictError)
    """
    calls = Calls(monkeypatch, "Confirmed")
    calls.fail["update_booking"] = BookingConflictError(["APPROVED_BOOKING"])

    response = edit(client)

    assert response.json["code"] == "VENUE_UNAVAILABLE"
    assert response.json["conflictTypes"] == ["APPROVED_BOOKING"]


@pytest.mark.parametrize("error, status", [(BookingStateError(), 409), (BookingNotFoundError(), 404)], ids=["state_error", "not_found"])
def test_scrum28_ac7_cancel_booking_failure_restores_approval(client, monkeypatch, error, status):
    """
    Summary: If the cancel fails, the approval is put back.
    AC3: Given an event has multiple venue bookings, when the Event Coordinator
        cancels one booking, then only the selected booking is cancelled and
        the other bookings remain unchanged.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cancel raises), Mock (restore called)
    """
    # Arrange (Given)
    calls = Calls(monkeypatch, "Confirmed")
    calls.fail["cancel_booking"] = error

    # Act + Assert (When / Then)
    assert cancel(client).status_code == status
    assert calls.names()[-1] == "restore_safety_after_venue_change"


@pytest.mark.parametrize(
    "error, status",
    [
        (SafetyApprovalError(409, {"code": "NO_APPROVED_SAFETY_CHECK", "message": "None."}), 409),
        (SafetyApprovalError(403, {"code": "NOT_ASSIGNED_COORDINATOR"}), 403),
        (SafetyApprovalError(500, {}), 502),
        (httpx.ConnectError("down"), 502),
    ],
    ids=["withdrawal_conflict", "withdrawal_forbidden", "withdrawal_error", "unreachable"],
)
@pytest.mark.parametrize("action", ACTIONS)
def test_scrum28_ac7_change_booking_when_withdrawal_fails_leaves_booking_untouched(client, monkeypatch, action, error, status):
    """
    Summary: If the approval cannot be withdrawn, the booking is never changed.
    AC1: Given an event has one or more venue bookings, when the Event
        Coordinator modifies a specific booking, then only that selected
        booking is updated.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (withdraw fails), Mock (no booking change)
    """
    # Arrange (Given)
    calls = Calls(monkeypatch, "Confirmed")
    calls.fail["withdraw_safety_for_venue_change"] = error
    send, booking_call = ACTIONS[action]

    # Act (When)
    response = send(client)

    # Assert (Then)
    assert response.status_code == status
    assert booking_call not in calls.names()
    assert "restore_safety_after_venue_change" not in calls.names()
    if status == 409:
        assert response.json["code"] == "NO_APPROVED_SAFETY_CHECK"


def test_scrum28_ac7_change_booking_when_restore_also_fails_logs_and_returns_booking_error(client, monkeypatch, caplog):
    """
    Summary: When the undo fails too, the original booking error is returned and the repair logged.
    AC1: Given an event has one or more venue bookings, when the Event
        Coordinator modifies a specific booking, then only that selected
        booking is updated.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (update and restore fail)
    """
    # Arrange (Given)
    calls = Calls(monkeypatch, "Confirmed")
    calls.fail["update_booking"] = BookingConflictError(["TENTATIVE_HOLD"])
    calls.fail["restore_safety_after_venue_change"] = RuntimeError("down")

    # Act (When)
    with caplog.at_level(logging.ERROR):
        response = edit(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["conflictTypes"] == ["TENTATIVE_HOLD"]
    assert WITHDRAWN_ID in caplog.text
    assert "manual repair" in caplog.text


def test_scrum28_ac7_change_booking_success_keeps_withdrawal(client, monkeypatch):
    """
    Summary: A saved change keeps the withdrawal so Venue Staff re-review the booking.
    AC1: Given an event has one or more venue bookings, when the Event
        Coordinator modifies a specific booking, then only that selected
        booking is updated.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Mock (no restore call)
    """
    # Arrange (Given)
    calls = Calls(monkeypatch, "Confirmed")

    edit(client)

    # Act + Assert (When / Then)
    assert "restore_safety_after_venue_change" not in calls.names()


# --- The two HTTP wrappers ----------------------------------------------------


def test_scrum28_ac7_withdraw_client_posts_the_change(monkeypatch):
    """
    Summary: The withdraw call sends the change to Safety Check Service.
    AC1: Given an event has one or more venue bookings, when the Event
        Coordinator modifies a specific booking, then only that selected
        booking is updated.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (respx Safety Check Service)
    """
    sent = {}

    def post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return httpx.Response(200, json={"withdrawnSafetyCheck": {"id": WITHDRAWN_ID}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(clients.httpx, "post", post)

    result = clients.withdraw_safety_for_venue_change(EVENT_ID, BOOKING_ID, "why")

    assert result["withdrawnSafetyCheck"]["id"] == WITHDRAWN_ID
    assert sent["url"] == f"{clients.SAFETY_CHECK_SERVICE_URL}/safety-checks/withdraw-for-venue-change"
    assert sent["json"] == {"eventId": EVENT_ID, "bookingId": BOOKING_ID, "reason": "why"}


@pytest.mark.parametrize(
    "response, body",
    [
        (lambda request: httpx.Response(409, json={"code": "EVENT_NOT_CONFIRMED"}, request=request), {"code": "EVENT_NOT_CONFIRMED"}),
        (lambda request: httpx.Response(502, text="<html>", request=request), {}),
    ],
    ids=["json_refusal", "text_refusal"],
)
def test_scrum28_ac7_withdraw_client_keeps_the_refusal(monkeypatch, response, body):
    """
    Summary: A refused withdrawal keeps its status and message.
    AC1: Given an event has one or more venue bookings, when the Event
        Coordinator modifies a specific booking, then only that selected
        booking is updated.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (respx answers a refusal)
    """
    monkeypatch.setattr(clients.httpx, "post", lambda url, **kwargs: response(httpx.Request("POST", url)))

    with pytest.raises(SafetyApprovalError) as raised:
        clients.withdraw_safety_for_venue_change(EVENT_ID, BOOKING_ID, "why")

    assert raised.value.body == body


def test_scrum28_ac7_restore_client_posts_the_withdrawn_round(monkeypatch):
    """
    Summary: The restore call names the withdrawn round.
    AC1: Given an event has one or more venue bookings, when the Event
        Coordinator modifies a specific booking, then only that selected
        booking is updated.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (respx Safety Check Service)
    """
    sent = {}

    def post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return httpx.Response(200, json={"event": {"status": "Confirmed"}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(clients.httpx, "post", post)

    clients.restore_safety_after_venue_change(EVENT_ID, WITHDRAWN_ID)

    assert sent["url"] == f"{clients.SAFETY_CHECK_SERVICE_URL}/safety-checks/restore-after-venue-change"
    assert sent["json"] == {"eventId": EVENT_ID, "withdrawnSafetyCheckId": WITHDRAWN_ID}


def test_scrum28_ac7_restore_client_raises_on_failure(monkeypatch):
    """
    Summary: A failed restore is raised.
    AC1: Given an event has one or more venue bookings, when the Event
        Coordinator modifies a specific booking, then only that selected
        booking is updated.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (respx answers 500)
    """
    monkeypatch.setattr(
        clients.httpx, "post",
        lambda url, **kwargs: httpx.Response(409, json={}, request=httpx.Request("POST", url)),
    )

    with pytest.raises(httpx.HTTPStatusError):
        clients.restore_safety_after_venue_change(EVENT_ID, WITHDRAWN_ID)
