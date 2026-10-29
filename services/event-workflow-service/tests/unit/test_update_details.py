"""SCRUM-20 AC2-AC4: PATCH /events/<id>/details on the workflow composite.

Every downstream call is mocked; `--disable-socket` would fail an unmocked one.
"""
import pytest

from app import clients, create_app
from tests.unit.factories import signed_in

EVENT_ID = "00000000-0000-0000-0000-000000000001"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
EVENT = {"id": EVENT_ID, "expectedAttendance": "100"}


@pytest.fixture
def client():
    return signed_in(create_app().test_client(), COORDINATOR_ID)


def patch(client, changes=None, **overrides):
    body = {"changes": changes or {"eventName": "New"}}
    body.update(overrides)
    return client.patch(f"/events/{EVENT_ID}/details", json=body)


def preview(high=(), changed=("eventName",)):
    return {
        "event": EVENT,
        "changedFields": list(changed),
        "highImpactFields": list(high),
        "labels": [],
    }


@pytest.fixture
def downstream(monkeypatch):
    calls = {"previewed": [], "saved": [], "checked": []}
    state = {"role": "Event Coordinator", "preview": preview(), "conflicts": []}

    monkeypatch.setattr(clients, "get_user", lambda user_id: {"role": state["role"]})

    def fake_preview(event_id, changes, actor_role=None):
        calls["previewed"].append(actor_role)
        return state["preview"]

    def fake_save(event_id, changes, actor_role=None):
        calls["saved"].append(changes)
        return {"id": event_id, "status": "Approved"}

    def fake_conflicts(event, changes, high):
        calls["checked"].append(high)
        return state["conflicts"]

    monkeypatch.setattr(clients, "preview_event_details", fake_preview)
    monkeypatch.setattr(clients, "save_event_details", fake_save)
    monkeypatch.setattr("app.checks.find_conflicts", fake_conflicts)
    return calls, state


def test_ac2_a_low_impact_edit_is_saved_without_any_arrangement_check(client, downstream):
    calls, _ = downstream

    response = patch(client)

    assert response.status_code == 200
    assert calls["saved"] == [{"eventName": "New"}]
    assert calls["checked"] == []


def test_ac3_a_high_impact_edit_with_no_contradiction_is_saved(client, downstream):
    calls, state = downstream
    state["preview"] = preview(high=["expectedAttendance"], changed=["expectedAttendance"])

    response = patch(client, {"expectedAttendance": "80"})

    assert response.status_code == 200
    assert calls["checked"] == [["expectedAttendance"]]
    assert len(calls["saved"]) == 1


def test_ac3_a_contradiction_prevents_the_update_and_says_why(client, downstream):
    calls, state = downstream
    state["preview"] = preview(high=["expectedAttendance"], changed=["expectedAttendance"])
    state["conflicts"] = [{"field": "expectedAttendance", "area": "venue", "message": "Too many."}]

    response = patch(client, {"expectedAttendance": "900"})

    assert response.status_code == 409
    assert response.json["code"] == "CHANGE_CONTRADICTS_ARRANGEMENTS"
    assert response.json["conflicts"] == state["conflicts"]
    assert calls["saved"] == []


def test_the_lead_is_passed_to_event_service_as_the_actor_role(client, downstream):
    calls, state = downstream
    state["role"] = "Event Coordinator Lead"

    patch(client)

    assert calls["previewed"] == ["Event Coordinator Lead"]


def test_any_other_role_is_left_to_event_services_assignment_check(client, downstream):
    calls, _ = downstream

    patch(client)

    assert calls["previewed"] == [None]


def test_an_unknown_caller_is_refused(client, monkeypatch):
    def missing(user_id):
        raise clients.UserNotFoundError

    monkeypatch.setattr(clients, "get_user", missing)

    response = patch(client)

    assert response.status_code == 403
    assert response.json["code"] == "NOT_ASSIGNED_COORDINATOR"


@pytest.mark.parametrize("status", [400, 403, 404, 409])
def test_event_service_refusals_are_passed_through(client, downstream, monkeypatch, status):
    def refuse(*args, **kwargs):
        raise clients.EventRejectedError(status, {"code": "X", "message": "No."})

    monkeypatch.setattr(clients, "preview_event_details", refuse)

    response = patch(client)

    assert response.status_code == status
    assert response.json == {"code": "X", "message": "No."}


def test_a_safety_recheck_gate_on_save_is_passed_through(client, downstream, monkeypatch):
    def gate(*args, **kwargs):
        raise clients.EventRejectedError(409, {"code": "SAFETY_RECHECK_REQUIRED"})

    monkeypatch.setattr(clients, "save_event_details", gate)

    response = patch(client)

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_RECHECK_REQUIRED"


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamTimeout, 504), (clients.DownstreamError, 502)],
)
def test_unreadable_arrangements_fail_closed(client, downstream, monkeypatch, error, status):
    _, state = downstream
    state["preview"] = preview(high=["preferredStartDate"])

    def unreadable(*args, **kwargs):
        raise error

    monkeypatch.setattr("app.checks.find_conflicts", unreadable)

    response = patch(client)

    assert response.status_code == status
    assert "Nothing was changed" in response.json["message"]


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"changes": {}},
        {"changes": {"expectedAttendance": 5}},
    ],
)
def test_malformed_bodies_are_rejected(client, downstream, body):
    response = client.patch(f"/events/{EVENT_ID}/details", json=body)

    assert response.status_code == 400


def test_a_non_json_body_is_rejected(client):
    response = client.patch(f"/events/{EVENT_ID}/details", data="x")

    assert response.status_code == 400


def test_an_invalid_event_id_is_rejected(client):
    response = client.patch(
        "/events/not-a-uuid/details",
        json={"changes": {"eventName": "x"}},
    )

    assert response.status_code == 400


def test_health(client):
    assert client.get("/health").json == {"status": "ok"}


def test_cors_allows_the_frontend_origin_only(client):
    allowed = client.options("/health", headers={"Origin": "http://localhost:5174"})
    denied = client.options("/health", headers={"Origin": "http://evil.example"})

    assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert "Access-Control-Allow-Origin" not in denied.headers


def test_cors_is_off_when_no_origin_is_configured(monkeypatch):
    monkeypatch.setenv("FRONTEND_ORIGIN", "")

    response = signed_in(create_app().test_client()).options("/health", headers={"Origin": "http://localhost:5174"})

    assert "Access-Control-Allow-Origin" not in response.headers
