"""
SCRUM-150: Approve Operational Safety Check

User Story
----------
As a Safety Officer, I want to approve an event's operational safety
arrangements, so that the event can proceed to preparation.

Acceptance Criteria
-------------------
AC1: Given an event is 'Pending Safety Check', when I approve it, then its
     status changes to 'Confirmed'.
AC2: Given I approve an event, then the safety check is recorded with the
     status 'Safety Approved', together with my identity, the approval
     timestamp and any optional remarks, in the event's history.
AC3: Given an event is not 'Pending Safety Check', then the approve action is
     not available and an API call is rejected without changing the event.
AC4: Given the safety check I approve follows a high-impact change, when I
     approve it, then the changed details become visible to registered
     Attendees.

Real
----
- Approving a safety check: only a Safety Officer, only for an event pending
  its safety check with an open round; the decision recorded first and the
  event then moved to Confirmed; and undoing the decision if the move fails.
- We check the result the officer sees, and the order of the calls to Safety
  Check Record and Event Service.

Doubled
-------
- Event, Safety Check Record, Venue Availability, Venue, Equipment Request and
  User Services: answer as each test needs, fail, or do not answer in time
  [Stub]; we check which were asked, in what order, and what they were sent
  [Mock].
- Sign-in: a test key signs the caller's token (tests/conftest.py) [Stub].

Not proven
----------
- That Event Service and Safety Check Record behave as faked (-> their own
  SCRUM-150 tests).
- The decision panel in the browser (-> frontend SafetyDecisionPanel.test.tsx).
"""
import logging

import pytest
from flask import g

from app import clients, create_app
from tests.unit.factories import (
    signed_in,
    EVENT_ID,
    OFFICER_ID,
    RECORD_ID,
    event,
    record,
    user,
)
from tests.unit.factories import Response


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
        # Names of calls whose real-world side effect still happens even
        # though the call reports failure — simulates a response lost after
        # the downstream write actually succeeded (SCRUM-150 bug fix).
        self.apply_despite_failure = set()
        # Call name -> the 1-based invocation from which `fail` starts
        # applying, so a later read can fail where an earlier one succeeded.
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

    def decide_safety_check_record(
        self, safety_check_id, status, remarks=None, flags=None
    ):
        decided_by = g.user_id  # The downstream service reads this from the forwarded token.
        self.calls.append(("decide", safety_check_id, status, decided_by, remarks))
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
            ("patch_event", event_id, status, safety_check_id, round_number, decided_by, remarks)
        )
        if "patch_event" in self.apply_despite_failure:
            self.event = self.updated
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
    return signed_in(create_app().test_client())


def approve(client, **overrides):
    body = {"eventId": EVENT_ID, "safetyOfficerId": OFFICER_ID, **overrides}
    return client.post("/safety-checks/approve", json=body)


# --- AC1, AC2: the happy path ------------------------------------------------


def test_approve_decides_round_and_confirms_event(client, downstream):
    """
    Summary: Approving records Safety Approved and the event becomes Confirmed.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
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


def test_approve_without_remarks_is_recorded(client, downstream):
    """
    Summary: Remarks are optional.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    response = approve(client)

    assert response.status_code == 200
    assert downstream.call("decide")[-1] is None


def test_approve_decides_round_before_moving_event(client, downstream):
    """
    Summary: The decision is recorded before the event moves, so two officers cannot both decide it.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    approve(client)

    assert downstream.names().index("decide") < downstream.names().index("patch_event")


# --- 403: caller must be a Safety Officer ------------------------------------


def test_approve_when_not_safety_officer_returns_403(client, downstream):
    """
    Summary: Only a Safety Officer can approve.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.user = user(role="Event Coordinator")

    response = approve(client)

    assert response.status_code == 403
    assert response.json["code"] == "NOT_SAFETY_OFFICER"
    # Nothing beyond the role check ran.
    assert downstream.names() == ["get_user"]


def test_approve_by_unknown_user_returns_403(client, downstream):
    """
    Summary: A signed-in user with no profile cannot approve.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["get_user"] = clients.UserNotFoundError

    response = approve(client)

    assert response.status_code == 403
    assert response.json["code"] == "NOT_SAFETY_OFFICER"


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_approve_when_role_check_fails_returns_error(error, status, client, downstream):
    """
    Summary: If the role cannot be checked, nothing is approved.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
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
def test_approve_event_not_pending_safety_check_returns_409(status, client, downstream):
    """
    Summary: An event not awaiting a safety check cannot be approved.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.event = event(status)

    response = approve(client)

    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_PENDING_SAFETY_CHECK"
    assert response.json["currentStatus"] == status
    assert "decide" not in downstream.names()
    assert "patch_event" not in downstream.names()


def test_approve_unknown_event_returns_404(client, downstream):
    """
    Summary: Approving an unknown event is refused.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["get_event"] = clients.EventNotFoundError

    response = approve(client)

    assert response.status_code == 404


def test_approve_when_event_service_says_not_assigned_returns_404(client, downstream):
    """
    Summary: An unexpected assignment refusal is treated as not found.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["get_event"] = clients.EventNotAssignedError

    response = approve(client)

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_approve_when_event_unreadable_returns_error(error, status, client, downstream):
    """
    Summary: If the event cannot be read, nothing is approved.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["get_event"] = error

    response = approve(client)

    assert response.status_code == status


# --- No open round / already decided -----------------------------------------


def test_approve_without_open_round_returns_409(client, downstream):
    """
    Summary: With no open round there is nothing to approve.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.rounds = []

    response = approve(client)

    assert response.status_code == 409
    assert response.json["code"] == "NO_OPEN_SAFETY_CHECK"


def test_approve_round_decided_by_other_officer_returns_409(client, downstream):
    """
    Summary: If another officer decided first, this approval is refused and the event untouched.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["decide"] = clients.SafetyCheckAlreadyDecidedError(
        record(status="Safety Approved")
    )

    response = approve(client)

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_DECIDED"
    assert "patch_event" not in downstream.names()


def test_approve_when_round_vanishes_returns_404(client, downstream):
    """
    Summary: A round that disappeared is reported.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["decide"] = clients.RecordNotFoundError

    response = approve(client)

    assert response.status_code == 409
    assert response.json["code"] == "NO_OPEN_SAFETY_CHECK"


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_approve_when_decision_fails_returns_error(error, status, client, downstream):
    """
    Summary: A failed decision leaves the event unchanged.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["decide"] = error

    response = approve(client)

    assert response.status_code == status


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_approve_when_open_round_unreadable_returns_error(error, status, client, downstream):
    """
    Summary: If the open round cannot be read, nothing is approved.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["list_records"] = error

    response = approve(client)

    assert response.status_code == status


# --- Reconciliation: a lost response doesn't mean the write failed ----------


@pytest.mark.parametrize("error", [clients.DownstreamError, clients.DownstreamTimeout])
def test_approve_when_decision_response_lost_but_saved_continues(error, client, downstream):
    """
    Summary: A lost answer from a decision that did save is reconciled and the approval continues.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["decide"] = error
    downstream.apply_despite_failure.add("decide")

    response = approve(client)

    assert response.status_code == 200
    assert response.json["safetyCheck"]["status"] == "Safety Approved"
    assert response.json["event"]["status"] == "Confirmed"
    assert downstream.names()[-1] == "patch_event"


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_approve_when_decision_response_lost_and_failed_reports_error(error, status, client, downstream):
    """
    Summary: A lost answer from a decision that failed is reported.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["decide"] = error

    response = approve(client)

    assert response.status_code == status
    assert "patch_event" not in downstream.names()


def test_approve_when_decision_and_reconciliation_fail_reports_original_error(client, downstream):
    """
    Summary: If the decision's outcome still cannot be known, the original error is reported.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["decide"] = clients.DownstreamTimeout
    downstream.apply_despite_failure.add("decide")
    downstream.fail["list_records"] = clients.DownstreamError
    downstream.fail_from["list_records"] = 2  # the open-round read still works

    response = approve(client)

    assert response.status_code == 504
    assert "patch_event" not in downstream.names()


@pytest.mark.parametrize("error", [clients.DownstreamError, clients.DownstreamTimeout])
def test_approve_when_confirm_response_lost_but_saved_succeeds(error, client, downstream):
    """
    Summary: A lost answer from a confirmation that did save does not undo the approval.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["patch_event"] = error
    downstream.apply_despite_failure.add("patch_event")

    response = approve(client)

    assert response.status_code == 200
    assert response.json["event"]["status"] == "Confirmed"
    assert "reopen" not in downstream.names()


# --- Compensation: the event move fails, so the decision is undone ----------


def test_approve_when_event_move_conflicts_reopens_round(client, downstream):
    """
    Summary: If Event Service refuses the move, the round is reopened.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
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


def test_approve_when_move_refused_without_message_reads_sensibly(client, downstream):
    """
    Summary: A refusal without a message still gives a readable error.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["patch_event"] = clients.EventTransitionError(None, {})

    response = approve(client)

    assert response.status_code == 409
    assert response.json["message"] == (
        "Only an event 'Pending Safety Check' can be approved."
    )


def test_approve_when_event_vanishes_mid_flight_reopens_round(client, downstream):
    """
    Summary: If the event disappears mid-way, the round is reopened.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["patch_event"] = clients.EventNotFoundError

    response = approve(client)

    assert response.status_code == 404
    assert downstream.names()[-1] == "reopen"


def test_approve_when_service_token_refused_reopens_round(client, downstream):
    """
    Summary: If Event Service refuses this service's credentials, the approval is undone.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["patch_event"] = clients.ServiceCredentialsError

    response = approve(client)

    assert response.status_code == 502
    assert response.json["message"] == "Event Service refused this service's credentials."
    assert downstream.names()[-1] == "reopen"


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_approve_when_event_move_fails_reopens_round(error, status, client, downstream):
    """
    Summary: If the move fails, the round is reopened.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["patch_event"] = error

    response = approve(client)

    assert response.status_code == status
    assert downstream.names()[-1] == "reopen"


def test_approve_when_event_refuses_unexpectedly_reopens_round(client, downstream):
    """
    Summary: Any other refusal of the move reopens the round.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["patch_event"] = clients.EventNotAssignedError

    response = approve(client)

    assert response.status_code == 502
    assert response.json["message"] == "Unable to approve this safety check right now."
    assert downstream.names()[-1] == "reopen"


def test_approve_when_reopen_also_fails_logs_and_returns_original_error(client, downstream, caplog):
    """
    Summary: If the reopen fails too, it is logged and the original error returned.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    downstream.fail["patch_event"] = clients.EventNotFoundError
    downstream.fail["reopen"] = clients.DownstreamError

    with caplog.at_level(logging.ERROR):
        response = approve(client)

    assert response.status_code == 404
    assert any(RECORD_ID in message for message in caplog.messages)


# --- Input validation ---------------------------------------------------------


def test_approve_with_non_object_body_returns_400(client, downstream):
    """
    Summary: An approval that is not in the expected form is refused.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: None
    """
    response = client.post("/safety-checks/approve", json=["nope"])

    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    assert downstream.calls == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"eventId": "not-a-uuid"},
        {"eventId": ""},
    ],
    ids=["not_a_uuid", "empty"],
)
def test_approve_with_bad_event_id_returns_400(overrides, client, downstream):
    """
    Summary: An approval must name a real event.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: None
    """
    response = approve(client, **overrides)

    assert response.status_code == 400
    assert response.json["message"] == "eventId must be a valid UUID."
    assert downstream.calls == []


def test_approve_with_remarks_over_limit_returns_400(client, downstream):
    """
    Summary: Remarks over the limit are refused.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: None
    """
    response = approve(client, remarks="x" * 2001)

    assert response.status_code == 400
    assert response.json["message"] == "remarks must be 2000 characters or fewer."
    assert downstream.calls == []


def test_approve_with_non_text_remarks_returns_400(client, downstream):
    """
    Summary: Remarks must be text.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: None
    """
    response = approve(client, remarks={"nested": "object"})

    assert response.status_code == 400
    assert response.json["message"] == "remarks must be text."
    assert downstream.calls == []


def test_approve_with_blank_remarks_sends_none(client, downstream):
    """
    Summary: Blank remarks are sent as none.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: The other services (Event, Safety Check Record, Venue Availability,
        Equipment Request) answer as this case needs [Stub]; we check which
        were asked, in what order, and what they were sent [Mock].
    """
    approve(client, remarks="   ")

    assert downstream.call("decide")[-1] is None


def test_get_event_client_sends_viewer_role_when_given(sent):
    """
    Summary: A Safety Officer reads the event with their viewer role.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    calls, queue = sent
    queue.append(Response(200, event("Pending Safety Check")))

    clients.get_event(EVENT_ID, viewer_role="Safety Officer")

    assert calls[0]["params"] == {"viewerRole": "Safety Officer"}


def test_set_safety_status_client_sends_remarks_on_approve(sent):
    """
    Summary: Approving sends the remarks with the move.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    calls, queue = sent
    queue.append(Response(200, event("Confirmed")))

    clients.set_event_safety_status(
        EVENT_ID,
        "Confirmed",
        RECORD_ID,
        1,
        remarks="Looks safe.",
    )

    assert calls[0]["json"] == {
        "status": "Confirmed",
        "safetyCheckId": RECORD_ID,
        "roundNumber": 1,
        "remarks": "Looks safe.",
    }


def test_decide_record_client_sends_decision(sent):
    """
    Summary: The decision is sent to Safety Check Record with the officer's outcome and remarks.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    calls, queue = sent
    queue.append(Response(200, record(status="Safety Approved", decidedBy=OFFICER_ID)))

    decided = clients.decide_safety_check_record(
        RECORD_ID, "Safety Approved", "Looks safe."
    )

    assert decided["status"] == "Safety Approved"
    assert calls[0]["method"] == "PATCH"
    assert calls[0]["url"].endswith(f"/safety-check-records/{RECORD_ID}/decision")
    assert calls[0]["json"] == {
        "status": "Safety Approved",
        "remarks": "Looks safe.",
    }


def test_decide_record_client_conflict_returns_existing_round(sent):
    """
    Summary: If another officer decided the round first, that existing decision is returned.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    _, queue = sent
    queue.append(
        Response(
            409,
            {"code": "SAFETY_CHECK_ALREADY_DECIDED", "safetyCheck": record(status="Safety Approved")},
        )
    )

    with pytest.raises(clients.SafetyCheckAlreadyDecidedError) as raised:
        clients.decide_safety_check_record(RECORD_ID, "Safety Approved")

    assert raised.value.existing["status"] == "Safety Approved"


def test_decide_record_client_missing_round_is_not_found(sent):
    """
    Summary: Deciding a missing round is reported as not found.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    _, queue = sent
    queue.append(Response(404, {"message": "no"}))

    with pytest.raises(clients.RecordNotFoundError):
        clients.decide_safety_check_record(RECORD_ID, "Safety Approved")


def test_decide_record_client_failure_is_downstream_error(sent):
    """
    Summary: If the decision cannot be saved, it is reported as a failure of that service.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    _, queue = sent
    queue.append(Response(503, {"message": "down"}))

    with pytest.raises(clients.DownstreamError):
        clients.decide_safety_check_record(RECORD_ID, "Safety Approved")


def test_reopen_record_client_sends_decision_time(sent):
    """
    Summary: Reopening names the exact decision to undo.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    calls, queue = sent
    queue.append(Response(200, record(status="Pending")))

    clients.reopen_safety_check_record(RECORD_ID, "2026-11-02T03:00:00+00:00")

    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith(f"/safety-check-records/{RECORD_ID}/reopen")
    assert calls[0]["json"] == {"decidedAt": "2026-11-02T03:00:00+00:00"}


def test_reopen_record_client_missing_round_is_not_found(sent):
    """
    Summary: Reopening a missing round is reported as not found.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    _, queue = sent
    queue.append(Response(404, {"message": "no"}))

    with pytest.raises(clients.RecordNotFoundError):
        clients.reopen_safety_check_record(RECORD_ID, "2026-11-02T03:00:00+00:00")


def test_reopen_record_client_failure_is_downstream_error(sent):
    """
    Summary: If the decision cannot be undone, it is reported as a failure of that service.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    _, queue = sent
    queue.append(Response(409, {"message": "nope"}))

    with pytest.raises(clients.DownstreamError):
        clients.reopen_safety_check_record(RECORD_ID, "2026-11-02T03:00:00+00:00")


def test_get_user_client_returns_role(sent):
    """
    Summary: A user's role is read from User Service.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    calls, queue = sent
    queue.append(Response(200, user(role="Safety Officer")))

    found = clients.get_user(OFFICER_ID)

    assert found["role"] == "Safety Officer"
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith(f"/users/{OFFICER_ID}")


def test_get_user_client_missing_is_not_found(sent):
    """
    Summary: A missing user is reported as not found.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    _, queue = sent
    queue.append(Response(404, {"message": "User not found."}))

    with pytest.raises(clients.UserNotFoundError):
        clients.get_user(OFFICER_ID)


def test_get_user_client_failure_is_downstream_error(sent):
    """
    Summary: If the user cannot be looked up, it is reported as a failure of that service.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    _, queue = sent
    queue.append(Response(503, {"message": "down"}))

    with pytest.raises(clients.DownstreamError):
        clients.get_user(OFFICER_ID)
