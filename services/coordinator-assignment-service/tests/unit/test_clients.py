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
