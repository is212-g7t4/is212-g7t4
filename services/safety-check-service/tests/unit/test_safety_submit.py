"""# Test scope and acceptance mapping — SCRUM-171 integration

- **SCRUM-149 submission/readiness regression; no direct SCRUM-171 AC:** original numbered criteria below belong to SCRUM-149, not SCRUM-171.
- **Separately approved venue-only compatibility:** `test_rejected_venue_history_uses_live_replacement_readiness` checks GET readiness and POST with approved replacement (allowed), no replacement (blocked), and pending replacement (blocked). Mocked downstreams do not prove real safety/database integration; equipment still blocks.

## Case/group traceability

The named test functions/cases below implement the groups above; their existing
names and assertions specify the scenario. No group is credited with all five ACs.

## Existing test contract and detailed cases

SCRUM-149: POST /safety-checks and GET /safety-checks/readiness.

AC1 Given an event assigned to the Event Coordinator has every venue booking
    approved and every equipment request approved/reserved (or no equipment
    requested), when the Event Coordinator submits it for a safety check, then
    its status changes to 'Pending Safety Check' and the submission time is
    recorded.
AC2 Given any venue booking or equipment request for the event is still
    pending or rejected, when the Event Coordinator tries to submit, then
    submission is blocked and the outstanding arrangements are listed.

SCRUM-171 authorised compatibility exception: rejected VENUE requests are
immutable history; require a live approved replacement. Equipment is unchanged.
AC3 Given the Event Coordinator is submitting, when they enter equipment
    placement and expected crowd movement notes, then the notes are saved with
    the safety check.
AC4 Given the event is already 'Pending Safety Check', when the Event
    Coordinator submits it again, then no duplicate safety check is created.
AC5 Given the Event Coordinator is not the assigned coordinator, then the
    submit action is not available and an API call is rejected.

Every downstream call is a monkeypatched `app.clients` wrapper, so these tests
exercise the orchestration and the error mapping, not HTTP (`test_clients.py`
covers that).
"""
import logging

import pytest

from app import clients, create_app
from tests.unit.factories import (
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

    def get_event(self, event_id, coordinator_id):
        self.calls.append(("get_event", event_id, coordinator_id))
        self._maybe_fail("get_event")
        return self.event

    def get_event_venue_bookings(self, event_id):
        self.calls.append(("bookings", event_id))
        self._maybe_fail("bookings")
        return self.bookings

    def get_event_equipment_requests(self, event_id, coordinator_id):
        self.calls.append(("requests", event_id, coordinator_id))
        self._maybe_fail("requests")
        return self.requests

    def list_safety_check_records(self, event_id, status=None):
        self.calls.append(("list_records", event_id, status))
        self._maybe_fail("list_records")
        return self.rounds

    def create_safety_check_record(self, event_id, submitted_by, placement=None, crowd=None):
        self.calls.append(("create", event_id, submitted_by, placement, crowd))
        self._maybe_fail("create")
        return self.created

    def set_event_safety_status(
        self,
        event_id,
        status,
        safety_check_id,
        round_number,
        coordinator_id=None,
        decided_by=None,
        remarks=None,
    ):
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
    return create_app().test_client()


def submit(client, **overrides):
    body = {"eventId": EVENT_ID, "coordinatorId": COORDINATOR_ID, **overrides}
    return client.post("/safety-checks", json=body)


def resubmit(client, **overrides):
    return client.post("/safety-checks/resubmit", json={
        "eventId": EVENT_ID, "coordinatorId": COORDINATOR_ID, **overrides,
    })


# Safety revision AC5 (mocked orchestration): approved arrangements open round 2 and move to Pending Safety Check.
# The old stub round remains unchanged; database history persistence is covered by Record Service tests.
def test_resubmission_opens_next_round_only_with_approved_arrangements(client, downstream):
    downstream.event = event("Safety Changes Requested")
    downstream.rounds = [record(1, "Changes Requested")]
    downstream.created = record(2)
    downstream.requests = [equipment_request("Approved")]
    response = resubmit(client, equipmentPlacementNotes=PLACEMENT, crowdMovementNotes=CROWD)
    assert response.status_code == 201
    assert response.json["safetyCheck"]["roundNumber"] == 2
    assert response.json["event"]["status"] == "Pending Safety Check"
    assert downstream.call("create") == ("create", EVENT_ID, COORDINATOR_ID, PLACEMENT, CROWD)
    assert "bookings" in downstream.names()
    assert "delete" not in downstream.names()
    assert downstream.rounds[0]["status"] == "Changes Requested"


# Safety revision AC3: pending equipment blocks resubmission before a new review round can be written.
def test_resubmission_with_pending_equipment_is_blocked_before_writes(client, downstream):
    downstream.event = event("Safety Changes Requested")
    downstream.requests = [equipment_request("Pending")]
    response = resubmit(client)
    assert response.status_code == 422
    assert response.json["outstanding"][0]["status"] == "Pending"
    assert "create" not in downstream.names()
    assert "bookings" in downstream.names()


# Safety revision AC5 (readiness): approved venue plus approved equipment, or no equipment, permits resubmission.
@pytest.mark.parametrize("requests", [[], [equipment_request("Approved")]])
def test_resubmission_readiness_requires_both_approved_arrangements(client, downstream, requests):
    downstream.event = event("Safety Changes Requested")
    downstream.requests = requests
    response = client.get("/safety-checks/resubmit/readiness", query_string={"eventId": EVENT_ID, "coordinatorId": COORDINATOR_ID})
    assert response.status_code == 200
    assert response.json == {"ready": True, "eventStatus": "Safety Changes Requested", "outstanding": []}
    assert "bookings" in downstream.names()


# Safety revision AC2/AC3: unresolved venue or equipment arrangements block both readiness and submission.
@pytest.mark.parametrize("venue_status,equipment_status", [("Pending Review", "Approved"), ("Approved", "Rejected"), ("Rejected", "Approved")])
def test_resubmission_blocks_unready_venue_or_equipment(client, downstream, venue_status, equipment_status):
    downstream.event = event("Safety Changes Requested")
    downstream.bookings = [booking(venue_status)]
    downstream.requests = [equipment_request(equipment_status)]
    assert resubmit(client).status_code == 422
    response = client.get(f"/safety-checks/resubmit/readiness?eventId={EVENT_ID}&coordinatorId={COORDINATOR_ID}")
    assert response.json["ready"] is False
    assert "create" not in downstream.names()


def test_resubmission_readiness_blocks_pending_equipment_and_other_event_stages(client, downstream):
    downstream.event = event("Safety Changes Requested")
    downstream.requests = [equipment_request("Pending")]
    url = f"/safety-checks/resubmit/readiness?eventId={EVENT_ID}&coordinatorId={COORDINATOR_ID}"
    assert client.get(url).json["ready"] is False
    downstream.event = event("Approved")
    downstream.requests = []
    assert client.get(url).json["ready"] is False
    assert resubmit(client).status_code == 409


def test_resubmission_readiness_rejects_invalid_identifiers(client, downstream):
    assert client.get("/safety-checks/resubmit/readiness?eventId=bad").status_code == 400
    assert downstream.calls == []


@pytest.mark.parametrize("error,code", [(clients.EventNotAssignedError(), 403), (clients.EventNotFoundError(), 404)])
def test_resubmission_access_denied_before_equipment_read(client, downstream, error, code):
    downstream.fail["get_event"] = error
    assert resubmit(client).status_code == code
    assert client.get(f"/safety-checks/resubmit/readiness?eventId={EVENT_ID}&coordinatorId={COORDINATOR_ID}").status_code == code
    assert "requests" not in downstream.names()


@pytest.mark.parametrize("error,code", [(clients.DownstreamError(), 502), (clients.DownstreamTimeout(), 504)])
def test_resubmission_equipment_failure_is_closed(client, downstream, error, code):
    downstream.event = event("Safety Changes Requested")
    downstream.fail["requests"] = error
    assert resubmit(client).status_code == code
    assert client.get(f"/safety-checks/resubmit/readiness?eventId={EVENT_ID}&coordinatorId={COORDINATOR_ID}").status_code == code
    assert "create" not in downstream.names()


# --- AC1, AC3: the happy path ------------------------------------------------


@pytest.mark.parametrize("replacement, ready, status", [
    ("Approved", True, 201), (None, False, 422), ("Pending Review", False, 422),
])
def test_rejected_venue_history_uses_live_replacement_readiness(client, downstream, replacement, ready, status):
    """Separately approved SCRUM-171 compatibility rule, not a sixth ticket AC."""
    downstream.bookings = [booking("Rejected")]
    if replacement:
        downstream.bookings.append(booking(replacement, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"))
    result = readiness(client)
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


def test_submission_creates_a_round_and_moves_the_event(client, downstream):
    """AC1: the event becomes 'Pending Safety Check' and the round is created."""
    response = submit(client)

    assert response.status_code == 201
    assert response.json["event"]["status"] == "Pending Safety Check"
    assert response.json["safetyCheck"]["roundNumber"] == 1
    assert response.json["safetyCheck"]["status"] == "Pending"
    assert response.json["safetyCheck"]["submittedAt"] == "2026-11-01T02:30:00+00:00"


def test_notes_are_sent_to_the_record_service(client, downstream):
    """AC3: both notes are saved with the safety check."""
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
)
def test_notes_are_optional(notes, client, downstream):
    """AC3: the notes are optional, and blank is not stored as an empty string."""
    response = submit(client, **notes)

    assert response.status_code == 201
    assert downstream.call("create")[3:] == (None, None)


def test_the_round_number_is_passed_to_event_service(client, downstream):
    """AC1: the event's history records which round it was submitted for."""
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


def test_the_record_is_created_before_the_event_moves(client, downstream):
    """The record service is the duplicate guard, so it must go first (AC4)."""
    submit(client)

    assert downstream.names().index("create") < downstream.names().index("patch_event")


def test_notes_at_the_limit_are_accepted(client, downstream):
    """AC3 boundary: 2000 characters is the limit."""
    response = submit(client, equipmentPlacementNotes="x" * 2000)

    assert response.status_code == 201


@pytest.mark.parametrize(
    ("field", "label"),
    [
        ("equipmentPlacementNotes", "Equipment placement notes"),
        ("crowdMovementNotes", "Expected crowd movement notes"),
    ],
)
def test_notes_over_the_limit_write_nothing(field, label, client, downstream):
    """AC3 boundary: 2001 characters is refused before anything is read or written."""
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
def test_non_text_notes_are_rejected(field, label, client, downstream):
    response = submit(client, **{field: 42})

    assert response.status_code == 400
    assert response.json["message"] == f"{label} must be text."
    assert downstream.calls == []


def test_equipment_requests_are_read_as_the_submitting_coordinator(client, downstream):
    """Contract: Equipment Request Service's READ_ROLES allow Event Coordinators.

    The composite passes the caller's own identity rather than inventing a
    service account — see `clients.get_event_equipment_requests`.
    """
    submit(client)

    assert downstream.call("requests") == ("requests", EVENT_ID, COORDINATOR_ID)


# --- AC2: outstanding arrangements block ------------------------------------


def test_pending_booking_blocks_the_submission(client, downstream):
    """AC2: blocked, with the outstanding arrangements listed and nothing written."""
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


def test_rejected_equipment_request_blocks_the_submission(client, downstream):
    """AC2: a rejected equipment request keeps blocking — there's no withdraw path."""
    downstream.requests = [equipment_request("Rejected")]

    response = submit(client)

    assert response.status_code == 422
    assert response.json["outstanding"][0]["type"] == "equipment"
    assert "create" not in downstream.names()


def test_event_with_no_booking_blocks_the_submission(client, downstream):
    """AC2 boundary: an event with nowhere to happen isn't ready."""
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


def test_already_pending_event_is_refused_with_its_open_round(client, downstream):
    """AC4: a second submission creates nothing and says when the first was."""
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


def test_already_pending_without_a_findable_round_still_refuses(client, downstream):
    """AC4 edge: the event says pending but no open round came back. Still no duplicate."""
    downstream.event = event("Pending Safety Check")
    downstream.rounds = []

    response = submit(client)

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_PENDING"
    assert response.json["message"] == (
        "This event is already waiting for its safety check."
    )
    assert response.json["safetyCheck"] is None


def test_record_service_conflict_is_the_same_conflict(client, downstream):
    """AC4's race: two submits at once, and the record service refuses the second."""
    downstream.fail["create"] = clients.SafetyCheckAlreadyPendingError(record())

    response = submit(client)

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_PENDING"
    assert response.json["safetyCheck"]["roundNumber"] == 1
    # Nothing moved the event: the round we'd have used is someone else's.
    assert "patch_event" not in downstream.names()


def test_event_service_conflict_rolls_the_round_back(client, downstream):
    """AC4's other race: Event Service's own lock catches the duplicate.

    The round we created is then deleted, so the event isn't left with an open
    round nobody is reviewing.
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


def test_another_coordinator_is_refused_before_anything_is_read(client, downstream):
    """AC5: an API call from anyone but the assigned coordinator is rejected."""
    downstream.fail["get_event"] = clients.EventNotAssignedError

    response = submit(client)

    assert response.status_code == 403
    assert response.json["code"] == "NOT_ASSIGNED_COORDINATOR"
    assert response.json["message"] == (
        "Only the event's assigned coordinator can submit it for a safety check."
    )
    # No arrangements read, nothing written: a stranger learns nothing.
    assert downstream.names() == ["get_event"]


def test_reassignment_mid_flight_rolls_the_round_back(client, downstream):
    """AC5 under a race: Event Service re-checks assignment inside its row lock.

    Our step-2 read can be stale, so a reassignment between the two is caught
    there — and the round we already created is removed again.
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
def test_only_an_approved_event_can_be_submitted(status, client, downstream):
    """An event that hasn't been approved yet, or is already past this point."""
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


def test_event_service_rejecting_the_transition_is_reported(client, downstream):
    """A status change between step 2 and step 6 — rare, but it must not 500."""
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


def test_transition_error_without_a_message_still_reads_sensibly(client, downstream):
    downstream.fail["patch_event"] = clients.EventTransitionError(
        "INVALID_SAFETY_TRANSITION", {}
    )

    response = submit(client)

    assert response.status_code == 409
    assert response.json["message"] == (
        "Only an Approved event can be submitted for a safety check."
    )


def test_missing_event_is_404(client, downstream):
    downstream.fail["get_event"] = clients.EventNotFoundError

    response = submit(client)

    assert response.status_code == 404
    assert response.json["message"] == "Event request not found."


def test_event_deleted_mid_flight_rolls_the_round_back(client, downstream):
    downstream.fail["patch_event"] = clients.EventNotFoundError

    response = submit(client)

    assert response.status_code == 404
    assert downstream.call("delete") == ("delete", RECORD_ID)


def test_service_credentials_error_rolls_the_round_back(client, downstream):
    """SCRUM-150: Event Service refusing our internal token is our problem."""
    downstream.fail["patch_event"] = clients.ServiceCredentialsError

    response = submit(client)

    assert response.status_code == 502
    assert response.json["message"] == "Event Service refused this service's credentials."
    assert downstream.call("delete") == ("delete", RECORD_ID)


# --- Downstream failures: fail closed ----------------------------------------


@pytest.mark.parametrize("failing", ["bookings", "requests"])
def test_unreadable_arrangements_block_the_submission(failing, client, downstream):
    """Fail closed: "couldn't check" must never be treated as "nothing outstanding"."""
    downstream.fail[failing] = clients.DownstreamError

    response = submit(client)

    assert response.status_code == 502
    assert response.json["message"] == (
        "Unable to check the event's arrangements right now."
    )
    assert "create" not in downstream.names()
    assert "patch_event" not in downstream.names()


@pytest.mark.parametrize("failing", ["bookings", "requests"])
def test_arrangement_timeouts_are_504(failing, client, downstream):
    downstream.fail[failing] = clients.DownstreamTimeout

    response = submit(client)

    assert response.status_code == 504
    assert "create" not in downstream.names()


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_event_read_failure_is_reported_without_writing(error, status, client, downstream):
    downstream.fail["get_event"] = error

    response = submit(client)

    assert response.status_code == status
    assert downstream.names() == ["get_event"]


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_record_creation_failure_is_reported(error, status, client, downstream):
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
def test_event_update_failure_rolls_the_round_back(error, status, client, downstream):
    downstream.fail["patch_event"] = error

    response = submit(client)

    assert response.status_code == status
    assert downstream.call("delete") == ("delete", RECORD_ID)


def test_failed_compensation_is_logged_with_the_record_id(client, downstream, caplog):
    """The one case with no clean recovery: say which round was left behind.

    The event then reads 'Approved' while the next submit gets
    ALREADY_PENDING; the README says how to clear it.
    """
    downstream.fail["patch_event"] = clients.DownstreamError
    downstream.fail["delete"] = clients.DownstreamError

    with caplog.at_level(logging.ERROR):
        response = submit(client)

    assert response.status_code == 502
    assert RECORD_ID in caplog.text
    assert "must be removed by hand" in caplog.text


def test_looking_up_the_open_round_can_fail_closed(client, downstream):
    """AC4's message needs the open round; if that read fails, say so rather than
    reporting a successful submission that never happened."""
    downstream.event = event("Pending Safety Check")
    downstream.fail["list_records"] = clients.DownstreamError

    response = submit(client)

    assert response.status_code == 502
    assert "create" not in downstream.names()


def test_open_round_lookup_timeout_is_504(client, downstream):
    downstream.event = event("Pending Safety Check")
    downstream.fail["list_records"] = clients.DownstreamTimeout

    response = submit(client)

    assert response.status_code == 504


# --- Input -------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"eventId": "not-a-uuid", "coordinatorId": COORDINATOR_ID},
        {"eventId": EVENT_ID, "coordinatorId": "nope"},
        {"eventId": EVENT_ID},
        {"coordinatorId": COORDINATOR_ID},
        {},
    ],
)
def test_bad_identifiers_are_rejected(body, client, downstream):
    response = client.post("/safety-checks", json=body)

    assert response.status_code == 400
    assert response.json["message"] == (
        "eventId and coordinatorId must be valid UUIDs."
    )
    assert downstream.calls == []


def test_non_object_body_is_rejected(client, downstream):
    response = client.post("/safety-checks", json="just a string")

    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    assert downstream.calls == []


# --- GET /safety-checks/readiness (read-only) --------------------------------


def readiness(client, event_id=EVENT_ID, coordinator_id=COORDINATOR_ID):
    return client.get(
        f"/safety-checks/readiness?eventId={event_id}&coordinatorId={coordinator_id}"
    )


def test_readiness_reports_a_ready_event(client, downstream):
    """AC1 ahead of the click: the panel can enable its submit button."""
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


def test_readiness_lists_what_is_outstanding(client, downstream):
    """AC2 ahead of the click: the coordinator sees what's missing before submitting."""
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


def test_readiness_on_a_pending_event_returns_the_open_round(client, downstream):
    """AC4 in the UI: once submitted, the panel shows the round instead of a button."""
    downstream.event = event("Pending Safety Check")
    downstream.rounds = [record()]

    response = readiness(client)

    assert response.status_code == 200
    assert response.json["ready"] is False
    assert response.json["eventStatus"] == "Pending Safety Check"
    assert response.json["openSafetyCheck"]["roundNumber"] == 1


@pytest.mark.parametrize("status", ["Submitted", "Under Review", "Confirmed"])
def test_readiness_is_false_for_a_non_approved_event(status, client, downstream):
    downstream.event = event(status)

    response = readiness(client)

    assert response.status_code == 200
    assert response.json["ready"] is False
    assert response.json["eventStatus"] == status
    assert response.json["openSafetyCheck"] is None


def test_readiness_refuses_another_coordinator(client, downstream):
    """AC5: the panel is hidden in the UI, and the API says no as well."""
    downstream.fail["get_event"] = clients.EventNotAssignedError

    response = readiness(client)

    assert response.status_code == 403
    assert response.json["code"] == "NOT_ASSIGNED_COORDINATOR"


def test_readiness_for_a_missing_event_is_404(client, downstream):
    downstream.fail["get_event"] = clients.EventNotFoundError

    assert readiness(client).status_code == 404


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_readiness_fails_closed(error, status, client, downstream):
    downstream.fail["bookings"] = error

    assert readiness(client).status_code == status


@pytest.mark.parametrize(
    ("error", "status"),
    [(clients.DownstreamError, 502), (clients.DownstreamTimeout, 504)],
)
def test_readiness_open_round_failure_is_reported(error, status, client, downstream):
    downstream.event = event("Pending Safety Check")
    downstream.fail["list_records"] = error

    assert readiness(client).status_code == status


@pytest.mark.parametrize(
    "query",
    [
        f"?eventId=nope&coordinatorId={COORDINATOR_ID}",
        f"?eventId={EVENT_ID}&coordinatorId=nope",
        f"?eventId={EVENT_ID}",
        "",
    ],
)
def test_readiness_needs_both_identifiers(query, client, downstream):
    response = client.get(f"/safety-checks/readiness{query}")

    assert response.status_code == 400
    assert downstream.calls == []


# --- Service plumbing --------------------------------------------------------


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_cors_allows_the_frontend_origin(client):
    response = client.get("/health", headers={"Origin": "http://localhost:5174"})

    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"


def test_cors_rejects_another_origin(client):
    response = client.get("/health", headers={"Origin": "http://evil.example"})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_cors_with_no_configured_origin_allows_nothing(monkeypatch):
    """A blank FRONTEND_ORIGIN must not become a wildcard."""
    monkeypatch.setenv("FRONTEND_ORIGIN", "")
    blank = create_app().test_client()

    response = blank.get("/health", headers={"Origin": "http://localhost:5174"})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_returns_200(client):
    response = client.options(
        "/safety-checks", headers={"Origin": "http://localhost:5174"}
    )

    assert response.status_code == 200
