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
- The Event Service routes in app/__init__.py and the rules in app/models.py,
  run through a real create_app(): request validation, the caller's role and
  ownership checks from the signed token, the status rules, and the SQL and
  parameters sent to the database (including notification outbox rows).
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
- That the notification outbox rows are delivered (-> Notification Service
  tests and the E2E journeys).
"""
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.models import FIELDS
from tests.unit.factories import signed_in

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


# --- AC1/AC2: the move and the history entry ---------------------------------


def test_pending_safety_check_moves_to_confirmed(setup):
    """
    Summary: 'Pending Safety Check' -> 'Confirmed' with the open round's id.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_history_entry_has_decided_by_safety_check_id_remarks_and_time(setup):
    """
    Summary: The event-side history entry carries the officer's decision.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Confirmed"),
    ]

    patch_safety_status(client, remarks="Looks safe.")

    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    action = stored["actionHistory"][-1]

    # Act + Assert (When / Then)
    assert action["status"] == "Confirmed"
    assert action["decidedBy"] == OFFICER_ID
    assert action["safetyCheckId"] == SAFETY_CHECK_ID
    assert action["remarks"] == "Looks safe."
    assert action["recordedAt"].endswith("+00:00")
    assert action["details"] == "Operational Safety Check approved (round 1)."
    # The earlier submit entry is kept, not replaced.
    assert stored["actionHistory"][0]["status"] == "Pending Safety Check"


def test_remarks_are_optional(setup):
    """
    Summary: Remarks are optional.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_no_coordinator_check_on_approve(setup):
    """
    Summary: The Safety Officer deciding need not be the assigned coordinator.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_coordinator_decision_is_left_alone(setup):
    """
    Summary: Coordinator decision is left alone.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Confirmed"),
    ]

    patch_safety_status(client)

    # Act (When)
    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])

    # Assert (Then)
    assert stored["decision"]["status"] == "Approved"
    assert stored["actionDetails"] == "Venue booked."


def test_move_runs_under_a_row_lock(setup):
    """
    Summary: Move runs under a row lock.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


# --- AC3: only 'Pending Safety Check' may move, and only with its own round -


@pytest.mark.parametrize("current_status", NON_PENDING_STATUSES)
def test_only_pending_safety_check_can_be_confirmed(current_status, setup):
    """
    Summary: Every other status is refused, and the event is not touched.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_stale_safety_check_id_is_refused(setup):
    """
    Summary: A round that isn't the one this event has open can't confirm it.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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
    Summary: No 'Pending Safety Check' action at all means there is no round to match.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Pending Safety Check", action_history=[])

    # Act (When)
    response = patch_safety_status(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "STALE_SAFETY_CHECK"


def test_a_coordinator_progress_save_does_not_make_the_open_round_stale(setup):
    """
    Summary: A progress note saved while the event waits for its decision writes its own 'Pending Safety Check' entry, with no round id.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_a_progress_save_cannot_stand_in_for_a_submission(setup):
    """
    Summary: The flip side: an entry with no round id is not a submission, so it can't satisfy the check on its own.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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
    Summary: Missing event is 404.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    # Act (When)
    response = patch_safety_status(client)

    # Assert (Then)
    assert response.status_code == 404
    assert response.json["message"] == "Event request not found."


# --- Input validation ---------------------------------------------------------


def test_remarks_over_the_limit_are_rejected(setup):
    """
    Summary: Remarks over the limit are rejected.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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
    Summary: Non text remarks are rejected.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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
    Summary: Bad safety check id is rejected.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = patch_safety_status(client, safetyCheckId="not-a-uuid")

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "A valid safety check ID is required."
    cursor.execute.assert_not_called()
