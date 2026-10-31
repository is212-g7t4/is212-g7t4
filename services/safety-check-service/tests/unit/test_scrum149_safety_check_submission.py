"""
SCRUM-149: Submit Event for Operational Safety Check

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

Real
----
- Submitting an event for its safety check: only the assigned coordinator, only
  an Approved event whose arrangements are all settled, the notes saved with
  the new round, no second round while one is open, and undoing the round if
  the event cannot be moved; plus the readiness check the page uses before
  submitting.
- We check the result the coordinator sees, and the order of the calls to Event
  Service and Safety Check Record.

Doubled
-------
- Event, Safety Check Record, Venue Availability, Venue, Equipment Request and
  User Services: answer as each test needs, fail, or do not answer in time
  [Stub]; we check which were asked, in what order, and what they were sent
  [Mock].
- Sign-in: a test key signs the caller's token (tests/conftest.py) [Stub].

Not proven
----------
- That Event Service and Safety Check Record behave as faked (-> their own
  SCRUM-149 tests, and tests/integration/ here).
- The submit panel in the browser (-> frontend SafetySubmitPanel.test.tsx).
"""
import logging

import pytest

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
import httpx
from tests.unit.factories import BOOKING_ID, Response

PLACEMENT = "Speakers either side of the stage, cables taped along the left wall."
CROWD = "Entry through Door A, exit through Doors B and C; queue in the foyer."


@pytest.fixture
def downstream(submission_downstream):
    return submission_downstream




@pytest.fixture
def client():
    return signed_in(create_app().test_client())


def submit(client, **overrides):
    body = {"eventId": EVENT_ID, "coordinatorId": COORDINATOR_ID, **overrides}
    return client.post("/safety-checks", json=body)


# --- AC1, AC3: the happy path ------------------------------------------------


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
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    response = submit(client)

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
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    downstream.created = record(
        equipmentPlacementNotes=PLACEMENT, crowdMovementNotes=CROWD
    )

    response = submit(
        client, equipmentPlacementNotes=PLACEMENT, crowdMovementNotes=CROWD
    )

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
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    response = submit(client, **notes)

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
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    downstream.created = record(round_number=3)

    submit(client)

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
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    submit(client)

    assert downstream.names().index("create") < downstream.names().index("patch_event")


def test_submit_with_notes_at_limit_is_accepted(client, downstream):
    """
    Summary: Notes exactly at the length limit are saved.
    AC3: Given the Event Coordinator is submitting, when they enter equipment
        placement and expected crowd movement notes, then the notes are saved
        with the safety check.
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    response = submit(client, equipmentPlacementNotes="x" * 2000)

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
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    response = submit(client, **{field: "x" * 2001})

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
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    response = submit(client, **{field: 42})

    assert response.status_code == 400
    assert response.json["message"] == f"{label} must be text."
    assert downstream.calls == []


def test_submit_reads_equipment_as_submitting_coordinator(client, downstream):
    """
    Summary: Equipment requests are read with the submitting coordinator's identity.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    submit(client)

    assert downstream.call("requests") == ("requests", EVENT_ID, COORDINATOR_ID)


# --- AC2: outstanding arrangements block ------------------------------------


def test_submit_with_pending_booking_is_blocked(client, downstream):
    """
    Summary: A pending venue booking blocks submission and is listed.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    downstream.bookings = [booking("Pending Review")]

    response = submit(client)

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
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    downstream.requests = [equipment_request("Rejected")]

    response = submit(client)

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
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    downstream.requests = [
        equipment_request("Rejected"),
        equipment_request("Pending", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
    ]

    response = submit(client)

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
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    downstream.bookings = []

    response = submit(client)

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
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    downstream.event = event("Pending Safety Check")
    downstream.rounds = [record()]

    response = submit(client)

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
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    downstream.event = event("Pending Safety Check")
    downstream.rounds = []

    response = submit(client)

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_PENDING"
    assert response.json["message"] == (
        "This event is already waiting for its safety check."
    )
    assert response.json["safetyCheck"] is None


def test_submit_when_record_service_conflicts_returns_409(client, downstream):
    """
    Summary: If Safety Check Record already has a round open, the coordinator is told the event is already submitted.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: Safety Check Record says a round is already open [Stub].
    """
    downstream.fail["create"] = clients.SafetyCheckAlreadyPendingError(record())

    response = submit(client)

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
    Double: Event Service refuses to move the event because its status changed
        [Stub]; we check the new round is removed [Mock].
    """
    downstream.fail["patch_event"] = clients.EventTransitionError(
        "SAFETY_CHECK_ALREADY_PENDING", {"code": "SAFETY_CHECK_ALREADY_PENDING"}
    )
    downstream.rounds = [record(round_number=2)]

    response = submit(client)

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_PENDING"
    assert downstream.call("delete") == ("delete", RECORD_ID)


# --- AC5: only the assigned coordinator -------------------------------------


def test_submit_by_another_coordinator_returns_403_before_reads(client, downstream):
    """
    Summary: A coordinator not assigned to the event is refused before anything is read.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Event Service says the caller is not the event's coordinator
        [Stub].
    """
    downstream.fail["get_event"] = clients.EventNotAssignedError

    response = submit(client)

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
    Double: Event Service says the caller is no longer the event's coordinator
        [Stub]; we check the new round is removed [Mock].
    """
    downstream.fail["patch_event"] = clients.EventNotAssignedError

    response = submit(client)

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
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    downstream.event = event(status)

    response = submit(client)

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
    Double: Event Service refuses to move the event, giving a reason [Stub]; we
        check the new round is removed [Mock].
    """
    downstream.fail["patch_event"] = clients.EventTransitionError(
        "INVALID_SAFETY_TRANSITION",
        {
            "code": "INVALID_SAFETY_TRANSITION",
            "message": "This event can't move to 'Pending Safety Check' from 'Cancelled'.",
            "currentStatus": "Cancelled",
        },
    )

    response = submit(client)

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
    Double: Event Service refuses to move the event without giving a reason
        [Stub].
    """
    downstream.fail["patch_event"] = clients.EventTransitionError(
        "INVALID_SAFETY_TRANSITION", {}
    )

    response = submit(client)

    assert response.status_code == 409
    assert response.json["message"] == (
        "Only an Approved event can be submitted for a safety check."
    )


def test_submit_for_missing_event_returns_404(client, downstream):
    """
    Summary: Submitting an event that does not exist says so.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Event Service does not know the event [Stub].
    """
    downstream.fail["get_event"] = clients.EventNotFoundError

    response = submit(client)

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
    Double: Event Service no longer knows the event [Stub]; we check the new
        round is removed [Mock].
    """
    downstream.fail["patch_event"] = clients.EventNotFoundError

    response = submit(client)

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
    Double: Event Service refuses this service's credentials [Stub]; we check
        the new round is removed [Mock].
    """
    downstream.fail["patch_event"] = clients.ServiceCredentialsError

    response = submit(client)

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
    Double: Venue Availability or Equipment Request fails [Stub].
    """
    downstream.fail[failing] = clients.DownstreamError

    response = submit(client)

    assert response.status_code == 502
    assert response.json["message"] == (
        "Unable to check the event's arrangements right now."
    )
    assert "create" not in downstream.names()
    assert "patch_event" not in downstream.names()


@pytest.mark.parametrize("failing", ["bookings", "requests"])
def test_submit_when_arrangements_time_out_returns_504(failing, client, downstream):
    """
    Summary: If bookings or equipment requests are not read in time, nothing is submitted.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: Venue Availability or Equipment Request does not answer in time
        [Stub].
    """
    downstream.fail[failing] = clients.DownstreamTimeout

    response = submit(client)

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
    Double: Event Service fails or does not answer in time [Stub].
    """
    downstream.fail["get_event"] = error

    response = submit(client)

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
    Double: Safety Check Record fails or does not answer in time [Stub].
    """
    downstream.fail["create"] = error

    response = submit(client)

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
    Double: Event Service fails or does not answer in time when moving the
        event [Stub]; we check the new round is removed [Mock].
    """
    downstream.fail["patch_event"] = error

    response = submit(client)

    assert response.status_code == status
    assert downstream.call("delete") == ("delete", RECORD_ID)


def test_submit_when_rollback_fails_logs_record_id(client, downstream, caplog):
    """
    Summary: If the new round also cannot be removed, it is logged for clean-up.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Event Service cannot move the event and Safety Check Record cannot
        remove the new round [Stub]; we check the round is logged for clean-up
        [Mock].
    """
    downstream.fail["patch_event"] = clients.DownstreamError
    downstream.fail["delete"] = clients.DownstreamError

    with caplog.at_level(logging.ERROR):
        response = submit(client)

    assert response.status_code == 502
    assert RECORD_ID in caplog.text
    assert "must be removed by hand" in caplog.text


def test_submit_when_open_round_lookup_fails_returns_502(client, downstream):
    """
    Summary: If the open round cannot be looked up, the submission fails closed.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: Safety Check Record fails when asked for the open round [Stub].
    """
    downstream.event = event("Pending Safety Check")
    downstream.fail["list_records"] = clients.DownstreamError

    response = submit(client)

    assert response.status_code == 502
    assert "create" not in downstream.names()


def test_submit_when_open_round_lookup_times_out_returns_504(client, downstream):
    """
    Summary: If Safety Check Record does not answer in time about the open round, nothing is submitted.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: Safety Check Record does not answer in time when asked for the open
        round [Stub].
    """
    downstream.event = event("Pending Safety Check")
    downstream.fail["list_records"] = clients.DownstreamTimeout

    response = submit(client)

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
    Summary: A submission must name a real event.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: None
    """
    response = client.post("/safety-checks", json=body)

    assert response.status_code == 400
    assert response.json["message"] == "eventId must be a valid UUID."
    assert downstream.calls == []


def test_submit_with_non_object_body_returns_400(client, downstream):
    """
    Summary: A submission that is not in the expected form is refused.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: None
    """
    response = client.post("/safety-checks", json="just a string")

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
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    response = readiness(client)

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
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    downstream.bookings = [booking("Pending Review")]
    downstream.requests = [equipment_request("Pending")]

    response = readiness(client)

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
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    downstream.requests = [equipment_request("Rejected")]

    response = readiness(client)

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
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    downstream.event = event("Pending Safety Check")
    downstream.rounds = [record()]

    response = readiness(client)

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
    Double: Event Service, Venue Availability and Equipment Request hold an
        event and its arrangements, and Safety Check Record accepts the new
        round [Stub].
    """
    downstream.event = event(status)

    response = readiness(client)

    assert response.status_code == 200
    assert response.json["ready"] is False
    assert response.json["eventStatus"] == status
    assert response.json["openSafetyCheck"] is None


def test_readiness_for_another_coordinator_returns_403(client, downstream):
    """
    Summary: Readiness is refused to a coordinator not assigned to the event.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Event Service says the caller is not the event's coordinator
        [Stub].
    """
    downstream.fail["get_event"] = clients.EventNotAssignedError

    response = readiness(client)

    assert response.status_code == 403
    assert response.json["code"] == "NOT_ASSIGNED_COORDINATOR"


def test_readiness_for_missing_event_returns_404(client, downstream):
    """
    Summary: Checking an event that does not exist says so.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Event Service does not know the event [Stub].
    """
    downstream.fail["get_event"] = clients.EventNotFoundError

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
    Double: The other services fail or do not answer in time [Stub].
    """
    downstream.fail["bookings"] = error

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
    Double: Safety Check Record fails or does not answer in time when asked for
        the open round [Stub].
    """
    downstream.event = event("Pending Safety Check")
    downstream.fail["list_records"] = error

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
    Summary: Checking readiness must name a real event.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: None
    """
    response = client.get(f"/safety-checks/readiness{query}")

    assert response.status_code == 400
    assert downstream.calls == []


# --- Service plumbing --------------------------------------------------------




def test_get_event_client_reads_as_the_coordinator(sent):
    """
    Summary: The event is read as the coordinator, so Event Service checks their assignment.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    calls, queue = sent
    queue.append(Response(200, event("Approved")))

    assert clients.get_event(EVENT_ID)["status"] == "Approved"
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith(f"/events/{EVENT_ID}")
    assert calls[0]["params"] == {}
    assert calls[0]["timeout"] == clients.TIMEOUT


def test_get_event_client_without_viewer_role_omits_it(sent):
    """
    Summary: No viewer role is sent when none is given.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
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
    Summary: Each way of failing to read the event (not assigned, not found, failed) is reported for what it is.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
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
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
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
    assert calls[0]["headers"] == {"X-Internal-Token": "shared-secret"}


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (404, clients.EventNotFoundError),
        (500, clients.DownstreamError),
    ],
)
def test_set_safety_status_client_maps_statuses(status, expected, sent):
    """
    Summary: Each way the event move can fail is reported for what it is.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
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
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    _, queue = sent
    queue.append(Response(403, {"message": "nope"}))

    with pytest.raises(clients.EventNotAssignedError):
        clients.set_event_safety_status(
            EVENT_ID, "Pending Safety Check", RECORD_ID, 1
        )


def test_set_safety_status_client_internal_only_403_is_credentials_error(sent):
    """
    Summary: If Event Service refuses this service's own credentials, it is reported as a set-up problem here, not as the user's fault.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
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
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
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
    Summary: If Event Service refuses a move without explaining why, it is still reported as a refused move.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    _, queue = sent
    queue.append(Response(409, None))

    with pytest.raises(clients.EventTransitionError) as raised:
        clients.set_event_safety_status(
            EVENT_ID, "Pending Safety Check", RECORD_ID, 1
        )

    assert raised.value.code is None
    assert raised.value.body == {}


def test_bookings_client_reads_every_booking_of_event(sent):
    """
    Summary: Every booking of the event is read, in every status.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    calls, queue = sent
    queue.append(Response(200, {"bookings": [booking("Approved")]}))

    bookings = clients.get_event_venue_bookings(EVENT_ID)

    assert [b["id"] for b in bookings] == [BOOKING_ID]
    assert calls[0]["url"].endswith(f"/events/{EVENT_ID}/venue-bookings")


def test_bookings_client_failure_is_downstream_error(sent):
    """
    Summary: If the event's bookings cannot be read, it is reported as a failure of that service.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    _, queue = sent
    queue.append(Response(503, {"message": "DATABASE_URL is not configured"}))

    with pytest.raises(clients.DownstreamError):
        clients.get_event_venue_bookings(EVENT_ID)


def test_equipment_client_reads_with_callers_token(sent):
    """
    Summary: Equipment requests are read as the signed-in user.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    calls, queue = sent
    queue.append(Response(200, {"requests": [equipment_request("Approved")]}))

    with create_app().test_request_context(headers={"Authorization": "Bearer caller-token"}):
        clients.get_event_equipment_requests(EVENT_ID)

    assert calls[0]["params"] == {"eventId": EVENT_ID}
    assert calls[0]["headers"] == {"Authorization": "Bearer caller-token"}


def test_equipment_client_refusal_is_downstream_error(sent):
    """
    Summary: If Equipment Request refuses to share the event's requests, it is reported as a failure of that service.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    _, queue = sent
    queue.append(Response(403, {"message": "Only Technical Support ..."}))

    with pytest.raises(clients.DownstreamError):
        clients.get_event_equipment_requests(EVENT_ID)


def test_create_record_client_sends_notes(sent):
    """
    Summary: A new round carries the coordinator's notes.
    AC3: Given the Event Coordinator is submitting, when they enter equipment
        placement and expected crowd movement notes, then the notes are saved
        with the safety check.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
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
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
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
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
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
    Summary: If Safety Check Record reports a duplicate round without details, it is still treated as a duplicate.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    _, queue = sent
    queue.append(Response(409, None))

    with pytest.raises(clients.SafetyCheckAlreadyPendingError) as raised:
        clients.create_safety_check_record(
EVENT_ID)

    assert raised.value.existing is None


def test_create_record_client_failure_is_downstream_error(sent):
    """
    Summary: If the new round cannot be recorded, it is reported as a failure of that service.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
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
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
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
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    calls, queue = sent
    queue.append(Response(200, {"safetyChecks": []}))

    assert clients.list_safety_check_records(EVENT_ID) == []
    assert calls[0]["params"] == {"eventId": EVENT_ID}


def test_list_records_client_failure_is_downstream_error(sent):
    """
    Summary: If the event's rounds cannot be read, it is reported as a failure of that service.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    _, queue = sent
    queue.append(Response(503, {"message": "down"}))

    with pytest.raises(clients.DownstreamError):
        clients.list_safety_check_records(EVENT_ID)


def test_delete_record_client_accepts_no_content(sent):
    """
    Summary: Undoing a round accepts an empty success answer.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
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
    Summary: Each way removing a round can fail is reported for what it is.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    _, queue = sent
    queue.append(Response(status, {"message": "no"}))

    with pytest.raises(expected):
        clients.delete_safety_check_record(RECORD_ID)


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
    Summary: When another service does not answer in time, or cannot be reached, it is reported as a failure of that service.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    _, queue = sent
    queue.append(raised)

    with pytest.raises(expected):
        clients.get_event(EVENT_ID)
