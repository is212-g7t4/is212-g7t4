"""SCRUM-43: coordinator review of organiser change requests."""

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


def test_ac1_ac2_assigned_coordinator_can_list_pending_requests(client, downstream):
    response = client.get(f"/change-requests")

    assert response.status_code == 200
    assert response.json["changeRequests"][0]["id"] == CHANGE_ID


def test_ac3_low_impact_approval_is_committed_without_arrangement_reads(client, downstream):
    _, calls = downstream

    response = patch(client)

    assert response.status_code == 200
    assert calls["previews"]
    assert calls["checks"] == []
    assert calls["decisions"] == [(CHANGE_ID, "Approved", None)]


def test_ac3_high_impact_approval_checks_arrangements_before_committing(client, downstream):
    state, calls = downstream
    state["preview"]["highImpactFields"] = ["expectedAttendance"]

    response = patch(client)

    assert response.status_code == 200
    assert len(calls["checks"]) == 1
    assert len(calls["decisions"]) == 1


def test_lead_role_is_forwarded_to_event_services_preview(client, downstream):
    state, calls = downstream
    state["role"] = "Event Coordinator Lead"
    response = patch(client)
    assert response.status_code == 200
    assert calls["previews"][0][-1] == "Event Coordinator Lead"


def test_ac3_conflict_refuses_approval_and_preserves_the_pending_request(client, downstream):
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


def test_ac4_rejection_requires_and_records_a_reason_without_impact_checks(client, downstream):
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


def test_non_coordinator_role_is_refused(client, downstream):
    state, calls = downstream
    state["role"] = "Event Organiser"

    response = patch(client)

    assert response.status_code == 403
    assert response.json["code"] == "COORDINATOR_REQUIRED"
    assert calls["decisions"] == []


def test_event_service_refusal_is_passed_through_on_the_queue(client, downstream, monkeypatch):
    def refused():
        raise clients.EventRejectedError(409, {"code": "STALE", "message": "Reload."})

    monkeypatch.setattr(clients, "list_pending_change_requests", refused)
    response = client.get(f"/change-requests")
    assert response.status_code == 409
    assert response.json == {"code": "STALE", "message": "Reload."}


@pytest.mark.parametrize("body", [None, {}, {"decision": "Maybe"}])
def test_malformed_decisions_are_rejected(client, downstream, body):
    response = client.patch(f"/change-requests/{CHANGE_ID}", json=body)
    assert response.status_code == 400


def test_invalid_ids_are_rejected(client, downstream):
    assert client.patch("/change-requests/bad", json={"decision": "Approved"}).status_code == 400


def test_rejection_reason_length_is_bounded(client, downstream):
    assert patch(client, decision="Rejected", reason="x" * 2001).status_code == 400


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamTimeout, 504), (clients.DownstreamError, 502)],
)
def test_downstream_failures_fail_closed(client, downstream, monkeypatch, error, status):
    monkeypatch.setattr(clients, "get_change_request", lambda *_args: (_ for _ in ()).throw(error))
    assert patch(client).status_code == status
