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
def test_ac1_a_coordinator_cannot_move_an_event_that_is_not_confirmed_to_confirmed(current_status, setup):
    """
    Summary: PATCH /events/<id>/progress asking for "Confirmed" on an event in Submitted, Under Review, Approved, Rejected, Pending Safety Check, Safety Changes Requested or Cancelled answers 409 SAFETY_APPROVAL_REQUIRED with the event's currentStatus and requiredStatus "Confirmed", and only the lookup SELECT ran, so the event was never updated.
    AC1: Given an event's status is not 'Confirmed', when the assigned Event
        Coordinator tries to move it to 'Confirmed' (the preparation stage)
        through either the UI or the API, then the change is blocked and the
        reason is shown.
    Double: Stub (cursor.fetchone returns the event in the parametrised status),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
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
def test_ac1_the_refusal_message_gives_the_reason_for_each_status(current_status, message, setup):
    """
    Summary: PATCH /events/<id>/progress asking for "Confirmed" answers 409 with a message specific to the event's status: submit it for safety check (Approved), approve it and pass the check first (Submitted, Under Review), it was rejected, it is waiting for the Safety Officer, changes were requested, or it was cancelled.
    AC1: Given an event's status is not 'Confirmed', when the assigned Event
        Coordinator tries to move it to 'Confirmed' (the preparation stage)
        through either the UI or the API, then the change is blocked and the
        reason is shown.
    Double: Stub (cursor.fetchone returns the event in the parametrised status); the 409 message text is the only assertion
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(current_status)

    # Act (When)
    response = patch_progress(client, "Confirmed")

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["message"] == message


def test_ac1_a_coordinator_cannot_confirm_an_event_through_the_safety_status_route_either(monkeypatch):
    """
    Summary: PATCH /events/<id>/safety-status asking for "Confirmed", sent without the internal token while the server has one configured, answers 403 with code INTERNAL_ONLY and no query is sent, so the API path around /progress is closed too.
    AC1: Given an event's status is not 'Confirmed', when the assigned Event
        Coordinator tries to move it to 'Confirmed' (the preparation stage)
        through either the UI or the API, then the change is blocked and the
        reason is shown.
    Double: Mock (cursor.execute asserted never called); psycopg2.connect is patched to a MagicMock connection and INTERNAL_SERVICE_TOKEN is configured
    """
    # Arrange (Given)
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    client = signed_in(create_app({
        "TESTING": True,
        "DATABASE_URL": "unused-test-url",
        "INTERNAL_SERVICE_TOKEN": "test-internal-token",
    }).test_client())

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/safety-status",
        json={
            "status": "Confirmed",
            "decidedBy": COORDINATOR_ID,
            "safetyCheckId": "55555555-5555-4555-8555-555555555555",
            "roundNumber": 1,
        },
    )

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["code"] == "INTERNAL_ONLY"
    cursor.execute.assert_not_called()


def test_ac1_a_coordinator_who_is_not_assigned_gets_403_without_the_safety_reason(setup):
    """
    Summary: PATCH /events/<id>/progress asking for "Confirmed" on an 'Approved' event assigned to a different coordinator answers 403 with no code in the body (the safety reason is not shown to someone who is not the assigned coordinator), and only the lookup read ran.
    AC1: Given an event's status is not 'Confirmed', when the assigned Event
        Coordinator tries to move it to 'Confirmed' (the preparation stage)
        through either the UI or the API, then the change is blocked and the
        reason is shown.
    Double: Stub (cursor.fetchone returns an event assigned to another coordinator),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
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


def test_ac1_an_event_that_is_already_confirmed_can_still_record_progress_at_confirmed(setup):
    """
    Summary: PATCH /events/<id>/progress keeping a 'Confirmed' event at "Confirmed" with new action details answers 200 with the status and action details, two queries ran (lookup and update), and the stored action history ends with "Confirmed", so the gate does not over-block.
    AC1: Given an event's status is not 'Confirmed', when the assigned Event
        Coordinator tries to move it to 'Confirmed' (the preparation stage)
        through either the UI or the API, then the change is blocked and the
        reason is shown.
    Double: Stub (cursor.fetchone returns the 'Confirmed' event, then the updated event),
        Mock (cursor.execute call count asserted to be 2; the UPDATE's metadata parameter asserted)
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
    "status",
    ["Pending Safety Check", "Confirmed", "Safety Changes Requested", "Cancelled"],
)
def test_ac2_saving_action_details_without_changing_the_status_keeps_working_for_safety_statuses(status, setup):
    """
    Summary: PATCH /events/<id>/progress keeping an event at "Pending Safety Check", "Confirmed", "Safety Changes Requested" or "Cancelled" with new action details answers 200 with the same status and the new action details.
    AC2: Given an event has not yet reached the safety check, then the existing
        status transitions (SCRUM-19) continue to work unchanged.
    Double: Stub (cursor.fetchone returns the event in the parametrised status, then the updated event); the 200 status, status and actionDetails are the only assertions
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


def test_ac1_only_pending_safety_check_leads_into_confirmed_in_the_transition_tables():
    """
    Summary: In SAFETY_TRANSITIONS the only status that can lead to "Confirmed" is "Pending Safety Check", and in ALLOWED_TRANSITIONS the only one is "Confirmed" itself (staying put), so a coordinator has no route into it.
    AC1: Given an event's status is not 'Confirmed', when the assigned Event
        Coordinator tries to move it to 'Confirmed' (the preparation stage)
        through either the UI or the API, then the change is blocked and the
        reason is shown.
    Double: None; the two transition tables are read directly, no route or database is used
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


def test_ac2_the_status_transitions_before_the_safety_check_are_unchanged():
    """
    Summary: ALLOWED_TRANSITIONS still lets Submitted go to Submitted or Under Review, Under Review go to Under Review, Approved or Rejected, and Approved and Rejected stay where they are.
    AC2: Given an event has not yet reached the safety check, then the existing
        status transitions (SCRUM-19) continue to work unchanged.
    Double: None; the transition table is read directly, no route or database is used
    """
    # Act + Assert (When / Then)
    assert ALLOWED_TRANSITIONS["Submitted"] == {"Submitted", "Under Review"}
    assert ALLOWED_TRANSITIONS["Under Review"] == {"Under Review", "Approved", "Rejected"}
    assert ALLOWED_TRANSITIONS["Approved"] == {"Approved"}
    assert ALLOWED_TRANSITIONS["Rejected"] == {"Rejected"}


def test_ac2_the_safety_workflow_cannot_start_from_an_event_that_has_not_reached_the_safety_check():
    """
    Summary: None of Submitted, Under Review or Rejected is a starting status in SAFETY_TRANSITIONS.
    AC2: Given an event has not yet reached the safety check, then the existing
        status transitions (SCRUM-19) continue to work unchanged.
    Double: None; the transition table is read directly, no route or database is used
    """
    # Act + Assert (When / Then)
    assert not set(SAFETY_TRANSITIONS) & {"Submitted", "Under Review", "Rejected"}


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


@pytest.mark.parametrize(
    "status", ["Pending Safety Check", "Safety Changes Requested", "Cancelled"]
)
def test_a_coordinator_cannot_set_the_safety_statuses_through_the_progress_route(status, setup):
    """
    Summary: PATCH /events/<id>/progress asking for "Pending Safety Check", "Safety Changes Requested" or "Cancelled" on an 'Approved' event answers 409 "This status change is not allowed for the event's current stage." and only the lookup read ran.
    Supporting design check: only the safety workflow writes the safety
        statuses
    Double: Stub (cursor.fetchone returns an 'Approved' event),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
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


@pytest.mark.parametrize("status", ["In Preparation", "Preparing", "SafetyApproved"])
def test_a_status_outside_the_documented_lifecycle_is_refused_with_400(status, setup):
    """
    Summary: PATCH /events/<id>/progress with status "In Preparation", "Preparing" or "SafetyApproved" answers 400 "Status must be one of: ..." and no query is sent.
    Supporting design check: only the documented lifecycle statuses are
        accepted
    Double: Mock (cursor.execute asserted never called)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = patch_progress(client, status)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"].startswith("Status must be one of: ")
    cursor.execute.assert_not_called()


def test_the_progress_lookup_takes_a_row_lock_so_a_concurrent_safety_decision_cannot_leave_it_stale(setup):
    """
    Summary: PATCH /events/<id>/progress asking for "Confirmed" runs a first query containing FOR UPDATE.
    Supporting design check: the gate reads the status under a row lock
    Double: Stub (cursor.fetchone returns an 'Approved' event),
        Mock (the first cursor.execute query asserted to contain FOR UPDATE)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Approved")

    # Act (When)
    patch_progress(client, "Confirmed")

    # Assert (Then)
    assert "FOR UPDATE" in cursor.execute.call_args_list[0].args[0]
