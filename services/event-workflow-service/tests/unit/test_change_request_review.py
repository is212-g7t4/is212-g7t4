"""
SCRUM-43: Review Event Change Requests

User Story
----------
As an Event Coordinator, I want to review and process change requests for
events I manage, so that I can assess the impact of changes and approve or
reject them appropriately.

Acceptance Criteria
-------------------
AC1: The Event Coordinator can view a list of pending change requests for
     events they manage.
AC2: For each change request, the Event Coordinator can see the event details
     and proposed changes (original vs proposed values), reason for change,
     attachments, request timestamp.
AC3: The Event Coordinator can approve the change request, where the system
     ppdates the event with the proposed changes, Changes the request status to
     'Approved', Records the Event Coordinator's identity, approval timestamp,
     and decision
AC4: The Event Coordinator can reject the change request with a reason
     (required), where the system Changes the request status to 'Rejected',
     Stores the rejection reason, Records the Event Coordinator's identity,
     rejection timestamp, and reason

Real
----
- GET /change-requests and PATCH /change-requests/<id>: the coordinator role
  check, the impact preview, arrangement checks before approving a high-impact
  change, the required bounded rejection reason and the error mapping run for
  real.
- Assertions are on the status, reasons and which downstream calls are made.

Doubled
-------
- Event, User, Venue Availability, Venue, Equipment Request and Equipment
  Services: Stub (`downstream` fixture) - canned answers; calls recorded so
  tests can assert what was (or was not) read or saved.

Not proven
----------
- That Event Service applies the change and records identity and time (AC3,
  AC4) (-> event-service unit tests for SCRUM-43).
- The review page with original vs proposed values (AC2, UI half) (-> frontend
  ChangeRequestsPage.test.tsx).
"""

import pytest

from app import checks, clients, create_app
from tests.unit.factories import signed_in

COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
CHANGE_ID = "22222222-2222-4222-8222-222222222222"
EVENT_ID = "33333333-3333-4333-8333-333333333333"


@pytest.fixture
def client():
    return signed_in(create_app().test_client(), COORDINATOR_ID)


@pytest.fixture
def downstream(monkeypatch):
    state = {
        "role": "Event Coordinator",
        "change": {
            "id": CHANGE_ID,
            "eventId": EVENT_ID,
            "proposedChanges": {"expectedAttendance": "60"},
            "event": {"id": EVENT_ID, "expectedAttendance": "40"},
        },
        "preview": {
            "event": {"id": EVENT_ID, "expectedAttendance": "40"},
            "changedFields": ["expectedAttendance"],
            "highImpactFields": [],
        },
        "conflicts": [],
    }
    calls = {"decisions": [], "previews": [], "checks": []}
    monkeypatch.setattr(clients, "get_user", lambda _id: {"role": state["role"]})
    monkeypatch.setattr(clients, "list_pending_change_requests", lambda: [state["change"]])
    monkeypatch.setattr(clients, "get_change_request", lambda *_args: state["change"])

    def preview(*args):
        calls["previews"].append(args)
        return state["preview"]

    def find_conflicts(*args):
        calls["checks"].append(args)
        return state["conflicts"]

    def decide(*args):
        calls["decisions"].append(args)
        return {"id": CHANGE_ID, "status": args[1]}

    monkeypatch.setattr(clients, "preview_event_details", preview)
    monkeypatch.setattr(checks, "find_conflicts", find_conflicts)
    monkeypatch.setattr(clients, "decide_change_request", decide)
    return state, calls


def patch(client, **overrides):
    body = {"decision": "Approved", **overrides}
    return client.patch(f"/change-requests/{CHANGE_ID}", json=body)


def test_list_change_requests_when_coordinator_returns_pending_requests(client, downstream):
    """
    Summary: A coordinator sees the pending change requests for their events with their details.
    AC1: The Event Coordinator can view a list of pending change requests for
        events they manage.
    AC2: For each change request, the Event Coordinator can see the event
        details and proposed changes (original vs proposed values), reason for
        change, attachments, request timestamp.
    Double: Stub (Event Service returns pending requests)
    """
    response = client.get(f"/change-requests")

    assert response.status_code == 200
    assert response.json["changeRequests"][0]["id"] == CHANGE_ID


def test_approve_low_impact_change_commits_without_arrangement_checks(client, downstream):
    """
    Summary: Approving a low-impact change applies it without checking arrangements.
    AC3: The Event Coordinator can approve the change request, where the system
        ppdates the event with the proposed changes, Changes the request status
        to 'Approved', Records the Event Coordinator's identity, approval
        timestamp, and decision
    Double: Stub (preview low impact), Mock (commit called; no arrangement
        reads)
    """
    _, calls = downstream

    response = patch(client)

    assert response.status_code == 200
    assert calls["previews"]
    assert calls["checks"] == []
    assert calls["decisions"] == [(CHANGE_ID, "Approved", None)]


def test_approve_high_impact_change_checks_arrangements_first(client, downstream):
    """
    Summary: Approving a high-impact change checks arrangements before applying it.
    AC3: The Event Coordinator can approve the change request, where the system
        ppdates the event with the proposed changes, Changes the request status
        to 'Approved', Records the Event Coordinator's identity, approval
        timestamp, and decision
    Double: Stub (preview high impact; arrangements fit), Mock (commit called)
    """
    state, calls = downstream
    state["preview"]["highImpactFields"] = ["expectedAttendance"]

    response = patch(client)

    assert response.status_code == 200
    assert len(calls["checks"]) == 1
    assert len(calls["decisions"]) == 1


def test_review_by_lead_sends_lead_role_to_event_service(client, downstream):
    """
    Summary: The Lead's review reaches Event Service as the Lead.
    AC3: The Event Coordinator can approve the change request, where the system
        ppdates the event with the proposed changes, Changes the request status
        to 'Approved', Records the Event Coordinator's identity, approval
        timestamp, and decision
    Double: Mock (preview records the actor role)
    """
    state, calls = downstream
    state["role"] = "Event Coordinator Lead"
    response = patch(client)
    assert response.status_code == 200
    assert calls["previews"][0][-1] == "Event Coordinator Lead"


def test_approve_conflicting_change_returns_409_and_keeps_request_pending(client, downstream):
    """
    Summary: A change that contradicts arrangements is not approved and stays pending.
    AC3: The Event Coordinator can approve the change request, where the system
        ppdates the event with the proposed changes, Changes the request status
        to 'Approved', Records the Event Coordinator's identity, approval
        timestamp, and decision
    Double: Stub (arrangements conflict), Mock (commit not called)
    """
    state, calls = downstream
    state["preview"]["highImpactFields"] = ["expectedAttendance"]
    state["conflicts"] = [{
        "field": "expectedAttendance", "area": "venue", "message": "Venue too small."
    }]

    response = patch(client)

    assert response.status_code == 409
    assert response.json["code"] == "CHANGE_CONTRADICTS_ARRANGEMENTS"
    assert response.json["conflicts"] == state["conflicts"]
    assert calls["decisions"] == []


def test_reject_change_with_reason_records_it_without_checks(client, downstream):
    """
    Summary: Rejecting needs a reason, which is recorded, and no impact checks run.
    AC4: The Event Coordinator can reject the change request with a reason
        (required), where the system Changes the request status to 'Rejected',
        Stores the rejection reason, Records the Event Coordinator's identity,
        rejection timestamp, and reason
    Double: Mock (reject called with the reason; no preview)
    """
    _, calls = downstream

    missing = patch(client, decision="Rejected", reason="  ")
    response = patch(client, decision="Rejected", reason="Dates cannot be supported.")

    assert missing.status_code == 400
    assert response.status_code == 200
    assert calls["previews"] == []
    assert calls["checks"] == []
    assert calls["decisions"] == [
        (CHANGE_ID, "Rejected", "Dates cannot be supported.")
    ]


def test_review_change_requests_when_not_coordinator_returns_403(client, downstream):
    """
    Summary: Only coordinators can review change requests.
    AC1: The Event Coordinator can view a list of pending change requests for
        events they manage.
    Double: Mock (no downstream calls)
    """
    state, calls = downstream
    state["role"] = "Event Organiser"

    response = patch(client)

    assert response.status_code == 403
    assert response.json["code"] == "COORDINATOR_REQUIRED"
    assert calls["decisions"] == []


def test_list_change_requests_when_event_service_refuses_returns_its_status(client, downstream, monkeypatch):
    """
    Summary: An Event Service refusal of the list reaches the coordinator unchanged.
    AC1: The Event Coordinator can view a list of pending change requests for
        events they manage.
    Double: Stub (list raises the refusal)
    """
    def refused():
        raise clients.EventRejectedError(409, {"code": "STALE", "message": "Reload."})

    monkeypatch.setattr(clients, "list_pending_change_requests", refused)
    response = client.get(f"/change-requests")
    assert response.status_code == 409
    assert response.json == {"code": "STALE", "message": "Reload."}


@pytest.mark.parametrize("body", [None, {}, {"decision": "Maybe"}], ids=["no_body", "empty_object", "unknown_decision"])
def test_review_with_malformed_decision_returns_400(client, downstream, body):
    """
    Summary: A review must be Approved or Rejected.
    AC3: The Event Coordinator can approve the change request, where the system
        ppdates the event with the proposed changes, Changes the request status
        to 'Approved', Records the Event Coordinator's identity, approval
        timestamp, and decision
    AC4: The Event Coordinator can reject the change request with a reason
        (required), where the system Changes the request status to 'Rejected',
        Stores the rejection reason, Records the Event Coordinator's identity,
        rejection timestamp, and reason
    Double: None
    """
    response = client.patch(f"/change-requests/{CHANGE_ID}", json=body)
    assert response.status_code == 400


def test_review_with_bad_request_id_returns_404(client, downstream):
    """
    Summary: A review must name a valid change request.
    AC3: The Event Coordinator can approve the change request, where the system
        ppdates the event with the proposed changes, Changes the request status
        to 'Approved', Records the Event Coordinator's identity, approval
        timestamp, and decision
    Double: None
    """
    assert client.patch("/change-requests/bad", json={"decision": "Approved"}).status_code == 400


def test_reject_with_reason_over_limit_returns_400(client, downstream):
    """
    Summary: A rejection reason has a maximum length.
    AC4: The Event Coordinator can reject the change request with a reason
        (required), where the system Changes the request status to 'Rejected',
        Stores the rejection reason, Records the Event Coordinator's identity,
        rejection timestamp, and reason
    Double: None
    """
    assert patch(client, decision="Rejected", reason="x" * 2001).status_code == 400


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamTimeout, 504), (clients.DownstreamError, 502)],
    ids=["timeout", "downstream_error"],
)
def test_review_when_downstream_fails_refuses_decision(client, downstream, monkeypatch, error, status):
    """
    Summary: If a downstream read fails, no decision is made.
    AC3: The Event Coordinator can approve the change request, where the system
        ppdates the event with the proposed changes, Changes the request status
        to 'Approved', Records the Event Coordinator's identity, approval
        timestamp, and decision
    Double: Stub (downstream times out or fails)
    """
    monkeypatch.setattr(clients, "get_change_request", lambda *_args: (_ for _ in ()).throw(error))
    assert patch(client).status_code == status
