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

SCRUM-28: Venue Booking Request Submission

User Story
----------
As an Event Coordinator, I want to submit a venue booking request for an event,
so that Venue Staff can assess whether the requested venue arrangement can be
accepted.

Acceptance Criteria
-------------------
AC1: Given an Event Coordinator is preparing a venue booking request for an
     event, when they enter the booking information, then they can provide the
     relevant event timing and venue requirements needed for Venue Staff to
     assess the booking.
AC2: Given the relevant event timing and venue requirements have been provided,
     when the Event Coordinator submits the venue booking request, then the
     request is recorded and made available to Venue Staff for review.
AC3: Given a venue booking request has been submitted, when Venue Staff access
     the request, then they can view the event to which the request relates
     together with the relevant event timing and venue requirements.
AC4: Given a venue booking request has been submitted and has not yet received
     a booking decision, when Venue Staff view requests requiring action, then
     the request can be identified as awaiting Venue Staff review.
AC5: Given an Event Coordinator submits a venue booking request for an event,
     when the request is recorded, then it remains associated with that event
     so that the booking can be assessed in the context of the corresponding
     event requirements.
AC6: Given an Event Coordinator submits a venue booking request for a venue and
     time slot, when the same venue has already been requested or booked for
     another event, and the requested event timing does not overlap with that
     other event's timing, then the request is accepted for Venue Staff review
     as normal, so the same venue can be booked for multiple events across
     non-overlapping time slots.
AC7: Given an event is 'Confirmed' after passing its Operational Safety Check,
     when the Event Coordinator edits or cancels one of its venue bookings,
     then the event's safety approval is withdrawn without opening a new safety
     check round, the event returns to 'Approved', and an edited booking
     returns to awaiting Venue Staff review, so the event must be submitted for
     a safety check again. If the booking change cannot be saved, the safety
     approval is restored and the event stays 'Confirmed'. While the event is
     'Pending Safety Check', its venue bookings cannot be edited or cancelled.

Real
----
- POST /safety-checks, POST /safety-checks/resubmit and GET
  /safety-checks/readiness: the assigned-coordinator check, the readiness
  rules, note validation, the duplicate-round guard, the order of writes and
  the compensating delete when a later step fails.
- /health and the CORS hook of the real create_app().
- Assertions are on the status, the body and the downstream calls made.

Doubled
-------
- Event, Venue Availability, Equipment Request and Safety Check Record
  Services: Stub (Downstream fixture monkeypatches app.clients) - canned rows
  or raised client errors; calls are recorded so tests assert what was (or was
  not) written and in which order.

Not proven
----------
- That the atomic services behave as stubbed, and that the compensating delete
  really removes the round (-> tests/integration/ here with respx, and Safety
  Check Record Service's own tests).
- That the UI hides the submit action from other coordinators (-> frontend
  Vitest suite).
"""
import logging

import pytest
from flask import g

from app import clients, create_app
from tests.unit.factories import (
    signed_in,
    COORDINATOR_ID,
    EVENT_ID,
    RECORD_ID,
    booking,
    equipment_request,
    event,
    record,
)

PLACEMENT = "Speakers either side of the stage, cables taped along the left wall."
CROWD = "Entry through Door A, exit through Doors B and C; queue in the foyer."


class Downstream:
    """Recorded stand-ins for every atomic this composite calls."""

    def __init__(self):
        self.event = event("Approved")
        self.bookings = [booking("Approved")]
        self.requests = []
        self.rounds = []
        self.created = record()
        self.updated = event("Pending Safety Check")
        self.calls = []
        self.fail = {}

    def _maybe_fail(self, name):
        error = self.fail.get(name)
        if error:
            raise error

    def get_event(self, event_id):
        coordinator_id = g.user_id  # The downstream service reads this from the forwarded token.
        self.calls.append(("get_event", event_id, coordinator_id))
        self._maybe_fail("get_event")
        return self.event

    def get_event_venue_bookings(self, event_id):
        self.calls.append(("bookings", event_id))
        self._maybe_fail("bookings")
        return self.bookings

    def get_event_equipment_requests(self, event_id):
        coordinator_id = g.user_id  # The downstream service reads this from the forwarded token.
        self.calls.append(("requests", event_id, coordinator_id))
        self._maybe_fail("requests")
        return self.requests

    def list_safety_check_records(self, event_id, status=None):
        self.calls.append(("list_records", event_id, status))
        self._maybe_fail("list_records")
        return self.rounds

    def create_safety_check_record(self, event_id, placement=None, crowd=None):
        submitted_by = g.user_id  # The downstream service reads this from the forwarded token.
        self.calls.append(("create", event_id, submitted_by, placement, crowd))
        self._maybe_fail("create")
        return self.created

    def set_event_safety_status(
        self,
        event_id,
        status,
        safety_check_id,
        round_number,
        remarks=None,
    ):
        coordinator_id = g.user_id  # The downstream service reads this from the forwarded token.
        self.calls.append(
            ("patch_event", event_id, status, coordinator_id, safety_check_id, round_number)
        )
        self._maybe_fail("patch_event")
        return self.updated

    def delete_safety_check_record(self, safety_check_id):
        self.calls.append(("delete", safety_check_id))
        self._maybe_fail("delete")

    def names(self):
        return [call[0] for call in self.calls]

    def call(self, name):
        return next(call for call in self.calls if call[0] == name)


@pytest.fixture
def downstream(monkeypatch):
    stub = Downstream()
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


@pytest.fixture
def client():
    return signed_in(create_app().test_client())


def submit(client, **overrides):
    body = {"eventId": EVENT_ID, "coordinatorId": COORDINATOR_ID, **overrides}
    return client.post("/safety-checks", json=body)


def resubmit(client, **overrides):
    return client.post("/safety-checks/resubmit", json={
        "eventId": EVENT_ID, "coordinatorId": COORDINATOR_ID, **overrides,
    })


def test_resubmit_with_approved_arrangements_opens_next_round(client, downstream):
    """
    Summary: With every flagged arrangement approved again, resubmitting opens a new round.
    SCRUM-164 AC5: Given all flagged arrangements are confirmed again, when I
        resubmit, then the status returns to 'Pending Safety Check' as a new
        review round, and earlier rounds remain in the history.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.event = event("Safety Changes Requested")
    downstream.rounds = [record(1, "Changes Requested")]
    downstream.created = record(2)
    downstream.requests = [equipment_request("Approved")]

    # Act (When)
    response = resubmit(client, equipmentPlacementNotes=PLACEMENT, crowdMovementNotes=CROWD)

    # Assert (Then)
    assert response.status_code == 201
    assert response.json["safetyCheck"]["roundNumber"] == 2
    assert response.json["event"]["status"] == "Pending Safety Check"
    assert downstream.call("create") == ("create", EVENT_ID, COORDINATOR_ID, PLACEMENT, CROWD)
    assert "bookings" in downstream.names()
    assert "delete" not in downstream.names()
    assert downstream.rounds[0]["status"] == "Changes Requested"


def test_resubmit_with_pending_equipment_is_blocked_before_writes(client, downstream):
    """
    Summary: A pending equipment request blocks resubmission before anything is written.
    SCRUM-164 AC3: Given the technical arrangement is flagged, then the
        affected equipment request must be reviewed again by Technical Support
        Staff before the event can be resubmitted.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.event = event("Safety Changes Requested")
    downstream.requests = [equipment_request("Pending")]

    # Act (When)
    response = resubmit(client)

    # Assert (Then)
    assert response.status_code == 422
    assert response.json["outstanding"][0]["status"] == "Pending"
    assert "create" not in downstream.names()
    assert "bookings" in downstream.names()


@pytest.mark.parametrize("requests", [[], [equipment_request("Approved")]], ids=["empty", "equipment_request_approved"])
def test_resubmit_readiness_with_approved_arrangements_is_ready(client, downstream, requests):
    """
    Summary: Resubmission readiness is true with an approved venue and no or approved equipment.
    SCRUM-164 AC5: Given all flagged arrangements are confirmed again, when I
        resubmit, then the status returns to 'Pending Safety Check' as a new
        review round, and earlier rounds remain in the history.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.event = event("Safety Changes Requested")
    downstream.requests = requests

    # Act (When)
    response = client.get("/safety-checks/resubmit/readiness", query_string={"eventId": EVENT_ID, "coordinatorId": COORDINATOR_ID})

    # Assert (Then)
    assert response.status_code == 200
    assert response.json == {"ready": True, "eventStatus": "Safety Changes Requested", "outstanding": []}
    assert "bookings" in downstream.names()


@pytest.mark.parametrize("venue_status,equipment_status", [("Pending Review", "Approved"), ("Rejected", "Approved")])
def test_resubmit_with_unready_venue_is_blocked(client, downstream, venue_status, equipment_status):
    """
    Summary: A venue booking that is not approved again blocks resubmission.
    SCRUM-164 AC2: Given the venue arrangement is flagged, then the affected
        venue booking must be reviewed again by Venue Staff (revised booking or
        replacement request) before the event can be resubmitted.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.event = event("Safety Changes Requested")
    downstream.bookings = [booking(venue_status)]

    # Act (When)
    downstream.requests = [equipment_request(equipment_status)]

    # Assert (Then)
    assert resubmit(client).status_code == 422
    response = client.get(f"/safety-checks/resubmit/readiness?eventId={EVENT_ID}&coordinatorId={COORDINATOR_ID}")
    assert response.json["ready"] is False
    assert "create" not in downstream.names()


def test_resubmit_ignores_rejected_equipment(client, downstream):
    """
    Summary: A rejected equipment request no longer blocks resubmission.
    SCRUM-164 AC3: Given the technical arrangement is flagged, then the
        affected equipment request must be reviewed again by Technical Support
        Staff before the event can be resubmitted.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.event = event("Safety Changes Requested")
    downstream.rounds = [record(1, "Changes Requested")]
    downstream.created = record(2)
    downstream.requests = [equipment_request("Rejected")]

    # Act (When)
    response = client.get(f"/safety-checks/resubmit/readiness?eventId={EVENT_ID}&coordinatorId={COORDINATOR_ID}")

    # Assert (Then)
    assert response.json == {"ready": True, "eventStatus": "Safety Changes Requested", "outstanding": []}
    assert "create" not in downstream.names()
    response = resubmit(client)
    assert response.status_code == 201
    assert response.json["safetyCheck"]["roundNumber"] == 2
    assert "patch_event" in downstream.names()


def test_resubmit_readiness_with_pending_equipment_or_wrong_stage_is_not_ready(client, downstream):
    """
    Summary: Resubmission readiness is false with pending equipment or outside 'Safety Changes Requested'.
    SCRUM-164 AC3: Given the technical arrangement is flagged, then the
        affected equipment request must be reviewed again by Technical Support
        Staff before the event can be resubmitted.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.event = event("Safety Changes Requested")
    downstream.requests = [equipment_request("Pending")]
    url = f"/safety-checks/resubmit/readiness?eventId={EVENT_ID}&coordinatorId={COORDINATOR_ID}"

    # Act + Assert (When / Then)
    assert client.get(url).json["ready"] is False
    downstream.event = event("Approved")
    downstream.requests = []
    assert client.get(url).json["ready"] is False
    assert resubmit(client).status_code == 409


def test_resubmit_readiness_with_bad_ids_returns_400(client, downstream):
    """
    Summary: Resubmission readiness needs valid event and coordinator ids.
    SCRUM-164 AC5: Given all flagged arrangements are confirmed again, when I
        resubmit, then the status returns to 'Pending Safety Check' as a new
        review round, and earlier rounds remain in the history.
    Double: None
    """
    # Arrange (Given): client, downstream, from fixtures

    # Act + Assert (When / Then)
    assert client.get("/safety-checks/resubmit/readiness?eventId=bad").status_code == 400
    assert downstream.calls == []


@pytest.mark.parametrize("error,code", [(clients.EventNotAssignedError(), 403), (clients.EventNotFoundError(), 404)], ids=["clients_eventnotassignederror_403", "clients_eventnotfounderror_404"])
def test_resubmit_when_not_assigned_is_refused_before_equipment_read(client, downstream, error, code):
    """
    Summary: A coordinator who is not assigned, or a missing event, stops resubmission before equipment is read.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Stub (get_event raises EventNotAssignedError or EventNotFoundError)
    """
    # Arrange (Given)
    downstream.fail["get_event"] = error

    # Act + Assert (When / Then)
    assert resubmit(client).status_code == code
    assert client.get(f"/safety-checks/resubmit/readiness?eventId={EVENT_ID}&coordinatorId={COORDINATOR_ID}").status_code == code
    assert "requests" not in downstream.names()


@pytest.mark.parametrize("error,code", [(clients.DownstreamError(), 502), (clients.DownstreamTimeout(), 504)], ids=["clients_downstreamerror_502", "clients_downstreamtimeout_504"])
def test_resubmit_when_equipment_unreadable_fails_closed(client, downstream, error, code):
    """
    Summary: If equipment requests cannot be read, resubmission fails closed.
    SCRUM-164 AC3: Given the technical arrangement is flagged, then the
        affected equipment request must be reviewed again by Technical Support
        Staff before the event can be resubmitted.
    Double: Stub (get_event_equipment_requests raises DownstreamError or
        DownstreamTimeout)
    """
    # Arrange (Given)
    downstream.event = event("Safety Changes Requested")
    downstream.fail["requests"] = error

    # Act + Assert (When / Then)
    assert resubmit(client).status_code == code
    assert client.get(f"/safety-checks/resubmit/readiness?eventId={EVENT_ID}&coordinatorId={COORDINATOR_ID}").status_code == code
    assert "create" not in downstream.names()


# --- AC1, AC3: the happy path ------------------------------------------------


@pytest.mark.parametrize("replacement, ready, status", [
    ("Approved", True, 201), (None, False, 422), ("Pending Review", False, 422),
])
def test_resubmit_after_rejected_venue_uses_replacement_booking(client, downstream, replacement, ready, status):
    """
    Summary: After a rejected venue, readiness follows the replacement booking's live status.
    SCRUM-164 AC2: Given the venue arrangement is flagged, then the affected
        venue booking must be reviewed again by Venue Staff (revised booking or
        replacement request) before the event can be resubmitted.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.bookings = [booking("Rejected")]
    if replacement:
        downstream.bookings.append(booking(replacement, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"))

    # Act (When)
    result = readiness(client)

    # Assert (Then)
    assert result.json["ready"] is ready
    if replacement is None:
        assert result.json["outstanding"][0]["label"] == "No venue booking"
    elif not ready:
        assert [item["status"] for item in result.json["outstanding"]] == [replacement]
    response = submit(client)
    assert response.status_code == status
    if not ready:
        assert response.json["code"] == "ARRANGEMENTS_OUTSTANDING"
        assert "create" not in downstream.names()
        assert "patch_event" not in downstream.names()


def test_submit_when_ready_creates_round_and_moves_event(client, downstream):
    """
    Summary: Submitting a ready event records a round and moves the event to 'Pending Safety Check'.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given): client, downstream, from fixtures

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 201
    assert response.json["event"]["status"] == "Pending Safety Check"
    assert response.json["safetyCheck"]["roundNumber"] == 1
    assert response.json["safetyCheck"]["status"] == "Pending"
    assert response.json["safetyCheck"]["submittedAt"] == "2026-11-01T02:30:00+00:00"


def test_submit_with_notes_saves_them_with_the_round(client, downstream):
    """
    Summary: Placement and crowd movement notes are saved with the safety check.
    AC3: Given the Event Coordinator is submitting, when they enter equipment
        placement and expected crowd movement notes, then the notes are saved
        with the safety check.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.created = record(
        equipmentPlacementNotes=PLACEMENT, crowdMovementNotes=CROWD
    )

    # Act (When)
    response = submit(
        client, equipmentPlacementNotes=PLACEMENT, crowdMovementNotes=CROWD
    )

    # Assert (Then)
    assert response.status_code == 201
    assert downstream.call("create") == (
        "create",
        EVENT_ID,
        COORDINATOR_ID,
        PLACEMENT,
        CROWD,
    )
    assert response.json["safetyCheck"]["equipmentPlacementNotes"] == PLACEMENT
    assert response.json["safetyCheck"]["crowdMovementNotes"] == CROWD


@pytest.mark.parametrize(
    "notes",
    [
        {},
        {"equipmentPlacementNotes": "", "crowdMovementNotes": ""},
        {"equipmentPlacementNotes": "  ", "crowdMovementNotes": "\n"},
        {"equipmentPlacementNotes": None, "crowdMovementNotes": None},
    ],
    ids=["empty", "equipmentplacementnotes_crowdmovementnotes", "equipmentplacementnotes_crowdmovementnotes_n", "equipmentplacementnotes_none_crowdmovementnotes"],
)
def test_submit_without_notes_saves_none(notes, client, downstream):
    """
    Summary: Missing, blank or null notes are saved as no notes.
    AC3: Given the Event Coordinator is submitting, when they enter equipment
        placement and expected crowd movement notes, then the notes are saved
        with the safety check.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given): notes, client, downstream, from fixtures

    # Act (When)
    response = submit(client, **notes)

    # Assert (Then)
    assert response.status_code == 201
    assert downstream.call("create")[3:] == (None, None)


def test_submit_passes_round_number_to_event_service(client, downstream):
    """
    Summary: The new round's number is recorded on the event.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.created = record(round_number=3)

    # Act (When)
    submit(client)

    # Assert (Then)
    assert downstream.call("patch_event") == (
        "patch_event",
        EVENT_ID,
        "Pending Safety Check",
        COORDINATOR_ID,
        RECORD_ID,
        3,
    )


def test_submit_creates_record_before_moving_event(client, downstream):
    """
    Summary: The round is written before the event moves, so a failure can be rolled back.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    submit(client)

    # Act + Assert (When / Then)
    assert downstream.names().index("create") < downstream.names().index("patch_event")


def test_submit_with_notes_at_limit_is_accepted(client, downstream):
    """
    Summary: Notes exactly at the length limit are saved.
    AC3: Given the Event Coordinator is submitting, when they enter equipment
        placement and expected crowd movement notes, then the notes are saved
        with the safety check.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given): client, downstream, from fixtures

    # Act (When)
    response = submit(client, equipmentPlacementNotes="x" * 2000)

    # Assert (Then)
    assert response.status_code == 201


@pytest.mark.parametrize(
    ("field", "label"),
    [
        ("equipmentPlacementNotes", "Equipment placement notes"),
        ("crowdMovementNotes", "Expected crowd movement notes"),
    ],
)
def test_submit_with_notes_over_limit_returns_400(field, label, client, downstream):
    """
    Summary: Notes over the length limit are refused and nothing is written.
    AC3: Given the Event Coordinator is submitting, when they enter equipment
        placement and expected crowd movement notes, then the notes are saved
        with the safety check.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given): field, label, client, downstream, from fixtures

    # Act (When)
    response = submit(client, **{field: "x" * 2001})

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == f"{label} must be 2000 characters or fewer."
    assert downstream.calls == []


@pytest.mark.parametrize(
    ("field", "label"),
    [
        ("equipmentPlacementNotes", "Equipment placement notes"),
        ("crowdMovementNotes", "Expected crowd movement notes"),
    ],
)
def test_submit_with_non_text_notes_returns_400(field, label, client, downstream):
    """
    Summary: Notes that are not text are refused.
    AC3: Given the Event Coordinator is submitting, when they enter equipment
        placement and expected crowd movement notes, then the notes are saved
        with the safety check.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given): field, label, client, downstream, from fixtures

    # Act (When)
    response = submit(client, **{field: 42})

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == f"{label} must be text."
    assert downstream.calls == []


def test_submit_reads_equipment_as_submitting_coordinator(client, downstream):
    """
    Summary: Equipment requests are read with the submitting coordinator's identity.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given): client, downstream, from fixtures

    # Act (When)
    submit(client)

    # Assert (Then)
    assert downstream.call("requests") == ("requests", EVENT_ID, COORDINATOR_ID)


# --- AC2: outstanding arrangements block ------------------------------------


def test_submit_with_pending_booking_is_blocked(client, downstream):
    """
    Summary: A pending venue booking blocks submission and is listed.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.bookings = [booking("Pending Review")]

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 422
    assert response.json["code"] == "ARRANGEMENTS_OUTSTANDING"
    assert len(response.json["outstanding"]) == 1
    assert response.json["outstanding"][0]["type"] == "venue"
    assert response.json["outstanding"][0]["reason"] == (
        "Waiting for Venue Staff approval."
    )
    assert "create" not in downstream.names()
    assert "patch_event" not in downstream.names()


def test_submit_ignores_rejected_equipment(client, downstream):
    """
    Summary: A rejected equipment request does not block submission.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.requests = [equipment_request("Rejected")]

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 201
    assert response.json["event"]["status"] == "Pending Safety Check"
    assert "create" in downstream.names()
    assert "patch_event" in downstream.names()


def test_submit_with_pending_and_rejected_equipment_is_blocked(client, downstream):
    """
    Summary: A pending equipment request still blocks beside a rejected one.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.requests = [
        equipment_request("Rejected"),
        equipment_request("Pending", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
    ]

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 422
    assert response.json["message"] == (
        "This event can't be submitted for a safety check until it has an "
        "approved venue booking and no venue booking or equipment request is "
        "still waiting for a decision."
    )
    assert [item["status"] for item in response.json["outstanding"]] == ["Pending"]
    assert "create" not in downstream.names()
    assert "patch_event" not in downstream.names()


def test_submit_without_booking_is_blocked(client, downstream):
    """
    Summary: An event with no approved venue booking cannot be submitted.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.bookings = []

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 422
    assert response.json["outstanding"] == [
        {
            "type": "venue",
            "id": None,
            "status": None,
            "label": "No venue booking",
            "reason": "No venue booking has been made for this event.",
        }
    ]


# --- AC4: no duplicate safety check ------------------------------------------


def test_submit_when_already_pending_returns_open_round(client, downstream):
    """
    Summary: Submitting an event already pending returns the open round and creates no duplicate.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.event = event("Pending Safety Check")
    downstream.rounds = [record()]

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_PENDING"
    assert response.json["message"] == (
        "This event is already waiting for its safety check. "
        "It was submitted on 2026-11-01T02:30:00+00:00."
    )
    assert response.json["safetyCheck"]["roundNumber"] == 1
    assert "create" not in downstream.names()
    assert "patch_event" not in downstream.names()
    # The arrangements aren't even read: there is nothing to submit.
    assert "bookings" not in downstream.names()


def test_submit_when_pending_without_open_round_still_refuses(client, downstream):
    """
    Summary: A pending event is refused even when its open round cannot be found.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.event = event("Pending Safety Check")
    downstream.rounds = []

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_PENDING"
    assert response.json["message"] == (
        "This event is already waiting for its safety check."
    )
    assert response.json["safetyCheck"] is None


def test_submit_when_record_service_conflicts_returns_409(client, downstream):
    """
    Summary: A duplicate round refused by the record service is reported as the same conflict.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: Stub (create_safety_check_record raises a conflict)
    """
    # Arrange (Given)
    downstream.fail["create"] = clients.SafetyCheckAlreadyPendingError(record())

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_PENDING"
    assert response.json["safetyCheck"]["roundNumber"] == 1
    # Nothing moved the event: the round we'd have used is someone else's.
    assert "patch_event" not in downstream.names()


def test_submit_when_event_service_conflicts_rolls_round_back(client, downstream):
    """
    Summary: If Event Service refuses the move as a conflict, the new round is deleted.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: Stub (set_event_safety_status raises a conflict)
    """
    # Arrange (Given)
    downstream.fail["patch_event"] = clients.EventTransitionError(
        "SAFETY_CHECK_ALREADY_PENDING", {"code": "SAFETY_CHECK_ALREADY_PENDING"}
    )
    downstream.rounds = [record(round_number=2)]

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_PENDING"
    assert downstream.call("delete") == ("delete", RECORD_ID)


# --- AC5: only the assigned coordinator -------------------------------------


def test_submit_by_another_coordinator_returns_403_before_reads(client, downstream):
    """
    Summary: A coordinator not assigned to the event is refused before anything is read.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Stub (get_event raises EventNotAssignedError)
    """
    # Arrange (Given)
    downstream.fail["get_event"] = clients.EventNotAssignedError

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["code"] == "NOT_ASSIGNED_COORDINATOR"
    assert response.json["message"] == (
        "Only the event's assigned coordinator can submit it for a safety check."
    )
    # No arrangements read, nothing written: a stranger learns nothing.
    assert downstream.names() == ["get_event"]


def test_submit_when_reassigned_mid_flight_rolls_round_back(client, downstream):
    """
    Summary: If the event is reassigned during submission, the new round is deleted.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Stub (set_event_safety_status raises EventNotAssignedError)
    """
    # Arrange (Given)
    downstream.fail["patch_event"] = clients.EventNotAssignedError

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["code"] == "NOT_ASSIGNED_COORDINATOR"
    assert downstream.call("delete") == ("delete", RECORD_ID)


# --- The event's status guard ------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [
        "Submitted",
        "Under Review",
        "Rejected",
        "Confirmed",
        "Safety Changes Requested",
        "Cancelled",
    ],
)
def test_submit_when_event_not_approved_returns_409(status, client, downstream):
    """
    Summary: Only an event in the approved stage can be submitted.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.event = event(status)

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_READY_FOR_SAFETY_CHECK"
    assert response.json["currentStatus"] == status
    assert response.json["message"] == (
        "Only an Approved event can be submitted for a safety check "
        f"(current status: '{status}')."
    )
    assert downstream.names() == ["get_event"]


def test_submit_when_transition_rejected_rolls_back_with_message(client, downstream):
    """
    Summary: Event Service's reason for refusing the move is passed back and the round deleted.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (set_event_safety_status raises a transition error)
    """
    # Arrange (Given)
    downstream.fail["patch_event"] = clients.EventTransitionError(
        "INVALID_SAFETY_TRANSITION",
        {
            "code": "INVALID_SAFETY_TRANSITION",
            "message": "This event can't move to 'Pending Safety Check' from 'Cancelled'.",
            "currentStatus": "Cancelled",
        },
    )

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_READY_FOR_SAFETY_CHECK"
    assert response.json["currentStatus"] == "Cancelled"
    assert downstream.call("delete") == ("delete", RECORD_ID)


def test_submit_when_transition_rejected_without_message_uses_default(client, downstream):
    """
    Summary: A refusal with no reason still gives a readable message.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (set_event_safety_status raises a transition error without a
        message)
    """
    # Arrange (Given)
    downstream.fail["patch_event"] = clients.EventTransitionError(
        "INVALID_SAFETY_TRANSITION", {}
    )

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["message"] == (
        "Only an Approved event can be submitted for a safety check."
    )


def test_submit_for_missing_event_returns_404(client, downstream):
    """
    Summary: Submitting an event that does not exist returns 404.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Stub (get_event raises EventNotFoundError)
    """
    # Arrange (Given)
    downstream.fail["get_event"] = clients.EventNotFoundError

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 404
    assert response.json["message"] == "Event request not found."


def test_submit_when_event_deleted_mid_flight_rolls_round_back(client, downstream):
    """
    Summary: If the event disappears during submission, the new round is deleted.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (set_event_safety_status raises EventNotFoundError)
    """
    # Arrange (Given)
    downstream.fail["patch_event"] = clients.EventNotFoundError

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 404
    assert downstream.call("delete") == ("delete", RECORD_ID)


def test_submit_when_service_credentials_fail_rolls_round_back(client, downstream):
    """
    Summary: A service credentials failure on the move deletes the new round.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (set_event_safety_status raises a credentials error)
    """
    # Arrange (Given)
    downstream.fail["patch_event"] = clients.ServiceCredentialsError

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 502
    assert response.json["message"] == "Event Service refused this service's credentials."
    assert downstream.call("delete") == ("delete", RECORD_ID)


# --- Downstream failures: fail closed ----------------------------------------


@pytest.mark.parametrize("failing", ["bookings", "requests"])
def test_submit_when_arrangements_unreadable_returns_502(failing, client, downstream):
    """
    Summary: If bookings or requests cannot be read, nothing is submitted.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: Stub (bookings or requests raise DownstreamError)
    """
    # Arrange (Given)
    downstream.fail[failing] = clients.DownstreamError

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 502
    assert response.json["message"] == (
        "Unable to check the event's arrangements right now."
    )
    assert "create" not in downstream.names()
    assert "patch_event" not in downstream.names()


@pytest.mark.parametrize("failing", ["bookings", "requests"])
def test_submit_when_arrangements_time_out_returns_504(failing, client, downstream):
    """
    Summary: Timeouts reading bookings or requests return 504 and nothing is submitted.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: Stub (bookings or requests raise DownstreamTimeout)
    """
    # Arrange (Given)
    downstream.fail[failing] = clients.DownstreamTimeout

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 504
    assert "create" not in downstream.names()


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_submit_when_event_unreadable_writes_nothing(error, status, client, downstream):
    """
    Summary: If the event cannot be read, the failure is reported and nothing is written.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (get_event raises DownstreamError or DownstreamTimeout)
    """
    # Arrange (Given)
    downstream.fail["get_event"] = error

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == status
    assert downstream.names() == ["get_event"]


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_submit_when_record_creation_fails_is_reported(error, status, client, downstream):
    """
    Summary: If the round cannot be recorded, the failure is reported and the event does not move.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (create_safety_check_record raises DownstreamError or
        DownstreamTimeout)
    """
    # Arrange (Given)
    downstream.fail["create"] = error

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == status
    assert "patch_event" not in downstream.names()
    # Nothing was created, so there is nothing to compensate for.
    assert "delete" not in downstream.names()


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_submit_when_event_update_fails_rolls_round_back(error, status, client, downstream):
    """
    Summary: If the event cannot be moved, the new round is deleted.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (set_event_safety_status raises DownstreamError or
        DownstreamTimeout)
    """
    # Arrange (Given)
    downstream.fail["patch_event"] = error

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == status
    assert downstream.call("delete") == ("delete", RECORD_ID)


def test_submit_when_rollback_fails_logs_record_id(client, downstream, caplog):
    """
    Summary: If deleting the new round also fails, its id is logged for clean-up.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (set_event_safety_status and delete_safety_check_record raise)
    """
    # Arrange (Given)
    downstream.fail["patch_event"] = clients.DownstreamError
    downstream.fail["delete"] = clients.DownstreamError

    # Act (When)
    with caplog.at_level(logging.ERROR):
        response = submit(client)

    # Assert (Then)
    assert response.status_code == 502
    assert RECORD_ID in caplog.text
    assert "must be removed by hand" in caplog.text


def test_submit_when_open_round_lookup_fails_returns_502(client, downstream):
    """
    Summary: If the open round cannot be looked up, the submission fails closed.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: Stub (list_safety_check_records raises DownstreamError)
    """
    # Arrange (Given)
    downstream.event = event("Pending Safety Check")
    downstream.fail["list_records"] = clients.DownstreamError

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 502
    assert "create" not in downstream.names()


def test_submit_when_open_round_lookup_times_out_returns_504(client, downstream):
    """
    Summary: A timeout looking up the open round returns 504.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: Stub (list_safety_check_records raises DownstreamTimeout)
    """
    # Arrange (Given)
    downstream.event = event("Pending Safety Check")
    downstream.fail["list_records"] = clients.DownstreamTimeout

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 504


# --- Input -------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"eventId": "not-a-uuid", "coordinatorId": COORDINATOR_ID},
        {"coordinatorId": COORDINATOR_ID},
        {},
    ],
    ids=["eventid_not_a_uuid_coordinatorid_coordinator_id", "coordinatorid_coordinator_id", "empty"],
)
def test_submit_with_bad_ids_returns_400(body, client, downstream):
    """
    Summary: A submission needs a valid event id.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: None
    """
    # Arrange (Given): body, client, downstream, from fixtures

    # Act (When)
    response = client.post("/safety-checks", json=body)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "eventId must be a valid UUID."
    assert downstream.calls == []


def test_submit_with_non_object_body_returns_400(client, downstream):
    """
    Summary: A body that is not a JSON object is refused.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: None
    """
    # Arrange (Given): client, downstream, from fixtures

    # Act (When)
    response = client.post("/safety-checks", json="just a string")

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    assert downstream.calls == []


# --- GET /safety-checks/readiness (read-only) --------------------------------


def readiness(client, event_id=EVENT_ID, coordinator_id=COORDINATOR_ID):
    return client.get(
        f"/safety-checks/readiness?eventId={event_id}&coordinatorId={coordinator_id}"
    )


def test_readiness_for_ready_event_reports_ready(client, downstream):
    """
    Summary: Readiness says an event with everything confirmed can be submitted.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given): client, downstream, from fixtures

    # Act (When)
    response = readiness(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json == {
        "ready": True,
        "eventStatus": "Approved",
        "outstanding": [],
        "openSafetyCheck": None,
    }
    # Read-only: nothing was created and the event never moved.
    assert "create" not in downstream.names()
    assert "patch_event" not in downstream.names()


def test_readiness_lists_outstanding_arrangements(client, downstream):
    """
    Summary: Readiness lists the arrangements still outstanding.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.bookings = [booking("Pending Review")]
    downstream.requests = [equipment_request("Pending")]

    # Act (When)
    response = readiness(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["ready"] is False
    assert [item["type"] for item in response.json["outstanding"]] == [
        "venue",
        "equipment",
    ]
    assert "create" not in downstream.names()


def test_readiness_ignores_rejected_equipment(client, downstream):
    """
    Summary: Rejected equipment is not listed as outstanding.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.requests = [equipment_request("Rejected")]

    # Act (When)
    response = readiness(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json == {
        "ready": True,
        "eventStatus": "Approved",
        "outstanding": [],
        "openSafetyCheck": None,
    }
    assert "create" not in downstream.names()
    assert "patch_event" not in downstream.names()


def test_readiness_for_pending_event_returns_open_round(client, downstream):
    """
    Summary: For an event already pending, readiness points at the open round.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.event = event("Pending Safety Check")
    downstream.rounds = [record()]

    # Act (When)
    response = readiness(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["ready"] is False
    assert response.json["eventStatus"] == "Pending Safety Check"
    assert response.json["openSafetyCheck"]["roundNumber"] == 1


@pytest.mark.parametrize("status", ["Submitted", "Under Review", "Confirmed"])
def test_readiness_for_non_approved_event_is_not_ready(status, client, downstream):
    """
    Summary: An event outside the approved stage is not ready.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.event = event(status)

    # Act (When)
    response = readiness(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["ready"] is False
    assert response.json["eventStatus"] == status
    assert response.json["openSafetyCheck"] is None


def test_readiness_for_another_coordinator_returns_403(client, downstream):
    """
    Summary: Readiness is refused to a coordinator not assigned to the event.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Stub (get_event raises EventNotAssignedError)
    """
    # Arrange (Given)
    downstream.fail["get_event"] = clients.EventNotAssignedError

    # Act (When)
    response = readiness(client)

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["code"] == "NOT_ASSIGNED_COORDINATOR"


def test_readiness_for_missing_event_returns_404(client, downstream):
    """
    Summary: Readiness for an event that does not exist returns 404.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Stub (get_event raises EventNotFoundError)
    """
    # Arrange (Given)
    downstream.fail["get_event"] = clients.EventNotFoundError

    # Act + Assert (When / Then)
    assert readiness(client).status_code == 404


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_readiness_when_downstream_fails_fails_closed(error, status, client, downstream):
    """
    Summary: If arrangements cannot be read, readiness fails closed.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: Stub (Downstream raises DownstreamError or DownstreamTimeout)
    """
    # Arrange (Given)
    downstream.fail["bookings"] = error

    # Act + Assert (When / Then)
    assert readiness(client).status_code == status


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_readiness_when_open_round_lookup_fails_is_reported(error, status, client, downstream):
    """
    Summary: If the open round cannot be looked up, readiness reports the failure.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: Stub (list_safety_check_records raises DownstreamError or
        DownstreamTimeout)
    """
    # Arrange (Given)
    downstream.event = event("Pending Safety Check")
    downstream.fail["list_records"] = error

    # Act + Assert (When / Then)
    assert readiness(client).status_code == status


@pytest.mark.parametrize(
    "query",
    [
        f"?eventId=nope&coordinatorId={COORDINATOR_ID}",
        "",
    ],
    ids=["f_eventid_nope_coordinatorid_coordinator_id", "empty"],
)
def test_readiness_with_bad_event_id_returns_400(query, client, downstream):
    """
    Summary: Readiness needs a valid event id.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: None
    """
    # Arrange (Given): query, client, downstream, from fixtures

    # Act (When)
    response = client.get(f"/safety-checks/readiness{query}")

    # Assert (Then)
    assert response.status_code == 400
    assert downstream.calls == []


# --- Service plumbing --------------------------------------------------------


def test_submit_after_booking_change_withdrawal_opens_next_round(client, downstream):
    """
    Summary: An event sent back to Approved by a booking change can be submitted again as the next round.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (Downstream: canned event, bookings and requests)
    """
    # Arrange (Given)
    downstream.event = event("Approved")
    downstream.rounds = [record(round_number=2, status="Approval Withdrawn")]
    downstream.created = record(round_number=3)

    # Act (When)
    response = submit(client)

    # Assert (Then)
    assert response.status_code == 201
    assert downstream.call("create")[1] == EVENT_ID
    assert downstream.call("patch_event")[2:] == ("Pending Safety Check", COORDINATOR_ID, RECORD_ID, 3)


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_health_without_token_returns_ok(client):
    """
    Summary: Anyone can check the service is up without signing in.
    Supporting design check: /health answers without a token
    Double: None
    """
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_cors_for_frontend_origin_returns_allow_origin(client):
    """
    Summary: The configured frontend may call the service from a browser.
    Supporting design check: the configured frontend origin gets a CORS grant
    Double: None
    """
    response = client.get("/health", headers={"Origin": "http://localhost:5174"})

    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"


def test_cors_for_other_origin_sends_no_grant(client):
    """
    Summary: Other websites are not granted browser access.
    Supporting design check: other origins get no CORS grant
    Double: None
    """
    response = client.get("/health", headers={"Origin": "http://evil.example"})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_cors_with_blank_origin_allows_nothing(monkeypatch):
    """
    Summary: Blanking FRONTEND_ORIGIN switches browser access off.
    Supporting design check: an empty FRONTEND_ORIGIN grants no origin
    Double: None
    """
    monkeypatch.setenv("FRONTEND_ORIGIN", "")
    blank = signed_in(create_app().test_client())

    response = blank.get("/health", headers={"Origin": "http://localhost:5174"})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_without_token_returns_200(client):
    """
    Summary: The browser's preflight is answered without a token.
    Supporting design check: preflight requests answer without a token
    Double: None
    """
    response = client.options(
        "/safety-checks", headers={"Origin": "http://localhost:5174"}
    )

    assert response.status_code == 200
