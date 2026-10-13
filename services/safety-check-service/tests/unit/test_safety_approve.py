"""SCRUM-150: POST /safety-checks/approve.

AC1 Given an event is 'Pending Safety Check', when I approve it, then its
    status changes to 'Confirmed'.
AC2 Given I approve an event, then the safety check is recorded with the
    status 'Safety Approved', together with my identity, the approval
    timestamp and any optional remarks, in the event's history.
AC3 Given an event is not 'Pending Safety Check', then the approve action is
    not available and an API call is rejected without changing the event.

Every downstream call is a monkeypatched `app.clients` wrapper, so these
tests exercise the orchestration and the error mapping, not HTTP
(`test_clients.py` covers that).
"""
import logging

import pytest

from app import clients, create_app
from tests.unit.factories import (
    EVENT_ID,
    OFFICER_ID,
    RECORD_ID,
    event,
    record,
    user,
)


class Downstream:
    """Recorded stand-ins for every atomic this composite calls."""

    def __init__(self):
        self.user = user(role="Safety Officer")
        self.event = event("Pending Safety Check")
        self.rounds = [record(status="Pending")]
        self.decided = record(status="Safety Approved", decidedBy=OFFICER_ID)
        self.updated = event("Confirmed")
        self.calls = []
        self.fail = {}

    def _maybe_fail(self, name):
        error = self.fail.get(name)
        if error:
            raise error

    def get_user(self, user_id):
        self.calls.append(("get_user", user_id))
        self._maybe_fail("get_user")
        return self.user

    def get_event(self, event_id, viewer_id, viewer_role=None):
        self.calls.append(("get_event", event_id, viewer_id, viewer_role))
        self._maybe_fail("get_event")
        return self.event

    def list_safety_check_records(self, event_id, status=None):
        self.calls.append(("list_records", event_id, status))
        self._maybe_fail("list_records")
        return self.rounds

    def decide_safety_check_record(self, safety_check_id, status, decided_by, remarks=None):
        self.calls.append(("decide", safety_check_id, status, decided_by, remarks))
        self._maybe_fail("decide")
        return self.decided

    def set_event_safety_status(
        self,
        event_id,
        status,
        safety_check_id,
        round_number,
        coordinator_id=None,
        decided_by=None,
        remarks=None,
    ):
        self.calls.append(
            ("patch_event", event_id, status, safety_check_id, round_number, decided_by, remarks)
        )
        self._maybe_fail("patch_event")
        return self.updated

    def reopen_safety_check_record(self, safety_check_id, decided_at):
        self.calls.append(("reopen", safety_check_id, decided_at))
        self._maybe_fail("reopen")

    def names(self):
        return [call[0] for call in self.calls]

    def call(self, name):
        return next(call for call in self.calls if call[0] == name)


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
    ):
        monkeypatch.setattr(f"app.clients.{name}", getattr(stub, name))
    return stub


@pytest.fixture
def client():
    return create_app().test_client()


def approve(client, **overrides):
    body = {"eventId": EVENT_ID, "safetyOfficerId": OFFICER_ID, **overrides}
    return client.post("/safety-checks/approve", json=body)


# --- AC1, AC2: the happy path ------------------------------------------------


def test_approval_decides_the_round_and_confirms_the_event(client, downstream):
    """AC1/AC2: the round is decided, the event becomes 'Confirmed'."""
    response = approve(client, remarks="Looks safe.")

    assert response.status_code == 200
    assert response.json["event"]["status"] == "Confirmed"
    assert response.json["safetyCheck"]["status"] == "Safety Approved"
    assert downstream.call("get_user") == ("get_user", OFFICER_ID)
    assert downstream.call("get_event") == (
        "get_event",
        EVENT_ID,
        OFFICER_ID,
        "Safety Officer",
    )
    assert downstream.call("decide") == (
        "decide",
        RECORD_ID,
        "Safety Approved",
        OFFICER_ID,
        "Looks safe.",
    )
    assert downstream.call("patch_event") == (
        "patch_event",
        EVENT_ID,
        "Confirmed",
        RECORD_ID,
        1,
        OFFICER_ID,
        "Looks safe.",
    )


def test_remarks_are_optional(client, downstream):
    response = approve(client)

    assert response.status_code == 200
    assert downstream.call("decide")[-1] is None


def test_record_is_decided_before_the_event_moves(client, downstream):
    """The record service is the race guard (AC3), so it must go first."""
    approve(client)

    assert downstream.names().index("decide") < downstream.names().index("patch_event")


# --- 403: caller must be a Safety Officer ------------------------------------


def test_caller_must_be_a_safety_officer(client, downstream):
    """AC3's spirit: an Event Coordinator can't approve."""
    downstream.user = user(role="Event Coordinator")

    response = approve(client)

    assert response.status_code == 403
    assert response.json["code"] == "NOT_SAFETY_OFFICER"
    # Nothing beyond the role check ran.
    assert downstream.names() == ["get_user"]


def test_unknown_caller_is_refused(client, downstream):
    downstream.fail["get_user"] = clients.UserNotFoundError

    response = approve(client)

    assert response.status_code == 403
    assert response.json["code"] == "NOT_SAFETY_OFFICER"


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_role_check_downstream_failure(error, status, client, downstream):
    downstream.fail["get_user"] = error

    response = approve(client)

    assert response.status_code == status


# --- AC3: the event must be 'Pending Safety Check' ---------------------------


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
def test_event_not_pending_safety_check_is_refused(status, client, downstream):
    """AC3: no write happens when the event isn't the right status."""
    downstream.event = event(status)

    response = approve(client)

    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_PENDING_SAFETY_CHECK"
    assert response.json["currentStatus"] == status
    assert "decide" not in downstream.names()
    assert "patch_event" not in downstream.names()


def test_event_not_found(client, downstream):
    downstream.fail["get_event"] = clients.EventNotFoundError

    response = approve(client)

    assert response.status_code == 404


def test_event_not_assigned_is_still_treated_as_not_found(client, downstream):
    """Defensive only: viewerRole is always sent, so this shouldn't happen."""
    downstream.fail["get_event"] = clients.EventNotAssignedError

    response = approve(client)

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_event_read_downstream_failure(error, status, client, downstream):
    downstream.fail["get_event"] = error

    response = approve(client)

    assert response.status_code == status


# --- No open round / already decided -----------------------------------------


def test_no_open_round(client, downstream):
    downstream.rounds = []

    response = approve(client)

    assert response.status_code == 409
    assert response.json["code"] == "NO_OPEN_SAFETY_CHECK"


def test_round_already_decided_by_another_officer(client, downstream):
    """The race (AC3): the record service is the guard, so the event isn't touched."""
    downstream.fail["decide"] = clients.SafetyCheckAlreadyDecidedError(
        record(status="Safety Approved")
    )

    response = approve(client)

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_DECIDED"
    assert "patch_event" not in downstream.names()


def test_round_missing_when_deciding(client, downstream):
    downstream.fail["decide"] = clients.RecordNotFoundError

    response = approve(client)

    assert response.status_code == 409
    assert response.json["code"] == "NO_OPEN_SAFETY_CHECK"


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_decide_downstream_failure(error, status, client, downstream):
    downstream.fail["decide"] = error

    response = approve(client)

    assert response.status_code == status


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_open_round_lookup_downstream_failure(error, status, client, downstream):
    downstream.fail["list_records"] = error

    response = approve(client)

    assert response.status_code == status


# --- Compensation: the event move fails, so the decision is undone ----------


def test_event_conflict_rolls_the_decision_back(client, downstream):
    downstream.fail["patch_event"] = clients.EventTransitionError(
        "STALE_SAFETY_CHECK", {"message": "stale", "currentStatus": "Pending Safety Check"}
    )

    response = approve(client)

    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_PENDING_SAFETY_CHECK"
    assert downstream.call("reopen") == (
        "reopen",
        RECORD_ID,
        downstream.decided["decidedAt"],
    )


def test_event_transition_error_without_a_message_still_reads_sensibly(client, downstream):
    downstream.fail["patch_event"] = clients.EventTransitionError(None, {})

    response = approve(client)

    assert response.status_code == 409
    assert response.json["message"] == (
        "Only an event 'Pending Safety Check' can be approved."
    )


def test_event_not_found_mid_flight_rolls_the_decision_back(client, downstream):
    downstream.fail["patch_event"] = clients.EventNotFoundError

    response = approve(client)

    assert response.status_code == 404
    assert downstream.names()[-1] == "reopen"


def test_service_credentials_error_rolls_the_decision_back(client, downstream):
    """Event Service refusing our internal token is our problem, not the caller's."""
    downstream.fail["patch_event"] = clients.ServiceCredentialsError

    response = approve(client)

    assert response.status_code == 502
    assert response.json["message"] == "Event Service refused this service's credentials."
    assert downstream.names()[-1] == "reopen"


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_event_update_downstream_failure_rolls_the_decision_back(error, status, client, downstream):
    downstream.fail["patch_event"] = error

    response = approve(client)

    assert response.status_code == status
    assert downstream.names()[-1] == "reopen"


def test_reopen_failure_is_logged_and_original_error_returned(client, downstream, caplog):
    """If the compensating reopen also fails, log it and still report the original error."""
    downstream.fail["patch_event"] = clients.EventNotFoundError
    downstream.fail["reopen"] = clients.DownstreamError

    with caplog.at_level(logging.ERROR):
        response = approve(client)

    assert response.status_code == 404
    assert any(RECORD_ID in message for message in caplog.messages)


# --- Input validation ---------------------------------------------------------


def test_non_object_body_is_rejected(client, downstream):
    response = client.post("/safety-checks/approve", json=["nope"])

    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    assert downstream.calls == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"eventId": "not-a-uuid"},
        {"safetyOfficerId": "not-a-uuid"},
        {"eventId": ""},
        {"safetyOfficerId": ""},
    ],
)
def test_bad_identifiers_are_rejected(overrides, client, downstream):
    response = approve(client, **overrides)

    assert response.status_code == 400
    assert response.json["message"] == "eventId and safetyOfficerId must be valid UUIDs."
    assert downstream.calls == []


def test_remarks_over_the_limit_are_rejected(client, downstream):
    response = approve(client, remarks="x" * 2001)

    assert response.status_code == 400
    assert response.json["message"] == "remarks must be 2000 characters or fewer."
    assert downstream.calls == []


def test_non_text_remarks_are_rejected(client, downstream):
    response = approve(client, remarks={"nested": "object"})

    assert response.status_code == 400
    assert response.json["message"] == "remarks must be text."
    assert downstream.calls == []


def test_blank_remarks_are_sent_as_none(client, downstream):
    approve(client, remarks="   ")

    assert downstream.call("decide")[-1] is None
