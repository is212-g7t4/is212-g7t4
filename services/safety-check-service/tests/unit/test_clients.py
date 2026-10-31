"""SCRUM-149: Submit Event for Operational Safety Check

User Story
----------
As an Event Coordinator, I want to submit my event for an Operational Safety
Check once its venue and technical arrangements are confirmed, so that the
Safety Officer can review it before preparation begins.

Acceptance Criteria
-------------------
AC1: Given an event assigned to the Event Coordinator has at least one approved
     venue booking, and none of its venue bookings or equipment requests is
     still pending, when the Event Coordinator submits it for a safety check,
     then its status changes to 'Pending Safety Check' and the submission time
     is recorded. Rejected, cancelled or expired venue bookings and rejected
     equipment requests are no longer part of the event's arrangements and do
     not block submission.
AC2: Given any venue booking or equipment request for the event is still
     pending, or the event has no approved venue booking, when the Event
     Coordinator tries to submit, then submission is blocked and the
     outstanding arrangements are listed.
AC3: Given the Event Coordinator is submitting, when they enter equipment
     placement and expected crowd movement notes, then the notes are saved with
     the safety check.
AC4: Given the event is already 'Pending Safety Check', when the Event
     Coordinator submits it again, then no duplicate safety check is created.
AC5: Given the Event Coordinator is not the assigned coordinator, then the
     submit action is not available and an API call is rejected.

SCRUM-150: Approve Operational Safety Check

User Story
----------
As a Safety Officer, I want to approve an event's operational safety
arrangements, so that the event can proceed to preparation.

Acceptance Criteria
-------------------
AC1: Given an event is 'Pending Safety Check', when I approve it, then its
     status changes to 'Confirmed'.
AC2: Given I approve an event, then the safety check is recorded with the
     status 'Safety Approved', together with my identity, the approval
     timestamp and any optional remarks, in the event's history.
AC3: Given an event is not 'Pending Safety Check', then the approve action is
     not available and an API call is rejected without changing the event.
AC4: Given the safety check I approve follows a high-impact change, when I
     approve it, then the changed details become visible to registered
     Attendees.

SCRUM-151: Reject or Request Changes to Safety Arrangements

Agreed revision from this conversation; pending confirmation that Jira has been updated

User Story
----------
As a Safety Officer, I want to reject an event's safety arrangement or request
changes, stating which planning area must be revisited, so that the Event
Coordinator knows exactly what to fix before the event can proceed.

Acceptance Criteria
-------------------
AC1: Given an event is 'Pending Safety Check', when I request changes, then I
     must select at least one affected area (venue arrangement,
     technical/equipment arrangement, event details) and describe the change
     needed; otherwise the decision is not saved.
AC2: Given changes are requested, then the event status changes to 'Safety Changes Requested', the event returns to the planning stage for each selected area, and its existing arrangements are preserved. For equipment requests affected by the requested changes, only requests with status 'Approved' return to 'Pending' for review. Requests already 'Pending' or 'Rejected' remain unchanged, including any recorded reviewer and rejection reason.
AC3: Given an event is 'Pending Safety Check', when I reject it, then a reason
     is required and I must confirm the rejection before it is saved.
AC4: Given I confirm a rejection, then the event status changes to 'Cancelled',
     and the event cannot be resubmitted for a safety check or moved to any
     further stage.
AC5: Given an event is cancelled by a safety rejection, then its venue bookings
     and equipment reservations are released so they no longer block other
     events, while their records remain in the event's history.
AC6: Given either decision, then the safety check is recorded with the status
     'Changes Requested' or 'Safety Rejected' respectively, together with my
     identity, the timestamp and the reason (plus the selected areas for a
     change request), and the original event information is retained.
AC7: Given an event is not 'Pending Safety Check', then these actions are not
     available and an API call is rejected without changing the event.

SCRUM-153: Re-check Safety After High-Impact Changes

User Story
----------
As an Event Coordinator, I want a safety approval to be withdrawn when a
high-impact detail changes afterwards, so that the event is never prepared on
the basis of an outdated safety review.

Acceptance Criteria
-------------------
AC1: Given an event is 'Confirmed', when its date/time, expected attendance,
     venue requirements, equipment requirements or accessibility needs change,
     then its status returns to 'Pending Safety Check' and the coordinator is
     told why.
AC2: Given only a low-impact field changes (name, description, purpose,
     registration needs), then the event stays 'Confirmed'.
AC3: Given a safety approval is withdrawn, then it stays visible in the event's
     safety history.
AC4: Given a high-impact change to a 'Confirmed' event is waiting for its new
     safety check, when a registered Attendee views the event, then they still
     see the previously approved details, and the changed details are shown to
     them only after the Safety Officer approves the new safety check.
AC5: Given the new safety check ends without approval (changes requested or the
     event is cancelled), then registered Attendees are never shown the
     unapproved change, and they continue to see the last approved details or
     the cancellation.

SCRUM-162: View Safety Check Queue

User Story
----------
As a Safety Officer, I want to view a list of events awaiting an Operational
Safety Check, so that I know which events I need to review.

Acceptance Criteria
-------------------
AC1: The queue shows only events with status 'Pending Safety Check'.
AC2: Each entry shows event name, event date/time, venue(s), expected
     attendance and submission date, with the nearest event date first.
AC3: Given an event was resubmitted after an earlier decision, then it is
     labelled as a resubmission.
AC4: Given a decision is recorded for an event, then it no longer appears in
     the queue.

SCRUM-164: Revise Arrangements and Resubmit for Safety Check

Agreed revision from this conversation; pending confirmation that Jira has been updated

User Story
----------
As an Event Coordinator, I want to see the Safety Officer's feedback and revise
the affected arrangements, so that I can resubmit the event for a safety check
without redoing unaffected planning.

Acceptance Criteria
-------------------
AC1: Given my event is 'Safety Changes Requested', when I open it, then I see
     the decision, reason, requested changes and affected areas.
AC2: Given the venue arrangement is flagged, then the affected venue booking
     must be reviewed again by Venue Staff (revised booking or replacement
     request) before the event can be resubmitted.
AC3: Given the technical arrangement is flagged, then the affected equipment requests that were previously 'Approved' return to 'Pending' and must be approved again by Technical Support Staff before the event can be resubmitted. The safety-change action does not reopen existing 'Rejected' requests or clear their rejection reasons, and requests already 'Pending' remain 'Pending'.
AC4: Given an arrangement was not flagged, then it stays confirmed and does not
     need to be reviewed again.
AC5: Given all flagged arrangements are confirmed again, when I resubmit, then
     the status returns to 'Pending Safety Check' as a new review round, and
     earlier rounds remain in the history.

Real
----
- app.clients: each downstream wrapper's request (URL, token, viewer role,
  body) and its mapping of statuses, codes and transport errors to typed
  exceptions.
- Assertions are on the request sent and the exception or value returned.

Doubled
-------
- httpx: Stub (respx) - canned responses or raised errors; requests inspected.

Not proven
----------
- That the real services accept these requests (-> tests/integration/ with
  respx and E2E journey J6b).
"""
import httpx
import pytest

from app import clients, create_app
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

NEXT_RECORD_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


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
    # SCRUM-46: these legacy wrapper cases isolate request/error mapping. The
    # actual venue HTTP lookup is exercised in test_attendee_notifications.py.
    monkeypatch.setattr(clients, "attendee_venue_name", lambda event_id: "Hall A")
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


def test_reset_equipment_client_sends_scoped_ids_with_internal_auth(sent, monkeypatch):
    """
    Summary: Equipment resets name only the flagged requests and use internal credentials.
    SCRUM-164 AC3: Given the technical arrangement is flagged, then the
        affected equipment request must be reviewed again by Technical Support
        Staff before the event can be resubmitted.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", "test-token")
    queue.append(Response(200, {"requests": [equipment_request("Pending")]}))
    assert clients.reset_equipment_safety_requests(EVENT_ID, ["request-id"])[0]["status"] == "Pending"
    assert calls[0]["url"].endswith(f"/events/{EVENT_ID}/equipment-requests/safety-reset")
    assert calls[0]["json"] == {"requestIds": ["request-id"]}
    assert calls[0]["headers"] == {"X-Internal-Service-Token": "test-token"}


def test_reset_venue_client_uses_owner_with_internal_auth(sent, monkeypatch):
    """
    Summary: Venue resets go to Venue Availability with internal credentials.
    SCRUM-164 AC2: Given the venue arrangement is flagged, then the affected
        venue booking must be reviewed again by Venue Staff (revised booking or
        replacement request) before the event can be resubmitted.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", "test-token")
    queue.append(Response(200, {"bookings": []}))
    assert clients.reset_venue_safety_bookings(EVENT_ID, [BOOKING_ID]) == []
    assert calls[0]["url"].endswith(f"/events/{EVENT_ID}/venue-bookings/safety-reset")
    assert calls[0]["json"] == {"bookingIds": [BOOKING_ID]}
    assert calls[0]["headers"] == {"X-Internal-Service-Token": "test-token"}


def test_get_event_client_reads_as_the_coordinator(sent):
    """
    Summary: The event is read as the coordinator, so Event Service checks their assignment.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, event("Approved")))

    assert clients.get_event(EVENT_ID)["status"] == "Approved"
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith(f"/events/{EVENT_ID}")
    assert calls[0]["params"] == {}
    assert calls[0]["timeout"] == clients.TIMEOUT


def test_get_event_client_sends_viewer_role_when_given(sent):
    """
    Summary: A Safety Officer reads the event with their viewer role.
    SCRUM-150 AC1: Given an event is 'Pending Safety Check', when I approve it,
        then its status changes to 'Confirmed'.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, event("Pending Safety Check")))

    clients.get_event(EVENT_ID, viewer_role="Safety Officer")

    assert calls[0]["params"] == {"viewerRole": "Safety Officer"}


def test_get_event_client_without_viewer_role_omits_it(sent):
    """
    Summary: No viewer role is sent when none is given.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, event("Approved")))

    clients.get_event(EVENT_ID, viewer_role=None)

    assert calls[0]["params"] == {}


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
def test_get_event_client_maps_statuses(status, expected, sent):
    """
    Summary: Event read failures are mapped to typed errors.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(status, {"message": "postgres://secret@host/db"}))

    with pytest.raises(expected):
        clients.get_event(EVENT_ID)


def test_set_safety_status_client_sends_the_round(sent, monkeypatch):
    """
    Summary: Moving the event's safety status names the round.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (respx; request inspected)
    """
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", "shared-secret")
    calls, queue = sent
    queue.append(Response(200, event("Pending Safety Check")))

    updated = clients.set_event_safety_status(
        EVENT_ID,
        "Pending Safety Check",
        RECORD_ID,
        2,
    )

    assert updated["status"] == "Pending Safety Check"
    assert calls[0]["method"] == "PATCH"
    assert calls[0]["url"].endswith(f"/events/{EVENT_ID}/safety-status")
    assert calls[0]["json"] == {
        "status": "Pending Safety Check",
        "safetyCheckId": RECORD_ID,
        "roundNumber": 2,
    }
    assert calls[0]["headers"] == {"X-Internal-Service-Token": "shared-secret"}


def test_set_safety_status_client_sends_remarks_on_approve(sent):
    """
    Summary: Approving sends the remarks with the move.
    SCRUM-150 AC2: Given I approve an event, then the safety check is recorded
        with the status 'Safety Approved', together with my identity, the
        approval timestamp and any optional remarks, in the event's history.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, event("Confirmed")))

    clients.set_event_safety_status(
        EVENT_ID,
        "Confirmed",
        RECORD_ID,
        1,
        remarks="Looks safe.",
    )

    assert calls[0]["json"] == {
        "status": "Confirmed",
        "safetyCheckId": RECORD_ID,
        "roundNumber": 1,
        "remarks": "Looks safe.",
    }


def test_set_safety_status_client_sends_areas_for_changes(sent):
    """
    Summary: A change request's areas travel with the move.
    SCRUM-151 AC2: Given changes are requested, then the event status changes
        to 'Safety Changes Requested', the event returns to the planning stage
        for each selected area, and its existing arrangements are preserved.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, event("Safety Changes Requested")))

    clients.set_event_safety_status(
        EVENT_ID,
        "Safety Changes Requested",
        RECORD_ID,
        1,
        remarks="Needs another look.",
        areas=["venue arrangement"],
    )

    assert calls[0]["json"] == {
        "status": "Safety Changes Requested",
        "safetyCheckId": RECORD_ID,
        "roundNumber": 1,
        "remarks": "Needs another look.",
        "areas": ["venue arrangement"],
    }


def test_set_safety_status_client_omits_absent_areas(sent):
    """
    Summary: No areas are sent when there are none.
    SCRUM-151 AC2: Given changes are requested, then the event status changes
        to 'Safety Changes Requested', the event returns to the planning stage
        for each selected area, and its existing arrangements are preserved.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, event("Cancelled")))

    clients.set_event_safety_status(
        EVENT_ID, "Cancelled", RECORD_ID, 1, remarks="Unsafe."
    )

    assert "areas" not in calls[0]["json"]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (404, clients.EventNotFoundError),
        (500, clients.DownstreamError),
    ],
)
def test_set_safety_status_client_maps_statuses(status, expected, sent):
    """
    Summary: Move failures are mapped to typed errors.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(status, {"message": "nope"}))

    with pytest.raises(expected):
        clients.set_event_safety_status(
            EVENT_ID, "Pending Safety Check", RECORD_ID, 1
        )


def test_set_safety_status_client_plain_403_is_not_assigned(sent):
    """
    Summary: A plain refusal means the coordinator is not assigned.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(403, {"message": "nope"}))

    with pytest.raises(clients.EventNotAssignedError):
        clients.set_event_safety_status(
            EVENT_ID, "Pending Safety Check", RECORD_ID, 1
        )


def test_set_safety_status_client_internal_only_403_is_credentials_error(sent):
    """
    Summary: A refusal of our own service token is reported as our misconfiguration.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(403, {"code": "INTERNAL_ONLY", "message": "nope"}))

    with pytest.raises(clients.ServiceCredentialsError):
        clients.set_event_safety_status(
            EVENT_ID, "Confirmed", RECORD_ID, 1
        )


@pytest.mark.parametrize(
    "code", ["SAFETY_CHECK_ALREADY_PENDING", "INVALID_SAFETY_TRANSITION", "STALE_SAFETY_CHECK"]
)
def test_event_client_conflicts_keep_their_code(code, sent):
    """
    Summary: Event Service's conflict codes survive the trip.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(409, {"code": code, "currentStatus": "Cancelled"}))

    with pytest.raises(clients.EventTransitionError) as raised:
        clients.set_event_safety_status(
            EVENT_ID, "Pending Safety Check", RECORD_ID, 1
        )

    assert raised.value.code == code
    assert raised.value.body["currentStatus"] == "Cancelled"


def test_event_client_conflict_without_json_is_transition_error(sent):
    """
    Summary: A conflict without a readable body is still a transition error.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(409, None))

    with pytest.raises(clients.EventTransitionError) as raised:
        clients.set_event_safety_status(
            EVENT_ID, "Pending Safety Check", RECORD_ID, 1
        )

    assert raised.value.code is None
    assert raised.value.body == {}


# --- Venue Availability Service ---------------------------------------------


def test_bookings_client_reads_every_booking_of_event(sent):
    """
    Summary: Every booking of the event is read, in every status.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, {"bookings": [booking("Approved")]}))

    bookings = clients.get_event_venue_bookings(EVENT_ID)

    assert [b["id"] for b in bookings] == [BOOKING_ID]
    assert calls[0]["url"].endswith(f"/events/{EVENT_ID}/venue-bookings")


def test_bookings_client_failure_is_downstream_error(sent):
    """
    Summary: A failed booking read is a downstream error.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(503, {"message": "DATABASE_URL is not configured"}))

    with pytest.raises(clients.DownstreamError):
        clients.get_event_venue_bookings(EVENT_ID)


def test_cancel_booking_client_sends_event_id(sent):
    """
    Summary: Releasing a booking on rejection names the event.
    SCRUM-151 AC5: Given an event is cancelled by a safety rejection, then its
        venue bookings and equipment reservations are released so they no
        longer block other events, while their records remain in the event's
        history.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, booking("Cancelled")))

    cancelled = clients.cancel_venue_booking(BOOKING_ID, EVENT_ID)

    assert cancelled["status"] == "Cancelled"
    assert calls[0]["method"] == "PATCH"
    assert calls[0]["url"].endswith(f"/venue-bookings/{BOOKING_ID}/cancel")
    assert calls[0]["json"] == {"eventId": EVENT_ID}


def test_cancel_booking_client_missing_is_not_found(sent):
    """
    Summary: Releasing a missing booking is reported as not found.
    SCRUM-151 AC5: Given an event is cancelled by a safety rejection, then its
        venue bookings and equipment reservations are released so they no
        longer block other events, while their records remain in the event's
        history.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(404, {"message": "no"}))

    with pytest.raises(clients.RecordNotFoundError):
        clients.cancel_venue_booking(BOOKING_ID, EVENT_ID)


def test_cancel_booking_client_failure_is_downstream_error(sent):
    """
    Summary: A failed release is a downstream error.
    SCRUM-151 AC5: Given an event is cancelled by a safety rejection, then its
        venue bookings and equipment reservations are released so they no
        longer block other events, while their records remain in the event's
        history.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(503, {"message": "down"}))

    with pytest.raises(clients.DownstreamError):
        clients.cancel_venue_booking(BOOKING_ID, EVENT_ID)


# --- Equipment Request Service ----------------------------------------------


def test_equipment_client_reads_with_callers_token(sent):
    """
    Summary: Equipment requests are read as the signed-in user.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, {"requests": [equipment_request("Approved")]}))

    with create_app().test_request_context(headers={"Authorization": "Bearer caller-token"}):
        clients.get_event_equipment_requests(EVENT_ID)

    assert calls[0]["params"] == {"eventId": EVENT_ID}
    assert calls[0]["headers"] == {"Authorization": "Bearer caller-token"}


def test_equipment_client_refusal_is_downstream_error(sent):
    """
    Summary: A refused equipment read is a misconfiguration, reported as a downstream error.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(403, {"message": "Only Technical Support ..."}))

    with pytest.raises(clients.DownstreamError):
        clients.get_event_equipment_requests(EVENT_ID)


def test_equipment_catalogue_client_reads_catalogue(sent):
    """
    Summary: The equipment catalogue is read for the review.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, {"equipment": [{"id": "fixture", "type": "Table"}]}))

    assert clients.list_equipment() == [{"id": "fixture", "type": "Table"}]
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith("/equipment")


def test_equipment_catalogue_client_failure_is_downstream_error(sent):
    """
    Summary: A failed catalogue read is a downstream error.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(503, {"message": "database unavailable"}))

    with pytest.raises(clients.DownstreamError):
        clients.list_equipment()


# --- Safety Check Record Service --------------------------------------------


def test_create_record_client_sends_notes(sent):
    """
    Summary: A new round carries the coordinator's notes.
    AC3: Given the Event Coordinator is submitting, when they enter equipment
        placement and expected crowd movement notes, then the notes are saved
        with the safety check.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(201, record()))

    created = clients.create_safety_check_record(
        EVENT_ID, "Speakers on the left.", "Enter via Door A."
    )

    assert created["roundNumber"] == 1
    assert calls[0]["method"] == "POST"
    assert calls[0]["json"] == {
        "eventId": EVENT_ID,
        "equipmentPlacementNotes": "Speakers on the left.",
        "crowdMovementNotes": "Enter via Door A.",
    }


def test_create_record_client_sends_null_for_absent_notes(sent):
    """
    Summary: Notes not given are sent as nothing.
    AC3: Given the Event Coordinator is submitting, when they enter equipment
        placement and expected crowd movement notes, then the notes are saved
        with the safety check.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(201, record()))

    clients.create_safety_check_record(
EVENT_ID)

    assert queue == []


def test_create_record_client_conflict_returns_open_round(sent):
    """
    Summary: A duplicate submission returns the round already open.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(
        Response(409, {"code": "SAFETY_CHECK_ALREADY_PENDING", "safetyCheck": record()})
    )

    with pytest.raises(clients.SafetyCheckAlreadyPendingError) as raised:
        clients.create_safety_check_record(
EVENT_ID)

    assert raised.value.existing["roundNumber"] == 1


def test_create_record_client_conflict_without_body_still_conflicts(sent):
    """
    Summary: A duplicate answer without a body is still a conflict.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(409, None))

    with pytest.raises(clients.SafetyCheckAlreadyPendingError) as raised:
        clients.create_safety_check_record(
EVENT_ID)

    assert raised.value.existing is None


def test_create_record_client_failure_is_downstream_error(sent):
    """
    Summary: A failed round creation is a downstream error.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(400, {"message": "eventId must be a valid UUID."}))

    with pytest.raises(clients.DownstreamError):
        clients.create_safety_check_record(
EVENT_ID)


def test_list_records_client_filters_by_status(sent):
    """
    Summary: Rounds can be read by status.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, {"safetyChecks": [record()]}))

    rounds = clients.list_safety_check_records(EVENT_ID, status="Pending")

    assert rounds[0]["status"] == "Pending"
    assert calls[0]["params"] == {"eventId": EVENT_ID, "status": "Pending"}


def test_list_records_client_without_status_reads_all(sent):
    """
    Summary: Without a status, every round is read.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, {"safetyChecks": []}))

    assert clients.list_safety_check_records(EVENT_ID) == []
    assert calls[0]["params"] == {"eventId": EVENT_ID}


def test_list_records_client_failure_is_downstream_error(sent):
    """
    Summary: A failed round read is a downstream error.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(503, {"message": "down"}))

    with pytest.raises(clients.DownstreamError):
        clients.list_safety_check_records(EVENT_ID)


def test_delete_record_client_accepts_no_content(sent):
    """
    Summary: Undoing a round accepts an empty success answer.
    AC1: (rollback)
    Double: Stub (respx; request inspected)
    """
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
def test_delete_record_client_maps_failures(status, expected, sent):
    """
    Summary: Undo failures are mapped to typed errors.
    AC1: (rollback)
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(status, {"message": "no"}))

    with pytest.raises(expected):
        clients.delete_safety_check_record(RECORD_ID)


def test_decide_record_client_sends_decision(sent):
    """
    Summary: The decision is sent to the record service.
    SCRUM-150 AC2: Given I approve an event, then the safety check is recorded
        with the status 'Safety Approved', together with my identity, the
        approval timestamp and any optional remarks, in the event's history.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, record(status="Safety Approved", decidedBy=OFFICER_ID)))

    decided = clients.decide_safety_check_record(
        RECORD_ID, "Safety Approved", "Looks safe."
    )

    assert decided["status"] == "Safety Approved"
    assert calls[0]["method"] == "PATCH"
    assert calls[0]["url"].endswith(f"/safety-check-records/{RECORD_ID}/decision")
    assert calls[0]["json"] == {
        "status": "Safety Approved",
        "remarks": "Looks safe.",
    }


def test_decide_record_client_sends_flags(sent):
    """
    Summary: A change request's flags travel with the decision.
    SCRUM-151 AC6: Given either decision, then the safety check is recorded
        with the status 'Changes Requested' or 'Safety Rejected' respectively,
        together with my identity, the timestamp and the reason (plus the
        selected areas for a change request), and the original event
        information is retained.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, record(status="Changes Requested")))

    flags = [{"area": "venue arrangement", "changeRequired": "Move the stage."}]
    clients.decide_safety_check_record(
        RECORD_ID, "Changes Requested", "Needs another look.", flags
    )

    assert calls[0]["json"] == {
        "status": "Changes Requested",
        "remarks": "Needs another look.",
        "flags": flags,
    }


def test_decide_record_client_omits_absent_flags(sent):
    """
    Summary: No flags are sent when there are none.
    SCRUM-151 AC6: Given either decision, then the safety check is recorded
        with the status 'Changes Requested' or 'Safety Rejected' respectively,
        together with my identity, the timestamp and the reason (plus the
        selected areas for a change request), and the original event
        information is retained.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, record(status="Safety Approved")))

    clients.decide_safety_check_record(RECORD_ID, "Safety Approved", "Looks safe.")

    assert "flags" not in calls[0]["json"]


def test_decide_record_client_conflict_returns_existing_round(sent):
    """
    Summary: A lost race returns the round as already decided.
    SCRUM-150 AC3: Given an event is not 'Pending Safety Check', then the
        approve action is not available and an API call is rejected without
        changing the event.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(
        Response(
            409,
            {"code": "SAFETY_CHECK_ALREADY_DECIDED", "safetyCheck": record(status="Safety Approved")},
        )
    )

    with pytest.raises(clients.SafetyCheckAlreadyDecidedError) as raised:
        clients.decide_safety_check_record(RECORD_ID, "Safety Approved")

    assert raised.value.existing["status"] == "Safety Approved"


def test_decide_record_client_missing_round_is_not_found(sent):
    """
    Summary: Deciding a missing round is reported as not found.
    SCRUM-150 AC3: Given an event is not 'Pending Safety Check', then the
        approve action is not available and an API call is rejected without
        changing the event.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(404, {"message": "no"}))

    with pytest.raises(clients.RecordNotFoundError):
        clients.decide_safety_check_record(RECORD_ID, "Safety Approved")


def test_decide_record_client_failure_is_downstream_error(sent):
    """
    Summary: A failed decision is a downstream error.
    SCRUM-150 AC2: Given I approve an event, then the safety check is recorded
        with the status 'Safety Approved', together with my identity, the
        approval timestamp and any optional remarks, in the event's history.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(503, {"message": "down"}))

    with pytest.raises(clients.DownstreamError):
        clients.decide_safety_check_record(RECORD_ID, "Safety Approved")


def test_reopen_record_client_sends_decision_time(sent):
    """
    Summary: Reopening names the exact decision to undo.
    SCRUM-150 AC1: (rollback)
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, record(status="Pending")))

    clients.reopen_safety_check_record(RECORD_ID, "2026-11-02T03:00:00+00:00")

    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith(f"/safety-check-records/{RECORD_ID}/reopen")
    assert calls[0]["json"] == {"decidedAt": "2026-11-02T03:00:00+00:00"}


def test_reopen_record_client_missing_round_is_not_found(sent):
    """
    Summary: Reopening a missing round is reported as not found.
    SCRUM-150 AC1: (rollback)
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(404, {"message": "no"}))

    with pytest.raises(clients.RecordNotFoundError):
        clients.reopen_safety_check_record(RECORD_ID, "2026-11-02T03:00:00+00:00")


def test_reopen_record_client_failure_is_downstream_error(sent):
    """
    Summary: A failed reopen is a downstream error.
    SCRUM-150 AC1: (rollback)
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(409, {"message": "nope"}))

    with pytest.raises(clients.DownstreamError):
        clients.reopen_safety_check_record(RECORD_ID, "2026-11-02T03:00:00+00:00")


# --- User Service -------------------------------------------------------------


def test_get_user_client_returns_role(sent):
    """
    Summary: A user's role is read from User Service.
    SCRUM-150 AC3: Given an event is not 'Pending Safety Check', then the
        approve action is not available and an API call is rejected without
        changing the event.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, user(role="Safety Officer")))

    found = clients.get_user(OFFICER_ID)

    assert found["role"] == "Safety Officer"
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith(f"/users/{OFFICER_ID}")


def test_get_user_client_missing_is_not_found(sent):
    """
    Summary: A missing user is reported as not found.
    SCRUM-150 AC3: Given an event is not 'Pending Safety Check', then the
        approve action is not available and an API call is rejected without
        changing the event.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(404, {"message": "User not found."}))

    with pytest.raises(clients.UserNotFoundError):
        clients.get_user(OFFICER_ID)


def test_get_user_client_failure_is_downstream_error(sent):
    """
    Summary: A failed user read is a downstream error.
    SCRUM-150 AC3: Given an event is not 'Pending Safety Check', then the
        approve action is not available and an API call is rejected without
        changing the event.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(503, {"message": "down"}))

    with pytest.raises(clients.DownstreamError):
        clients.get_user(OFFICER_ID)


# --- SCRUM-162: the queue's reads ----------------------------------------------


def test_list_events_client_reads_as_viewer_role(sent):
    """
    Summary: The queue's events are read in the Safety Officer's view.
    SCRUM-162 AC1: The queue shows only events with status 'Pending Safety
        Check'.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, {"events": [event("Pending Safety Check")]}))

    found = clients.list_events_by_status("Pending Safety Check", "Safety Officer")

    assert found[0]["status"] == "Pending Safety Check"
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith("/events")
    assert calls[0]["params"] == {
        "viewerRole": "Safety Officer",
        "status": "Pending Safety Check",
    }


@pytest.mark.parametrize("status", [400, 403, 503])
def test_list_events_client_failure_is_downstream_error(status, sent):
    """
    Summary: A failed event list is a downstream error.
    SCRUM-162 AC1: The queue shows only events with status 'Pending Safety
        Check'.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(status, {"message": "no"}))

    with pytest.raises(clients.DownstreamError):
        clients.list_events_by_status("Pending Safety Check", "Safety Officer")


def test_list_venues_client_reads_whole_catalogue(sent):
    """
    Summary: The whole venue catalogue is read.
    SCRUM-162 AC2: Each entry shows event name, event date/time, venue(s),
        expected attendance and submission date, with the nearest event date
        first.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, {"venues": [{"id": "v1", "name": "Main Hall"}]}))

    assert clients.list_venues() == [{"id": "v1", "name": "Main Hall"}]
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith("/venues")
    assert "params" not in calls[0]


def test_list_venues_client_failure_is_downstream_error(sent):
    """
    Summary: A failed venue read is a downstream error.
    SCRUM-162 AC2: Each entry shows event name, event date/time, venue(s),
        expected attendance and submission date, with the nearest event date
        first.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(503, {"message": "down"}))

    with pytest.raises(clients.DownstreamError):
        clients.list_venues()


# --- SCRUM-153: the re-check's three wrappers --------------------------------


def test_update_details_client_sends_edit_and_both_round_ids(sent, monkeypatch):
    """
    Summary: A re-check edit carries both round ids so Event Service can verify it.
    SCRUM-153 AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (respx; request inspected)
    """
    monkeypatch.setattr("app.clients.INTERNAL_SERVICE_TOKEN", "shared-secret")
    calls, queue = sent
    queue.append(Response(200, event("Pending Safety Check")))

    changes = {"expectedAttendance": "400"}
    safety_recheck = {
        "withdrawnSafetyCheckId": RECORD_ID,
        "safetyCheckId": NEXT_RECORD_ID,
        "roundNumber": 3,
    }
    updated = clients.update_event_details(
        EVENT_ID, changes, safety_recheck
    )

    assert updated["status"] == "Pending Safety Check"
    assert calls[0]["method"] == "PATCH"
    assert calls[0]["url"].endswith(f"/events/{EVENT_ID}/details")
    assert calls[0]["json"] == {
        "changes": changes,
        # SCRUM-46 forwards the doubled pre-edit venue alongside unchanged round IDs.
        "safetyRecheck": {**safety_recheck, "venueBefore": "Hall A"},
    }
    assert calls[0]["headers"] == {"X-Internal-Service-Token": "shared-secret"}


def test_update_details_client_sends_empty_token_when_unconfigured(
    sent, monkeypatch
):
    """
    Summary: An unconfigured token is sent empty rather than omitted.
    SCRUM-153 AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (respx; request inspected)
    """
    monkeypatch.setattr("app.clients.INTERNAL_SERVICE_TOKEN", None)
    calls, queue = sent
    queue.append(Response(200, event("Pending Safety Check")))

    clients.update_event_details(EVENT_ID, {}, {})

    assert calls[0]["headers"] == {"X-Internal-Service-Token": ""}


@pytest.mark.parametrize("status", [400, 409])
def test_update_details_client_refusals_keep_status(status, sent):
    """
    Summary: Event Service's refusals keep their status.
    SCRUM-153 AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(status, {"code": "STALE_SAFETY_CHECK", "message": "no"}))

    with pytest.raises(clients.EventDetailsRejectedError) as raised:
        clients.update_event_details(EVENT_ID, {}, {})

    assert raised.value.status == status
    assert raised.value.code == "STALE_SAFETY_CHECK"
    assert raised.value.body["message"] == "no"


def test_update_details_client_maps_not_found_and_forbidden(sent):
    """
    Summary: Not-found and forbidden answers are mapped to typed errors.
    SCRUM-153 AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(404, {"message": "gone"}))
    with pytest.raises(clients.EventNotFoundError):
        clients.update_event_details(EVENT_ID, {}, {})

    queue.append(Response(403, {"message": "not yours"}))
    with pytest.raises(clients.EventNotAssignedError):
        clients.update_event_details(EVENT_ID, {}, {})


def test_update_details_client_maps_refused_token(sent):
    """
    Summary: A refused service token is reported as our misconfiguration.
    SCRUM-153 AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(403, {"code": "INTERNAL_ONLY"}))

    with pytest.raises(clients.ServiceCredentialsError):
        clients.update_event_details(EVENT_ID, {}, {})


def test_update_details_client_other_failures_are_downstream_errors(sent):
    """
    Summary: Other failures are downstream errors.
    SCRUM-153 AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(503, {"message": "down"}))

    with pytest.raises(clients.DownstreamError):
        clients.update_event_details(EVENT_ID, {}, {})


def test_withdraw_client_returns_withdrawn_and_new_round(sent):
    """
    Summary: A withdrawal returns both the withdrawn and the new round.
    SCRUM-153 AC3: Given a safety approval is withdrawn, then it stays visible
        in the event's safety history.
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(
        Response(
            201,
            {
                "withdrawn": record(round_number=2, status="Approval Withdrawn"),
                "opened": record(round_number=3, status="Pending", id=NEXT_RECORD_ID),
            },
        )
    )

    withdrawn, opened = clients.withdraw_safety_approval(
        RECORD_ID, "Date/time changed after safety approval."
    )

    assert withdrawn["status"] == "Approval Withdrawn"
    assert opened["roundNumber"] == 3
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith(f"/safety-check-records/{RECORD_ID}/withdraw")
    assert calls[0]["json"] == {
        "reason": "Date/time changed after safety approval.",
    }


def test_withdraw_client_conflict_returns_the_round(sent):
    """
    Summary: A lost race returns the round as already withdrawn.
    SCRUM-153 AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(
        Response(
            409,
            {
                "code": "ROUND_NOT_APPROVED",
                "safetyCheck": record(round_number=2, status="Approval Withdrawn"),
            },
        )
    )

    with pytest.raises(clients.RoundNotApprovedError) as raised:
        clients.withdraw_safety_approval(RECORD_ID, "why")

    assert raised.value.code == "ROUND_NOT_APPROVED"
    assert raised.value.body["safetyCheck"]["status"] == "Approval Withdrawn"


def test_withdraw_client_missing_round_is_not_found(sent):
    """
    Summary: Withdrawing a missing round is reported as not found.
    SCRUM-153 AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(404, {"message": "gone"}))

    with pytest.raises(clients.RecordNotFoundError):
        clients.withdraw_safety_approval(RECORD_ID, "why")


def test_withdraw_client_failure_is_downstream_error(sent):
    """
    Summary: A failed withdrawal is a downstream error.
    SCRUM-153 AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(503, {"message": "down"}))

    with pytest.raises(clients.DownstreamError):
        clients.withdraw_safety_approval(RECORD_ID, "why")


def test_restore_client_names_round_to_remove(sent):
    """
    Summary: A restore names the round to remove.
    SCRUM-153 AC1: (rollback)
    Double: Stub (respx; request inspected)
    """
    calls, queue = sent
    queue.append(Response(200, record(round_number=2, status="Safety Approved")))

    restored = clients.restore_safety_approval(RECORD_ID, NEXT_RECORD_ID)

    assert restored["status"] == "Safety Approved"
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith(f"/safety-check-records/{RECORD_ID}/restore")
    assert calls[0]["json"] == {"openedSafetyCheckId": NEXT_RECORD_ID}


def test_restore_client_missing_round_is_not_found(sent):
    """
    Summary: Restoring a missing round is reported as not found.
    SCRUM-153 AC1: (rollback)
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(404, {"message": "gone"}))

    with pytest.raises(clients.RecordNotFoundError):
        clients.restore_safety_approval(RECORD_ID, NEXT_RECORD_ID)


def test_restore_client_failure_is_downstream_error(sent):
    """
    Summary: A failed restore is a downstream error.
    SCRUM-153 AC1: (rollback)
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(Response(409, {"code": "NOT_RESTORABLE"}))

    with pytest.raises(clients.DownstreamError):
        clients.restore_safety_approval(RECORD_ID, NEXT_RECORD_ID)


# --- Transport failures ------------------------------------------------------


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (httpx.ReadTimeout("too slow"), clients.DownstreamTimeout),
        (httpx.ConnectTimeout("too slow"), clients.DownstreamTimeout),
        (httpx.ConnectError("refused"), clients.DownstreamError),
        (httpx.RemoteProtocolError("garbage"), clients.DownstreamError),
    ],
    ids=["read_timeout", "connect_timeout", "connect_error", "protocol_error"],
)
def test_clients_map_transport_failures_to_502_or_504(raised, expected, sent):
    """
    Summary: A timeout becomes a 504 and any other transport failure a 502.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (respx; request inspected)
    """
    _, queue = sent
    queue.append(raised)

    with pytest.raises(expected):
        clients.get_event(EVENT_ID)


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_clients_default_to_local_host_ports():
    """
    Summary: Without configuration, the clients use the local development ports.
    Supporting design check: downstream URLs default for local runs
    Double: Stub (respx; request inspected)
    """
    assert clients.EVENT_SERVICE_URL.endswith((":5003", ":5000"))
    assert clients.VENUE_AVAILABILITY_SERVICE_URL.endswith((":5008", ":5000"))
    assert clients.EQUIPMENT_REQUEST_SERVICE_URL.endswith((":5011", ":5000"))
    assert clients.SAFETY_CHECK_RECORD_SERVICE_URL.endswith((":5013", ":5000"))
    assert clients.USER_SERVICE_URL.endswith((":5001", ":5000"))
    assert clients.VENUE_SERVICE_URL.endswith((":5006", ":5000"))
