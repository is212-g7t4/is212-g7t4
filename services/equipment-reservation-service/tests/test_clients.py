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

    def fake(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return fake.response

    fake.response = FakeResponse(body={})
    monkeypatch.setattr("app.clients.httpx.request", fake)
    return calls, fake


def test_list_requests_forwards_only_identity_headers_and_filters(sent):
    calls, fake = sent
    fake.response = FakeResponse(body={"requests": [1]})

    assert clients.list_requests(HEADERS, "Approved", ["a", "b"]) == [1]

    method, url, kwargs = calls[0]
    assert (method, url) == ("GET", "http://localhost:5009/equipment-requests")
    assert kwargs["params"] == {"status": "Approved", "eventIds": "a,b"}
    assert kwargs["headers"] == {"X-Dev-User-Id": "u", "X-Dev-Role": "Technical Support"}


def test_list_requests_with_no_event_ids_skips_the_call(sent):
    calls, _ = sent
    assert clients.list_requests(HEADERS, "Approved", []) == []
    assert calls == []


def test_list_requests_without_filters(sent):
    calls, fake = sent
    fake.response = FakeResponse(body={"requests": []})
    clients.list_requests(HEADERS)
    assert calls[0][2]["params"] == {}


def test_get_and_review_calls(sent):
    calls, fake = sent
    fake.response = FakeResponse(body={"request": {"id": "r"}, "requests": [{"id": "r"}]})

    assert clients.get_request(HEADERS, "r") == {"id": "r"}
    assert clients.review_request(HEADERS, "r", "Approved") == {"id": "r"}
    assert clients.review_event_requests(HEADERS, "ev", "Rejected") == [{"id": "r"}]

    assert [(c[0], c[1]) for c in calls] == [
        ("GET", "http://localhost:5009/equipment-requests/r"),
        ("PATCH", "http://localhost:5009/equipment-requests/r"),
        ("PATCH", "http://localhost:5009/events/ev/equipment-requests"),
    ]
    assert calls[1][2]["json"] == {"status": "Approved"}


def test_event_summaries_are_fetched_in_chunks_of_100(sent):
    calls, fake = sent
    fake.response = FakeResponse(body={"events": [{"id": "x"}]})

    assert len(clients.get_event_summaries([str(i) for i in range(150)])) == 2
    assert len(calls) == 2 and calls[0][1] == "http://localhost:5003/events/summaries"
    assert len(calls[1][2]["params"]["ids"].split(",")) == 50


def test_list_assigned_event_ids_uses_coordinator_scoped_event_endpoint(sent):
    calls, fake = sent
    fake.response = FakeResponse(body={"events": [{"id": "event-1"}, {"id": "event-2"}]})

    assert clients.list_assigned_event_ids("coordinator-1") == ["event-1", "event-2"]
    assert calls[0][0:2] == ("GET", "http://localhost:5003/events")
    assert calls[0][2]["params"] == {"coordinatorId": "coordinator-1"}


def test_overlapping_events_and_equipment_calls(sent):
    calls, fake = sent
    fake.response = FakeResponse(body={"events": [], "equipment": [{"id": "e"}]})

    assert clients.get_overlapping_events("s", "e", ("Approved", "Confirmed", "Submitted"), "ev") == []
    assert clients.list_equipment() == [{"id": "e"}]
    assert calls[0][2]["params"] == {"start": "s", "end": "e", "statuses": "Approved,Confirmed,Submitted", "excludeEventId": "ev"}
    assert calls[1][1] == "http://localhost:5002/equipment"


def test_base_urls_can_be_overridden(sent, monkeypatch):
    calls, fake = sent
    fake.response = FakeResponse(body={"equipment": []})
    monkeypatch.setenv("EQUIPMENT_SERVICE_URL", "http://equipment-service:5000")
    clients.list_equipment()
    assert calls[0][1] == "http://equipment-service:5000/equipment"


@pytest.mark.parametrize("status", [401, 403, 404, 409])
def test_expected_downstream_errors_pass_through_with_their_message(sent, status):
    _, fake = sent
    fake.response = FakeResponse(status, {"message": "nope"})
    with pytest.raises(DownstreamError) as error:
        clients.get_request(HEADERS, "r")
    assert (error.value.status, error.value.message) == (status, "nope")


@pytest.mark.parametrize("response", [FakeResponse(500, {"message": "db password"}), FakeResponse(400, json_error=True), FakeResponse(500, ["x"])])
def test_other_downstream_failures_become_502_with_a_generic_message_for_bad_bodies(sent, response):
    _, fake = sent
    fake.response = response
    with pytest.raises(DownstreamError) as error:
        clients.get_request(HEADERS, "r")
    assert error.value.status == 502


def test_unreachable_service_is_503(monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr("app.clients.httpx.request", boom)
    with pytest.raises(DownstreamError) as error:
        clients.list_equipment()
    assert error.value.status == 503
