"""Workflow integration fixtures: HTTP boundary only, never a database or broker."""
import pytest
import respx
from app.dispatcher import OutboxAPI


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("EVENT_SERVICE_URL", "https://event.test")
    monkeypatch.setenv("USER_SERVICE_URL", "https://user.test")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "scrum45-test-token")
    return OutboxAPI()


@pytest.fixture
def http():
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        yield router
