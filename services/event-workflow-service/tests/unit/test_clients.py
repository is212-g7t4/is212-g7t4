"""Each client wrapper maps downstream answers to the service's own exceptions."""
import httpx
import pytest

from app import clients


class Reply:
    def __init__(self, status=200, body=None, json_error=False):
        self.status_code = status
        self.is_success = 200 <= status < 300
        self._body = body
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError
        return self._body


@pytest.fixture
def send(monkeypatch):
    sent = []
    replies = []

    def fake(method, url, **kwargs):
        sent.append((method, url, kwargs))
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(httpx, "request", fake)
    return sent, replies


def test_a_timeout_is_its_own_error(send):
    _, replies = send
    replies.append(httpx.ReadTimeout("slow"))
    with pytest.raises(clients.DownstreamTimeout):
        clients.list_equipment()


def test_a_transport_failure_is_a_downstream_error(send):
    _, replies = send
    replies.append(httpx.ConnectError("down"))
    with pytest.raises(clients.DownstreamError):
        clients.list_equipment()


def test_a_server_error_is_a_downstream_error(send):
    _, replies = send
    replies.append(Reply(500, {}))
    with pytest.raises(clients.DownstreamError):
        clients.list_venues()


def test_get_user_returns_the_account_or_not_found(send):
    _, replies = send
    replies.extend([Reply(200, {"role": "Event Coordinator Lead"}), Reply(404, {})])
    assert clients.get_user("u1")["role"] == "Event Coordinator Lead"
    with pytest.raises(clients.UserNotFoundError):
        clients.get_user("u2")


def test_preview_sends_a_dry_run_with_the_internal_token(send, monkeypatch):
    sent, replies = send
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", "secret")
    replies.append(Reply(200, {"highImpactFields": []}))

    clients.preview_event_details("e1", "c1", {"eventName": "x"}, "Event Coordinator Lead")

    method, url, kwargs = sent[0]
    assert (method, url.endswith("/events/e1/details")) == ("PATCH", True)
    assert kwargs["json"] == {
        "coordinatorId": "c1",
        "changes": {"eventName": "x"},
        "dryRun": True,
        "actorRole": "Event Coordinator Lead",
    }
    assert kwargs["headers"] == {"X-Internal-Service-Token": "secret"}


def test_save_is_not_a_dry_run_and_omits_a_missing_role(send, monkeypatch):
    sent, replies = send
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", None)
    replies.append(Reply(200, {"id": "e1"}))

    assert clients.save_event_details("e1", "c1", {"eventName": "x"}) == {"id": "e1"}

    assert sent[0][2]["json"] == {"coordinatorId": "c1", "changes": {"eventName": "x"}, "dryRun": False}
    assert sent[0][2]["headers"] == {"X-Internal-Service-Token": ""}


@pytest.mark.parametrize("status", [400, 403, 404, 409])
def test_event_service_refusals_keep_their_status_and_body(send, status):
    _, replies = send
    replies.append(Reply(status, {"code": "X"}))
    with pytest.raises(clients.EventRejectedError) as raised:
        clients.save_event_details("e1", "c1", {"eventName": "x"})
    assert (raised.value.status, raised.value.body) == (status, {"code": "X"})


def test_an_unreadable_refusal_body_becomes_empty(send):
    _, replies = send
    replies.append(Reply(409, json_error=True))
    with pytest.raises(clients.EventRejectedError) as raised:
        clients.save_event_details("e1", "c1", {"eventName": "x"})
    assert raised.value.body == {}


def test_overlapping_events_are_read_with_the_window(send):
    sent, replies = send
    replies.append(Reply(200, {"events": [{"id": "o"}]}))

    assert clients.list_overlapping_events("s", "e", ("Approved", "Confirmed"), "e1") == [{"id": "o"}]

    assert sent[0][2]["params"] == {
        "start": "s",
        "end": "e",
        "statuses": "Approved,Confirmed",
        "excludeEventId": "e1",
    }


def test_each_read_unwraps_its_list(send):
    _, replies = send
    replies.extend(
        [
            Reply(200, {"bookings": ["b"]}),
            Reply(200, {"venues": ["v"]}),
            Reply(200, {"requests": ["r"]}),
            Reply(200, {"requests": ["a"]}),
            Reply(200, {"equipment": ["q"]}),
        ]
    )
    assert clients.get_event_venue_bookings("e1") == ["b"]
    assert clients.list_venues() == ["v"]
    assert clients.list_event_equipment_requests("e1", "c1") == ["r"]
    assert clients.list_approved_equipment_requests(["o1", "o2"], "c1") == ["a"]
    assert clients.list_equipment() == ["q"]


def test_equipment_requests_are_read_as_an_event_coordinator(send):
    sent, replies = send
    replies.extend([Reply(200, {"requests": []}), Reply(200, {"requests": []})])

    clients.list_event_equipment_requests("e1", "c1")
    clients.list_approved_equipment_requests(["o1", "o2"], "c1")

    assert sent[0][2]["params"] == {"eventId": "e1"}
    assert sent[1][2]["params"] == {"status": "Approved", "eventIds": "o1,o2"}
    for _, _, kwargs in sent:
        assert kwargs["headers"] == {"X-Dev-User-Id": "c1", "X-Dev-Role": "Event Coordinator"}
