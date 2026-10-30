import pytest

from app import clients, create_app
from tests.unit.fakes import TARGET, USER, FakeResponse, World


@pytest.fixture
def world(monkeypatch):
    """Fake Event, Equipment and Equipment Request Services, wired in where app.clients is looked up."""
    fake = World()
    for name in ("list_requests", "get_request", "review_request", "review_event_requests",
                 "get_event_summaries", "list_assigned_event_ids", "list_assigned_events",
                 "get_overlapping_events", "list_equipment", "create_event_requests", "get_event_safety_checks"):
        monkeypatch.setattr(f"app.clients.{name}", getattr(fake, name))
    return fake


@pytest.fixture
def client():
    return create_app({"FRONTEND_ORIGIN": "http://localhost:5174"}).test_client()


@pytest.fixture
def assigned(world):
    """The fake world with TARGET assigned to the signed-in coordinator."""
    world.coordinator_assignments = {TARGET: USER}
    return world


@pytest.fixture
def sent(monkeypatch):
    """httpx.request replaced by a recorder: returns (calls, fake); set fake.response per test.

    The notification snapshot is stubbed so client tests stay on their own
    downstream call; the SCRUM-48 suites exercise the real snapshot lookup.
    """
    calls = []
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "synthetic")
    monkeypatch.setattr(clients, "notification_snapshot", lambda *args, **kwargs: {"eventId": "ev"})

    def fake(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return fake.response

    fake.response = FakeResponse(body={})
    monkeypatch.setattr("app.clients.httpx.request", fake)
    return calls, fake
