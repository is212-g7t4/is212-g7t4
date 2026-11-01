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
     updates the event with the proposed changes, Changes the request status to
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
- app.clients change-request wrappers: the request (URL, token, body) and the
  mapping of Event Service refusals to EventRejectedError.
- Assertions are on the status, reasons, which downstream calls are made, and
  the request sent or exception raised by each client.

Doubled
-------
- Event, User, Venue Availability, Venue, Equipment Request and Equipment
  Services: Stub (`downstream` fixture) - canned answers; calls recorded so
  tests can assert what was (or was not) read or saved.
- httpx (the `send` fixture, client tests only): Stub - canned responses; the
  outgoing requests are recorded and inspected.

Not proven
----------
- That Event Service applies the change and records identity and time (AC3,
  AC4) (-> event-service unit tests for SCRUM-43).
- The review page with original vs proposed values (AC2, UI half) (-> frontend
  ChangeRequestsPage.test.tsx).
"""

import httpx
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


def test_ac1_list_change_requests_when_coordinator_returns_pending_requests(client, downstream):
    """
    Summary: GET /change-requests by a signed-in Event Coordinator answers 200
        with the pending change request list returned by Event Service (the
        test checks only that the request id is present, not its details).
    AC1: The Event Coordinator can view a list of pending change requests for
        events they manage.
    Double: Stub (get_user returns role Event Coordinator;
        list_pending_change_requests returns one change request)
    """
    response = client.get(f"/change-requests")

    assert response.status_code == 200
    assert response.json["changeRequests"][0]["id"] == CHANGE_ID


def test_ac3_approve_low_impact_change_commits_without_arrangement_checks(client, downstream):
    """
    Summary: PATCH /change-requests/<id> with decision Approved on a request
        whose preview has no high-impact fields answers 200 and sends one
        (id, "Approved", None) decision to Event Service without running the
        arrangement check.
    AC3: The Event Coordinator can approve the change request, where the system
        updates the event with the proposed changes, Changes the request status
        to 'Approved', Records the Event Coordinator's identity, approval
        timestamp, and decision
    Double: Stub (get_user returns Event Coordinator; get_change_request
        returns a request; preview_event_details returns highImpactFields=[]),
        Mock (decide_change_request called once with Approved; find_conflicts
        not called)
    """
    _, calls = downstream

    response = patch(client)

    assert response.status_code == 200
    assert calls["previews"]
    assert calls["checks"] == []
    assert calls["decisions"] == [(CHANGE_ID, "Approved", None)]


def test_ac3_approve_high_impact_change_checks_arrangements_first(client, downstream):
    """
    Summary: PATCH /change-requests/<id> with decision Approved on a request
        whose preview lists expectedAttendance as high impact runs the
        arrangement check once, finds no conflict, answers 200 and sends one
        decision to Event Service.
    AC3: The Event Coordinator can approve the change request, where the system
        updates the event with the proposed changes, Changes the request status
        to 'Approved', Records the Event Coordinator's identity, approval
        timestamp, and decision
    Double: Stub (preview_event_details returns highImpactFields=
        ["expectedAttendance"]; find_conflicts returns []), Mock
        (find_conflicts called once; decide_change_request called once)
    """
    state, calls = downstream
    state["preview"]["highImpactFields"] = ["expectedAttendance"]

    response = patch(client)

    assert response.status_code == 200
    assert len(calls["checks"]) == 1
    assert len(calls["decisions"]) == 1


def test_review_by_lead_sends_lead_role_to_event_service(client, downstream):
    """
    Summary: When User Service says the signed-in user is the Lead, approving
        a change request answers 200 and the preview call to Event Service
        carries actor role "Event Coordinator Lead".
    Supporting design check: the Lead's role is forwarded so Event Service
        skips its assigned-coordinator check
    Double: Stub (get_user returns role Event Coordinator Lead), Mock
        (preview_event_details records its last argument, the actor role)
    """
    state, calls = downstream
    state["role"] = "Event Coordinator Lead"
    response = patch(client)
    assert response.status_code == 200
    assert calls["previews"][0][-1] == "Event Coordinator Lead"


def test_ac3_approve_conflicting_change_returns_409_and_sends_no_decision(client, downstream):
    """
    Summary: Approving a high-impact request whose arrangement check finds a
        venue conflict answers 409 CHANGE_CONTRADICTS_ARRANGEMENTS with the
        conflicts, and no decision is sent to Event Service, so the request
        stays pending.
    AC3: The Event Coordinator can approve the change request, where the system
        updates the event with the proposed changes, Changes the request status
        to 'Approved', Records the Event Coordinator's identity, approval
        timestamp, and decision
    Double: Stub (preview_event_details returns highImpactFields=
        ["expectedAttendance"]; find_conflicts returns one venue conflict),
        Mock (decide_change_request not called)
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


def test_ac4_reject_change_with_reason_records_it_without_checks(client, downstream):
    """
    Summary: Rejecting with a blank reason ("  ") answers 400; rejecting with
        "Dates cannot be supported." answers 200 and sends exactly one
        (id, "Rejected", reason) decision, with no preview and no arrangement
        check.
    AC4: The Event Coordinator can reject the change request with a reason
        (required), where the system Changes the request status to 'Rejected',
        Stores the rejection reason, Records the Event Coordinator's identity,
        rejection timestamp, and reason
    Double: Stub (get_user returns Event Coordinator), Mock
        (decide_change_request called once with the reason; preview_event_details
        and find_conflicts not called)
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


def test_list_change_requests_when_event_service_refuses_returns_its_status(client, downstream, monkeypatch):
    """
    Summary: When Event Service refuses the pending list with 409 STALE,
        GET /change-requests answers 409 with the same body.
    Supporting design check: Event Service refusals reach the coordinator
        unchanged
    Double: Stub (list_pending_change_requests raises EventRejectedError 409
        STALE; get_user returns Event Coordinator)
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
    Summary: PATCH /change-requests/<id> with no body, an empty object or
        decision "Maybe" answers 400 because the decision must be Approved or
        Rejected.
    Supporting design check: only Approved or Rejected decisions are accepted
    Double: Stub (get_user returns Event Coordinator via the downstream
        fixture); no decision call is expected, the request is refused first
    """
    response = client.patch(f"/change-requests/{CHANGE_ID}", json=body)
    assert response.status_code == 400


def test_review_with_bad_request_id_returns_400(client, downstream):
    """
    Summary: PATCH /change-requests/bad (an id that is not a UUID) with
        decision Approved answers 400.
    Supporting design check: a review must name a valid change request id
    Double: Stub (get_user returns Event Coordinator via the downstream
        fixture); no decision call is expected, the id is refused first
    """
    assert client.patch("/change-requests/bad", json={"decision": "Approved"}).status_code == 400


def test_reject_with_reason_over_limit_returns_400(client, downstream):
    """
    Summary: Rejecting with a 2001-character reason answers 400.
    Supporting design check: a rejection reason is limited to 2000 characters
    Double: Stub (get_user returns Event Coordinator via the downstream
        fixture); no decision call is expected, the reason is refused first
    """
    assert patch(client, decision="Rejected", reason="x" * 2001).status_code == 400


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamTimeout, 504), (clients.DownstreamError, 502)],
    ids=["timeout", "downstream_error"],
)
def test_review_when_downstream_fails_refuses_decision(client, downstream, monkeypatch, error, status):
    """
    Summary: Approving answers 504 when get_change_request times out and 502
        when it raises a downstream error.
    Supporting design check: an unreadable downstream is reported as 504/502
    Double: Stub (get_change_request raises DownstreamTimeout, or
        DownstreamError; get_user returns Event Coordinator)
    """
    monkeypatch.setattr(clients, "get_change_request", lambda *_args: (_ for _ in ()).throw(error))
    assert patch(client).status_code == status


def test_ac2_list_change_requests_passes_through_event_details_changes_reason_attachments_and_time(client, downstream):
    """
    Summary: GET /change-requests answers 200 with the change request exactly
        as Event Service returned it: the current event values, the proposed
        changes, the reason, the attachments and the request timestamp are all
        present and unaltered. This service adds and removes nothing, so what is
        shown is decided by Event Service.
    AC2: For each change request, the Event Coordinator can see the event
        details and proposed changes (original vs proposed values), reason for
        change, attachments, request timestamp.
    Double: Stub (get_user returns Event Coordinator;
        list_pending_change_requests returns one request carrying the event
        values, proposedChanges, reason, attachments and createdAt)
    """
    # Arrange (Given)
    state, _ = downstream
    full_request = {
        "id": CHANGE_ID,
        "eventId": EVENT_ID,
        "event": {"id": EVENT_ID, "eventName": "Workshop", "expectedAttendance": "40"},
        "proposedChanges": {"expectedAttendance": "60"},
        "reason": "More sign-ups than expected.",
        "attachments": [{"name": "plan.pdf", "url": "https://files.test/plan.pdf"}],
        "createdAt": "2030-02-01T03:00:00+00:00",
    }
    state["change"] = full_request

    # Act (When)
    response = client.get("/change-requests")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["changeRequests"] == [full_request]


# --- app.clients change-request wrappers ---------------------------------------


class Reply:
    def __init__(self, status=200, body=None, json_error=False):
        self.status_code = status
        self.is_success = 200 <= status < 300
        self._body = body
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError
        return self._body


@pytest.fixture
def send(monkeypatch):
    sent = []
    replies = []

    def fake(method, url, **kwargs):
        sent.append((method, url, kwargs))
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(httpx, "request", fake)
    return sent, replies


def test_ac1_ac3_ac4_change_request_clients_call_event_service_as_trusted_service(send, monkeypatch):
    """
    Summary: list_pending_change_requests, get_change_request and
        decide_change_request("c1", "Rejected", "No") each send one request
        with the X-Internal-Token header; the list and read carry no query
        params and the decision body is {"decision": "Rejected", "reason":
        "No"}; each returns the response data.
    AC1: The Event Coordinator can view a list of pending change requests for
        events they manage.
    AC3: The Event Coordinator can approve the change request, where the system
        updates the event with the proposed changes, Changes the request status
        to 'Approved', Records the Event Coordinator's identity, approval
        timestamp, and decision
    AC4: The Event Coordinator can reject the change request with a reason
        (required), where the system Changes the request status to 'Rejected',
        Stores the rejection reason, Records the Event Coordinator's identity,
        rejection timestamp, and reason
    Double: Stub (httpx.request returns {"changeRequests": [{"id": "c1"}]},
        then {"id": "c1"}, then {"id": "c1", "status": "Rejected"};
        INTERNAL_SERVICE_TOKEN set to "secret"), Mock (the recorded requests'
        params, body and headers are asserted)
    """
    sent, replies = send
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", "secret")
    replies.extend([
        Reply(200, {"changeRequests": [{"id": "c1"}]}),
        Reply(200, {"id": "c1"}),
        Reply(200, {"id": "c1", "status": "Rejected"}),
    ])

    assert clients.list_pending_change_requests() == [{"id": "c1"}]
    assert clients.get_change_request("c1") == {"id": "c1"}
    assert clients.decide_change_request("c1", "Rejected", "No") == {
        "id": "c1", "status": "Rejected"
    }
    assert "params" not in sent[0][2] and "params" not in sent[1][2]
    assert sent[2][2]["json"] == {"decision": "Rejected", "reason": "No"}
    assert all(call[2]["headers"] == {"X-Internal-Token": "secret"} for call in sent)


def test_ac3_approve_change_request_client_sends_no_reason(send):
    """
    Summary: decide_change_request("c1", "Approved") sends the body
        {"decision": "Approved"} with no "reason" key.
    AC3: The Event Coordinator can approve the change request, where the system
        updates the event with the proposed changes, Changes the request status
        to 'Approved', Records the Event Coordinator's identity, approval
        timestamp, and decision
    Double: Stub (httpx.request returns 200 {"status": "Approved"}), Mock (the
        recorded request body is asserted)
    """
    sent, replies = send
    replies.append(Reply(200, {"status": "Approved"}))
    clients.decide_change_request("c1", "Approved")
    assert sent[0][2]["json"] == {"decision": "Approved"}


def test_change_request_client_when_refused_keeps_status_and_body(send):
    """
    Summary: get_change_request raises EventRejectedError carrying status 409
        and body {"code": "ALREADY_DECIDED"} when Event Service answers 409.
    Supporting design check: Event Service refusals of change-request calls
        keep their status and body
    Double: Stub (httpx.request returns 409 {"code": "ALREADY_DECIDED"})
    """
    _, replies = send
    replies.append(Reply(409, {"code": "ALREADY_DECIDED"}))
    with pytest.raises(clients.EventRejectedError) as raised:
        clients.get_change_request("c1")
    assert raised.value.status == 409
    assert raised.value.body == {"code": "ALREADY_DECIDED"}
