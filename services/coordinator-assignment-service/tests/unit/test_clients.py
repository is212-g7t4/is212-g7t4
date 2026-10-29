from unittest.mock import Mock

import httpx
import pytest

from app import clients


def response(status, body):
    return httpx.Response(status, json=body, request=httpx.Request("GET", "http://user.test"))


def test_available_coordinators_include_the_lead(monkeypatch):
    """The Lead can be assigned an event, including by themselves."""
    by_role = {
        "Event Coordinator Lead": [{"user_id": "lead", "role": "Event Coordinator Lead"}],
        "Event Coordinator": [{"user_id": "coord", "role": "Event Coordinator"}],
    }
    get = Mock(side_effect=lambda url, params, headers: response(200, {"users": by_role[params["role"]]}))
    monkeypatch.setattr(clients.httpx, "get", get)

    coordinators = clients.get_available_coordinators()

    assert [c["user_id"] for c in coordinators] == ["lead", "coord"]
    assert [call.kwargs["params"]["role"] for call in get.call_args_list] == list(clients.ASSIGNABLE_ROLES)


def test_available_coordinators_propagate_user_service_failure(monkeypatch):
    monkeypatch.setattr(clients.httpx, "get", Mock(return_value=response(503, {})))
    with pytest.raises(httpx.HTTPStatusError):
        clients.get_available_coordinators()


def test_assignment_worklist_comes_from_submitted_event_requests(monkeypatch):
    get = Mock(return_value=response(200, {"events": [
        {"id": "evt-1", "coordinatorId": None, "status": "Submitted"},
        {"id": "evt-2", "coordinatorId": "coord", "status": "Under Review"},
    ]}))
    monkeypatch.setattr(clients.httpx, "get", get)

    assert clients.get_assignment_events() == [
        {"id": "evt-1", "coordinatorId": None, "status": "Submitted"},
        {"id": "evt-2", "coordinatorId": "coord", "status": "Under Review"},
    ]
    assert get.call_args.args[0] == f"{clients.EVENT_SERVICE_URL}/events/submitted"
    assert get.call_args.kwargs["params"] == {"viewerRole": "Event Coordinator Lead"}


def test_active_events_come_from_event_service(monkeypatch):
    get = Mock(return_value=response(200, {"events": [{"id": "evt-1"}]}))
    monkeypatch.setattr(clients.httpx, "get", get)

    assert clients.get_active_events() == [{"id": "evt-1"}]
    assert get.call_args.args[0] == f"{clients.EVENT_SERVICE_URL}/events/active"


def test_assignment_names_only_the_new_coordinator(monkeypatch):
    """Event Service records the signed-in Lead (from the forwarded token) as the assigner."""
    saved = {"id": "evt-1", "coordinatorId": "coord", "assignedBy": "lead"}
    patch = Mock(return_value=httpx.Response(
        200, json=saved, request=httpx.Request("PATCH", "http://event.test")))
    monkeypatch.setattr(clients.httpx, "patch", patch)

    assert clients.assign_event_coordinator("evt-1", "coord") == saved
    assert patch.call_args.args[0] == f"{clients.EVENT_SERVICE_URL}/events/evt-1"
    assert patch.call_args.kwargs["json"] == {"assignedCoordinatorId": "coord"}


def test_assignment_propagates_event_service_failure(monkeypatch):
    monkeypatch.setattr(clients.httpx, "patch", Mock(return_value=httpx.Response(
        404, json={}, request=httpx.Request("PATCH", "http://event.test"))))
    with pytest.raises(httpx.HTTPStatusError):
        clients.assign_event_coordinator("evt-1", "coord")


def test_downstream_calls_carry_the_callers_token(monkeypatch):
    """SCRUM-8: inside a request, User and Event Service see the same signed-in user."""
    from app import create_app

    get = Mock(return_value=response(200, {"events": []}))
    monkeypatch.setattr(clients.httpx, "get", get)

    with create_app().test_request_context(headers={"Authorization": "Bearer lead-token"}):
        clients.get_active_events()

    assert get.call_args.kwargs["headers"] == {"Authorization": "Bearer lead-token"}


def test_calls_outside_a_request_carry_no_token(monkeypatch):
    get = Mock(return_value=response(200, {"events": []}))
    monkeypatch.setattr(clients.httpx, "get", get)

    clients.get_active_events()

    assert get.call_args.kwargs["headers"] == {}
