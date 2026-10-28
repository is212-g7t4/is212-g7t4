"""Unit fixtures for Safety Check notification worker HTTP contracts.

Only Event/User HTTP responses are doubled; no database or broker is used.
"""
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
