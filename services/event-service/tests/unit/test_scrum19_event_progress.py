"""
SCRUM-19: Update Event Status

User Story
----------
As an Event Coordinator, I would like to be able to view and update the status
of an Event, so that I can update and let others know the progress of an Event.

Acceptance Criteria
-------------------
AC1: Event Coordinator should be able to view and filter his/her events and its
     status
AC2: Event Coordinator should be able to view the details of an Event and its
     status
AC3: Event Coordinator should be able to update and edit the status of an Event
AC4: Event Coordinator should be able to add and update the details of the
     actions done for the Event

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
    metadata = {
        "_connectsphere": "event-submission-v1",
        "description": "A practical workshop",
        "purpose": "Learning",
        "decision": None,
        "decisionHistory": [],
        "actionDetails": action_details,
        "actionHistory": [],
    }
    row["description"] = json.dumps(metadata)
    return row


def test_ac3_ac4_assigned_coordinator_changes_the_status_and_the_action_taken_is_recorded(setup):
    """
    Summary: PATCH /events/<id>/progress by the assigned coordinator, moving an 'Under Review' event to "Approved" with padded action details, answers 200 with status "Approved", the trimmed actionDetails, an action-history entry carrying the coordinator id and the decision; the UPDATE (after a FOR UPDATE lookup) sets status and the description metadata with the same action history and the event id.
    AC3: Event Coordinator should be able to update and edit the status of an
        Event
    AC4: Event Coordinator should be able to add and update the details of the
        actions done for the Event
    Double: Stub (cursor.fetchone returns the 'Under Review' event, then the updated 'Approved' event),
        Mock (the lookup and UPDATE queries and parameters asserted; connection.__exit__ called once)
    """
    client, connection, cursor = setup
    updated = event_row("Approved", action_details="Venue and equipment confirmed.")
    updated_metadata = json.loads(updated["description"])
    updated_metadata["decision"] = {
        "status": "Approved",
        "coordinatorId": COORDINATOR_ID,
        "decidedAt": "2026-10-02T02:00:00+00:00",
        "reason": None,
    }
    updated_metadata["decisionHistory"] = [updated_metadata["decision"]]
    updated_metadata["actionHistory"] = [{
        "status": "Approved",
        "details": "Venue and equipment confirmed.",
        "coordinatorId": COORDINATOR_ID,
        "recordedAt": "2026-10-02T02:00:00+00:00",
    }]
    updated["description"] = json.dumps(updated_metadata)
    cursor.fetchone.side_effect = [event_row("Under Review"), updated]

    response = client.patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": "Approved",
            "actionDetails": "  Venue and equipment confirmed.  ",
        },
    )

    assert response.status_code == 200
    assert response.json["status"] == "Approved"
    assert response.json["actionDetails"] == "Venue and equipment confirmed."
    assert response.json["actionHistory"][0]["coordinatorId"] == COORDINATOR_ID
    assert response.json["decision"]["status"] == "Approved"
    assert cursor.execute.call_count == 2
    select_query = cursor.execute.call_args_list[0].args[0]
    assert "FOR UPDATE" in select_query
    update_query, parameters = cursor.execute.call_args_list[1].args
    assert "SET status = %s, description = %s" in update_query
    assert parameters[0] == "Approved"
    stored = json.loads(parameters[1])
    assert stored["actionDetails"] == "Venue and equipment confirmed."
    assert stored["actionHistory"][0]["status"] == "Approved"
    assert parameters[2] == EVENT_ID
    connection.__exit__.assert_called_once()


def test_ac4_saving_the_same_status_with_new_action_details_adds_an_action_without_a_duplicate_decision(setup):
    """
    Summary: PATCH /events/<id>/progress keeping an 'Approved' event at "Approved" with new action details answers 200; the stored metadata keeps the earlier decision history unchanged and appends the new details as the latest action.
    AC4: Event Coordinator should be able to add and update the details of the
        actions done for the Event
    Double: Stub (cursor.fetchone returns the 'Approved' event with one decision, then the updated event),
        Mock (the UPDATE's metadata parameter asserted)
    """
    client, _, cursor = setup
    current = event_row("Approved", action_details="Venue confirmed.")
    current_metadata = json.loads(current["description"])
    current_metadata["decision"] = {
        "status": "Approved",
        "coordinatorId": COORDINATOR_ID,
        "decidedAt": "2026-10-01T02:00:00+00:00",
        "reason": None,
    }
    current_metadata["decisionHistory"] = [current_metadata["decision"]]
    current["description"] = json.dumps(current_metadata)
    updated = event_row("Approved", action_details="Equipment confirmed too.")
    cursor.fetchone.side_effect = [current, updated]

    response = client.patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": "Approved",
            "actionDetails": "Equipment confirmed too.",
        },
    )

    assert response.status_code == 200
    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    assert stored["decisionHistory"] == current_metadata["decisionHistory"]
    assert stored["actionHistory"][-1]["details"] == "Equipment confirmed too."


@pytest.mark.parametrize(
    ("current_status", "requested_status"),
    # ("Under Review", "Confirmed") moved to test_scrum152_safety_gate.py — it now
    # returns the safety reason instead of this generic message (SCRUM-152).
    [("Submitted", "Approved"), ("Submitted", "Rejected"),
     ("Approved", "Submitted"),
     ("Approved", "Rejected"), ("Confirmed", "Approved"),
     ("Rejected", "Submitted"), ("Rejected", "Approved")],
)
def test_ac3_a_status_change_that_is_not_allowed_from_the_current_stage_is_refused(current_status, requested_status, setup):
    """
    Summary: PATCH /events/<id>/progress asking for Submitted to Approved or Rejected, Approved to Submitted or Rejected, Confirmed to Approved, or Rejected to Submitted or Approved answers 409 "This status change is not allowed for the event's current stage." and only the lookup read ran.
    AC3: Event Coordinator should be able to update and edit the status of an
        Event
    Double: Stub (cursor.fetchone returns the event in the current status),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(current_status)

    response = client.patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": requested_status,
            "actionDetails": "Attempted status change.",
        },
    )

    assert response.status_code == 409
    assert response.json["message"] == (
        "This status change is not allowed for the event's current stage."
    )
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize(
    ("current_status", "requested_status"),
    [("Submitted", "Under Review"), ("Under Review", "Approved"),
     ("Under Review", "Rejected")],
)
def test_ac3_the_status_changes_before_the_safety_check_are_allowed_and_recorded(current_status, requested_status, setup):
    """
    Summary: PATCH /events/<id>/progress moving Submitted to Under Review, or Under Review to Approved or Rejected, answers 200 with the new status, and the stored action history ends with that status.
    AC3: Event Coordinator should be able to update and edit the status of an
        Event
    Double: Stub (cursor.fetchone returns the event in the current status, then the event in the new status),
        Mock (the UPDATE's metadata parameter asserted)
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row(current_status),
        event_row(requested_status, action_details="Reviewed."),
    ]

    response = client.patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": requested_status,
            "actionDetails": "Reviewed.",
        },
    )

    assert response.status_code == 200
    assert response.json["status"] == requested_status
    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    assert stored["actionHistory"][-1]["status"] == requested_status


def test_ac3_an_update_is_forbidden_for_an_event_assigned_to_another_coordinator(setup):
    """
    Summary: PATCH /events/<id>/progress by a coordinator when the event is assigned to a different coordinator answers 403 and only the lookup read ran.
    AC3: Event Coordinator should be able to update and edit the status of an
        Event
    Double: Stub (cursor.fetchone returns an event assigned to another coordinator),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=OTHER_COORDINATOR_ID)

    response = client.patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": "Approved",
            "actionDetails": "Reviewed.",
        },
    )

    assert response.status_code == 403
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("status", ["", "Pending", "approved", "Preparing", None])
def test_ac3_a_status_value_the_service_does_not_support_is_refused_before_any_query(status, setup):
    """
    Summary: PATCH /events/<id>/progress with status "", "Pending", "approved" (wrong case), "Preparing" or null answers 400 and no query is sent.
    AC3: Event Coordinator should be able to update and edit the status of an
        Event
    Double: Mock (cursor.execute asserted never called)
    """
    response = setup[0].patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": status,
            "actionDetails": "Reviewed.",
        },
    )
    assert response.status_code == 400
    setup[2].execute.assert_not_called()


@pytest.mark.parametrize("details", ["", "   ", None, [], "x" * 1001], ids=["empty", "empty_2", "none", "empty_3", "x_1001"])
def test_ac4_action_details_that_are_missing_blank_not_text_or_too_long_are_refused_before_any_query(details, setup):
    """
    Summary: PATCH /events/<id>/progress with actionDetails empty, whitespace, null, a list or 1001 characters answers 400 and no query is sent.
    AC4: Event Coordinator should be able to add and update the details of the
        actions done for the Event
    Double: Mock (cursor.execute asserted never called)
    """
    response = setup[0].patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": "Submitted",
            "actionDetails": details,
        },
    )
    assert response.status_code == 400
    setup[2].execute.assert_not_called()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


@pytest.mark.parametrize("body", [{}, None, {"coordinatorId": "not-a-uuid"}], ids=["empty", "none", "coordinatorid_not_a_uuid"])
def test_a_progress_update_without_a_valid_coordinator_id_is_refused_before_any_query(body, setup):
    """
    Summary: PATCH /events/<id>/progress with an empty body, no JSON, or a coordinatorId that is not a UUID answers 400 and no query is sent.
    Supporting design check: the coordinator id in the body must be a valid UUID
    Double: Mock (cursor.execute asserted never called)
    """
    response = setup[0].patch(f"/events/{EVENT_ID}/progress", json=body)
    assert response.status_code == 400
    setup[2].execute.assert_not_called()


def test_a_progress_update_for_an_unknown_event_answers_404(setup):
    """
    Summary: PATCH /events/<id>/progress answers 404 when the database finds no such event.
    Supporting design check: updating an event that does not exist is a 404
    Double: Stub (cursor.fetchone returns None)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = None
    response = client.patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": "Submitted",
            "actionDetails": "Reviewed.",
        },
    )
    assert response.status_code == 404


def test_progress_update_answers_503_when_no_database_is_configured():
    """
    Summary: With no DATABASE_URL set, PATCH /events/<id>/progress answers 503.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None for the database, since the app has none configured; only the Supabase JWKS Stub, which verifies the signed token
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client())
    response = client.patch(
        f"/events/{EVENT_ID}/progress",
        json={
            "coordinatorId": COORDINATOR_ID,
            "status": "Submitted",
            "actionDetails": "Reviewed.",
        },
    )
    assert response.status_code == 503
