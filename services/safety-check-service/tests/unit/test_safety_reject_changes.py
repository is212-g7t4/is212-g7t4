"""SCRUM-151: POST /safety-checks/request-changes and POST /safety-checks/reject.

AC1 ... when I request changes, then I must select at least one affected
    area and describe the change needed; otherwise the decision is not saved.
AC2 ... then the event status changes to 'Safety Changes Requested' ...
    and its existing arrangements are preserved.
AC3 ... when I reject it, then a reason is required and I must confirm the
    rejection before it is saved.
AC4 ... then the event status changes to 'Cancelled', and the event cannot
    be resubmitted for a safety check or moved to any further stage.
AC5 ... then its venue bookings and equipment reservations are released ...
AC6 ... the safety check is recorded with the status 'Changes Requested' or
    'Safety Rejected' ..., together with identity, timestamp and reason
    (plus the selected areas for a change request).
AC7 ... these actions are not available and an API call is rejected without
    changing the event.

Every downstream call is a monkeypatched `app.clients` wrapper, so these
tests exercise the orchestration and the error mapping, not HTTP
(`test_clients.py` covers that).
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


def test_request_changes_decides_the_round_and_moves_the_event(client, downstream):
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


def test_request_changes_with_multiple_areas(client, downstream):
    response = request_changes(
        client,
        flags=[
            {"area": "venue arrangement", "changeRequired": "Move the stage."},
            {"area": "event details", "changeRequired": "Fix the start time."},
        ],
    )

    assert response.status_code == 200
    assert downstream.call("patch_event")[-1] == ["venue arrangement", "event details"]


# Safety revision AC3: a technical-area flag sends equipment back for staff review before the event moves.
def test_technical_area_flag_returns_all_event_equipment_to_staff_review(client, downstream):
    response = request_changes(client, flags=[{"area": "technical arrangement", "changeRequired": "Move cables."}])
    assert response.status_code == 200
    assert downstream.call("reset_equipment") == ("reset_equipment", EVENT_ID, [REQUEST_ID])
    assert downstream.names().index("decide") < downstream.names().index("reset_equipment") < downstream.names().index("patch_event")


# Safety revision AC3/AC4 (orchestration): reset only the flagged request ID; database preservation is not exercised here.
def test_targeted_equipment_flag_leaves_unflagged_requests_confirmed(client, downstream):
    downstream.equipment.append(equipment_request("Approved", OTHER_BOOKING_ID))
    response = request_changes(client, flags=[{"area": "technical arrangement", "equipmentRequestId": REQUEST_ID, "changeRequired": "Move cables."}])
    assert response.status_code == 200
    assert downstream.call("reset_equipment")[-1] == [REQUEST_ID]
    assert downstream.call("decide")[-1][0]["equipmentRequestId"] == REQUEST_ID


def test_multiple_targeted_equipment_flags_share_one_history_area(client, downstream):
    downstream.equipment.append(equipment_request("Approved", OTHER_BOOKING_ID))
    flags = [{"area": "technical arrangement", "equipmentRequestId": request_id, "changeRequired": "Move cables."}
        for request_id in [REQUEST_ID, OTHER_BOOKING_ID]]
    assert request_changes(client, flags=flags).status_code == 200
    assert set(downstream.call("reset_equipment")[-1]) == {REQUEST_ID, OTHER_BOOKING_ID}
    assert downstream.call("patch_event")[-1] == ["technical arrangement"]


def test_targeted_flag_cannot_reset_another_events_equipment(client, downstream):
    response = request_changes(client, flags=[{"area": "technical arrangement", "equipmentRequestId": OTHER_BOOKING_ID, "changeRequired": "Move cables."}])
    assert response.status_code == 400
    assert "decide" not in downstream.names()
    assert "reset_equipment" not in downstream.names()


def test_technical_area_without_equipment_needs_no_reset(client, downstream):
    downstream.equipment = []
    assert request_changes(client, flags=[{"area": "technical arrangement", "changeRequired": "Update notes."}]).status_code == 200
    assert "reset_equipment" not in downstream.names()


@pytest.mark.parametrize("name", ["get_equipment", "reset_equipment"])
@pytest.mark.parametrize("error,code", [(clients.DownstreamError(), 502), (clients.DownstreamTimeout(), 504)])
def test_equipment_reset_failure_never_reports_success(client, downstream, name, error, code):
    downstream.fail[name] = error
    assert request_changes(client, flags=[{"area": "technical arrangement", "changeRequired": "Move cables."}]).status_code == code
    assert "patch_event" not in downstream.names()
    assert ("reopen" in downstream.names()) == (name == "reset_equipment")


@pytest.mark.parametrize("area,reference", [("technical arrangement", "bad"), ("venue arrangement", REQUEST_ID)])
def test_invalid_targeted_equipment_flags_are_rejected(client, downstream, area, reference):
    assert request_changes(client, flags=[{"area": area, "equipmentRequestId": reference, "changeRequired": "Move."}]).status_code == 400
    assert downstream.calls == []


# Safety revision AC2: flagging a venue reopens its booking for staff review rather than cancelling it.
def test_venue_flag_reopens_booking_without_cancelling_it(client, downstream):
    request_changes(client)

    assert downstream.call("reset_bookings") == ("reset_bookings", EVENT_ID, [BOOKING_ID])
    assert "cancel_booking" not in downstream.names()


# Safety revision AC2/AC4 (orchestration): only the affected booking ID is sent for reset, not its approved sibling.
def test_targeted_venue_flag_leaves_unaffected_booking_approved(client, downstream):
    downstream.bookings.append(booking("Approved", OTHER_BOOKING_ID))
    assert request_changes(client, flags=[{"area": "venue arrangement", "bookingId": BOOKING_ID, "changeRequired": "Move stage."}]).status_code == 200
    assert downstream.call("reset_bookings")[-1] == [BOOKING_ID]


def test_venue_flag_ignores_terminal_history(client, downstream):
    downstream.bookings = [booking("Rejected")]
    assert request_changes(client).status_code == 200
    assert "reset_bookings" not in downstream.names()


def test_venue_flag_rejects_foreign_booking(client, downstream):
    assert request_changes(client, flags=[{"area": "venue arrangement", "bookingId": OTHER_BOOKING_ID, "changeRequired": "Move."}]).status_code == 400
    assert "decide" not in downstream.names()


@pytest.mark.parametrize("reference,area", [("bad", "venue arrangement"), (BOOKING_ID, "event details")])
def test_venue_flag_validates_reference(client, downstream, reference, area):
    assert request_changes(client, flags=[{"area": area, "bookingId": reference, "changeRequired": "Move."}]).status_code == 400


# Safety revision AC2 (failure): failed venue re-review setup must not advance the event.
@pytest.mark.parametrize("name", ["get_bookings", "reset_bookings"])
@pytest.mark.parametrize("error,code", [(clients.DownstreamError(), 502), (clients.DownstreamTimeout(), 504)])
def test_venue_reset_failure_prevents_success(client, downstream, name, error, code):
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
)
def test_request_changes_validation_failures_write_nothing(overrides, client, downstream):
    """AC1: nothing is saved while the request is invalid."""
    response = request_changes(client, **overrides)

    assert response.status_code == 400
    assert downstream.calls == []


# --- AC3, AC4, AC5, AC6: reject happy path -----------------------------------


def test_reject_decides_the_round_moves_the_event_and_releases_bookings(client, downstream):
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


def test_reject_skips_bookings_that_already_block_nothing(client, downstream):
    downstream.updated = event("Cancelled")
    downstream.bookings = [
        booking("Rejected", booking_id=BOOKING_ID),
        booking("Expired", booking_id=OTHER_BOOKING_ID),
    ]

    reject(client)

    assert "cancel_booking" not in downstream.names()


def test_reject_without_confirmed_true_saves_nothing(client, downstream):
    response = reject(client, confirmed=False)

    assert response.status_code == 400
    assert response.json["code"] == "REJECTION_NOT_CONFIRMED"
    assert downstream.calls == []


def test_reject_without_confirmed_field_saves_nothing(client, downstream):
    response = reject(client, confirmed=None)

    assert response.status_code == 400
    assert response.json["code"] == "REJECTION_NOT_CONFIRMED"
    assert downstream.calls == []


@pytest.mark.parametrize("reason", [None, "   "])
def test_reject_requires_a_reason(reason, client, downstream):
    response = reject(client, reason=reason)

    assert response.status_code == 400
    assert downstream.calls == []


def test_reject_release_continues_past_a_failed_cancel(client, downstream):
    """AC5: the decision stands even if a booking can't be released."""
    downstream.updated = event("Cancelled")
    downstream.bookings = [
        booking("Approved", booking_id=BOOKING_ID),
        booking("Approved", booking_id=OTHER_BOOKING_ID),
    ]
    downstream.fail["cancel_booking"] = clients.DownstreamError

    response = reject(client)

    assert response.status_code == 200
    assert response.json["release"]["venueBookingsNotReleased"] != []


def test_reject_release_tolerates_a_listing_failure(client, downstream, caplog):
    downstream.updated = event("Cancelled")
    downstream.fail["get_bookings"] = clients.DownstreamError

    with caplog.at_level(logging.ERROR):
        response = reject(client)

    assert response.status_code == 200
    assert response.json["release"]["venueBookingsReleased"] == []
    assert any(EVENT_ID in message for message in caplog.messages)


def test_reject_never_releases_bookings_when_the_decision_fails(client, downstream):
    downstream.fail["decide"] = clients.DownstreamError

    response = reject(client)

    assert response.status_code == 502
    assert "get_bookings" not in downstream.names()
    assert "cancel_booking" not in downstream.names()


def test_reject_never_releases_bookings_when_the_event_move_fails(client, downstream):
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
def test_request_changes_requires_pending_safety_check(status, client, downstream):
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
def test_reject_requires_pending_safety_check(status, client, downstream):
    downstream.event = event(status)

    response = reject(client)

    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_PENDING_SAFETY_CHECK"
    assert "decide" not in downstream.names()


def test_request_changes_caller_must_be_a_safety_officer(client, downstream):
    downstream.user = user(role="Event Coordinator")

    response = request_changes(client)

    assert response.status_code == 403
    assert response.json["code"] == "NOT_SAFETY_OFFICER"


def test_reject_caller_must_be_a_safety_officer(client, downstream):
    downstream.user = user(role="Event Coordinator")

    response = reject(client)

    assert response.status_code == 403
    assert response.json["code"] == "NOT_SAFETY_OFFICER"


def test_request_changes_no_open_round_is_refused(client, downstream):
    downstream.rounds = []

    response = request_changes(client)

    assert response.status_code == 409
    assert response.json["code"] == "NO_OPEN_SAFETY_CHECK"


def test_reject_already_decided_round_is_refused(client, downstream):
    downstream.fail["decide"] = clients.SafetyCheckAlreadyDecidedError(
        record(status="Safety Rejected")
    )

    response = reject(client)

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_DECIDED"


# --- Compensation: the event move fails, so the decision is undone ----------


def test_request_changes_event_conflict_rolls_the_decision_back(client, downstream):
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


def test_reject_event_conflict_rolls_the_decision_back(client, downstream):
    downstream.fail["patch_event"] = clients.EventTransitionError(
        "STALE_SAFETY_CHECK", {"message": "stale", "currentStatus": "Pending Safety Check"}
    )

    response = reject(client)

    assert response.status_code == 409
    assert downstream.names()[-1] == "reopen"


def test_reject_event_transition_error_without_a_message_reads_sensibly(client, downstream):
    downstream.fail["patch_event"] = clients.EventTransitionError(None, {})

    response = reject(client)

    assert response.status_code == 409
    assert response.json["message"] == (
        "Only an event 'Pending Safety Check' can be rejected."
    )


def test_request_changes_transition_error_without_a_message_reads_sensibly(client, downstream):
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
def test_request_changes_event_update_downstream_failure_rolls_back(error, status, client, downstream):
    downstream.fail["patch_event"] = error

    response = request_changes(client)

    assert response.status_code == status
    assert downstream.names()[-1] == "reopen"


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_reject_event_update_downstream_failure_rolls_back(error, status, client, downstream):
    downstream.fail["patch_event"] = error

    response = reject(client)

    assert response.status_code == status
    assert downstream.names()[-1] == "reopen"


def test_reject_response_lost_but_it_actually_succeeded(client, downstream):
    """A lost response on the event-move call must not undo a decision that
    already went through end to end."""
    downstream.updated = event("Cancelled")
    downstream.fail["patch_event"] = clients.DownstreamError
    downstream.apply_despite_failure.add("patch_event")

    response = reject(client)

    assert response.status_code == 200
    assert response.json["event"]["status"] == "Cancelled"
    assert "reopen" not in downstream.names()


def test_decide_response_lost_but_it_actually_succeeded(client, downstream):
    """Same reconciliation one step earlier: the decide call's response is
    lost but the record service actually decided the round."""
    downstream.decided = record(status="Changes Requested", decidedBy=OFFICER_ID)
    downstream.fail["decide"] = clients.DownstreamError
    downstream.apply_despite_failure.add("decide")

    response = request_changes(client)

    assert response.status_code == 200
    assert response.json["safetyCheck"]["status"] == "Changes Requested"


def test_service_credentials_error_rolls_the_decision_back(client, downstream):
    downstream.fail["patch_event"] = clients.ServiceCredentialsError

    response = reject(client)

    assert response.status_code == 502
    assert response.json["message"] == "Event Service refused this service's credentials."
    assert downstream.names()[-1] == "reopen"


def test_unexpected_event_refusal_rolls_the_decision_back(client, downstream):
    downstream.fail["patch_event"] = clients.EventNotAssignedError

    response = reject(client)

    assert response.status_code == 502
    assert response.json["message"] == "Unable to reject this safety check right now."


# --- Input validation ---------------------------------------------------------


def test_request_changes_non_object_body_is_rejected(client, downstream):
    response = client.post("/safety-checks/request-changes", json=["not", "an", "object"])

    assert response.status_code == 400
    assert downstream.calls == []


def test_reject_non_object_body_is_rejected(client, downstream):
    response = client.post("/safety-checks/reject", json=["not", "an", "object"])

    assert response.status_code == 400
    assert downstream.calls == []


@pytest.mark.parametrize(
    "body",
    [
        {"eventId": "not-a-uuid", "safetyOfficerId": OFFICER_ID},
        {"eventId": EVENT_ID, "safetyOfficerId": "nope"},
    ],
)
def test_request_changes_bad_identifiers_are_rejected(body, client, downstream):
    response = client.post("/safety-checks/request-changes", json=body)

    assert response.status_code == 400
    assert downstream.calls == []


@pytest.mark.parametrize(
    "body",
    [
        {"eventId": "not-a-uuid", "safetyOfficerId": OFFICER_ID},
        {"eventId": EVENT_ID, "safetyOfficerId": "nope"},
    ],
)
def test_reject_bad_identifiers_are_rejected(body, client, downstream):
    response = client.post("/safety-checks/reject", json=body)

    assert response.status_code == 400
    assert downstream.calls == []


def test_reason_over_the_limit_is_rejected(client, downstream):
    response = request_changes(client, reason="x" * 2001)

    assert response.status_code == 400
    assert downstream.calls == []
