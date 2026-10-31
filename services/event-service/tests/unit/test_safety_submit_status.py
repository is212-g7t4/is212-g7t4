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
OTHER_COORDINATOR_ID = "22222222-2222-4222-8222-222222222222"
OFFICER_ID = "33333333-3333-4333-8333-333333333333"
SAFETY_CHECK_ID = "55555555-5555-4555-8555-555555555555"
INTERNAL_TOKEN = "test-internal-token"
INTERNAL_HEADERS = {"X-Internal-Token": INTERNAL_TOKEN}

# Every status an event can hold that must not reach 'Pending Safety Check'.
# Initial submission and requested-change resubmission are allowed.
NON_APPROVED_STATUSES = [
    "Submitted",
    "Under Review",
    "Rejected",
    "Confirmed",
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


def event_row(status="Approved", coordinator_id=COORDINATOR_ID, action_history=None):
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
            "actionHistory": action_history or [],
        }
    )
    return row


def patch_safety_status(client, headers=INTERNAL_HEADERS, **overrides):
    body = {
        "status": "Pending Safety Check",
        "coordinatorId": COORDINATOR_ID,
        "safetyCheckId": SAFETY_CHECK_ID,
        "roundNumber": 1,
        **overrides,
    }
    return client.patch(f"/events/{EVENT_ID}/safety-status", json=body, headers=headers)


# --- AC1: the move and the submission time ----------------------------------


@pytest.mark.parametrize("source_status", ["Approved", "Safety Changes Requested"])
def test_approved_or_revised_event_moves_to_pending_safety_check(setup, source_status):
    """
    Summary: 'Approved' -> 'Pending Safety Check' for the assigned coordinator.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row(source_status),
        event_row("Pending Safety Check"),
    ]

    # Act (When)
    response = patch_safety_status(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Pending Safety Check"
    # Event update and SCRUM-168 outbox insert share the same cursor/transaction.
    assert cursor.execute.call_count == 3
    assert cursor.execute.call_args_list[1].args[1][0] == "Pending Safety Check"


def test_submission_is_recorded_in_the_action_history(setup):
    """
    Summary: The event keeps its own note of it.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Approved", action_history=[{"status": "Approved"}]),
        event_row("Pending Safety Check"),
    ]

    patch_safety_status(client, roundNumber=2)

    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    action = stored["actionHistory"][-1]

    # Act + Assert (When / Then)
    assert action["status"] == "Pending Safety Check"
    assert action["details"] == (
        "Submitted for Operational Safety Check (round 2)."
    )
    assert action["coordinatorId"] == COORDINATOR_ID
    assert action["safetyCheckId"] == SAFETY_CHECK_ID
    assert action["recordedAt"].endswith("+00:00")
    # The earlier history is kept, not replaced.
    assert stored["actionHistory"][0] == {"status": "Approved"}


def test_coordinator_decision_is_left_alone(setup):
    """
    Summary: A safety submission is not a coordinator decision: `decision` is untouched.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Approved"),
        event_row("Pending Safety Check"),
    ]

    patch_safety_status(client)

    # Act (When)
    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])

    # Assert (Then)
    assert stored["decision"]["status"] == "Approved"
    assert stored["actionDetails"] == "Venue booked."


def test_move_runs_under_a_row_lock(setup):
    """
    Summary: The composite's earlier read can be stale, so the checks repeat in the lock.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Approved"),
        event_row("Pending Safety Check"),
    ]

    # Act (When)
    patch_safety_status(client)

    # Assert (Then)
    assert "FOR UPDATE" in cursor.execute.call_args_list[0].args[0]


# --- AC5: only the assigned coordinator -------------------------------------


def test_another_coordinator_is_refused(setup):
    """
    Summary: An API call from anyone but the assigned coordinator is rejected.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(
        "Approved", coordinator_id=OTHER_COORDINATOR_ID
    )

    # Act (When)
    response = patch_safety_status(client)

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["message"] == (
        "This event request is not assigned to the current coordinator."
    )
    # Only the SELECT ran: the event was never updated.
    assert cursor.execute.call_count == 1


def test_unassigned_event_is_refused(setup):
    """
    Summary: An event with no coordinator has no assigned coordinator.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Approved", coordinator_id=None)

    # Act (When)
    response = patch_safety_status(client)

    # Assert (Then)
    assert response.status_code == 403
    assert cursor.execute.call_count == 1


def test_another_coordinator_on_a_pending_event_gets_403_not_409(setup):
    """
    Summary: A stranger learns nothing about the event's stage.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(
        "Pending Safety Check", coordinator_id=OTHER_COORDINATOR_ID
    )

    # Act (When)
    response = patch_safety_status(client)

    # Assert (Then)
    assert response.status_code == 403
    assert "code" not in response.json


# --- AC4 and the lifecycle guard --------------------------------------------


def test_already_pending_event_is_a_conflict(setup):
    """
    Summary: A second submission can't re-enter 'Pending Safety Check'.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Pending Safety Check")

    # Act (When)
    response = patch_safety_status(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_PENDING"
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("current_status", NON_APPROVED_STATUSES)
def test_events_outside_submission_stages_cannot_be_submitted(current_status, setup):
    """
    Summary: Only initial submission and requested-change resubmission stages are allowed.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
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
    assert response.json["message"] == (
        f"This event can't move to 'Pending Safety Check' from '{current_status}'."
    )
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize(
    "status", ["Safety Changes Requested", "Cancelled"]
)
def test_safety_changes_and_rejection_are_only_reachable_from_pending(status, setup):
    """
    Summary: SCRUM-151's two moves, like SCRUM-150's, only leave 'Pending Safety Check'.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Approved")

    # Act (When)
    response = patch_safety_status(
        client,
        status=status,
        decidedBy=OFFICER_ID,
        remarks="Needs another look." if status == "Safety Changes Requested" else "Unsafe.",
        areas=["venue arrangement"] if status == "Safety Changes Requested" else None,
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "INVALID_SAFETY_TRANSITION"


def test_missing_event_is_404(setup):
    """
    Summary: Missing event is 404.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
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


# --- Input and configuration -------------------------------------------------


@pytest.mark.parametrize("status", ["Approved", "Submitted", "Under Review", "Rejected"])
def test_pre_safety_statuses_are_not_accepted(status, setup):
    """
    Summary: This endpoint only sets safety statuses; the rest is PATCH /progress.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = patch_safety_status(client, status=status)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"].startswith("Status must be one of: ")
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"safetyCheckId": "not-a-uuid"}, "A valid safety check ID is required."),
        ({"safetyCheckId": None}, "A valid safety check ID is required."),
    ],
    ids=["safetycheckid_not_a_uuid_a_valid_safety_check_id", "safetycheckid_none_a_valid_safety_check_id_is_re"],
)
def test_bad_identifiers_are_rejected(overrides, message, setup):
    """
    Summary: Bad identifiers are rejected.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = patch_safety_status(client, **overrides)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == message
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("round_number", [0, -1, 1.5, "1", True, None], ids=["0", "1", "1_5", "1_2", "true", "none"])
def test_bad_round_number_is_rejected(round_number, setup):
    """
    Summary: Bad round number is rejected.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = patch_safety_status(client, roundNumber=round_number)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "roundNumber must be a positive whole number."
    cursor.execute.assert_not_called()


def test_non_object_body_is_rejected(setup):
    """
    Summary: Non object body is rejected.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/safety-status", json=["nope"], headers=INTERNAL_HEADERS
    )

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    cursor.execute.assert_not_called()


# --- Regression: PATCH /progress is still shut out (SCRUM-152) ---------------


def test_progress_endpoint_still_cannot_set_pending_safety_check(setup):
    """
    Summary: The coordinator's own endpoint can't do this.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Approved")

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": "Pending Safety Check",
            "actionDetails": "Trying the back door.",
        },
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["message"] == (
        "This status change is not allowed for the event's current stage."
    )
    assert cursor.execute.call_count == 1


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_without_database_url():
    """
    Summary: Without database url.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None
    """
    client = signed_in(create_app(
        {
            "TESTING": True,
            "DATABASE_URL": None,
            "INTERNAL_SERVICE_TOKEN": INTERNAL_TOKEN,
        }
    ).test_client())

    response = patch_safety_status(client)

    assert response.status_code == 503
    assert "DATABASE_URL" in response.json["message"]
