from unittest.mock import Mock

import httpx
import pytest

from app import clients


def response(status, body):
    request = httpx.Request("GET", "http://service.test")
    return httpx.Response(status, json=body, request=request)


def test_get_confirmed_event_finds_requested_event(monkeypatch):
    get = Mock(return_value=response(200, {"events": [{"id": "event-1"}, {"id": "event-2"}]}))
    monkeypatch.setattr(clients.httpx, "get", get)
    assert clients.get_confirmed_event("event-2") == {"id": "event-2"}
    assert clients.get_confirmed_event("missing") is None


def test_get_confirmed_event_propagates_service_failure(monkeypatch):
    monkeypatch.setattr(clients.httpx, "get", Mock(return_value=response(503, {})))
    with pytest.raises(httpx.HTTPStatusError):
        clients.get_confirmed_event("event-1")


def test_save_registration_returns_atomic_record(monkeypatch):
    post = Mock(return_value=response(201, {"registration": {"status": "Confirmed"}}))
    monkeypatch.setattr(clients.httpx, "post", post)
    assert clients.save_registration({"eventId": "event-1"}) == {"status": "Confirmed"}


def test_save_registration_maps_conflict(monkeypatch):
    monkeypatch.setattr(
        clients.httpx,
        "post",
        Mock(return_value=response(409, {"code": "EVENT_FULL", "message": "Full"})),
    )
    with pytest.raises(clients.RegistrationConflictError) as caught:
        clients.save_registration({"eventId": "event-1"})
    assert caught.value.code == "EVENT_FULL"


def test_save_registration_propagates_other_failures(monkeypatch):
    monkeypatch.setattr(clients.httpx, "post", Mock(return_value=response(503, {})))
    with pytest.raises(httpx.HTTPStatusError):
        clients.save_registration({"eventId": "event-1"})
