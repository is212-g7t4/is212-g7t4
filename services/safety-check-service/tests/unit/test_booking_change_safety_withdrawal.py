"""SCRUM-28 Part B: withdraw a Confirmed event's safety approval when a venue booking changes.

Decided by Clarice on 25 Oct: editing or cancelling a venue booking of a
'Confirmed' event withdraws its safety approval and returns the event to
'Approved'. Venue Staff re-review the booking, then the coordinator
resubmits through SCRUM-149 (round N+1). Venue Booking Service calls
`POST /safety-checks/withdraw-for-venue-change` before it changes the
booking, and `POST /safety-checks/restore-after-venue-change` if the change
then fails.

Record first, then event, as in SCRUM-153's re-check. Downstream calls are
monkeypatched `app.clients` wrappers for the routes; the wrappers' own HTTP
shape is tested with `httpx.request` patched.
"""
import logging

import httpx
import pytest

from app import clients, create_app
from tests.unit.factories import (
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

    def get_event(self, event_id, viewer_id, viewer_role=None):
        self._record("get_event", event_id, viewer_id)
        return self.event

    def list_safety_check_records(self, event_id, status=None):
        self._record("list_records", event_id)
        return self.rounds

    def withdraw_approval_without_next_round(self, round_id, withdrawn_by, reason):
        self._record("withdraw", round_id, withdrawn_by, reason)
        return self.withdrawn

    def restore_approval_without_next_round(self, round_id):
        self._record("restore", round_id)
        return self.restored

    def set_event_venue_change_status(self, event_id, coordinator_id, round_id, round_number, withdraw, reason=None):
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
    return create_app().test_client()


def withdraw(client, **overrides):
    body = {"eventId": EVENT_ID, "coordinatorId": COORDINATOR_ID, "bookingId": BOOKING_ID, "reason": REASON, **overrides}
    return client.post("/safety-checks/withdraw-for-venue-change", json=body)


def restore(client, **overrides):
    body = {"eventId": EVENT_ID, "coordinatorId": COORDINATOR_ID, "withdrawnSafetyCheckId": RECORD_ID, **overrides}
    return client.post("/safety-checks/restore-after-venue-change", json=body)


# --- withdraw-for-venue-change -----------------------------------------------


def test_withdrawal_withdraws_the_round_then_moves_the_event_to_approved(client, downstream):
    """Normal: no round is opened; the event goes back to Approved with the reason."""
    response = withdraw(client)

    assert response.status_code == 200
    assert response.json["event"]["status"] == "Approved"
    assert response.json["withdrawnSafetyCheck"]["status"] == "Approval Withdrawn"
    assert response.json["bookingId"] == BOOKING_ID
    assert downstream.names() == ["get_event", "list_records", "withdraw", "move_event"]
    assert downstream.calls[2] == ("withdraw", RECORD_ID, COORDINATOR_ID, REASON)
    assert downstream.calls[3] == ("move_event", EVENT_ID, COORDINATOR_ID, RECORD_ID, 2, True, REASON)


@pytest.mark.parametrize("status", ["Approved", "Pending Safety Check", "Safety Changes Requested", "Cancelled"])
def test_withdrawal_needs_a_confirmed_event(client, downstream, status):
    """Conflict: only a Confirmed event has an approval to withdraw; nothing is written."""
    downstream.event = event(status)

    response = withdraw(client)

    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_CONFIRMED"
    assert response.json["currentStatus"] == status
    assert downstream.names() == ["get_event"]


@pytest.mark.parametrize("rounds", [[], [record(round_number=2, status="Approval Withdrawn")]], ids=["none", "withdrawn"])
def test_withdrawal_needs_an_approved_latest_round(client, downstream, rounds):
    """Conflict: the latest round must be the approval in force."""
    downstream.rounds = rounds

    response = withdraw(client)

    assert response.status_code == 409
    assert response.json["code"] == "NO_APPROVED_SAFETY_CHECK"
    assert "withdraw" not in downstream.names()


def test_withdrawal_by_another_coordinator_is_refused(client, downstream):
    """Failure: Event Service's 403 for a stranger stops the workflow."""
    downstream.fail["get_event"] = clients.EventNotAssignedError()

    response = withdraw(client, coordinatorId=OTHER_COORDINATOR_ID)

    assert response.status_code == 403
    assert downstream.names() == ["get_event"]


def test_withdrawal_round_listing_failure_is_reported(client, downstream):
    """Failure: if the rounds can't be read, nothing is withdrawn."""
    downstream.fail["list_records"] = clients.DownstreamError()

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
)
def test_withdrawal_record_failure_never_moves_the_event(client, downstream, error, status, code):
    """Conflict/Failure: a lost race or a record-service failure leaves the event Confirmed."""
    downstream.fail["withdraw"] = error

    response = withdraw(client)

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
)
def test_event_move_failure_restores_the_approval(client, downstream, error, status):
    """Failure: the withdrawal is undone so the round and the event agree again."""
    downstream.fail["move_event"] = error

    response = withdraw(client)

    assert response.status_code == status
    assert downstream.names()[-1] == "restore"
    assert downstream.calls[-1] == ("restore", RECORD_ID)


def test_a_failed_compensation_is_logged_for_manual_repair(client, downstream, caplog):
    """Failure: when even the undo fails, the original error is returned and both ids are logged."""
    downstream.fail["move_event"] = clients.DownstreamError()
    downstream.fail["restore"] = clients.DownstreamError()

    with caplog.at_level(logging.ERROR):
        response = withdraw(client)

    assert response.status_code == 502
    assert RECORD_ID in caplog.text
    assert EVENT_ID in caplog.text


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"eventId": "x"}, "eventId, coordinatorId and bookingId must be valid UUIDs."),
        ({"bookingId": None}, "eventId, coordinatorId and bookingId must be valid UUIDs."),
        ({"reason": " "}, "reason is required."),
    ],
)
def test_withdrawal_body_is_validated(client, downstream, overrides, message):
    """Failure: a malformed request makes no downstream call."""
    response = withdraw(client, **overrides)

    assert response.status_code == 400
    assert response.json["message"] == message
    assert downstream.calls == []


def test_withdrawal_rejects_a_non_object_body(client, downstream):
    response = client.post("/safety-checks/withdraw-for-venue-change", json=[])

    assert response.status_code == 400
    assert downstream.calls == []


# --- restore-after-venue-change ----------------------------------------------


def test_restore_reinstates_the_round_then_confirms_the_event(client, downstream):
    """Normal: record first, then event, so the event is never Confirmed without an approval."""
    downstream.event = event("Approved")

    response = restore(client)

    assert response.status_code == 200
    assert response.json["event"]["status"] == "Confirmed"
    assert response.json["safetyCheck"]["status"] == "Safety Approved"
    assert downstream.names() == ["get_event", "restore", "move_event"]
    assert downstream.calls[2] == ("move_event", EVENT_ID, COORDINATOR_ID, RECORD_ID, 2, False, None)


def test_restore_needs_an_approved_event(client, downstream):
    """Conflict: only an event the withdrawal sent back to Approved can be restored."""
    response = restore(client)

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
)
def test_restore_record_failure_leaves_the_event_alone(client, downstream, error, status, code):
    """Failure: if the round can't be restored the event is not confirmed."""
    downstream.event = event("Approved")
    downstream.fail["restore"] = error

    response = restore(client)

    assert response.status_code == status
    assert response.json.get("code") == code
    assert "move_event" not in downstream.names()


def test_restore_event_failure_is_logged(client, downstream, caplog):
    """Failure: the round is approved again but the event stays Approved; that is logged."""
    downstream.event = event("Approved")
    downstream.fail["move_event"] = clients.EventTransitionError("STALE_SAFETY_CHECK", {"code": "STALE_SAFETY_CHECK"})

    with caplog.at_level(logging.ERROR):
        response = restore(client)

    assert response.status_code == 409
    assert "left Approved" in caplog.text


def test_restore_failure_on_event_load_is_reported(client, downstream):
    downstream.fail["get_event"] = clients.EventNotFoundError()

    assert restore(client).status_code == 404


@pytest.mark.parametrize("body", [[], {"eventId": EVENT_ID, "coordinatorId": COORDINATOR_ID}])
def test_restore_body_is_validated(client, downstream, body):
    """Failure: a malformed restore makes no downstream call."""
    response = client.post("/safety-checks/restore-after-venue-change", json=body)

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
    calls, queue = [], []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return queue.pop(0)

    monkeypatch.setattr("app.clients.httpx.request", fake_request)
    return calls, queue


def test_withdraw_wrapper_asks_for_no_next_round(sent):
    calls, queue = sent
    queue.append(Response(201, {"withdrawn": record(status="Approval Withdrawn"), "opened": None}))

    assert clients.withdraw_approval_without_next_round(RECORD_ID, COORDINATOR_ID, REASON)["status"] == "Approval Withdrawn"
    assert calls[0]["url"].endswith(f"/safety-check-records/{RECORD_ID}/withdraw")
    assert calls[0]["json"] == {"withdrawnBy": COORDINATOR_ID, "reason": REASON, "openNextRound": False}


def test_restore_wrapper_names_no_round(sent):
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
def test_record_wrappers_map_failures(sent, wrapper, status_code, error):
    _, queue = sent
    queue.append(Response(status_code, {"code": "X"}))

    with pytest.raises(error):
        if wrapper == "withdraw":
            clients.withdraw_approval_without_next_round(RECORD_ID, COORDINATOR_ID, REASON)
        else:
            clients.restore_approval_without_next_round(RECORD_ID)


@pytest.mark.parametrize("withdraw_move", [True, False])
def test_event_wrapper_sends_the_marker_for_each_direction(sent, monkeypatch, withdraw_move):
    calls, queue = sent
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", "secret")
    queue.append(Response(200, event("Approved" if withdraw_move else "Confirmed")))

    clients.set_event_venue_change_status(EVENT_ID, COORDINATOR_ID, RECORD_ID, 2, withdraw_move, REASON if withdraw_move else None)

    assert calls[0]["method"] == "PATCH"
    assert calls[0]["url"].endswith(f"/events/{EVENT_ID}/safety-status")
    assert calls[0]["headers"] == {"X-Internal-Service-Token": "secret"}
    expected = {"safetyCheckId": RECORD_ID, "roundNumber": 2, "coordinatorId": COORDINATOR_ID}
    if withdraw_move:
        expected |= {"status": "Approved", "withdrawnSafetyCheckId": RECORD_ID, "reason": REASON}
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
)
def test_event_wrapper_maps_failures(sent, status_code, payload, error):
    _, queue = sent
    queue.append(Response(status_code, payload))

    with pytest.raises(error):
        clients.set_event_venue_change_status(EVENT_ID, COORDINATOR_ID, RECORD_ID, 2, True, REASON)


def test_wrappers_hide_transport_errors(monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.ConnectTimeout("slow")

    monkeypatch.setattr("app.clients.httpx.request", boom)
    with pytest.raises(clients.DownstreamTimeout):
        clients.set_event_venue_change_status(EVENT_ID, COORDINATOR_ID, RECORD_ID, 2, True, REASON)
