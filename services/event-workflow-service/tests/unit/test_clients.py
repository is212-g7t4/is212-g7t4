"""
SCRUM-20: Event Information Management & Impact Validation

User Story
----------
As the Event Coordinator assigned to an event, I want to update event
information during the planning process, so that event details remain up to
date without introducing conflicts with arrangements already made for the
event.

Acceptance Criteria
-------------------
AC1: Given a field being updated is one of the low-impact fields (Event Name,
     Description, Purpose, Registration Needs), when the assigned Event
     Coordinator saves the change, then the update is applied and the system
     records the new information.
AC2: Given a field being updated is one of the high-impact fields (Date/Time,
     Expected Attendance, Venue Requirements, Equipment Requirements,
     Accessibility Needs), when the assigned Event Coordinator attempts to save
     the change, then the system checks the update against other arrangements
     already made for the event (e.g. confirmed venue bookings, equipment
     reservations) for contradictions before the change is applied.
AC3: Given a high-impact update contradicts an existing arrangement, the update
     is blocked and the Coordinator is shown the reason.
AC4: Given a high-impact update passes validation with no contradiction found,
     then the update is applied and saved.

SCRUM-43: Review Event Change Requests

User Story
----------
As an Event Coordinator, I want to review and process change requests for
events I manage, so that I can assess the impact of changes and approve or
reject them appropriately.

Acceptance Criteria
-------------------
AC1: The Event Coordinator can view a list of pending change requests for
     events they manage.
AC2: For each change request, the Event Coordinator can see the event details
     and proposed changes (original vs proposed values), reason for change,
     attachments, request timestamp.
AC3: The Event Coordinator can approve the change request, where the system
     ppdates the event with the proposed changes, Changes the request status to
     'Approved', Records the Event Coordinator's identity, approval timestamp,
     and decision
AC4: The Event Coordinator can reject the change request with a reason
     (required), where the system Changes the request status to 'Rejected',
     Stores the rejection reason, Records the Event Coordinator's identity,
     rejection timestamp, and reason

Real
----
- app.clients: each downstream wrapper's request (URL, token, dry-run flag,
  actor role) and its mapping of timeouts, transport and server errors and
  refusals to the service's own exceptions run for real.
- Assertions are on the request sent and the exception or value returned.

Doubled
-------
- httpx (the `send` fixture): Stub - canned responses or raised errors; the
  outgoing requests are recorded and inspected.

Not proven
----------
- That the real services accept these requests (-> tests/integration/ with
  respx, and E2E journeys).
"""
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


def test_downstream_call_when_timing_out_raises_timeout(send):
    """
    Summary: A timeout is reported as its own error, separate from other failures.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (send raises TimeoutException)
    """
    _, replies = send
    replies.append(httpx.ReadTimeout("slow"))
    with pytest.raises(clients.DownstreamTimeout):
        clients.list_equipment()


def test_downstream_call_when_transport_fails_raises_downstream_error(send):
    """
    Summary: A connection failure is reported as a downstream error.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (send raises ConnectError)
    """
    _, replies = send
    replies.append(httpx.ConnectError("down"))
    with pytest.raises(clients.DownstreamError):
        clients.list_equipment()


def test_downstream_call_when_server_errors_raises_downstream_error(send):
    """
    Summary: A server error is reported as a downstream error.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (send answers 500)
    """
    _, replies = send
    replies.append(Reply(500, {}))
    with pytest.raises(clients.DownstreamError):
        clients.list_venues()


def test_get_user_returns_profile_or_none(send):
    """
    Summary: A user's profile is read, or reported missing.
    AC1: Given a field being updated is one of the low-impact fields (Event
        Name, Description, Purpose, Registration Needs), when the assigned
        Event Coordinator saves the change, then the update is applied and the
        system records the new information.
    Double: Stub (send returns a user or 404)
    """
    _, replies = send
    replies.extend([Reply(200, {"role": "Event Coordinator Lead"}), Reply(404, {})])
    assert clients.get_user("u1")["role"] == "Event Coordinator Lead"
    with pytest.raises(clients.UserNotFoundError):
        clients.get_user("u2")


def test_preview_details_sends_dry_run_with_internal_token(send, monkeypatch):
    """
    Summary: The impact check asks Event Service for a dry run, as a trusted service.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (send returns a preview; request inspected)
    """
    sent, replies = send
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", "secret")
    replies.append(Reply(200, {"highImpactFields": []}))

    clients.preview_event_details("e1", {"eventName": "x"}, "Event Coordinator Lead")

    method, url, kwargs = sent[0]
    assert (method, url.endswith("/events/e1/details")) == ("PATCH", True)
    assert kwargs["json"] == {
        "changes": {"eventName": "x"},
        "dryRun": True,
        "actorRole": "Event Coordinator Lead",
    }
    assert kwargs["headers"] == {"X-Internal-Service-Token": "secret"}


def test_save_details_sends_real_save_without_empty_role(send, monkeypatch):
    """
    Summary: Saving is a real save and sends no empty actor role.
    AC1: Given a field being updated is one of the low-impact fields (Event
        Name, Description, Purpose, Registration Needs), when the assigned
        Event Coordinator saves the change, then the update is applied and the
        system records the new information.
    AC4: Given a high-impact update passes validation with no contradiction
        found, then the update is applied and saved.
    Double: Stub (send returns the event; request inspected)
    """
    sent, replies = send
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", None)
    replies.append(Reply(200, {"id": "e1"}))

    assert clients.save_event_details("e1", {"eventName": "x"}) == {"id": "e1"}

    assert sent[0][2]["json"] == {"changes": {"eventName": "x"}, "dryRun": False}
    assert sent[0][2]["headers"] == {"X-Internal-Service-Token": ""}


def test_change_request_clients_call_event_service_as_trusted_service(send, monkeypatch):
    """
    Summary: Change-request reads and decisions go to Event Service as a trusted service.
    SCRUM-43 AC1: The Event Coordinator can view a list of pending change
        requests for events they manage.
    SCRUM-43 AC3: The Event Coordinator can approve the change request, where
        the system ppdates the event with the proposed changes, Changes the
        request status to 'Approved', Records the Event Coordinator's identity,
        approval timestamp, and decision
    Double: Stub (send returns rows; requests inspected)
    """
    sent, replies = send
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", "secret")
    replies.extend([
        Reply(200, {"changeRequests": [{"id": "c1"}]}),
        Reply(200, {"id": "c1"}),
        Reply(200, {"id": "c1", "status": "Rejected"}),
    ])

    assert clients.list_pending_change_requests() == [{"id": "c1"}]
    assert clients.get_change_request("c1") == {"id": "c1"}
    assert clients.decide_change_request("c1", "Rejected", "No") == {
        "id": "c1", "status": "Rejected"
    }
    assert "params" not in sent[0][2] and "params" not in sent[1][2]
    assert sent[2][2]["json"] == {"decision": "Rejected", "reason": "No"}
    assert all(call[2]["headers"] == {"X-Internal-Service-Token": "secret"} for call in sent)


def test_approve_change_request_client_sends_no_reason(send):
    """
    Summary: An approval is sent without a rejection reason.
    SCRUM-43 AC3: The Event Coordinator can approve the change request, where
        the system ppdates the event with the proposed changes, Changes the
        request status to 'Approved', Records the Event Coordinator's identity,
        approval timestamp, and decision
    Double: Stub (send; request inspected)
    """
    sent, replies = send
    replies.append(Reply(200, {"status": "Approved"}))
    clients.decide_change_request("c1", "Approved")
    assert sent[0][2]["json"] == {"decision": "Approved"}


def test_change_request_client_when_refused_keeps_status_and_body(send):
    """
    Summary: Event Service's refusal of a change-request call keeps its status and body.
    SCRUM-43 AC3: The Event Coordinator can approve the change request, where
        the system ppdates the event with the proposed changes, Changes the
        request status to 'Approved', Records the Event Coordinator's identity,
        approval timestamp, and decision
    Double: Stub (send answers 409)
    """
    _, replies = send
    replies.append(Reply(409, {"code": "ALREADY_DECIDED"}))
    with pytest.raises(clients.EventRejectedError) as raised:
        clients.get_change_request("c1")
    assert raised.value.status == 409
    assert raised.value.body == {"code": "ALREADY_DECIDED"}


@pytest.mark.parametrize("status", [400, 403, 404, 409], ids=["bad_request", "forbidden", "not_found", "conflict"])
def test_event_client_when_refused_keeps_status_and_body(send, status):
    """
    Summary: Event Service refusals keep their status and body.
    AC3: Given a high-impact update contradicts an existing arrangement, the
        update is blocked and the Coordinator is shown the reason.
    Double: Stub (send answers the refusal)
    """
    _, replies = send
    replies.append(Reply(status, {"code": "X"}))
    with pytest.raises(clients.EventRejectedError) as raised:
        clients.save_event_details("e1", {"eventName": "x"})
    assert (raised.value.status, raised.value.body) == (status, {"code": "X"})


def test_event_client_when_refusal_unreadable_returns_empty_body(send):
    """
    Summary: A refusal whose body cannot be read is passed on with an empty body.
    AC3: Given a high-impact update contradicts an existing arrangement, the
        update is blocked and the Coordinator is shown the reason.
    Double: Stub (send answers 409 with non-JSON)
    """
    _, replies = send
    replies.append(Reply(409, json_error=True))
    with pytest.raises(clients.EventRejectedError) as raised:
        clients.save_event_details("e1", {"eventName": "x"})
    assert raised.value.body == {}


def test_overlapping_events_client_sends_the_time_window(send):
    """
    Summary: Overlapping events are looked up for the new time window.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (send; request inspected)
    """
    sent, replies = send
    replies.append(Reply(200, {"events": [{"id": "o"}]}))

    assert clients.list_overlapping_events("s", "e", ("Approved", "Confirmed"), "e1") == [{"id": "o"}]

    assert sent[0][2]["params"] == {
        "start": "s",
        "end": "e",
        "statuses": "Approved,Confirmed",
        "excludeEventId": "e1",
    }


def test_list_clients_return_the_inner_list(send):
    """
    Summary: Each list read returns the list inside the response.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (send returns wrapped lists)
    """
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
    assert clients.list_event_equipment_requests("e1") == ["r"]
    assert clients.list_approved_equipment_requests(["o1", "o2"]) == ["a"]
    assert clients.list_equipment() == ["q"]


def test_equipment_requests_client_sends_callers_token(send):
    """
    Summary: Equipment requests are read as the signed-in coordinator.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (send; headers inspected)
    """
    from app import create_app

    sent, replies = send
    replies.extend([Reply(200, {"requests": []}), Reply(200, {"requests": []})])

    with create_app().test_request_context(headers={"Authorization": "Bearer lead-token"}):
        clients.list_event_equipment_requests("e1")
        clients.list_approved_equipment_requests(["o1", "o2"])

    assert sent[0][2]["params"] == {"eventId": "e1"}
    assert sent[1][2]["params"] == {"status": "Approved", "eventIds": "o1,o2"}
    for _, _, kwargs in sent:
        assert kwargs["headers"] == {"Authorization": "Bearer lead-token"}
