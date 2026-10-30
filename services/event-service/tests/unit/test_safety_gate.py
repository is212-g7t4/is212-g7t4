"""
SCRUM-152: Block Preparation Until Safety Approval

User Story
----------
As a Safety Officer, I want the system to stop an event moving to preparation
until it has passed its Operational Safety Check, so that no event proceeds
with unreviewed safety arrangements.

Acceptance Criteria
-------------------
AC1: Given an event's status is not 'Confirmed', when the assigned Event
     Coordinator tries to move it to 'Confirmed' (the preparation stage)
     through either the UI or the API, then the change is blocked and the
     reason is shown.
AC2: Given an event has not yet reached the safety check, then the existing
     status transitions (SCRUM-19) continue to work unchanged.

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
from app.models import ALLOWED_TRANSITIONS, FIELDS, SAFETY_TRANSITIONS
from tests.unit.factories import signed_in

EVENT_ID = "00000000-0000-0000-0000-000000000001"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OTHER_COORDINATOR_ID = "22222222-2222-4222-8222-222222222222"

# Every status that isn't 'Confirmed' — the gate must block all of them.
UNCONFIRMED_STATUSES = [
    "Submitted",
    "Under Review",
    "Approved",
    "Rejected",
    "Pending Safety Check",
    "Safety Changes Requested",
    "Cancelled",
]


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client()), connection, cursor


def event_row(status="Submitted", coordinator_id=COORDINATOR_ID, action_details=""):
    row = {column: "" for column in FIELDS.values()}
    row.update(
        event_id=EVENT_ID,
        event_name="Community Workshop",
        status=status,
        coordinator_id=coordinator_id,
        submission_date=datetime(2026, 10, 1, 8, tzinfo=UTC),
        preferred_start_date=datetime(2026, 10, 10, 9),
        preferred_end_date=datetime(2026, 10, 10, 12),
        expected_attendance=30,
    )
    row["description"] = json.dumps({
        "_connectsphere": "event-submission-v1",
        "description": "A practical workshop",
        "purpose": "Learning",
        "decision": None,
        "decisionHistory": [],
        "actionDetails": action_details,
        "actionHistory": [],
    })
    return row


def patch_progress(client, status, action_details="Recording progress."):
    return client.patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": status,
            "actionDetails": action_details,
        },
    )


@pytest.mark.parametrize("current_status", UNCONFIRMED_STATUSES)
def test_coordinator_cannot_confirm_event(current_status, setup):
    """
    Summary: Only the safety workflow sets 'Confirmed'.
    AC1: Given an event's status is not 'Confirmed', when the assigned Event
        Coordinator tries to move it to 'Confirmed' (the preparation stage)
        through either the UI or the API, then the change is blocked and the
        reason is shown.
    AC2: Given an event has not yet reached the safety check, then the existing
        status transitions (SCRUM-19) continue to work unchanged.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(current_status)

    # Act (When)
    response = patch_progress(client, "Confirmed", "All arrangements done.")

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_APPROVAL_REQUIRED"
    assert response.json["currentStatus"] == current_status
    assert response.json["requiredStatus"] == "Confirmed"
    # Only the SELECT ran — the event was never updated.
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize(
    ("current_status", "message"),
    [
        (
            "Approved",
            "Submit this event for safety check for it to progress to Confirmed.",
        ),
        (
            "Submitted",
            "This event must be approved and pass its Operational Safety Check "
            "before it can progress to Confirmed.",
        ),
        (
            "Under Review",
            "This event must be approved and pass its Operational Safety Check "
            "before it can progress to Confirmed.",
        ),
        ("Rejected", "This event was rejected, so it can't progress to Confirmed."),
        (
            "Pending Safety Check",
            "This event is waiting for the Safety Officer's decision.",
        ),
        (
            "Safety Changes Requested",
            "The Safety Officer has requested changes that must be made and resubmitted.",
        ),
        (
            "Cancelled",
            "This event was cancelled after its safety check, so it can't progress to Confirmed.",
        ),
    ],
)
def test_block_message_names_the_reason(current_status, message, setup):
    """
    Summary: The 409 message explains why, per status.
    AC1: Given an event's status is not 'Confirmed', when the assigned Event
        Coordinator tries to move it to 'Confirmed' (the preparation stage)
        through either the UI or the API, then the change is blocked and the
        reason is shown.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(current_status)

    # Act (When)
    response = patch_progress(client, "Confirmed")

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["message"] == message


def test_approved_event_tells_the_coordinator_to_submit_for_safety_check(setup):
    """
    Summary: The actionable case — an approved event's next step is SCRUM-149.
    AC1: Given an event's status is not 'Confirmed', when the assigned Event
        Coordinator tries to move it to 'Confirmed' (the preparation stage)
        through either the UI or the API, then the change is blocked and the
        reason is shown.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Approved")

    # Act (When)
    response = patch_progress(client, "Confirmed")

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["message"] == (
        "Submit this event for safety check for it to progress to Confirmed."
    )


def test_cancelled_event_cannot_progress(setup):
    """
    Summary: A safety rejection ends the lifecycle.
    AC1: Given an event's status is not 'Confirmed', when the assigned Event
        Coordinator tries to move it to 'Confirmed' (the preparation stage)
        through either the UI or the API, then the change is blocked and the
        reason is shown.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Cancelled")

    # Act (When)
    response = patch_progress(client, "Confirmed")

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_APPROVAL_REQUIRED"
    assert cursor.execute.call_count == 1


def test_gate_checks_assignment_first(setup):
    """
    Summary: Others get 403, not the reason.
    AC1: Given an event's status is not 'Confirmed', when the assigned Event
        Coordinator tries to move it to 'Confirmed' (the preparation stage)
        through either the UI or the API, then the change is blocked and the
        reason is shown.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Approved", coordinator_id=OTHER_COORDINATOR_ID)

    # Act (When)
    response = patch_progress(client, "Confirmed")

    # Assert (Then)
    assert response.status_code == 403
    assert "code" not in response.json
    assert cursor.execute.call_count == 1


def test_confirmed_event_stays_confirmed_and_records_progress(setup):
    """
    Summary: The gate must not over-block.
    AC1: Given an event's status is not 'Confirmed', when the assigned Event
        Coordinator tries to move it to 'Confirmed' (the preparation stage)
        through either the UI or the API, then the change is blocked and the
        reason is shown.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Confirmed"),
        event_row("Confirmed", action_details="Preparation under way."),
    ]

    # Act (When)
    response = patch_progress(client, "Confirmed", "Preparation under way.")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Confirmed"
    assert response.json["actionDetails"] == "Preparation under way."
    assert cursor.execute.call_count == 2
    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    assert stored["actionHistory"][-1]["status"] == "Confirmed"


@pytest.mark.parametrize(
    "status", ["Pending Safety Check", "Safety Changes Requested", "Cancelled"]
)
def test_coordinator_cannot_set_other_safety_status(status, setup):
    """
    Summary: Guards the safety workflow: only it writes the safety statuses.
    AC1: Given an event's status is not 'Confirmed', when the assigned Event
        Coordinator tries to move it to 'Confirmed' (the preparation stage)
        through either the UI or the API, then the change is blocked and the
        reason is shown.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Approved")

    # Act (When)
    response = patch_progress(client, status)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["message"] == (
        "This status change is not allowed for the event's current stage."
    )
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize(
    "status",
    ["Pending Safety Check", "Confirmed", "Safety Changes Requested", "Cancelled"],
)
def test_self_save_on_safety_status_keeps_working(status, setup):
    """
    Summary: Recording action details never changes the status, so it's allowed.
    AC2: Given an event has not yet reached the safety check, then the existing
        status transitions (SCRUM-19) continue to work unchanged.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row(status),
        event_row(status, action_details="Logged the latest progress."),
    ]

    # Act (When)
    response = patch_progress(client, status, "Logged the latest progress.")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == status
    assert response.json["actionDetails"] == "Logged the latest progress."


@pytest.mark.parametrize("status", ["In Preparation", "Preparing", "SafetyApproved"])
def test_unknown_status_is_400(status, setup):
    """
    Summary: Only the documented lifecycle statuses are accepted.
    AC1: Given an event's status is not 'Confirmed', when the assigned Event
        Coordinator tries to move it to 'Confirmed' (the preparation stage)
        through either the UI or the API, then the change is blocked and the
        reason is shown.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = patch_progress(client, status)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"].startswith("Status must be one of: ")
    cursor.execute.assert_not_called()


def test_gate_runs_under_row_lock(setup):
    """
    Summary: A concurrent safety decision can't make the gate act on a stale status.
    AC1: Given an event's status is not 'Confirmed', when the assigned Event
        Coordinator tries to move it to 'Confirmed' (the preparation stage)
        through either the UI or the API, then the change is blocked and the
        reason is shown.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Approved")

    # Act (When)
    patch_progress(client, "Confirmed")

    # Assert (Then)
    assert "FOR UPDATE" in cursor.execute.call_args_list[0].args[0]


def test_only_pending_safety_check_leads_into_confirmed():
    """
    Summary: 'Pending Safety Check' is the only route into 'Confirmed'.
    AC1: Given an event's status is not 'Confirmed', when the assigned Event
        Coordinator tries to move it to 'Confirmed' (the preparation stage)
        through either the UI or the API, then the change is blocked and the
        reason is shown.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Act (When)
    sources_in_safety_transitions = {
        source
        for source, targets in SAFETY_TRANSITIONS.items()
        if "Confirmed" in targets
    }

    # Assert (Then)
    assert sources_in_safety_transitions == {"Pending Safety Check"}

    sources_in_allowed_transitions = {
        source
        for source, targets in ALLOWED_TRANSITIONS.items()
        if "Confirmed" in targets
    }
    assert sources_in_allowed_transitions == {"Confirmed"}


def test_pre_safety_transitions_unchanged():
    """
    Summary: SCRUM-19's transitions keep working unchanged.
    AC2: Given an event has not yet reached the safety check, then the existing
        status transitions (SCRUM-19) continue to work unchanged.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Act + Assert (When / Then)
    assert ALLOWED_TRANSITIONS["Submitted"] == {"Submitted", "Under Review"}
    assert ALLOWED_TRANSITIONS["Under Review"] == {"Under Review", "Approved", "Rejected"}
    assert ALLOWED_TRANSITIONS["Approved"] == {"Approved"}
    assert ALLOWED_TRANSITIONS["Rejected"] == {"Rejected"}


def test_safety_workflow_never_starts_before_approval():
    """
    Summary: The safety workflow can't touch an event that hasn't reached the safety check yet.
    AC2: Given an event has not yet reached the safety check, then the existing
        status transitions (SCRUM-19) continue to work unchanged.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Act + Assert (When / Then)
    assert not set(SAFETY_TRANSITIONS) & {"Submitted", "Under Review", "Rejected"}
