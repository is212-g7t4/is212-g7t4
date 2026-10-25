"""SCRUM-28 Part B: editing or cancelling a venue booking is gated by the event's status.

Decided by Clarice on 25 Oct:

| Event status                                                 | Edit / cancel a booking |
| Submitted, Under Review, Approved, Safety Changes Requested  | allowed, as before       |
| Confirmed                                                    | allowed, but the safety approval is withdrawn first (event -> Approved) |
| Pending Safety Check, Clarification Requested, Rejected, Cancelled | 409 EVENT_NOT_ACCEPTING_VENUE_CHANGES |

For a Confirmed event this composite asks Safety Check Service to withdraw the
approval **before** touching the booking, and asks it to restore the approval
if the booking change then fails. Every downstream call is patched where
app.routes looks it up.
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
    return create_app().test_client()


# --- The gate -----------------------------------------------------------------


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("status", OPEN_STATUSES)
def test_open_statuses_change_the_booking_without_any_safety_call(client, monkeypatch, action, status):
    """Normal: before the safety check starts, changes work exactly as before."""
    calls = Calls(monkeypatch, status)
    send, booking_call = ACTIONS[action]

    response = send(client)

    assert response.status_code == 200
    assert booking_call in calls.names()
    assert "withdraw_safety_for_venue_change" not in calls.names()


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("status", CLOSED_STATUSES)
def test_closed_statuses_refuse_the_change_before_any_other_call(client, monkeypatch, action, status):
    """Conflict: while the safety check is pending or the event is closed, nothing changes."""
    calls = Calls(monkeypatch, status)
    send, _ = ACTIONS[action]

    response = send(client)

    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_ACCEPTING_VENUE_CHANGES"
    assert response.json["eventStatus"] == status
    assert calls.names() == ["get_event"]


def test_changeable_statuses_are_the_submittable_four_plus_confirmed():
    """Normal: the gate matches the table agreed on 25 Oct."""
    assert CHANGEABLE_EVENT_STATUSES == (
        "Submitted", "Under Review", "Approved", "Safety Changes Requested", "Confirmed",
    )


# --- Confirmed: withdraw first, then change -----------------------------------


def test_confirmed_edit_withdraws_the_approval_before_updating_the_booking(client, monkeypatch):
    """Normal: Event -> Venue -> Safety Check withdraw -> Venue Availability update."""
    calls = Calls(monkeypatch, "Confirmed")

    response = edit(client)

    assert response.status_code == 200
    assert calls.names() == ["get_event", "get_venues", "withdraw_safety_for_venue_change", "update_booking"]
    assert calls.args("withdraw_safety_for_venue_change") == (
        EVENT_ID, "coord-1", BOOKING_ID,
        "A venue booking (Grand Ballroom) was edited after safety approval.",
    )


def test_confirmed_cancel_withdraws_the_approval_before_cancelling(client, monkeypatch):
    """Normal: removing a venue also changes the arrangement the Safety Officer approved."""
    calls = Calls(monkeypatch, "Confirmed")

    response = cancel(client)

    assert response.status_code == 200
    assert calls.names() == ["get_event", "withdraw_safety_for_venue_change", "cancel_booking"]
    assert calls.args("withdraw_safety_for_venue_change")[3] == "A venue booking was cancelled after safety approval."


def test_confirmed_edit_that_fails_validation_never_withdraws(client, monkeypatch):
    """Boundary: an over-capacity edit is refused before the approval is touched."""
    calls = Calls(monkeypatch, "Confirmed")
    monkeypatch.setattr("app.routes.get_venues", lambda: [{**VENUE, "capacity": 10}])

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
)
def test_failed_edit_restores_the_approval_and_returns_the_booking_error(client, monkeypatch, error, status):
    """Conflict/Failure: the approval is put back so it still matches the unchanged booking."""
    calls = Calls(monkeypatch, "Confirmed")
    calls.fail["update_booking"] = error

    response = edit(client)

    assert response.status_code == status
    assert calls.names()[-1] == "restore_safety_after_venue_change"
    assert calls.args("restore_safety_after_venue_change") == (EVENT_ID, "coord-1", WITHDRAWN_ID)


def test_conflicting_edit_still_reports_the_conflict_types(client, monkeypatch):
    """Conflict: the coordinator sees the venue conflict, not a safety message."""
    calls = Calls(monkeypatch, "Confirmed")
    calls.fail["update_booking"] = BookingConflictError(["APPROVED_BOOKING"])

    response = edit(client)

    assert response.json["code"] == "VENUE_UNAVAILABLE"
    assert response.json["conflictTypes"] == ["APPROVED_BOOKING"]


@pytest.mark.parametrize("error, status", [(BookingStateError(), 409), (BookingNotFoundError(), 404)])
def test_failed_cancel_restores_the_approval(client, monkeypatch, error, status):
    calls = Calls(monkeypatch, "Confirmed")
    calls.fail["cancel_booking"] = error

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
)
@pytest.mark.parametrize("action", ACTIONS)
def test_withdrawal_failure_leaves_the_booking_untouched(client, monkeypatch, action, error, status):
    """Failure: if the approval can't be withdrawn, the booking is never changed."""
    calls = Calls(monkeypatch, "Confirmed")
    calls.fail["withdraw_safety_for_venue_change"] = error
    send, booking_call = ACTIONS[action]

    response = send(client)

    assert response.status_code == status
    assert booking_call not in calls.names()
    assert "restore_safety_after_venue_change" not in calls.names()
    if status == 409:
        assert response.json["code"] == "NO_APPROVED_SAFETY_CHECK"


def test_a_failed_restore_is_logged_and_the_booking_error_still_returned(client, monkeypatch, caplog):
    """Failure: when the undo fails too, the original error wins and the repair is logged."""
    calls = Calls(monkeypatch, "Confirmed")
    calls.fail["update_booking"] = BookingConflictError(["TENTATIVE_HOLD"])
    calls.fail["restore_safety_after_venue_change"] = RuntimeError("down")

    with caplog.at_level(logging.ERROR):
        response = edit(client)

    assert response.status_code == 409
    assert response.json["conflictTypes"] == ["TENTATIVE_HOLD"]
    assert WITHDRAWN_ID in caplog.text
    assert "manual repair" in caplog.text


def test_a_successful_change_never_restores(client, monkeypatch):
    """Normal: a saved change keeps the withdrawal; Venue Staff re-review the booking."""
    calls = Calls(monkeypatch, "Confirmed")

    edit(client)

    assert "restore_safety_after_venue_change" not in calls.names()


# --- The two HTTP wrappers ----------------------------------------------------


def test_withdraw_wrapper_posts_the_change(monkeypatch):
    sent = {}

    def post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return httpx.Response(200, json={"withdrawnSafetyCheck": {"id": WITHDRAWN_ID}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(clients.httpx, "post", post)

    result = clients.withdraw_safety_for_venue_change(EVENT_ID, "coord-1", BOOKING_ID, "why")

    assert result["withdrawnSafetyCheck"]["id"] == WITHDRAWN_ID
    assert sent["url"] == f"{clients.SAFETY_CHECK_SERVICE_URL}/safety-checks/withdraw-for-venue-change"
    assert sent["json"] == {"eventId": EVENT_ID, "coordinatorId": "coord-1", "bookingId": BOOKING_ID, "reason": "why"}


@pytest.mark.parametrize(
    "response, body",
    [
        (lambda request: httpx.Response(409, json={"code": "EVENT_NOT_CONFIRMED"}, request=request), {"code": "EVENT_NOT_CONFIRMED"}),
        (lambda request: httpx.Response(502, text="<html>", request=request), {}),
    ],
)
def test_withdraw_wrapper_carries_the_refusal(monkeypatch, response, body):
    monkeypatch.setattr(clients.httpx, "post", lambda url, **kwargs: response(httpx.Request("POST", url)))

    with pytest.raises(SafetyApprovalError) as raised:
        clients.withdraw_safety_for_venue_change(EVENT_ID, "coord-1", BOOKING_ID, "why")

    assert raised.value.body == body


def test_restore_wrapper_posts_the_withdrawn_round(monkeypatch):
    sent = {}

    def post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return httpx.Response(200, json={"event": {"status": "Confirmed"}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(clients.httpx, "post", post)

    clients.restore_safety_after_venue_change(EVENT_ID, "coord-1", WITHDRAWN_ID)

    assert sent["url"] == f"{clients.SAFETY_CHECK_SERVICE_URL}/safety-checks/restore-after-venue-change"
    assert sent["json"] == {"eventId": EVENT_ID, "coordinatorId": "coord-1", "withdrawnSafetyCheckId": WITHDRAWN_ID}


def test_restore_wrapper_raises_on_failure(monkeypatch):
    monkeypatch.setattr(
        clients.httpx, "post",
        lambda url, **kwargs: httpx.Response(409, json={}, request=httpx.Request("POST", url)),
    )

    with pytest.raises(httpx.HTTPStatusError):
        clients.restore_safety_after_venue_change(EVENT_ID, "coord-1", WITHDRAWN_ID)
