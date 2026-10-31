"""
SCRUM-151: Reject or Request Changes to Safety Arrangements

User Story
----------
As a Safety Officer, I want to reject an event's safety arrangement or request
changes, stating which planning area must be revisited, so that the Event
Coordinator knows exactly what to fix before the event can proceed.

Acceptance Criteria
-------------------
AC1: Given an event is 'Pending Safety Check', when I request changes, then I
     must select at least one affected area (venue arrangement,
     technical/equipment arrangement, event details) and describe the change
     needed; otherwise the decision is not saved.
AC2: Given changes are requested, then the event status changes to 'Safety
     Changes Requested', the event returns to the planning stage for each
     selected area, and its existing arrangements are preserved. For equipment
     requests affected by the requested changes, only requests with status
     'Approved' return to 'Pending' for review. Requests already 'Pending' or
     'Rejected' remain unchanged, including any recorded reviewer and rejection
     reason.
AC3: Given an event is 'Pending Safety Check', when I reject it, then a reason
     is required and I must confirm the rejection before it is saved.
AC4: Given I confirm a rejection, then the event status changes to 'Cancelled',
     and the event cannot be resubmitted for a safety check or moved to any
     further stage.
AC5: Given an event is cancelled by a safety rejection, then its venue bookings
     and equipment reservations are released so they no longer block other
     events, while their records remain in the event's history.
AC6: Given either decision, then the safety check is recorded with the status
     'Changes Requested' or 'Safety Rejected' respectively, together with my
     identity, the timestamp and the reason (plus the selected areas for a
     change request), and the original event information is retained.
AC7: Given an event is not 'Pending Safety Check', then these actions are not
     available and an API call is rejected without changing the event.

Real
----
- Requesting changes or rejecting a safety check: only a Safety Officer, only
  for an event pending its safety check; a change request needs at least one
  area and what to change; flagged venue bookings and approved equipment
  requests go back for review while others stay as they are; a rejection needs
  a reason and confirmation, cancels the event and releases its bookings; and
  the decision is undone if the event cannot be moved.
- We check the result the officer sees, and what each other service is asked to
  do.

Doubled
-------
- Event, Safety Check Record, Venue Availability, Venue, Equipment Request and
  User Services: answer as each test needs, fail, or do not answer in time
  [Stub]; we check which were asked, in what order, and what they were sent
  [Mock].
- Sign-in: a test key signs the caller's token (tests/conftest.py) [Stub].

Not proven
----------
- That the other services apply the resets and releases correctly (-> their own
  SCRUM-151 tests).
"""
import logging

import pytest
from flask import g

from app import clients, create_app
from tests.unit.factories import (
    signed_in,
    BOOKING_ID,
    EVENT_ID,
    OFFICER_ID,
    RECORD_ID,
    REQUEST_ID,
    booking,
    event,
    equipment_request,
    record,
    user,
)
from tests.unit.factories import Response

OTHER_BOOKING_ID = "99999999-9999-4999-8999-999999999999"


class Downstream:
    """Recorded stand-ins for every atomic this composite calls."""

    def __init__(self):
        self.user = user(role="Safety Officer")
        self.event = event("Pending Safety Check")
        self.rounds = [record(status="Pending")]
        self.decided = record(status="Changes Requested", decidedBy=OFFICER_ID)
        self.updated = event("Safety Changes Requested")
        self.bookings = [booking("Approved")]
        self.equipment = [equipment_request("Approved")]
        self.calls = []
        self.fail = {}
        self.apply_despite_failure = set()
        self.fail_from = {}

    def _maybe_fail(self, name):
        error = self.fail.get(name)
        made = len([call for call in self.calls if call[0] == name])
        if error and made >= self.fail_from.get(name, 1):
            raise error

    def get_user(self, user_id):
        self.calls.append(("get_user", user_id))
        self._maybe_fail("get_user")
        return self.user

    def get_event(self, event_id, viewer_role=None):
        viewer_id = g.user_id  # The downstream service reads this from the forwarded token.
        self.calls.append(("get_event", event_id, viewer_id, viewer_role))
        self._maybe_fail("get_event")
        return self.event

    def list_safety_check_records(self, event_id, status=None):
        self.calls.append(("list_records", event_id, status))
        self._maybe_fail("list_records")
        return self.rounds

    def decide_safety_check_record(self, safety_check_id, status, remarks=None, flags=None):
        decided_by = g.user_id  # The downstream service reads this from the forwarded token.
        self.calls.append(("decide", safety_check_id, status, decided_by, remarks, flags))
        if "decide" in self.apply_despite_failure:
            self.rounds = [self.decided]
        self._maybe_fail("decide")
        return self.decided

    def set_event_safety_status(
        self,
        event_id,
        status,
        safety_check_id,
        round_number,
        remarks=None,
        areas=None,
    ):
        decided_by = g.user_id  # The downstream service reads this from the forwarded token.
        self.calls.append(
            (
                "patch_event",
                event_id,
                status,
                safety_check_id,
                round_number,
                decided_by,
                remarks,
                areas,
            )
        )
        if "patch_event" in self.apply_despite_failure:
            self.event = self.updated
        self._maybe_fail("patch_event")
        return self.updated

    def reopen_safety_check_record(self, safety_check_id, decided_at):
        self.calls.append(("reopen", safety_check_id, decided_at))
        self._maybe_fail("reopen")

    def get_event_venue_bookings(self, event_id):
        self.calls.append(("get_bookings", event_id))
        self._maybe_fail("get_bookings")
        return self.bookings

    def cancel_venue_booking(self, booking_id, event_id):
        self.calls.append(("cancel_booking", booking_id, event_id))
        self._maybe_fail("cancel_booking")
        return {"id": booking_id, "status": "Cancelled"}

    def get_event_equipment_requests(self, event_id):
        coordinator_id = g.user_id  # The downstream service reads this from the forwarded token.
        self.calls.append(("get_equipment", event_id, coordinator_id))
        self._maybe_fail("get_equipment")
        return self.equipment

    def reset_equipment_safety_requests(self, event_id, request_ids):
        self.calls.append(("reset_equipment", event_id, request_ids))
        self._maybe_fail("reset_equipment")
        return []

    def reset_venue_safety_bookings(self, event_id, booking_ids):
        self.calls.append(("reset_bookings", event_id, booking_ids))
        self._maybe_fail("reset_bookings")
        return []

    def names(self):
        return [call[0] for call in self.calls]

    def call(self, name):
        return next(call for call in self.calls if call[0] == name)

    def call_count(self, name):
        return len([call for call in self.calls if call[0] == name])


@pytest.fixture
def downstream(monkeypatch):
    stub = Downstream()
    for name in (
        "get_user",
        "get_event",
        "list_safety_check_records",
        "decide_safety_check_record",
        "set_event_safety_status",
        "reopen_safety_check_record",
        "get_event_venue_bookings",
        "cancel_venue_booking",
        "get_event_equipment_requests",
        "reset_equipment_safety_requests",
        "reset_venue_safety_bookings",
    ):
        monkeypatch.setattr(f"app.clients.{name}", getattr(stub, name))
    return stub


@pytest.fixture
def client():
    return signed_in(create_app().test_client())


def request_changes(client, **overrides):
    body = {
        "eventId": EVENT_ID,
        "safetyOfficerId": OFFICER_ID,
        "reason": "Needs another look.",
        "flags": [{"area": "venue arrangement", "changeRequired": "Move the stage."}],
        **overrides,
    }
    return client.post("/safety-checks/request-changes", json=body)


def reject(client, **overrides):
    body = {
        "eventId": EVENT_ID,
        "safetyOfficerId": OFFICER_ID,
        "reason": "Unsafe egress plan.",
        "confirmed": True,
        **overrides,
    }
    return client.post("/safety-checks/reject", json=body)


# --- AC1, AC2, AC6: request changes happy path -------------------------------


def test_request_changes_decides_round_and_moves_event(client, downstream):
    """
    Summary: Requesting changes records the decision and moves the event to Safety Changes Requested.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    AC6: Given either decision, then the safety check is recorded with the
        status 'Changes Requested' or 'Safety Rejected' respectively, together
        with my identity, the timestamp and the reason (plus the selected areas
        for a change request), and the original event information is retained.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    response = request_changes(client)

    assert response.status_code == 200
    assert response.json["event"]["status"] == "Safety Changes Requested"
    assert response.json["safetyCheck"]["status"] == "Changes Requested"
    assert downstream.call("decide") == (
        "decide",
        RECORD_ID,
        "Changes Requested",
        OFFICER_ID,
        "Needs another look.",
        [{"area": "venue arrangement", "changeRequired": "Move the stage."}],
    )
    assert downstream.call("patch_event") == (
        "patch_event",
        EVENT_ID,
        "Safety Changes Requested",
        RECORD_ID,
        1,
        OFFICER_ID,
        "Needs another look.",
        ["venue arrangement"],
    )


def test_request_changes_with_several_areas_records_each(client, downstream):
    """
    Summary: Several areas can be flagged at once.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    response = request_changes(
        client,
        flags=[
            {"area": "venue arrangement", "changeRequired": "Move the stage."},
            {"area": "event details", "changeRequired": "Fix the start time."},
        ],
    )

    assert response.status_code == 200
    assert downstream.call("patch_event")[-1] == ["venue arrangement", "event details"]


def test_request_changes_on_technical_area_resets_approved_equipment(client, downstream):
    """
    Summary: Flagging the technical area sends the event's approved equipment back for review, after the decision is recorded and before the event moves.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests with
        status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The event has one approved equipment request [Stub]; we check the
        order in which the other services are asked [Mock].
    """
    response = request_changes(client, flags=[{"area": "technical arrangement", "changeRequired": "Move cables."}])

    assert response.status_code == 200
    assert downstream.call("reset_equipment") == ("reset_equipment", EVENT_ID, [REQUEST_ID])
    assert downstream.names().index("decide") < downstream.names().index("reset_equipment") < downstream.names().index("patch_event")


def test_request_changes_on_several_items_records_one_area(client, downstream):
    """
    Summary: Several flagged items are recorded under one technical area.
    AC6: Given either decision, then the safety check is recorded with the
        status 'Changes Requested' or 'Safety Rejected' respectively, together
        with my identity, the timestamp and the reason (plus the selected areas
        for a change request), and the original event information is retained.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.equipment.append(equipment_request("Approved", OTHER_BOOKING_ID))
    flags = [{"area": "technical arrangement", "equipmentRequestId": request_id, "changeRequired": "Move cables."}
        for request_id in [REQUEST_ID, OTHER_BOOKING_ID]]

    assert request_changes(client, flags=flags).status_code == 200
    assert set(downstream.call("reset_equipment")[-1]) == {REQUEST_ID, OTHER_BOOKING_ID}
    assert downstream.call("patch_event")[-1] == ["technical arrangement"]


def test_request_changes_cannot_reset_other_events_equipment(client, downstream):
    """
    Summary: A flag cannot reset another event's equipment.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    response = request_changes(client, flags=[{"area": "technical arrangement", "equipmentRequestId": OTHER_BOOKING_ID, "changeRequired": "Move cables."}])

    assert response.status_code == 400
    assert "decide" not in downstream.names()
    assert "reset_equipment" not in downstream.names()


@pytest.mark.parametrize("name", ["get_equipment", "reset_equipment"])
@pytest.mark.parametrize("error,code", [(clients.DownstreamError(), 502), (clients.DownstreamTimeout(), 504)], ids=["clients_downstreamerror_502", "clients_downstreamtimeout_504"])
def test_request_changes_when_equipment_reset_fails_never_reports_success(client, downstream, name, error, code):
    """
    Summary: If equipment cannot be reset, the change request is not reported as done.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail[name] = error

    assert request_changes(client, flags=[{"area": "technical arrangement", "changeRequired": "Move cables."}]).status_code == code
    assert "patch_event" not in downstream.names()
    assert ("reopen" in downstream.names()) == (name == "reset_equipment")


@pytest.mark.parametrize("area,reference", [("technical arrangement", "bad"), ("venue arrangement", REQUEST_ID)], ids=["technical_arrangement_bad", "venue_arrangement_request_id"])
def test_request_changes_with_bad_equipment_flag_returns_400(client, downstream, area, reference):
    """
    Summary: A flag on a bad equipment request, or the wrong area, is refused.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: None
    """
    assert request_changes(client, flags=[{"area": area, "equipmentRequestId": reference, "changeRequired": "Move."}]).status_code == 400
    assert downstream.calls == []


def test_request_changes_on_venue_reopens_booking_without_cancelling(client, downstream):
    """
    Summary: Flagging the venue sends the booking back to Venue Staff without cancelling it.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    request_changes(client)

    assert downstream.call("reset_bookings") == ("reset_bookings", EVENT_ID, [BOOKING_ID])
    assert "cancel_booking" not in downstream.names()


def test_request_changes_on_one_booking_leaves_others_approved(client, downstream):
    """
    Summary: Flagging one booking leaves the others approved.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.bookings.append(booking("Approved", OTHER_BOOKING_ID))

    assert request_changes(client, flags=[{"area": "venue arrangement", "bookingId": BOOKING_ID, "changeRequired": "Move stage."}]).status_code == 200
    assert downstream.call("reset_bookings")[-1] == [BOOKING_ID]


def test_request_changes_on_venue_ignores_closed_bookings(client, downstream):
    """
    Summary: Cancelled or rejected bookings are not reopened.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.bookings = [booking("Rejected")]

    assert request_changes(client).status_code == 200
    assert "reset_bookings" not in downstream.names()


def test_request_changes_on_other_events_booking_returns_400(client, downstream):
    """
    Summary: A flag cannot name another event's booking.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    assert request_changes(client, flags=[{"area": "venue arrangement", "bookingId": OTHER_BOOKING_ID, "changeRequired": "Move."}]).status_code == 400
    assert "decide" not in downstream.names()


@pytest.mark.parametrize("reference,area", [("bad", "venue arrangement"), (BOOKING_ID, "event details")], ids=["bad_venue_arrangement", "booking_id_event_details"])
def test_request_changes_with_bad_booking_reference_returns_400(client, downstream, reference, area):
    """
    Summary: A venue flag must point at a valid booking in the right area.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: None
    """
    assert request_changes(client, flags=[{"area": area, "bookingId": reference, "changeRequired": "Move."}]).status_code == 400


@pytest.mark.parametrize("name", ["get_bookings", "reset_bookings"])
@pytest.mark.parametrize("error,code", [(clients.DownstreamError(), 502), (clients.DownstreamTimeout(), 504)], ids=["clients_downstreamerror_502", "clients_downstreamtimeout_504"])
def test_request_changes_when_booking_reset_fails_never_reports_success(client, downstream, name, error, code):
    """
    Summary: If bookings cannot be reset, the change request is not reported as done.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail[name] = error

    assert request_changes(client).status_code == code
    assert "patch_event" not in downstream.names()


@pytest.mark.parametrize(
    "overrides",
    [
        {"flags": []},
        {"flags": [{"area": "not a real area", "changeRequired": "x"}]},
        {
            "flags": [
                {"area": "venue arrangement", "changeRequired": "x"},
                {"area": "venue arrangement", "changeRequired": "y"},
            ]
        },
        {"flags": [{"area": "venue arrangement", "changeRequired": ""}]},
        {"flags": [{"area": "venue arrangement", "changeRequired": "x" * 2001}]},
        {"flags": "not a list"},
        {"flags": ["not an object"]},
        {
            "flags": [
                {"area": "venue arrangement", "changeRequired": "a"},
                {"area": "technical arrangement", "changeRequired": "b"},
                {"area": "event details", "changeRequired": "c"},
                {"area": "venue arrangement", "changeRequired": "d"},
            ]
        },
        {"reason": None},
        {"reason": "   "},
    ],
    ids=["flags", "flags_area_not_a_real_area_changerequired_x", "flags_area_venue_arrangement_changerequired_x_ar", "flags_area_venue_arrangement_changerequired", "flags_area_venue_arrangement_changerequired_x_20", "flags_not_a_list", "flags_not_an_object", "flags_area_venue_arrangement_changerequired_a_ar", "reason_none", "reason"],
)
def test_request_changes_with_invalid_input_saves_nothing(overrides, client, downstream):
    """
    Summary: Nothing is saved while the change request is invalid.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: We check nothing is changed in any other service [Mock].
    """
    response = request_changes(client, **overrides)

    assert response.status_code == 400
    assert downstream.calls == []


# --- AC3, AC4, AC5, AC6: reject happy path -----------------------------------


def test_reject_decides_round_cancels_event_and_releases_bookings(client, downstream):
    """
    Summary: A rejection records the decision, cancels the event and releases its bookings.
    AC4: Given I confirm a rejection, then the event status changes to
        'Cancelled', and the event cannot be resubmitted for a safety check or
        moved to any further stage.
    AC5: Given an event is cancelled by a safety rejection, then its venue
        bookings and equipment reservations are released so they no longer
        block other events, while their records remain in the event's history.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.decided = record(status="Safety Rejected", decidedBy=OFFICER_ID)
    downstream.updated = event("Cancelled")
    downstream.bookings = [
        booking("Approved", booking_id=BOOKING_ID),
        booking("Pending Review", booking_id=OTHER_BOOKING_ID),
        booking("Cancelled", booking_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    ]

    response = reject(client)

    assert response.status_code == 200
    assert response.json["event"]["status"] == "Cancelled"
    assert response.json["safetyCheck"]["status"] == "Safety Rejected"
    assert sorted(response.json["release"]["venueBookingsReleased"]) == sorted(
        [BOOKING_ID, OTHER_BOOKING_ID]
    )
    assert response.json["release"]["venueBookingsNotReleased"] == []
    cancel_calls = [call for call in downstream.calls if call[0] == "cancel_booking"]
    assert {call[1] for call in cancel_calls} == {BOOKING_ID, OTHER_BOOKING_ID}
    assert downstream.call("decide")[1:5] == (
        RECORD_ID,
        "Safety Rejected",
        OFFICER_ID,
        "Unsafe egress plan.",
    )


def test_reject_skips_bookings_already_released(client, downstream):
    """
    Summary: Bookings that already block nothing are not released again.
    AC5: Given an event is cancelled by a safety rejection, then its venue
        bookings and equipment reservations are released so they no longer
        block other events, while their records remain in the event's history.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.updated = event("Cancelled")
    downstream.bookings = [
        booking("Rejected", booking_id=BOOKING_ID),
        booking("Expired", booking_id=OTHER_BOOKING_ID),
    ]

    reject(client)

    assert "cancel_booking" not in downstream.names()


def test_reject_without_confirmation_saves_nothing(client, downstream):
    """
    Summary: A rejection must be confirmed before it is saved.
    AC3: Given an event is 'Pending Safety Check', when I reject it, then a
        reason is required and I must confirm the rejection before it is saved.
    Double: We check nothing is changed in any other service [Mock].
    """
    response = reject(client, confirmed=False)

    assert response.status_code == 400
    assert response.json["code"] == "REJECTION_NOT_CONFIRMED"
    assert downstream.calls == []


def test_reject_missing_confirmation_saves_nothing(client, downstream):
    """
    Summary: A rejection without the confirmation field saves nothing.
    AC3: Given an event is 'Pending Safety Check', when I reject it, then a
        reason is required and I must confirm the rejection before it is saved.
    Double: We check nothing is changed in any other service [Mock].
    """
    response = reject(client, confirmed=None)

    assert response.status_code == 400
    assert response.json["code"] == "REJECTION_NOT_CONFIRMED"
    assert downstream.calls == []


@pytest.mark.parametrize("reason", [None, "   "])
def test_reject_without_reason_returns_400(reason, client, downstream):
    """
    Summary: A rejection needs a reason.
    AC3: Given an event is 'Pending Safety Check', when I reject it, then a
        reason is required and I must confirm the rejection before it is saved.
    Double: None
    """
    response = reject(client, reason=reason)

    assert response.status_code == 400
    assert downstream.calls == []


def test_reject_continues_releasing_after_one_cancel_fails(client, downstream):
    """
    Summary: The decision stands and other bookings are released even if one cannot be.
    AC5: Given an event is cancelled by a safety rejection, then its venue
        bookings and equipment reservations are released so they no longer
        block other events, while their records remain in the event's history.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.updated = event("Cancelled")
    downstream.bookings = [
        booking("Approved", booking_id=BOOKING_ID),
        booking("Approved", booking_id=OTHER_BOOKING_ID),
    ]
    downstream.fail["cancel_booking"] = clients.DownstreamError

    response = reject(client)

    assert response.status_code == 200
    assert response.json["release"]["venueBookingsNotReleased"] != []


def test_reject_when_booking_list_fails_still_records_decision(client, downstream, caplog):
    """
    Summary: The rejection stands even if the bookings cannot be listed.
    AC5: Given an event is cancelled by a safety rejection, then its venue
        bookings and equipment reservations are released so they no longer
        block other events, while their records remain in the event's history.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.updated = event("Cancelled")
    downstream.fail["get_bookings"] = clients.DownstreamError

    with caplog.at_level(logging.ERROR):
        response = reject(client)

    assert response.status_code == 200
    assert response.json["release"]["venueBookingsReleased"] == []
    assert any(EVENT_ID in message for message in caplog.messages)


def test_reject_when_decision_fails_releases_nothing(client, downstream):
    """
    Summary: If the decision fails, no booking is released.
    AC5: Given an event is cancelled by a safety rejection, then its venue
        bookings and equipment reservations are released so they no longer
        block other events, while their records remain in the event's history.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["decide"] = clients.DownstreamError

    response = reject(client)

    assert response.status_code == 502
    assert "get_bookings" not in downstream.names()
    assert "cancel_booking" not in downstream.names()


def test_reject_when_event_move_fails_releases_nothing(client, downstream):
    """
    Summary: If the event move fails, no booking is released.
    AC5: Given an event is cancelled by a safety rejection, then its venue
        bookings and equipment reservations are released so they no longer
        block other events, while their records remain in the event's history.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["patch_event"] = clients.EventNotFoundError

    response = reject(client)

    assert response.status_code == 404
    assert "get_bookings" not in downstream.names()
    assert "cancel_booking" not in downstream.names()


# --- AC7: only 'Pending Safety Check' may be decided, and only once ---------


@pytest.mark.parametrize(
    "status",
    [
        "Submitted",
        "Under Review",
        "Approved",
        "Rejected",
        "Confirmed",
        "Safety Changes Requested",
        "Cancelled",
    ],
)
def test_request_changes_for_event_not_pending_returns_409(status, client, downstream):
    """
    Summary: Changes can only be requested for an event awaiting a safety check.
    AC7: Given an event is not 'Pending Safety Check', then these actions are
        not available and an API call is rejected without changing the event.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.event = event(status)

    response = request_changes(client)

    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_PENDING_SAFETY_CHECK"
    assert "decide" not in downstream.names()


@pytest.mark.parametrize(
    "status",
    [
        "Submitted",
        "Under Review",
        "Approved",
        "Rejected",
        "Confirmed",
        "Safety Changes Requested",
        "Cancelled",
    ],
)
def test_reject_event_not_pending_returns_409(status, client, downstream):
    """
    Summary: Only an event awaiting a safety check can be rejected.
    AC7: Given an event is not 'Pending Safety Check', then these actions are
        not available and an API call is rejected without changing the event.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.event = event(status)

    response = reject(client)

    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_PENDING_SAFETY_CHECK"
    assert "decide" not in downstream.names()


def test_request_changes_when_not_safety_officer_returns_403(client, downstream):
    """
    Summary: Only a Safety Officer can request changes.
    AC7: Given an event is not 'Pending Safety Check', then these actions are
        not available and an API call is rejected without changing the event.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.user = user(role="Event Coordinator")

    response = request_changes(client)

    assert response.status_code == 403
    assert response.json["code"] == "NOT_SAFETY_OFFICER"


def test_reject_when_not_safety_officer_returns_403(client, downstream):
    """
    Summary: Only a Safety Officer can reject.
    AC7: Given an event is not 'Pending Safety Check', then these actions are
        not available and an API call is rejected without changing the event.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.user = user(role="Event Coordinator")

    response = reject(client)

    assert response.status_code == 403
    assert response.json["code"] == "NOT_SAFETY_OFFICER"


def test_request_changes_without_open_round_returns_409(client, downstream):
    """
    Summary: With no open round there is nothing to decide.
    AC7: Given an event is not 'Pending Safety Check', then these actions are
        not available and an API call is rejected without changing the event.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.rounds = []

    response = request_changes(client)

    assert response.status_code == 409
    assert response.json["code"] == "NO_OPEN_SAFETY_CHECK"


def test_reject_decided_round_returns_409(client, downstream):
    """
    Summary: A round already decided cannot be rejected.
    AC7: Given an event is not 'Pending Safety Check', then these actions are
        not available and an API call is rejected without changing the event.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["decide"] = clients.SafetyCheckAlreadyDecidedError(
        record(status="Safety Rejected")
    )

    response = reject(client)

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_DECIDED"


# --- Compensation: the event move fails, so the decision is undone ----------


def test_request_changes_when_event_move_conflicts_reopens_round(client, downstream):
    """
    Summary: If the event move is refused, the decision is undone.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["patch_event"] = clients.EventTransitionError(
        "STALE_SAFETY_CHECK", {"message": "stale", "currentStatus": "Pending Safety Check"}
    )

    response = request_changes(client)

    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_PENDING_SAFETY_CHECK"
    assert downstream.call("reopen") == (
        "reopen",
        RECORD_ID,
        downstream.decided["decidedAt"],
    )


def test_reject_when_event_move_conflicts_reopens_round(client, downstream):
    """
    Summary: If the event move is refused, the rejection is undone.
    AC4: Given I confirm a rejection, then the event status changes to
        'Cancelled', and the event cannot be resubmitted for a safety check or
        moved to any further stage.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["patch_event"] = clients.EventTransitionError(
        "STALE_SAFETY_CHECK", {"message": "stale", "currentStatus": "Pending Safety Check"}
    )

    response = reject(client)

    assert response.status_code == 409
    assert downstream.names()[-1] == "reopen"


def test_reject_when_move_refused_without_message_reads_sensibly(client, downstream):
    """
    Summary: A refused rejection with no message still gives a readable error.
    AC4: Given I confirm a rejection, then the event status changes to
        'Cancelled', and the event cannot be resubmitted for a safety check or
        moved to any further stage.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["patch_event"] = clients.EventTransitionError(None, {})

    response = reject(client)

    assert response.status_code == 409
    assert response.json["message"] == (
        "Only an event 'Pending Safety Check' can be rejected."
    )


def test_request_changes_when_move_refused_without_message_reads_sensibly(client, downstream):
    """
    Summary: A refused change request with no message still gives a readable error.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["patch_event"] = clients.EventTransitionError(None, {})

    response = request_changes(client)

    assert response.status_code == 409
    assert response.json["message"] == (
        "Only an event 'Pending Safety Check' can have changes requested."
    )


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_request_changes_when_event_move_fails_reopens_round(error, status, client, downstream):
    """
    Summary: If the event move fails, the decision is undone.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["patch_event"] = error

    response = request_changes(client)

    assert response.status_code == status
    assert downstream.names()[-1] == "reopen"


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_reject_when_event_move_fails_reopens_round(error, status, client, downstream):
    """
    Summary: If the event move fails, the rejection is undone.
    AC4: Given I confirm a rejection, then the event status changes to
        'Cancelled', and the event cannot be resubmitted for a safety check or
        moved to any further stage.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["patch_event"] = error

    response = reject(client)

    assert response.status_code == status
    assert downstream.names()[-1] == "reopen"


def test_reject_when_move_response_lost_but_saved_succeeds(client, downstream):
    """
    Summary: A lost answer from a move that did save does not undo the rejection.
    AC4: Given I confirm a rejection, then the event status changes to
        'Cancelled', and the event cannot be resubmitted for a safety check or
        moved to any further stage.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.updated = event("Cancelled")
    downstream.fail["patch_event"] = clients.DownstreamError
    downstream.apply_despite_failure.add("patch_event")

    response = reject(client)

    assert response.status_code == 200
    assert response.json["event"]["status"] == "Cancelled"
    assert "reopen" not in downstream.names()


def test_request_changes_when_decision_response_lost_but_saved_continues(client, downstream):
    """
    Summary: A lost answer from a decision that did save is reconciled and the request continues.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.decided = record(status="Changes Requested", decidedBy=OFFICER_ID)
    downstream.fail["decide"] = clients.DownstreamError
    downstream.apply_despite_failure.add("decide")

    response = request_changes(client)

    assert response.status_code == 200
    assert response.json["safetyCheck"]["status"] == "Changes Requested"


def test_decision_when_service_token_refused_reopens_round(client, downstream):
    """
    Summary: If Event Service refuses this service's credentials, the decision is undone.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["patch_event"] = clients.ServiceCredentialsError

    response = reject(client)

    assert response.status_code == 502
    assert response.json["message"] == "Event Service refused this service's credentials."
    assert downstream.names()[-1] == "reopen"


def test_decision_when_event_refuses_unexpectedly_reopens_round(client, downstream):
    """
    Summary: Any other refusal of the move undoes the decision.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["patch_event"] = clients.EventNotAssignedError

    response = reject(client)

    assert response.status_code == 502
    assert response.json["message"] == "Unable to reject this safety check right now."


# --- Input validation ---------------------------------------------------------


def test_request_changes_with_non_object_body_returns_400(client, downstream):
    """
    Summary: A change request that is not in the expected form is refused.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: None
    """
    response = client.post("/safety-checks/request-changes", json=["not", "an", "object"])

    assert response.status_code == 400
    assert downstream.calls == []


def test_reject_with_non_object_body_returns_400(client, downstream):
    """
    Summary: A rejection that is not in the expected form is refused.
    AC3: Given an event is 'Pending Safety Check', when I reject it, then a
        reason is required and I must confirm the rejection before it is saved.
    Double: None
    """
    response = client.post("/safety-checks/reject", json=["not", "an", "object"])

    assert response.status_code == 400
    assert downstream.calls == []


@pytest.mark.parametrize(
    "body",
    [
        {"eventId": "not-a-uuid", "safetyOfficerId": OFFICER_ID},
        {"eventId": EVENT_ID, "safetyOfficerId": "nope"},
    ],
    ids=["eventid_not_a_uuid_safetyofficerid_officer_id", "eventid_event_id_safetyofficerid_nope"],
)
def test_request_changes_with_bad_ids_returns_400(body, client, downstream):
    """
    Summary: A change request must name a real event.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: None
    """
    response = client.post("/safety-checks/request-changes", json=body)

    assert response.status_code == 400
    assert downstream.calls == []


@pytest.mark.parametrize(
    "body",
    [
        {"eventId": "not-a-uuid", "safetyOfficerId": OFFICER_ID},
        {"eventId": EVENT_ID, "safetyOfficerId": "nope"},
    ],
    ids=["eventid_not_a_uuid_safetyofficerid_officer_id", "eventid_event_id_safetyofficerid_nope"],
)
def test_reject_with_bad_ids_returns_400(body, client, downstream):
    """
    Summary: A rejection must name a real event.
    AC3: Given an event is 'Pending Safety Check', when I reject it, then a
        reason is required and I must confirm the rejection before it is saved.
    Double: None
    """
    response = client.post("/safety-checks/reject", json=body)

    assert response.status_code == 400
    assert downstream.calls == []


def test_decision_with_reason_over_limit_returns_400(client, downstream):
    """
    Summary: A reason over the limit is refused.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: None
    """
    response = request_changes(client, reason="x" * 2001)

    assert response.status_code == 400
    assert downstream.calls == []


def test_reset_equipment_client_sends_scoped_ids_with_internal_auth(sent, monkeypatch):
    """
    Summary: Equipment resets name only the flagged requests and use internal credentials.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    calls, queue = sent
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", "test-token")
    queue.append(Response(200, {"requests": [equipment_request("Pending")]}))
    assert clients.reset_equipment_safety_requests(EVENT_ID, ["request-id"])[0]["status"] == "Pending"
    assert calls[0]["url"].endswith(f"/events/{EVENT_ID}/equipment-requests/safety-reset")
    assert calls[0]["json"] == {"requestIds": ["request-id"]}
    assert calls[0]["headers"] == {"X-Internal-Token": "test-token"}


def test_reset_venue_client_uses_owner_with_internal_auth(sent, monkeypatch):
    """
    Summary: Venue resets go to Venue Availability with internal credentials.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    calls, queue = sent
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", "test-token")
    queue.append(Response(200, {"bookings": []}))
    assert clients.reset_venue_safety_bookings(EVENT_ID, [BOOKING_ID]) == []
    assert calls[0]["url"].endswith(f"/events/{EVENT_ID}/venue-bookings/safety-reset")
    assert calls[0]["json"] == {"bookingIds": [BOOKING_ID]}
    assert calls[0]["headers"] == {"X-Internal-Token": "test-token"}


def test_set_safety_status_client_sends_areas_for_changes(sent):
    """
    Summary: A change request's areas travel with the move.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    calls, queue = sent
    queue.append(Response(200, event("Safety Changes Requested")))

    clients.set_event_safety_status(
        EVENT_ID,
        "Safety Changes Requested",
        RECORD_ID,
        1,
        remarks="Needs another look.",
        areas=["venue arrangement"],
    )

    assert calls[0]["json"] == {
        "status": "Safety Changes Requested",
        "safetyCheckId": RECORD_ID,
        "roundNumber": 1,
        "remarks": "Needs another look.",
        "areas": ["venue arrangement"],
    }


def test_set_safety_status_client_omits_absent_areas(sent):
    """
    Summary: No areas are sent when there are none.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    calls, queue = sent
    queue.append(Response(200, event("Cancelled")))

    clients.set_event_safety_status(
        EVENT_ID, "Cancelled", RECORD_ID, 1, remarks="Unsafe."
    )

    assert "areas" not in calls[0]["json"]


def test_cancel_booking_client_sends_event_id(sent):
    """
    Summary: Releasing a booking on rejection names the event.
    AC5: Given an event is cancelled by a safety rejection, then its venue
        bookings and equipment reservations are released so they no longer
        block other events, while their records remain in the event's history.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    calls, queue = sent
    queue.append(Response(200, booking("Cancelled")))

    cancelled = clients.cancel_venue_booking(BOOKING_ID, EVENT_ID)

    assert cancelled["status"] == "Cancelled"
    assert calls[0]["method"] == "PATCH"
    assert calls[0]["url"].endswith(f"/venue-bookings/{BOOKING_ID}/cancel")
    assert calls[0]["json"] == {"eventId": EVENT_ID}


def test_cancel_booking_client_missing_is_not_found(sent):
    """
    Summary: Releasing a missing booking is reported as not found.
    AC5: Given an event is cancelled by a safety rejection, then its venue
        bookings and equipment reservations are released so they no longer
        block other events, while their records remain in the event's history.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    _, queue = sent
    queue.append(Response(404, {"message": "no"}))

    with pytest.raises(clients.RecordNotFoundError):
        clients.cancel_venue_booking(BOOKING_ID, EVENT_ID)


def test_cancel_booking_client_failure_is_downstream_error(sent):
    """
    Summary: If a booking cannot be released, it is reported as a failure of that service.
    AC5: Given an event is cancelled by a safety rejection, then its venue
        bookings and equipment reservations are released so they no longer
        block other events, while their records remain in the event's history.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    _, queue = sent
    queue.append(Response(503, {"message": "down"}))

    with pytest.raises(clients.DownstreamError):
        clients.cancel_venue_booking(BOOKING_ID, EVENT_ID)


def test_decide_record_client_sends_flags(sent):
    """
    Summary: A change request's flags travel with the decision.
    AC6: Given either decision, then the safety check is recorded with the
        status 'Changes Requested' or 'Safety Rejected' respectively, together
        with my identity, the timestamp and the reason (plus the selected areas
        for a change request), and the original event information is retained.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    calls, queue = sent
    queue.append(Response(200, record(status="Changes Requested")))

    flags = [{"area": "venue arrangement", "changeRequired": "Move the stage."}]
    clients.decide_safety_check_record(
        RECORD_ID, "Changes Requested", "Needs another look.", flags
    )

    assert calls[0]["json"] == {
        "status": "Changes Requested",
        "remarks": "Needs another look.",
        "flags": flags,
    }


def test_decide_record_client_omits_absent_flags(sent):
    """
    Summary: No flags are sent when there are none.
    AC6: Given either decision, then the safety check is recorded with the
        status 'Changes Requested' or 'Safety Rejected' respectively, together
        with my identity, the timestamp and the reason (plus the selected areas
        for a change request), and the original event information is retained.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    calls, queue = sent
    queue.append(Response(200, record(status="Safety Approved")))

    clients.decide_safety_check_record(RECORD_ID, "Safety Approved", "Looks safe.")

    assert "flags" not in calls[0]["json"]
