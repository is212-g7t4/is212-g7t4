"""Fixtures shared by the safety-check unit tests (pytest finds them by name)."""

import pytest

from app import clients
from tests.unit.factories import SubmissionDownstream


@pytest.fixture
def sent(monkeypatch):
    """Record every outgoing HTTP call and answer each with the next queued response (or raise it)."""
    # The attendee-notice venue lookup has its own tests (SCRUM-46); here it is fixed.
    monkeypatch.setattr(clients, "attendee_venue_name", lambda event_id: "Hall A")
    calls = []
    queue = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        result = queue.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("app.clients.httpx.request", fake_request)
    return calls, queue


@pytest.fixture
def submission_downstream(monkeypatch):
    """The services a safety submission calls, replaced by SubmissionDownstream."""
    stub = SubmissionDownstream()
    for name in (
        "get_event",
        "get_event_venue_bookings",
        "get_event_equipment_requests",
        "list_safety_check_records",
        "create_safety_check_record",
        "set_event_safety_status",
        "delete_safety_check_record",
    ):
        monkeypatch.setattr(f"app.clients.{name}", getattr(stub, name))
    return stub
