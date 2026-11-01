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
- AC2 and AC3: which arrangements are pending and the saved notes belong to
  Safety Check Service, which calls this route (-> Safety Check Service tests).
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
def test_ac1_an_approved_or_revised_event_moves_to_pending_safety_check(setup, source_status):
    """
    Summary: PATCH /events/<id>/safety-status to "Pending Safety Check" by the assigned coordinator on an 'Approved' or 'Safety Changes Requested' event answers 200 with status "Pending Safety Check"; three statements ran (lookup, event UPDATE, notification outbox INSERT) and the UPDATE's first parameter is that status.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (cursor.fetchone returns the event in the parametrised status, then the 'Pending Safety Check' event),
        Mock (cursor.execute call count asserted to be 3; the UPDATE's status parameter asserted)
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


def test_ac1_the_submission_is_recorded_in_the_event_s_action_history_with_its_time(setup):
    """
    Summary: After submitting round 2, the stored action history ends with an entry whose status is "Pending Safety Check", details "Submitted for Operational Safety Check (round 2).", the coordinator id, the safety check id and a UTC timestamp, and the earlier history entry is still first.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: Stub (cursor.fetchone returns an 'Approved' event with one history entry, then the 'Pending Safety Check' event),
        Mock (the UPDATE's metadata parameter asserted)
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


# --- AC4: no duplicate safety check -------------------------------------------


def test_ac4_submitting_an_event_that_is_already_pending_safety_check_is_a_conflict(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Pending Safety Check" by the assigned coordinator on an event already 'Pending Safety Check' answers 409 SAFETY_CHECK_ALREADY_PENDING and only the lookup read ran, so no second check is created.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: Stub (cursor.fetchone returns a 'Pending Safety Check' event),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
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


# --- AC5: only the assigned coordinator -------------------------------------


def test_ac5_a_coordinator_the_event_is_not_assigned_to_is_refused(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Pending Safety Check" by a coordinator when the event is assigned to a different one answers 403 "This event request is not assigned to the current coordinator." and only the lookup read ran.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Stub (cursor.fetchone returns an 'Approved' event assigned to another coordinator),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
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


def test_ac5_an_event_with_no_assigned_coordinator_is_refused(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Pending Safety Check" on an 'Approved' event with no coordinator answers 403 and only the lookup read ran.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Stub (cursor.fetchone returns an 'Approved' event with no coordinator),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Approved", coordinator_id=None)

    # Act (When)
    response = patch_safety_status(client)

    # Assert (Then)
    assert response.status_code == 403
    assert cursor.execute.call_count == 1


def test_ac5_a_coordinator_who_is_not_assigned_gets_403_rather_than_the_already_pending_conflict(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Pending Safety Check" by a coordinator when the event is already 'Pending Safety Check' but assigned to a different coordinator answers 403 with no code in the body, so a stranger learns nothing about the event's stage.
    AC5: Given the Event Coordinator is not the assigned coordinator, then the
        submit action is not available and an API call is rejected.
    Double: Stub (cursor.fetchone returns a 'Pending Safety Check' event assigned to another coordinator); the 403 status and the absence of a code are the only assertions
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


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_a_safety_submission_leaves_the_coordinators_decision_and_action_details_alone(setup):
    """
    Summary: After submitting for a safety check, the metadata written by the UPDATE still holds the earlier decision status "Approved" and actionDetails "Venue booked.".
    Supporting design check: a safety submission is not a coordinator decision,
        so `decision` is untouched
    Double: Stub (cursor.fetchone returns an 'Approved' event, then the 'Pending Safety Check' event),
        Mock (the UPDATE's metadata parameter asserted)
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


def test_the_safety_submission_reads_the_event_under_a_row_lock(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Pending Safety Check" runs a first query containing FOR UPDATE.
    Supporting design check: the composite's earlier read can be stale, so the
        checks repeat under the row lock
    Double: Stub (cursor.fetchone returns an 'Approved' event, then the 'Pending Safety Check' event),
        Mock (the first cursor.execute query asserted to contain FOR UPDATE)
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


@pytest.mark.parametrize("current_status", NON_APPROVED_STATUSES)
def test_an_event_outside_the_submission_stages_cannot_be_submitted_for_a_safety_check(current_status, setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Pending Safety Check" on an event that is Submitted, Under Review, Rejected, Confirmed or Cancelled answers 409 INVALID_SAFETY_TRANSITION with the currentStatus and the message "This event can't move to 'Pending Safety Check' from '<status>'.", and only the lookup read ran.
    Supporting design check: only initial submission and requested-change
        resubmission stages may enter a safety check
    Double: Stub (cursor.fetchone returns the event in the parametrised status),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
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


def test_a_safety_submission_for_an_event_that_does_not_exist_answers_404(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Pending Safety Check" answers 404 "Event request not found." when the database finds no such event.
    Supporting design check: submitting an event that does not exist is a 404
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


@pytest.mark.parametrize("status", ["Approved", "Submitted", "Under Review", "Rejected"])
def test_the_safety_status_route_refuses_the_statuses_that_belong_to_the_progress_route(status, setup):
    """
    Summary: PATCH /events/<id>/safety-status with status "Approved", "Submitted", "Under Review" or "Rejected" answers 400 "Status must be one of: ..." and no query is sent.
    Supporting design check: this route only sets safety statuses; the rest is
        PATCH /progress
    Double: Mock (cursor.execute asserted never called)
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
def test_a_safety_check_id_that_is_missing_or_not_a_uuid_is_refused_before_any_query(overrides, message, setup):
    """
    Summary: PATCH /events/<id>/safety-status with safetyCheckId "not-a-uuid" or null answers 400 "A valid safety check ID is required." and no query is sent.
    Supporting design check: the round id must be a valid UUID
    Double: Mock (cursor.execute asserted never called)
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
def test_a_round_number_that_is_not_a_positive_whole_number_is_refused_before_any_query(round_number, setup):
    """
    Summary: PATCH /events/<id>/safety-status with roundNumber 0, -1, 1.5, "1", true or null answers 400 "roundNumber must be a positive whole number." and no query is sent.
    Supporting design check: the round number must be a positive integer
    Double: Mock (cursor.execute asserted never called)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = patch_safety_status(client, roundNumber=round_number)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "roundNumber must be a positive whole number."
    cursor.execute.assert_not_called()


def test_a_safety_status_body_that_is_not_a_json_object_is_refused_before_any_query(setup):
    """
    Summary: PATCH /events/<id>/safety-status with a JSON list as the body answers 400 "Send a JSON object." and no query is sent.
    Supporting design check: the request body must be a JSON object
    Double: Mock (cursor.execute asserted never called)
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


def test_the_safety_status_route_answers_503_when_no_database_is_configured():
    """
    Summary: With no DATABASE_URL set, PATCH /events/<id>/safety-status answers 503 with a message naming DATABASE_URL.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None for the database, since the app has none configured; only the Supabase JWKS Stub, which verifies the signed token
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
