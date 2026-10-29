"""Unit fixtures for Safety Check and Event Change notification worker HTTP contracts.

Only Event/User HTTP responses are doubled; no database or broker is used.
"""
import json
from unittest.mock import Mock

import httpx
import pytest
import respx

from app.dispatcher import OutboxAPI


@pytest.fixture
def safety_outbox_http(monkeypatch):
    """Run the real outbox client against strict synthetic HTTP routes only."""
    monkeypatch.setenv('EVENT_SERVICE_URL', 'http://event.test')
    monkeypatch.setenv('USER_SERVICE_URL', 'http://user.test')
    monkeypatch.setenv('INTERNAL_SERVICE_TOKEN', 'synthetic')
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        yield OutboxAPI(), router


@pytest.fixture
def event_change_http(monkeypatch):
    """Exercise SCRUM-49 through strict HTTP doubles, with sockets still blocked."""
    monkeypatch.setenv("EVENT_SERVICE_URL", "http://event.test")
    monkeypatch.setenv("USER_SERVICE_URL", "http://user.test")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "synthetic")
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        yield OutboxAPI(), router


@pytest.fixture
def prepare_change(event_change_http):
    """Register the exact owner contract and enforce freeze-before-publish ordering."""
    from tests.unit.factories import (
        CONTEXT, COORDINATOR, EVENT, ORGANISER, OUTBOX, change_envelope,
    )
    api, http = event_change_http

    def prepare(item, recipient, message, *, unassigned=False):
        # Event app/outbox.py::serialize/operate; app/__init__.py::notification_context.
        http.post(OUTBOX + "/claim", json={}).respond(200, json={"jobs": [item]})
        http.get(CONTEXT, params={"includeOrganiser": "true"}).respond(200, json={
            "id": EVENT, "eventName": "Later renamed event", "organiserId": ORGANISER,
            "coordinatorId": None if unassigned else COORDINATOR,
        })
        expected = change_envelope(item, recipient, message)
        # Owner result deliberately differs: publication must not use the local draft.
        frozen = {**expected, "ownerRevision": "frozen"}
        broker = Mock()

        def freeze(request):
            broker.assert_not_called()
            assert request.headers["X-Internal-Token"] == "synthetic"
            assert json.loads(request.content) == {"leaseToken": item["leaseToken"], "envelope": expected}
            return httpx.Response(200, json={"envelope": frozen})

        http.post(f"{OUTBOX}/{item['id']}/freeze").mock(side_effect=freeze)

        def completed(request):
            broker.assert_called_once_with(frozen)
            assert json.loads(request.content) == {"leaseToken": item["leaseToken"]}
            return httpx.Response(200, json={"id": item["id"], "status": "published"})

        http.post(f"{OUTBOX}/{item['id']}/published").mock(side_effect=completed)
        return api, broker, frozen

    return prepare


@pytest.fixture
def attendee_http(monkeypatch):
    """Yield the real OutboxAPI client and a strict respx router at synthetic service URLs.
    Every registered response must be used and every HTTP request must be registered.
    Restore environment values after each case; neither database nor broker is started.
    """
    monkeypatch.setenv("EVENT_SERVICE_URL", "http://event.test")
    monkeypatch.setenv("REGISTRATION_SERVICE_URL", "http://registration.test")
    monkeypatch.setenv("VENUE_AVAILABILITY_SERVICE_URL", "http://availability.test")
    monkeypatch.setenv("VENUE_SERVICE_URL", "http://venue.test")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "synthetic")
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        yield OutboxAPI(), router
