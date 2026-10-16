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
    get = Mock(side_effect=lambda url, params: response(200, {"users": by_role[params["role"]]}))
    monkeypatch.setattr(clients.httpx, "get", get)

    coordinators = clients.get_available_coordinators()

    assert [c["user_id"] for c in coordinators] == ["lead", "coord"]
    assert [call.kwargs["params"]["role"] for call in get.call_args_list] == list(clients.ASSIGNABLE_ROLES)


def test_available_coordinators_propagate_user_service_failure(monkeypatch):
    monkeypatch.setattr(clients.httpx, "get", Mock(return_value=response(503, {})))
    with pytest.raises(httpx.HTTPStatusError):
        clients.get_available_coordinators()


def test_unassigned_events_come_from_event_service(monkeypatch):
    get = Mock(return_value=response(200, {"events": [{"id": "evt-1"}]}))
    monkeypatch.setattr(clients.httpx, "get", get)

    assert clients.get_unassigned_events() == [{"id": "evt-1"}]
    assert get.call_args.args[0] == f"{clients.EVENT_SERVICE_URL}/events/unassigned"


def test_active_events_come_from_event_service(monkeypatch):
    get = Mock(return_value=response(200, {"events": [{"id": "evt-1"}]}))
    monkeypatch.setattr(clients.httpx, "get", get)

    assert clients.get_active_events() == [{"id": "evt-1"}]
    assert get.call_args.args[0] == f"{clients.EVENT_SERVICE_URL}/events/active"


def test_assignment_records_who_assigned_the_coordinator(monkeypatch):
    """Event Service is told who made the assignment, for the event's detail page."""
    saved = {"id": "evt-1", "coordinatorId": "coord", "assignedBy": "lead"}
    patch = Mock(return_value=httpx.Response(
        200, json=saved, request=httpx.Request("PATCH", "http://event.test")))
    monkeypatch.setattr(clients.httpx, "patch", patch)

    assert clients.assign_event_coordinator("evt-1", "coord", "lead") == saved
    assert patch.call_args.args[0] == f"{clients.EVENT_SERVICE_URL}/events/evt-1"
    assert patch.call_args.kwargs["json"] == {"assignedCoordinatorId": "coord", "assignedBy": "lead"}


def test_assignment_propagates_event_service_failure(monkeypatch):
    monkeypatch.setattr(clients.httpx, "patch", Mock(return_value=httpx.Response(
        404, json={}, request=httpx.Request("PATCH", "http://event.test"))))
    with pytest.raises(httpx.HTTPStatusError):
        clients.assign_event_coordinator("evt-1", "coord", "lead")
