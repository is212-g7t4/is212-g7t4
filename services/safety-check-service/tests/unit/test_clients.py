"""SCRUM-149: each downstream wrapper's request shape and status mapping.

A composite is the only service allowed to call other services, so these are
the calls that make the submit workflow work — and the one place where another
service's status codes become this service's own exceptions. `httpx` is mocked
(unit tests are hermetic; `pytest-socket` would block a real call anyway).

Every failure maps to `DownstreamError`/`DownstreamTimeout` with no downstream
URL or error text attached: the routes must not be able to leak our topology
into a browser response.
"""
import httpx
import pytest

from app import clients
from tests.unit.factories import (
    BOOKING_ID,
    COORDINATOR_ID,
    EVENT_ID,
    OFFICER_ID,
    RECORD_ID,
    booking,
    equipment_request,
    event,
    record,
    user,
)


class Response:
    def __init__(self, status_code=200, payload=None, text="{}"):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    @property
    def is_success(self):
        return 200 <= self.status_code < 300

    def json(self):
        if self._payload is None:
            raise ValueError("not JSON")
        return self._payload


@pytest.fixture
def sent(monkeypatch):
    """Record every httpx call and hand back a queued response."""
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


# --- Event Service -----------------------------------------------------------


def test_get_event_scopes_the_read_to_the_coordinator(sent):
    """Event Service does AC5's check, so the coordinator travels with the read."""
    calls, queue = sent
    queue.append(Response(200, event("Approved")))

    assert clients.get_event(EVENT_ID, COORDINATOR_ID)["status"] == "Approved"
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith(f"/events/{EVENT_ID}")
    assert calls[0]["params"] == {"coordinatorId": COORDINATOR_ID}
    assert calls[0]["timeout"] == clients.TIMEOUT


def test_get_event_passes_viewer_role_when_given(sent):
    """SCRUM-150: the Safety Officer reads with viewerRole, not as the coordinator."""
    calls, queue = sent
    queue.append(Response(200, event("Pending Safety Check")))

    clients.get_event(EVENT_ID, OFFICER_ID, viewer_role="Safety Officer")

    assert calls[0]["params"] == {
        "coordinatorId": OFFICER_ID,
        "viewerRole": "Safety Officer",
    }


def test_get_event_without_viewer_role_omits_it(sent):
    calls, queue = sent
    queue.append(Response(200, event("Approved")))

    clients.get_event(EVENT_ID, COORDINATOR_ID, viewer_role=None)

    assert calls[0]["params"] == {"coordinatorId": COORDINATOR_ID}


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (404, clients.EventNotFoundError),
        (403, clients.EventNotAssignedError),
        (400, clients.DownstreamError),
        (500, clients.DownstreamError),
        (503, clients.DownstreamError),
    ],
)
def test_get_event_status_mapping(status, expected, sent):
    _, queue = sent
    queue.append(Response(status, {"message": "postgres://secret@host/db"}))

    with pytest.raises(expected):
        clients.get_event(EVENT_ID, COORDINATOR_ID)


def test_set_event_safety_status_sends_the_round(sent, monkeypatch):
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", "shared-secret")
    calls, queue = sent
    queue.append(Response(200, event("Pending Safety Check")))

    updated = clients.set_event_safety_status(
        EVENT_ID,
        "Pending Safety Check",
        RECORD_ID,
        2,
        coordinator_id=COORDINATOR_ID,
    )

    assert updated["status"] == "Pending Safety Check"
    assert calls[0]["method"] == "PATCH"
    assert calls[0]["url"].endswith(f"/events/{EVENT_ID}/safety-status")
    assert calls[0]["json"] == {
        "status": "Pending Safety Check",
        "safetyCheckId": RECORD_ID,
        "roundNumber": 2,
        "coordinatorId": COORDINATOR_ID,
    }
    assert calls[0]["headers"] == {"X-Internal-Service-Token": "shared-secret"}


def test_set_event_safety_status_sends_decided_by_and_remarks_for_approve(sent):
    """SCRUM-150: approving sends decidedBy and remarks, not coordinatorId."""
    calls, queue = sent
    queue.append(Response(200, event("Confirmed")))

    clients.set_event_safety_status(
        EVENT_ID,
        "Confirmed",
        RECORD_ID,
        1,
        decided_by=OFFICER_ID,
        remarks="Looks safe.",
    )

    assert calls[0]["json"] == {
        "status": "Confirmed",
        "safetyCheckId": RECORD_ID,
        "roundNumber": 1,
        "decidedBy": OFFICER_ID,
        "remarks": "Looks safe.",
    }


def test_set_event_safety_status_sends_areas_when_given(sent):
    """SCRUM-151: a change request's areas travel with the move."""
    calls, queue = sent
    queue.append(Response(200, event("Safety Changes Requested")))

    clients.set_event_safety_status(
        EVENT_ID,
        "Safety Changes Requested",
        RECORD_ID,
        1,
        decided_by=OFFICER_ID,
        remarks="Needs another look.",
        areas=["venue arrangement"],
    )

    assert calls[0]["json"] == {
        "status": "Safety Changes Requested",
        "safetyCheckId": RECORD_ID,
        "roundNumber": 1,
        "decidedBy": OFFICER_ID,
        "remarks": "Needs another look.",
        "areas": ["venue arrangement"],
    }


def test_set_event_safety_status_omits_areas_when_not_given(sent):
    calls, queue = sent
    queue.append(Response(200, event("Cancelled")))

    clients.set_event_safety_status(
        EVENT_ID, "Cancelled", RECORD_ID, 1, decided_by=OFFICER_ID, remarks="Unsafe."
    )

    assert "areas" not in calls[0]["json"]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (404, clients.EventNotFoundError),
        (500, clients.DownstreamError),
    ],
)
def test_set_event_safety_status_mapping(status, expected, sent):
    _, queue = sent
    queue.append(Response(status, {"message": "nope"}))

    with pytest.raises(expected):
        clients.set_event_safety_status(
            EVENT_ID, "Pending Safety Check", RECORD_ID, 1, coordinator_id=COORDINATOR_ID
        )


def test_set_event_safety_status_403_without_internal_only_code_is_not_assigned(sent):
    """A plain 403 (AC5) is still EventNotAssignedError, not a credentials error."""
    _, queue = sent
    queue.append(Response(403, {"message": "nope"}))

    with pytest.raises(clients.EventNotAssignedError):
        clients.set_event_safety_status(
            EVENT_ID, "Pending Safety Check", RECORD_ID, 1, coordinator_id=COORDINATOR_ID
        )


def test_set_event_safety_status_403_internal_only_is_a_credentials_error(sent):
    """SCRUM-150: Event Service refusing our token is our problem, not the caller's."""
    _, queue = sent
    queue.append(Response(403, {"code": "INTERNAL_ONLY", "message": "nope"}))

    with pytest.raises(clients.ServiceCredentialsError):
        clients.set_event_safety_status(
            EVENT_ID, "Confirmed", RECORD_ID, 1, decided_by=OFFICER_ID
        )


@pytest.mark.parametrize(
    "code", ["SAFETY_CHECK_ALREADY_PENDING", "INVALID_SAFETY_TRANSITION", "STALE_SAFETY_CHECK"]
)
def test_event_conflicts_keep_their_code(code, sent):
    """The routes branch on the code, so it has to survive the trip."""
    _, queue = sent
    queue.append(Response(409, {"code": code, "currentStatus": "Cancelled"}))

    with pytest.raises(clients.EventTransitionError) as raised:
        clients.set_event_safety_status(
            EVENT_ID, "Pending Safety Check", RECORD_ID, 1, coordinator_id=COORDINATOR_ID
        )

    assert raised.value.code == code
    assert raised.value.body["currentStatus"] == "Cancelled"


def test_event_conflict_without_a_json_body(sent):
    """Boundary: a 409 that isn't JSON still becomes a transition error, not a 500."""
    _, queue = sent
    queue.append(Response(409, None))

    with pytest.raises(clients.EventTransitionError) as raised:
        clients.set_event_safety_status(
            EVENT_ID, "Pending Safety Check", RECORD_ID, 1, coordinator_id=COORDINATOR_ID
        )

    assert raised.value.code is None
    assert raised.value.body == {}


# --- Venue Availability Service ---------------------------------------------


def test_bookings_are_read_for_the_whole_event(sent):
    """Every booking, all statuses: an event can have several (SCRUM-156)."""
    calls, queue = sent
    queue.append(Response(200, {"bookings": [booking("Approved")]}))

    bookings = clients.get_event_venue_bookings(EVENT_ID)

    assert [b["id"] for b in bookings] == [BOOKING_ID]
    assert calls[0]["url"].endswith(f"/events/{EVENT_ID}/venue-bookings")


def test_booking_read_failure_is_a_downstream_error(sent):
    _, queue = sent
    queue.append(Response(503, {"message": "DATABASE_URL is not configured"}))

    with pytest.raises(clients.DownstreamError):
        clients.get_event_venue_bookings(EVENT_ID)


def test_cancel_venue_booking_sends_the_event_id(sent):
    """SCRUM-151 AC5: releasing a booking on a safety rejection."""
    calls, queue = sent
    queue.append(Response(200, booking("Cancelled")))

    cancelled = clients.cancel_venue_booking(BOOKING_ID, EVENT_ID)

    assert cancelled["status"] == "Cancelled"
    assert calls[0]["method"] == "PATCH"
    assert calls[0]["url"].endswith(f"/venue-bookings/{BOOKING_ID}/cancel")
    assert calls[0]["json"] == {"eventId": EVENT_ID}


def test_cancel_venue_booking_missing_is_not_found(sent):
    _, queue = sent
    queue.append(Response(404, {"message": "no"}))

    with pytest.raises(clients.RecordNotFoundError):
        clients.cancel_venue_booking(BOOKING_ID, EVENT_ID)


def test_cancel_venue_booking_failure_is_a_downstream_error(sent):
    _, queue = sent
    queue.append(Response(503, {"message": "down"}))

    with pytest.raises(clients.DownstreamError):
        clients.cancel_venue_booking(BOOKING_ID, EVENT_ID)


# --- Equipment Request Service ----------------------------------------------


def test_equipment_requests_are_read_with_dev_identity_headers(sent):
    """Contract: that endpoint is behind the DEV headers, and READ_ROLES
    already allow Event Coordinators — so we send the caller's own identity."""
    calls, queue = sent
    queue.append(Response(200, {"requests": [equipment_request("Approved")]}))

    clients.get_event_equipment_requests(EVENT_ID, COORDINATOR_ID)

    assert calls[0]["params"] == {"eventId": EVENT_ID}
    assert calls[0]["headers"] == {
        "X-Dev-User-Id": COORDINATOR_ID,
        "X-Dev-Role": "Event Coordinator",
    }


def test_equipment_read_rejection_is_a_downstream_error(sent):
    """A 403 here is a misconfiguration, not the caller's fault — so not AC5's 403."""
    _, queue = sent
    queue.append(Response(403, {"message": "Only Technical Support ..."}))

    with pytest.raises(clients.DownstreamError):
        clients.get_event_equipment_requests(EVENT_ID, COORDINATOR_ID)


# --- Safety Check Record Service --------------------------------------------


def test_create_record_sends_the_notes(sent):
    calls, queue = sent
    queue.append(Response(201, record()))

    created = clients.create_safety_check_record(
        EVENT_ID, COORDINATOR_ID, "Speakers on the left.", "Enter via Door A."
    )

    assert created["roundNumber"] == 1
    assert calls[0]["method"] == "POST"
    assert calls[0]["json"] == {
        "eventId": EVENT_ID,
        "submittedBy": COORDINATOR_ID,
        "equipmentPlacementNotes": "Speakers on the left.",
        "crowdMovementNotes": "Enter via Door A.",
    }


def test_create_record_omits_absent_notes_as_null(sent):
    _, queue = sent
    queue.append(Response(201, record()))

    clients.create_safety_check_record(EVENT_ID, COORDINATOR_ID)

    assert queue == []


def test_create_record_conflict_carries_the_open_round(sent):
    """AC4: the open round comes back so the route can say when it was submitted."""
    _, queue = sent
    queue.append(
        Response(409, {"code": "SAFETY_CHECK_ALREADY_PENDING", "safetyCheck": record()})
    )

    with pytest.raises(clients.SafetyCheckAlreadyPendingError) as raised:
        clients.create_safety_check_record(EVENT_ID, COORDINATOR_ID)

    assert raised.value.existing["roundNumber"] == 1


def test_create_record_conflict_without_a_body(sent):
    _, queue = sent
    queue.append(Response(409, None))

    with pytest.raises(clients.SafetyCheckAlreadyPendingError) as raised:
        clients.create_safety_check_record(EVENT_ID, COORDINATOR_ID)

    assert raised.value.existing is None


def test_create_record_failure_is_a_downstream_error(sent):
    _, queue = sent
    queue.append(Response(400, {"message": "eventId must be a valid UUID."}))

    with pytest.raises(clients.DownstreamError):
        clients.create_safety_check_record(EVENT_ID, COORDINATOR_ID)


def test_list_records_filters_by_status(sent):
    calls, queue = sent
    queue.append(Response(200, {"safetyChecks": [record()]}))

    rounds = clients.list_safety_check_records(EVENT_ID, status="Pending")

    assert rounds[0]["status"] == "Pending"
    assert calls[0]["params"] == {"eventId": EVENT_ID, "status": "Pending"}


def test_list_records_without_a_status_filter(sent):
    calls, queue = sent
    queue.append(Response(200, {"safetyChecks": []}))

    assert clients.list_safety_check_records(EVENT_ID) == []
    assert calls[0]["params"] == {"eventId": EVENT_ID}


def test_list_records_failure_is_a_downstream_error(sent):
    _, queue = sent
    queue.append(Response(503, {"message": "down"}))

    with pytest.raises(clients.DownstreamError):
        clients.list_safety_check_records(EVENT_ID)


def test_delete_record_accepts_204(sent):
    """Compensation: 204 is the success case, with no body to parse."""
    calls, queue = sent
    queue.append(Response(204, None))

    assert clients.delete_safety_check_record(RECORD_ID) is None
    assert calls[0]["method"] == "DELETE"
    assert calls[0]["url"].endswith(f"/safety-check-records/{RECORD_ID}")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (404, clients.RecordNotFoundError),
        (409, clients.DownstreamError),
        (503, clients.DownstreamError),
    ],
)
def test_delete_record_mapping(status, expected, sent):
    _, queue = sent
    queue.append(Response(status, {"message": "no"}))

    with pytest.raises(expected):
        clients.delete_safety_check_record(RECORD_ID)


def test_decide_record_sends_the_decision(sent):
    calls, queue = sent
    queue.append(Response(200, record(status="Safety Approved", decidedBy=OFFICER_ID)))

    decided = clients.decide_safety_check_record(
        RECORD_ID, "Safety Approved", OFFICER_ID, "Looks safe."
    )

    assert decided["status"] == "Safety Approved"
    assert calls[0]["method"] == "PATCH"
    assert calls[0]["url"].endswith(f"/safety-check-records/{RECORD_ID}/decision")
    assert calls[0]["json"] == {
        "status": "Safety Approved",
        "decidedBy": OFFICER_ID,
        "remarks": "Looks safe.",
    }


def test_decide_record_sends_flags_when_given(sent):
    """SCRUM-151: a change request's flags travel with the decision."""
    calls, queue = sent
    queue.append(Response(200, record(status="Changes Requested")))

    flags = [{"area": "venue arrangement", "changeRequired": "Move the stage."}]
    clients.decide_safety_check_record(
        RECORD_ID, "Changes Requested", OFFICER_ID, "Needs another look.", flags
    )

    assert calls[0]["json"] == {
        "status": "Changes Requested",
        "decidedBy": OFFICER_ID,
        "remarks": "Needs another look.",
        "flags": flags,
    }


def test_decide_record_omits_flags_when_not_given(sent):
    calls, queue = sent
    queue.append(Response(200, record(status="Safety Approved")))

    clients.decide_safety_check_record(RECORD_ID, "Safety Approved", OFFICER_ID, "Looks safe.")

    assert "flags" not in calls[0]["json"]


def test_decide_record_conflict_carries_the_existing_round(sent):
    _, queue = sent
    queue.append(
        Response(
            409,
            {"code": "SAFETY_CHECK_ALREADY_DECIDED", "safetyCheck": record(status="Safety Approved")},
        )
    )

    with pytest.raises(clients.SafetyCheckAlreadyDecidedError) as raised:
        clients.decide_safety_check_record(RECORD_ID, "Safety Approved", OFFICER_ID)

    assert raised.value.existing["status"] == "Safety Approved"


def test_decide_record_missing_round_is_not_found(sent):
    _, queue = sent
    queue.append(Response(404, {"message": "no"}))

    with pytest.raises(clients.RecordNotFoundError):
        clients.decide_safety_check_record(RECORD_ID, "Safety Approved", OFFICER_ID)


def test_decide_record_failure_is_a_downstream_error(sent):
    _, queue = sent
    queue.append(Response(503, {"message": "down"}))

    with pytest.raises(clients.DownstreamError):
        clients.decide_safety_check_record(RECORD_ID, "Safety Approved", OFFICER_ID)


def test_reopen_record_sends_decided_at(sent):
    calls, queue = sent
    queue.append(Response(200, record(status="Pending")))

    clients.reopen_safety_check_record(RECORD_ID, "2026-11-02T03:00:00+00:00")

    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith(f"/safety-check-records/{RECORD_ID}/reopen")
    assert calls[0]["json"] == {"decidedAt": "2026-11-02T03:00:00+00:00"}


def test_reopen_record_missing_round_is_not_found(sent):
    _, queue = sent
    queue.append(Response(404, {"message": "no"}))

    with pytest.raises(clients.RecordNotFoundError):
        clients.reopen_safety_check_record(RECORD_ID, "2026-11-02T03:00:00+00:00")


def test_reopen_record_failure_is_a_downstream_error(sent):
    _, queue = sent
    queue.append(Response(409, {"message": "nope"}))

    with pytest.raises(clients.DownstreamError):
        clients.reopen_safety_check_record(RECORD_ID, "2026-11-02T03:00:00+00:00")


# --- User Service -------------------------------------------------------------


def test_get_user_returns_the_role(sent):
    calls, queue = sent
    queue.append(Response(200, user(role="Safety Officer")))

    found = clients.get_user(OFFICER_ID)

    assert found["role"] == "Safety Officer"
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith(f"/users/{OFFICER_ID}")


def test_get_user_not_found(sent):
    _, queue = sent
    queue.append(Response(404, {"message": "User not found."}))

    with pytest.raises(clients.UserNotFoundError):
        clients.get_user(OFFICER_ID)


def test_get_user_failure_is_a_downstream_error(sent):
    _, queue = sent
    queue.append(Response(503, {"message": "down"}))

    with pytest.raises(clients.DownstreamError):
        clients.get_user(OFFICER_ID)


# --- SCRUM-162: the queue's reads ----------------------------------------------


def test_list_events_by_status_reads_as_the_viewer_role(sent):
    """The officer isn't anyone's coordinator, so viewerRole lets them see all events."""
    calls, queue = sent
    queue.append(Response(200, {"events": [event("Pending Safety Check")]}))

    found = clients.list_events_by_status("Pending Safety Check", OFFICER_ID, "Safety Officer")

    assert found[0]["status"] == "Pending Safety Check"
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith("/events")
    assert calls[0]["params"] == {
        "coordinatorId": OFFICER_ID,
        "viewerRole": "Safety Officer",
        "status": "Pending Safety Check",
    }


@pytest.mark.parametrize("status", [400, 403, 503])
def test_list_events_by_status_failure_is_a_downstream_error(status, sent):
    _, queue = sent
    queue.append(Response(status, {"message": "no"}))

    with pytest.raises(clients.DownstreamError):
        clients.list_events_by_status("Pending Safety Check", OFFICER_ID, "Safety Officer")


def test_list_venues_reads_the_whole_catalogue(sent):
    calls, queue = sent
    queue.append(Response(200, {"venues": [{"id": "v1", "name": "Main Hall"}]}))

    assert clients.list_venues() == [{"id": "v1", "name": "Main Hall"}]
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith("/venues")
    assert "params" not in calls[0]


def test_list_venues_failure_is_a_downstream_error(sent):
    _, queue = sent
    queue.append(Response(503, {"message": "down"}))

    with pytest.raises(clients.DownstreamError):
        clients.list_venues()


# --- Transport failures ------------------------------------------------------


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (httpx.ReadTimeout("too slow"), clients.DownstreamTimeout),
        (httpx.ConnectTimeout("too slow"), clients.DownstreamTimeout),
        (httpx.ConnectError("refused"), clients.DownstreamError),
        (httpx.RemoteProtocolError("garbage"), clients.DownstreamError),
    ],
)
def test_transport_failures_are_mapped(raised, expected, sent):
    """A timeout becomes a 504 upstream and anything else a 502 — never a 500."""
    _, queue = sent
    queue.append(raised)

    with pytest.raises(expected):
        clients.get_event(EVENT_ID, COORDINATOR_ID)


def test_default_urls_are_the_host_ports():
    """`uv run flask run` outside Docker must work without an .env."""
    assert clients.EVENT_SERVICE_URL.endswith((":5003", ":5000"))
    assert clients.VENUE_AVAILABILITY_SERVICE_URL.endswith((":5008", ":5000"))
    assert clients.EQUIPMENT_REQUEST_SERVICE_URL.endswith((":5011", ":5000"))
    assert clients.SAFETY_CHECK_RECORD_SERVICE_URL.endswith((":5013", ":5000"))
    assert clients.USER_SERVICE_URL.endswith((":5001", ":5000"))
    assert clients.VENUE_SERVICE_URL.endswith((":5006", ":5000"))
