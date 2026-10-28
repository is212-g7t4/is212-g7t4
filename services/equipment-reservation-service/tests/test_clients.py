"""HTTP wrappers: success, pass-through errors and unreachable services. httpx is stubbed."""
import httpx
import pytest

from app import clients
from app.clients import DownstreamError

HEADERS = {"X-Dev-User-Id": "u", "X-Dev-Role": "Technical Support", "Cookie": "must-not-be-forwarded"}


class FakeResponse:
    def __init__(self, status=200, body=None, json_error=False):
        self.status_code, self._body, self._json_error = status, body, json_error
        self.is_success = 200 <= status < 300

    def json(self):
        if self._json_error:
            raise ValueError("not json")
        return self._body


@pytest.fixture
def sent(monkeypatch):
    calls = []
    # Keep pre-existing transport scenarios focused on their downstream write.
    # SCRUM-48's three integration scenarios exercise the real snapshot lookup.
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "synthetic")
    monkeypatch.setattr(clients, "notification_snapshot", lambda *args, **kwargs: {"eventId": "ev"})

    def fake(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return fake.response

    fake.response = FakeResponse(body={})
    monkeypatch.setattr("app.clients.httpx.request", fake)
    return calls, fake


# Review AC1/AC3 / Reservation AC2 (transport): forward identity and event/status filters to request storage.
def test_list_requests_forwards_only_identity_headers_and_filters(sent):
    calls, fake = sent
    fake.response = FakeResponse(body={"requests": [1]})

    assert clients.list_requests(HEADERS, "Approved", ["a", "b"]) == [1]

    method, url, kwargs = calls[0]
    assert (method, url) == ("GET", "http://localhost:5011/equipment-requests")
    assert kwargs["params"] == {"status": "Approved", "eventIds": "a,b"}
    assert kwargs["headers"] == {"X-Dev-User-Id": "u", "X-Dev-Role": "Technical Support"}


# Review AC3 (access boundary): no assigned event IDs means no request lookup.
def test_list_requests_with_no_event_ids_skips_the_call(sent):
    calls, _ = sent
    assert clients.list_requests(HEADERS, "Approved", []) == []
    assert calls == []


def test_safety_records_are_read_for_only_the_requested_event(sent, monkeypatch):
    calls, fake = sent
    monkeypatch.setenv("SAFETY_CHECK_RECORD_SERVICE_URL", "http://records:5000")
    fake.response = FakeResponse(body={"safetyChecks": [{"roundNumber": 2}]})
    assert clients.get_event_safety_checks("event-id") == [{"roundNumber": 2}]
    assert calls[0] == ("GET", "http://records:5000/safety-check-records", {"timeout": 10, "params": {"eventId": "event-id"}})


# Review AC1 (transport): support an unfiltered staff request-list lookup.
def test_list_requests_without_filters(sent):
    calls, fake = sent
    fake.response = FakeResponse(body={"requests": []})
    clients.list_requests(HEADERS)
    assert calls[0][2]["params"] == {}


# Review AC1/AC2 / Reservation AC2 (transport): target individual records and event-scoped bulk decisions.
def test_get_and_review_calls(sent):
    calls, fake = sent
    fake.response = FakeResponse(body={"request": {"id": "r", "eventId": "ev"}, "requests": [{"id": "r"}]})

    assert clients.get_request(HEADERS, "r") == {"id": "r", "eventId": "ev"}
    assert clients.review_request(HEADERS, "r", "Approved") == {"id": "r", "eventId": "ev"}
    assert clients.review_event_requests(HEADERS, "ev", "Rejected", "No technician available.") == [{"id": "r"}]

    assert [(c[0], c[1]) for c in calls] == [
        ("GET", "http://localhost:5011/equipment-requests/r"),
        ("GET", "http://localhost:5011/equipment-requests/r"),
        ("PATCH", "http://localhost:5011/equipment-requests/r"),
        ("PATCH", "http://localhost:5011/events/ev/equipment-requests"),
    ]
    assert calls[2][2]["json"] == {"status": "Approved", "notificationContext": {"eventId": "ev"}}
    assert calls[3][2]["json"] == {"status": "Rejected", "rejectionReason": "No technician available.", "notificationContext": {"eventId": "ev"}}


# Create request AC1/AC2 (transport): forward equipment needs, the event ID and caller identity to storage.
def test_create_event_requests_posts_items_with_identity_headers(sent):
    calls, fake = sent
    fake.response = FakeResponse(201, body={"requests": [{"id": "r"}]})
    items = [{"equipmentId": "e", "quantityRequested": 2, "technicalRequirements": ""}]

    assert clients.create_event_requests(HEADERS, "ev", items) == [{"id": "r"}]

    method, url, kwargs = calls[0]
    assert (method, url) == ("POST", "http://localhost:5011/events/ev/equipment-requests")
    assert kwargs["json"] == {"items": items, "notificationContext": {"eventId": "ev"}}
    assert kwargs["headers"] == {"X-Dev-User-Id": "u", "X-Dev-Role": "Technical Support", "X-Internal-Token": "synthetic"}


# Review AC1 / Reservation AC2 (supporting lookup): resolve summaries for the requested event IDs.
def test_event_summaries_are_fetched_in_chunks_of_100(sent):
    calls, fake = sent
    fake.response = FakeResponse(body={"events": [{"id": "x"}]})

    assert len(clients.get_event_summaries([str(i) for i in range(150)])) == 2
    assert len(calls) == 2 and calls[0][1] == "http://localhost:5003/events/summaries"
    assert len(calls[1][2]["params"]["ids"].split(",")) == 50


# Review AC3 (transport): obtain only event IDs assigned to the current coordinator.
def test_list_assigned_event_ids_uses_coordinator_scoped_event_endpoint(sent):
    calls, fake = sent
    fake.response = FakeResponse(body={"events": [{"id": "event-1"}, {"id": "event-2"}]})

    assert clients.list_assigned_event_ids("coordinator-1") == ["event-1", "event-2"]
    assert calls[0][0:2] == ("GET", "http://localhost:5003/events")
    assert calls[0][2]["params"] == {"coordinatorId": "coordinator-1"}


# Reservation AC1 / Availability AC1/AC2 (transport): fetch overlapping events and the equipment catalogue.
def test_overlapping_events_and_equipment_calls(sent):
    calls, fake = sent
    fake.response = FakeResponse(body={"events": [], "equipment": [{"id": "e"}]})

    assert clients.get_overlapping_events("s", "e", ("Approved", "Confirmed", "Submitted"), "ev") == []
    assert clients.list_equipment() == [{"id": "e"}]
    assert calls[0][2]["params"] == {"start": "s", "end": "e", "statuses": "Approved,Confirmed,Submitted", "excludeEventId": "ev"}
    assert calls[1][1] == "http://localhost:5002/equipment"


# Availability AC1/AC2 (supporting configuration): allow the catalogue endpoint to follow deployment settings.
def test_base_urls_can_be_overridden(sent, monkeypatch):
    calls, fake = sent
    fake.response = FakeResponse(body={"equipment": []})
    monkeypatch.setenv("EQUIPMENT_SERVICE_URL", "http://equipment-service:5000")
    clients.list_equipment()
    assert calls[0][1] == "http://equipment-service:5000/equipment"


@pytest.mark.parametrize("status", [401, 403, 404, 409])
def test_expected_downstream_errors_pass_through_with_their_message(sent, status):
    # Review AC1/AC2 (failure transport): preserve expected downstream authorization and decision errors.
    _, fake = sent
    fake.response = FakeResponse(status, {"message": "nope"})
    with pytest.raises(DownstreamError) as error:
        clients.get_request(HEADERS, "r")
    assert (error.value.status, error.value.message) == (status, "nope")


@pytest.mark.parametrize("response", [FakeResponse(500, {"message": "db password"}), FakeResponse(400, json_error=True), FakeResponse(500, ["x"])])
def test_other_downstream_failures_become_502_with_a_generic_message_for_bad_bodies(sent, response):
    # Review AC1/AC2 (failure transport): handle malformed or unexpected downstream errors safely.
    _, fake = sent
    fake.response = response
    with pytest.raises(DownstreamError) as error:
        clients.get_request(HEADERS, "r")
    assert error.value.status == 502


# Review AC1/AC2 (failure transport): report an unreachable dependency rather than false success.
def test_unreachable_service_is_503(monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr("app.clients.httpx.request", boom)
    with pytest.raises(DownstreamError) as error:
        clients.list_equipment()
    assert error.value.status == 503
