"""
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

Real
----
- PATCH /events/<id>/safety-status in app/__init__.py and the status rules in
  app/models.py, run through a real create_app(): request validation, the
  status and round checks, the history entry written, and the SQL and
  parameters sent to the database. AC4 is shown through GET
  /events/attendee-summaries.
- Assertions are on the HTTP status, the response body and the queries and
  parameters the cursor received.

Doubled
-------
- psycopg2.connect: Stub (fixture) - a MagicMock connection whose cursor
  returns canned rows; Mock - its execute calls are asserted to prove what was
  (or was not) written.
- Supabase JWKS: Stub (tests/conftest.py) - tokens are signed with a throwaway
  ES256 key.

Not proven
----------
- That the SQL runs against the real Postgres schema, constraints and row locks
  (-> tests/integration/ against a throwaway postgres:17.6).
- That the 'Safety Approved' record of AC2 is written: this service only holds
  the event-side history entry (status 'Confirmed').
- Who may call the endpoint (-> test_infra_safety_status_internal_lock.py).
- That the notification outbox rows are written and delivered
  (-> test_scrum168_safety_check_notifications.py, Notification Service tests and the
  E2E journeys).
"""
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.models import FIELDS
from tests.unit.factories import (
    signed_in,
    EVENT,
    approval_entry,
    attendee_summary_row,
    baseline_entry,
)

# The live row holds the coordinator's new, unapproved window (2030-03-02 09:00-18:00 SGT).
LIVE = {"startTime": "2030-03-02T09:00:00", "endTime": "2030-03-02T18:00:00"}
EVENT_ID = "00000000-0000-0000-0000-000000000001"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OFFICER_ID = "33333333-3333-4333-8333-333333333333"
SAFETY_CHECK_ID = "55555555-5555-4555-8555-555555555555"
OTHER_SAFETY_CHECK_ID = "66666666-6666-4666-8666-666666666666"
INTERNAL_TOKEN = "test-internal-token"
INTERNAL_HEADERS = {"X-Internal-Token": INTERNAL_TOKEN}

# Every status an event can hold that isn't 'Pending Safety Check'; none of
# them may move to 'Confirmed' through this endpoint (AC3).
NON_PENDING_STATUSES = [
    "Submitted",
    "Under Review",
    "Approved",
    "Rejected",
    "Confirmed",
    "Safety Changes Requested",
    "Cancelled",
]


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": "unused-test-url",
            "INTERNAL_SERVICE_TOKEN": INTERNAL_TOKEN,
        }
    )
    return signed_in(app.test_client()), connection, cursor


def event_row(
    status="Pending Safety Check",
    coordinator_id=COORDINATOR_ID,
    action_history=None,
):
    row = {column: "" for column in FIELDS.values()}
    row.update(
        event_id=EVENT_ID,
        event_name="Community Workshop",
        status=status,
        coordinator_id=coordinator_id,
        organiser_id=None,
        submission_date=datetime(2026, 10, 1, 8, tzinfo=UTC),
        preferred_start_date=datetime(2026, 11, 12, 9),
        preferred_end_date=datetime(2026, 11, 12, 17),
        expected_attendance=120,
    )
    if action_history is None:
        action_history = [
            {
                "status": "Pending Safety Check",
                "details": "Submitted for Operational Safety Check (round 1).",
                "coordinatorId": COORDINATOR_ID,
                "safetyCheckId": SAFETY_CHECK_ID,
                "recordedAt": "2026-11-01T02:30:00+00:00",
            }
        ]
    row["description"] = json.dumps(
        {
            "_connectsphere": "event-submission-v1",
            "description": "A practical workshop",
            "purpose": "Learning",
            "decision": {
                "status": "Approved",
                "coordinatorId": COORDINATOR_ID,
                "decidedAt": "2026-10-02T01:00:00+00:00",
                "reason": None,
            },
            "decisionHistory": [],
            "actionDetails": "Venue booked.",
            "actionHistory": action_history,
        }
    )
    return row


def patch_safety_status(client, headers=INTERNAL_HEADERS, **overrides):
    body = {
        "status": "Confirmed",
        "decidedBy": OFFICER_ID,
        "safetyCheckId": SAFETY_CHECK_ID,
        "roundNumber": 1,
        **overrides,
    }
    return client.patch(f"/events/{EVENT_ID}/safety-status", json=body, headers=headers)


# --- AC1/AC2: the move and the history entry ----------------------------------


def test_ac1_pending_safety_check_moves_to_confirmed(setup):
    """
    Summary: 'Pending Safety Check' -> 'Confirmed' with the open round's id.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor.fetchone returns the 'Pending Safety Check' row, then the updated 'Confirmed' row), Mock (the status parameter of the UPDATE asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Confirmed"),
    ]

    # Act (When)
    response = patch_safety_status(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Confirmed"
    assert cursor.execute.call_args_list[1].args[1][0] == "Confirmed"


def test_ac2_history_entry_has_decided_by_safety_check_id_remarks_and_time(setup):
    """
    Summary: The event-side history entry (status 'Confirmed', not the 'Safety Approved' safety-check record) carries the officer's identity, the round, the remarks and the approval time, and keeps the earlier entries.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: Stub (cursor.fetchone returns the pending row, then the confirmed row), Mock (the metadata JSON passed to the UPDATE asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Confirmed"),
    ]

    # Act (When)
    patch_safety_status(client, remarks="Looks safe.")

    # Assert (Then)
    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    action = stored["actionHistory"][-1]
    assert action["status"] == "Confirmed"
    assert action["decidedBy"] == OFFICER_ID
    assert action["safetyCheckId"] == SAFETY_CHECK_ID
    assert action["remarks"] == "Looks safe."
    assert action["recordedAt"].endswith("+00:00")
    assert action["details"] == "Operational Safety Check approved (round 1)."
    # The earlier submit entry is kept, not replaced.
    assert stored["actionHistory"][0]["status"] == "Pending Safety Check"


def test_ac2_remarks_are_optional(setup):
    """
    Summary: Approving with remarks=None still succeeds, and the history entry records remarks as None.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: Stub (cursor.fetchone returns the pending row, then the confirmed row), Mock (the metadata JSON passed to the UPDATE asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Confirmed"),
    ]

    # Act (When)
    response = patch_safety_status(client, remarks=None)

    # Assert (Then)
    assert response.status_code == 200
    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    assert stored["actionHistory"][-1]["remarks"] is None


def test_ac1_no_coordinator_check_on_approve(setup):
    """
    Summary: The Safety Officer deciding need not be the event's assigned coordinator (decidedBy differs from the coordinator id).
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor.fetchone returns a pending row assigned to a different coordinator, then the confirmed row)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check", coordinator_id=COORDINATOR_ID),
        event_row("Confirmed"),
    ]

    # Act (When)
    response = patch_safety_status(client, decidedBy=OFFICER_ID)

    # Assert (Then)
    assert response.status_code == 200


def test_ac1_a_coordinator_progress_save_does_not_make_the_open_round_stale(setup):
    """
    Summary: A progress note saved while the event waits for its decision writes its own 'Pending Safety Check' entry, with no round id; approving the open round still succeeds.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor.fetchone returns a pending row whose history ends in a round-less progress note, then the confirmed row), Mock (the UPDATE's status parameter asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row(
            "Pending Safety Check",
            action_history=[
                {
                    "status": "Pending Safety Check",
                    "details": "Submitted for Operational Safety Check (round 1).",
                    "coordinatorId": COORDINATOR_ID,
                    "safetyCheckId": SAFETY_CHECK_ID,
                    "recordedAt": "2026-11-01T02:30:00+00:00",
                },
                {
                    "status": "Pending Safety Check",
                    "details": "Chased the venue for the floor plan.",
                    "coordinatorId": COORDINATOR_ID,
                    "recordedAt": "2026-11-01T06:00:00+00:00",
                },
            ],
        ),
        event_row("Confirmed"),
    ]

    # Act (When)
    response = patch_safety_status(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Confirmed"
    assert cursor.execute.call_args_list[1].args[1][0] == "Confirmed"


# --- AC3: only 'Pending Safety Check' may be confirmed -------------------------


@pytest.mark.parametrize("current_status", NON_PENDING_STATUSES)
def test_ac3_only_pending_safety_check_can_be_confirmed(current_status, setup):
    """
    Summary: Every other status is refused with 409 INVALID_SAFETY_TRANSITION, and no update runs.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: Stub (cursor.fetchone returns a row in each non-pending status), Mock (cursor.execute call count asserted: the SELECT only, no UPDATE)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(current_status)

    # Act (When)
    response = patch_safety_status(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "INVALID_SAFETY_TRANSITION"
    assert response.json["currentStatus"] == current_status
    # Only the SELECT ran: nothing was updated.
    assert cursor.execute.call_count == 1


# --- AC4: approving after a high-impact change releases the new details -------


def test_ac4_approval_after_recheck_releases_the_new_details(setup):
    """
    Summary: A Confirmed event took a high-impact time edit and the Safety Officer approved round 2; the attendee read now shows the new window instead of the approved-details fallback.
    AC4: Given the safety check I approve follows a high-impact change, when I
        approve it, then the changed details become visible to registered
        Attendees.
    Double: Stub (cursor.fetchall returns one 'Confirmed' row: approval, baseline, then an approval for a second round), read through GET /events/attendee-summaries
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchall.return_value = [attendee_summary_row("Confirmed", [
        approval_entry(), baseline_entry(), approval_entry(round_id=OTHER_SAFETY_CHECK_ID),
    ])]

    # Act (When)
    response = client.get(f"/events/attendee-summaries?ids={EVENT}")

    # Assert (Then)
    assert response.status_code == 200
    [event] = response.json["events"]
    assert (event["startTime"], event["endTime"]) == (LIVE["startTime"], LIVE["endTime"])
    assert event["attendeeVenueName"] is None


# --- Supporting/supplementary design checks -----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# story relies on (row locking, round matching, the not-found and validation
# responses).


def test_remarks_of_exactly_the_limit_are_accepted(setup):
    """
    Summary: Remarks of exactly 2000 characters are stored, one under the rejected 2001.
    Supporting design check: remarks are capped at 2000 characters
    Double: Stub (cursor.fetchone returns the pending row, then the confirmed row), Mock (the metadata JSON passed to the UPDATE asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Confirmed"),
    ]

    # Act (When)
    response = patch_safety_status(client, remarks="x" * 2000)

    # Assert (Then)
    assert response.status_code == 200
    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    assert stored["actionHistory"][-1]["remarks"] == "x" * 2000


@pytest.mark.parametrize("round_number", [0, -1, True, "1", None], ids=["zero", "negative", "bool", "text", "missing"])
def test_bad_round_number_is_rejected(setup, round_number):
    """
    Summary: roundNumber must be a positive whole number: 0, a negative, a boolean, text or nothing is a 400, and nothing is written.
    Supporting design check: the round number must be a positive integer
    Double: Mock (cursor.execute asserted not called)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = patch_safety_status(client, roundNumber=round_number)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "roundNumber must be a positive whole number."
    cursor.execute.assert_not_called()


def test_unknown_status_is_rejected(setup):
    """
    Summary: A status outside the safety workflow (here a pre-safety 'Submitted') is a 400, and nothing is written.
    Supporting design check: this endpoint only moves events along the safety
        statuses
    Double: Mock (cursor.execute asserted not called)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = patch_safety_status(client, status="Submitted")

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"].startswith("Status must be one of:")
    cursor.execute.assert_not_called()


def test_non_object_body_is_rejected(setup):
    """
    Summary: A JSON list instead of an object is a 400, and nothing is written.
    Supporting design check: the request body must be a JSON object
    Double: Mock (cursor.execute asserted not called)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = client.patch(f"/events/{EVENT_ID}/safety-status", json=["Confirmed"], headers=INTERNAL_HEADERS)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    cursor.execute.assert_not_called()


def test_coordinator_decision_is_left_alone(setup):
    """
    Summary: Approving rewrites only the status and history; the stored coordinator decision ('Approved') and the booking note are written back unchanged.
    Supporting design check: the safety approval must not overwrite the
        earlier event-request decision
    Double: Stub (cursor.fetchone returns the pending row, then the confirmed row), Mock (the metadata JSON passed to the UPDATE asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Confirmed"),
    ]

    # Act (When)
    patch_safety_status(client)

    # Assert (Then)
    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    assert stored["decision"]["status"] == "Approved"
    assert stored["actionDetails"] == "Venue booked."


def test_move_runs_under_a_row_lock(setup):
    """
    Summary: The first query reads the event with FOR UPDATE, so two approvals cannot both pass the status check.
    Supporting design check: concurrent decisions on one event are serialised
    Double: Stub (cursor.fetchone returns the pending row, then the confirmed row), Mock (the SQL of the first cursor.execute asserted to contain FOR UPDATE)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Confirmed"),
    ]

    # Act (When)
    patch_safety_status(client)

    # Assert (Then)
    assert "FOR UPDATE" in cursor.execute.call_args_list[0].args[0]


def test_stale_safety_check_id_is_refused(setup):
    """
    Summary: The event is 'Pending Safety Check', but the request names a round other than the one it has open: 409 STALE_SAFETY_CHECK and no update.
    Supporting design check: an approval of an old round cannot confirm the
        event
    Double: Stub (cursor.fetchone returns a pending row for a different round), Mock (cursor.execute call count asserted: the SELECT only)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Pending Safety Check")

    # Act (When)
    response = patch_safety_status(client, safetyCheckId=OTHER_SAFETY_CHECK_ID)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "STALE_SAFETY_CHECK"
    # Only the SELECT ran: nothing was updated.
    assert cursor.execute.call_count == 1


def test_missing_pending_entry_is_refused(setup):
    """
    Summary: A 'Pending Safety Check' event whose history has no action at all has no round to match: 409 STALE_SAFETY_CHECK.
    Supporting design check: an event with no open round cannot be confirmed
    Double: Stub (cursor.fetchone returns a pending row with an empty history)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Pending Safety Check", action_history=[])

    # Act (When)
    response = patch_safety_status(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "STALE_SAFETY_CHECK"


def test_a_progress_save_cannot_stand_in_for_a_submission(setup):
    """
    Summary: The flip side of the progress-save test: a lone entry with no round id is not a submission, so it can't satisfy the round check (409 STALE_SAFETY_CHECK).
    Supporting design check: only a submission entry opens a round
    Double: Stub (cursor.fetchone returns a pending row whose only history entry is a round-less progress note)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(
        "Pending Safety Check",
        action_history=[
            {
                "status": "Pending Safety Check",
                "details": "Chased the venue for the floor plan.",
                "coordinatorId": COORDINATOR_ID,
                "recordedAt": "2026-11-01T06:00:00+00:00",
            },
        ],
    )

    # Act (When)
    response = patch_safety_status(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "STALE_SAFETY_CHECK"


def test_missing_event_is_404(setup):
    """
    Summary: An unknown event id answers 404 'Event request not found.'.
    Supporting design check: approving a nonexistent event fails cleanly
    Double: Stub (cursor.fetchone returns None)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    # Act (When)
    response = patch_safety_status(client)

    # Assert (Then)
    assert response.status_code == 404
    assert response.json["message"] == "Event request not found."


def test_remarks_over_the_limit_are_rejected(setup):
    """
    Summary: Remarks of 2001 characters are a 400, and nothing is written.
    Supporting design check: remarks are capped at 2000 characters
    Double: Mock (cursor.execute asserted not called)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = patch_safety_status(client, remarks="x" * 2001)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "remarks must be 2000 characters or fewer."
    cursor.execute.assert_not_called()


def test_non_text_remarks_are_rejected(setup):
    """
    Summary: Remarks that are an object rather than text are a 400, and nothing is written.
    Supporting design check: remarks must be text
    Double: Mock (cursor.execute asserted not called)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = patch_safety_status(client, remarks={"nested": "object"})

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "remarks must be text."
    cursor.execute.assert_not_called()


def test_bad_safety_check_id_is_rejected(setup):
    """
    Summary: A safetyCheckId that is not a UUID is a 400, and nothing is written.
    Supporting design check: the round id must be a valid UUID
    Double: Mock (cursor.execute asserted not called)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = patch_safety_status(client, safetyCheckId="not-a-uuid")

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "A valid safety check ID is required."
    cursor.execute.assert_not_called()
