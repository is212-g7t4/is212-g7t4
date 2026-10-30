"""
SCRUM-15: Request Clarification on Event Submission

User Story
----------
As an Event Coordinator, I want to request clarification on a submitted event
request assigned to me, so that I can get the information I need to decide
without altering the request itself.

Acceptance Criteria
-------------------
AC1: Given an Event Request is assigned to the current Event Coordinator and
     has status “Under Review”, when they request clarification, then the
     status changes to 'Clarification Requested'.
AC2: The Event Coordinator must provide a question/message, which is stored
     with the request.
AC3: The Event Organiser can reply with a response; no fields on the original
     request become editable as part of this flow.
AC4: Given the Event Organiser responds, the status reverts to 'Submitted' and
     the request remains assigned to the same Event Coordinator.
AC5: The requesting Event Coordinator's identity and timestamp are recorded for
     auditability.

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
from app.models import FIELDS, RejectionReasonError, _aware, decide_event
from tests.unit.factories import signed_in

EVENT_ID = "00000000-0000-4000-8000-000000000001"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OTHER_COORDINATOR_ID = "22222222-2222-4222-8222-222222222222"
ORGANISER_ID = "33333333-3333-4333-8333-333333333333"
OTHER_ORGANISER_ID = "44444444-4444-4444-8444-444444444444"


def event_row(status="Under Review", coordinator_id=COORDINATOR_ID, organiser_id=ORGANISER_ID):
    row = {column: "" for column in FIELDS.values()}
    row.update(
        event_id=EVENT_ID,
        event_name="Community Workshop",
        status=status,
        coordinator_id=coordinator_id,
        organiser_id=organiser_id,
        assigned_by=None,
        assigned_at=None,
        previous_coordinator_id=None,
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
        "actionDetails": "Review started.",
        "actionHistory": [],
        "clarificationHistory": [],
    })
    return row


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client()), connection, cursor


def test_clarification_assigned_coordinator_requests_clarification_with_auditable_history(setup):
    """
    Summary: The assigned coordinator's question is stored, the status moves, and who and when are recorded.
    AC1: Given an Event Request is assigned to the current Event Coordinator
        and has status “Under Review”, when they request clarification, then
        the status changes to 'Clarification Requested'.
    AC2: The Event Coordinator must provide a question/message, which is stored
        with the request.
    AC5: The requesting Event Coordinator's identity and timestamp are recorded
        for auditability.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, connection, cursor = setup
    updated = event_row("Clarification Requested")
    cursor.fetchone.side_effect = [event_row(), updated]

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-request",
        json={"coordinatorId": COORDINATOR_ID, "message": "  Which audience is invited?  "},
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Clarification Requested"
    assert response.json["coordinatorId"] == COORDINATOR_ID
    query, parameters = cursor.execute.call_args_list[1].args
    assert "SET status = 'Clarification Requested'" in query
    stored = json.loads(parameters[0])
    clarification = stored["clarificationHistory"][0]
    assert clarification["question"] == "Which audience is invited?"
    assert clarification["requestedBy"] == COORDINATOR_ID
    assert clarification["requestedAt"]
    assert clarification["response"] is None
    assert stored["description"] == "A practical workshop"
    assert stored["actionDetails"] == "Review started."
    assert stored["actionHistory"][-1]["status"] == "Clarification Requested"
    assert parameters[1] == EVENT_ID
    connection.__exit__.assert_called_once()


@pytest.mark.parametrize("starting_status", ["Submitted", "Under Review"])
def test_clarification_is_allowed_from_both_supported_starting_states(starting_status, setup):
    """
    Summary: Clarification can be requested from 'Submitted' or 'Under Review'.
    AC1: Given an Event Request is assigned to the current Event Coordinator
        and has status “Under Review”, when they request clarification, then
        the status changes to 'Clarification Requested'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(starting_status), event_row("Clarification Requested")]

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-request",
        json={"coordinatorId": COORDINATOR_ID, "message": "Please clarify."},
    )

    # Assert (Then)
    assert response.status_code == 200


def test_clarification_only_assigned_coordinator_can_request_clarification(setup):
    """
    Summary: Only the assigned coordinator can request clarification.
    AC1: Given an Event Request is assigned to the current Event Coordinator
        and has status “Under Review”, when they request clarification, then
        the status changes to 'Clarification Requested'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=OTHER_COORDINATOR_ID)

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-request",
        json={"coordinatorId": COORDINATOR_ID, "message": "Please clarify."},
    )

    # Assert (Then)
    assert response.status_code == 403
    assert cursor.execute.call_count == 1


def test_clarification_unassigned_event_cannot_receive_a_clarification_request(setup):
    """
    Summary: An unassigned event cannot be sent a clarification request.
    AC1: Given an Event Request is assigned to the current Event Coordinator
        and has status “Under Review”, when they request clarification, then
        the status changes to 'Clarification Requested'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=None)

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-request",
        json={"coordinatorId": COORDINATOR_ID, "message": "Please clarify."},
    )

    # Assert (Then)
    assert response.status_code == 403


def test_clarification_cannot_request_another_clarification_while_one_is_open(setup):
    """
    Summary: A second clarification cannot be opened while one is unanswered.
    AC1: Given an Event Request is assigned to the current Event Coordinator
        and has status “Under Review”, when they request clarification, then
        the status changes to 'Clarification Requested'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Clarification Requested")

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-request",
        json={"coordinatorId": COORDINATOR_ID, "message": "Another question."},
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "CLARIFICATION_NOT_ALLOWED"


@pytest.mark.parametrize("message", [None, "", "   ", [], "x" * 1001], ids=["none", "empty", "empty_2", "empty_3", "x_1001"])
def test_clarification_request_requires_a_valid_message(message, setup):
    """
    Summary: A clarification request needs a question.
    AC2: The Event Coordinator must provide a question/message, which is stored
        with the request.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    response = setup[0].patch(
        f"/events/{EVENT_ID}/clarification-request",
        json={"coordinatorId": COORDINATOR_ID, "message": message},
    )
    assert response.status_code == 400
    setup[2].execute.assert_not_called()


def test_clarification_organiser_response_returns_to_submitted_and_keeps_assignment(setup):
    """
    Summary: The organiser's reply returns the request to 'Submitted' with the same coordinator.
    AC3: The Event Organiser can reply with a response; no fields on the
        original request become editable as part of this flow.
    AC4: Given the Event Organiser responds, the status reverts to 'Submitted'
        and the request remains assigned to the same Event Coordinator.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, connection, cursor = setup
    current = event_row("Clarification Requested")
    metadata = json.loads(current["description"])
    metadata["clarificationHistory"] = [{
        "id": "clarification-1",
        "question": "Which audience is invited?",
        "requestedBy": COORDINATOR_ID,
        "requestedAt": "2026-10-20T01:00:00+00:00",
        "response": None,
        "respondedBy": None,
        "respondedAt": None,
    }]
    current["description"] = json.dumps(metadata)
    updated = event_row("Submitted")
    cursor.fetchone.side_effect = [current, updated]

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-response",
        json={"organiserId": ORGANISER_ID, "response": "  All enrolled students.  "},
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Submitted"
    assert response.json["coordinatorId"] == COORDINATOR_ID
    query, parameters = cursor.execute.call_args_list[1].args
    assert "SET status = 'Submitted'" in query
    stored = json.loads(parameters[0])
    clarification = stored["clarificationHistory"][0]
    assert clarification["question"] == "Which audience is invited?"
    assert clarification["response"] == "All enrolled students."
    assert clarification["respondedBy"] == ORGANISER_ID
    assert clarification["respondedAt"]
    assert stored["actionHistory"][-1]["organiserId"] == ORGANISER_ID
    assert parameters[1] == EVENT_ID
    connection.__exit__.assert_called_once()


def test_clarification_only_owning_organiser_can_respond(setup):
    """
    Summary: Only the organiser who owns the request can reply.
    AC3: The Event Organiser can reply with a response; no fields on the
        original request become editable as part of this flow.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Clarification Requested", organiser_id=OTHER_ORGANISER_ID)
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-response",
        json={"organiserId": ORGANISER_ID, "response": "Here is the answer."},
    )
    assert response.status_code == 403
    assert cursor.execute.call_count == 1


def test_clarification_event_without_an_organiser_cannot_be_answered(setup):
    """
    Summary: A request with no recorded organiser cannot be answered.
    AC3: The Event Organiser can reply with a response; no fields on the
        original request become editable as part of this flow.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Clarification Requested", organiser_id=None)
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-response",
        json={"organiserId": ORGANISER_ID, "response": "Here is the answer."},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("status", ["Submitted", "Under Review", "Approved"])
def test_clarification_response_requires_an_open_clarification_status(status, setup):
    """
    Summary: A reply needs the request to be awaiting clarification.
    AC4: Given the Event Organiser responds, the status reverts to 'Submitted'
        and the request remains assigned to the same Event Coordinator.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(status)

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-response",
        json={"organiserId": ORGANISER_ID, "response": "Here is the answer."},
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "CLARIFICATION_NOT_OPEN"


def test_clarification_response_requires_an_open_history_entry_even_if_status_is_stale(setup):
    """
    Summary: A reply needs an open question in the history, not just the status.
    AC4: Given the Event Organiser responds, the status reverts to 'Submitted'
        and the request remains assigned to the same Event Coordinator.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Clarification Requested")

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-response",
        json={"organiserId": ORGANISER_ID, "response": "Here is the answer."},
    )

    # Assert (Then)
    assert response.status_code == 409
    assert cursor.execute.call_count == 1


def test_clarification_response_requires_an_unanswered_history_entry(setup):
    """
    Summary: A question already answered cannot be answered again.
    AC4: Given the Event Organiser responds, the status reverts to 'Submitted'
        and the request remains assigned to the same Event Coordinator.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    current = event_row("Clarification Requested")
    metadata = json.loads(current["description"])
    metadata["clarificationHistory"] = [{"response": "Already answered."}]
    current["description"] = json.dumps(metadata)
    cursor.fetchone.return_value = current

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-response",
        json={"organiserId": ORGANISER_ID, "response": "A second answer."},
    )

    # Assert (Then)
    assert response.status_code == 409


@pytest.mark.parametrize("response_text", [None, "", "   ", [], "x" * 1001], ids=["none", "empty", "empty_2", "empty_3", "x_1001"])
def test_clarification_response_requires_valid_text(response_text, setup):
    """
    Summary: A reply needs text.
    AC3: The Event Organiser can reply with a response; no fields on the
        original request become editable as part of this flow.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    response = setup[0].patch(
        f"/events/{EVENT_ID}/clarification-response",
        json={"organiserId": ORGANISER_ID, "response": response_text},
    )
    assert response.status_code == 400
    setup[2].execute.assert_not_called()


@pytest.mark.parametrize("endpoint, body", [
    ("clarification-request", {"coordinatorId": COORDINATOR_ID, "message": "Question"}),
    ("clarification-response", {"organiserId": ORGANISER_ID, "response": "Answer"}),
], ids=["clarification_request_coordinatorid_coordinator", "clarification_response_organiserid_organiser_id"])
def test_clarification_endpoints_return_not_found(endpoint, body, setup):
    """
    Summary: Both clarification endpoints return 404 for a missing event.
    AC1: Given an Event Request is assigned to the current Event Coordinator
        and has status “Under Review”, when they request clarification, then
        the status changes to 'Clarification Requested'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    setup[2].fetchone.return_value = None

    # Act (When)
    response = setup[0].patch(f"/events/{EVENT_ID}/{endpoint}", json=body)

    # Assert (Then)
    assert response.status_code == 404


def test_clarification_existing_validation_helpers_keep_their_boundary_branches(setup):
    """
    Summary: The shared text-length validation keeps its limits.
    AC2: The Event Coordinator must provide a question/message, which is stored
        with the request.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    aware = datetime(2026, 10, 20, tzinfo=UTC)
    assert _aware(aware) is aware
    with pytest.raises(RejectionReasonError):
        decide_event("unused-test-url", EVENT_ID, COORDINATOR_ID, "Rejected", None)


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


@pytest.mark.parametrize("endpoint, body", [
    ("clarification-request", {"coordinatorId": COORDINATOR_ID, "message": "Question"}),
    ("clarification-response", {"organiserId": ORGANISER_ID, "response": "Answer"}),
], ids=["clarification_request_coordinatorid_coordinator", "clarification_response_organiserid_organiser_id"])
def test_clarification_endpoints_require_database_configuration(endpoint, body):
    """
    Summary: Clarification endpoints require database configuration.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client())
    response = client.patch(f"/events/{EVENT_ID}/{endpoint}", json=body)
    assert response.status_code == 503
