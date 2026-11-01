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
from app.models import FIELDS
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


def test_ac1_ac2_ac5_assigned_coordinator_requests_clarification_and_the_question_who_and_when_are_stored(setup):
    """
    Summary: PATCH /events/<id>/clarification-request by the assigned coordinator with a padded question answers 200 with status 'Clarification Requested'; the UPDATE stores a clarificationHistory entry holding the trimmed question, the requesting coordinator's id, a requestedAt time and no response, keeps the description and earlier action details, and appends a 'Clarification Requested' action.
    AC1: Given an Event Request is assigned to the current Event Coordinator
        and has status “Under Review”, when they request clarification, then
        the status changes to 'Clarification Requested'.
    AC2: The Event Coordinator must provide a question/message, which is stored
        with the request.
    AC5: The requesting Event Coordinator's identity and timestamp are recorded
        for auditability.
    Double: Stub (cursor.fetchone returns the 'Under Review' event, then the 'Clarification Requested' event),
        Mock (the UPDATE query and its JSON metadata parameter asserted; connection.__exit__ called once)
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
def test_ac1_clarification_can_be_requested_from_submitted_or_under_review(starting_status, setup):
    """
    Summary: PATCH /events/<id>/clarification-request on an assigned event that is 'Submitted' or 'Under Review' answers 200 for each.
    AC1: Given an Event Request is assigned to the current Event Coordinator
        and has status “Under Review”, when they request clarification, then
        the status changes to 'Clarification Requested'.
    Double: Stub (cursor.fetchone returns the event in the starting status, then a 'Clarification Requested' event); the response status is the only assertion
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


def test_ac1_a_coordinator_the_event_is_not_assigned_to_cannot_request_clarification(setup):
    """
    Summary: PATCH /events/<id>/clarification-request by a coordinator when the event is assigned to a different one answers 403 and only the lookup read ran.
    AC1: Given an Event Request is assigned to the current Event Coordinator
        and has status “Under Review”, when they request clarification, then
        the status changes to 'Clarification Requested'.
    Double: Stub (cursor.fetchone returns an event assigned to another coordinator),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
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


def test_ac1_an_unassigned_event_cannot_receive_a_clarification_request(setup):
    """
    Summary: PATCH /events/<id>/clarification-request when the event has no assigned coordinator answers 403.
    AC1: Given an Event Request is assigned to the current Event Coordinator
        and has status “Under Review”, when they request clarification, then
        the status changes to 'Clarification Requested'.
    Double: Stub (cursor.fetchone returns an event with no coordinator); the response status is the only assertion
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


def test_ac1_a_second_clarification_cannot_be_requested_while_one_is_open(setup):
    """
    Summary: PATCH /events/<id>/clarification-request on an event already 'Clarification Requested' answers 409 with code CLARIFICATION_NOT_ALLOWED.
    AC1: Given an Event Request is assigned to the current Event Coordinator
        and has status “Under Review”, when they request clarification, then
        the status changes to 'Clarification Requested'.
    Double: Stub (cursor.fetchone returns an event already in 'Clarification Requested'); the 409 status and code are asserted
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
def test_ac2_a_clarification_request_without_a_valid_question_is_refused(message, setup):
    """
    Summary: PATCH /events/<id>/clarification-request with a null, empty, blank, non-text or 1001-character message answers 400 and no query is sent.
    AC2: The Event Coordinator must provide a question/message, which is stored
        with the request.
    Double: Mock (cursor.execute asserted never called)
    """
    response = setup[0].patch(
        f"/events/{EVENT_ID}/clarification-request",
        json={"coordinatorId": COORDINATOR_ID, "message": message},
    )
    assert response.status_code == 400
    setup[2].execute.assert_not_called()


def test_ac3_ac4_organiser_reply_is_stored_and_the_request_returns_to_submitted_with_the_same_coordinator(setup):
    """
    Summary: PATCH /events/<id>/clarification-response by the owning organiser with a padded reply answers 200 with status 'Submitted' and the same coordinatorId; the UPDATE keeps the question, stores the trimmed reply with the organiser's id and a respondedAt time, and appends an action carrying the organiser id.
    AC3: The Event Organiser can reply with a response; no fields on the
        original request become editable as part of this flow.
    AC4: Given the Event Organiser responds, the status reverts to 'Submitted'
        and the request remains assigned to the same Event Coordinator.
    Double: Stub (cursor.fetchone returns the 'Clarification Requested' event with one unanswered question, then the 'Submitted' event),
        Mock (the UPDATE query and its JSON metadata parameter asserted; connection.__exit__ called once)
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


def test_ac3_an_organiser_who_does_not_own_the_request_cannot_reply(setup):
    """
    Summary: PATCH /events/<id>/clarification-response by an organiser when the event belongs to a different organiser answers 403 and only the lookup read ran.
    AC3: The Event Organiser can reply with a response; no fields on the
        original request become editable as part of this flow.
    Double: Stub (cursor.fetchone returns a 'Clarification Requested' event owned by another organiser),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Clarification Requested", organiser_id=OTHER_ORGANISER_ID)
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-response",
        json={"organiserId": ORGANISER_ID, "response": "Here is the answer."},
    )
    assert response.status_code == 403
    assert cursor.execute.call_count == 1


def test_ac3_a_request_with_no_recorded_organiser_cannot_be_answered(setup):
    """
    Summary: PATCH /events/<id>/clarification-response on an event with no organiser recorded answers 403.
    AC3: The Event Organiser can reply with a response; no fields on the
        original request become editable as part of this flow.
    Double: Stub (cursor.fetchone returns a 'Clarification Requested' event with no organiser); the response status is the only assertion
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Clarification Requested", organiser_id=None)
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-response",
        json={"organiserId": ORGANISER_ID, "response": "Here is the answer."},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("status", ["Submitted", "Under Review", "Approved"])
def test_ac4_a_reply_is_refused_unless_the_request_is_awaiting_clarification(status, setup):
    """
    Summary: PATCH /events/<id>/clarification-response on an event that is 'Submitted', 'Under Review' or 'Approved' answers 409 with code CLARIFICATION_NOT_OPEN.
    AC4: Given the Event Organiser responds, the status reverts to 'Submitted'
        and the request remains assigned to the same Event Coordinator.
    Double: Stub (cursor.fetchone returns the event in the parametrised status); the 409 status and code are asserted
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


def test_ac4_a_reply_is_refused_when_the_status_is_clarification_requested_but_the_history_has_no_question(setup):
    """
    Summary: PATCH /events/<id>/clarification-response on an event whose status is 'Clarification Requested' but whose clarification history is empty answers 409 and only the lookup read ran.
    AC4: Given the Event Organiser responds, the status reverts to 'Submitted'
        and the request remains assigned to the same Event Coordinator.
    Double: Stub (cursor.fetchone returns a 'Clarification Requested' event with an empty clarificationHistory),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
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


def test_ac4_a_question_that_already_has_a_reply_cannot_be_answered_again(setup):
    """
    Summary: PATCH /events/<id>/clarification-response when the only clarification entry already has a response answers 409.
    AC4: Given the Event Organiser responds, the status reverts to 'Submitted'
        and the request remains assigned to the same Event Coordinator.
    Double: Stub (cursor.fetchone returns a 'Clarification Requested' event whose history entry already has a response); the 409 status is the only assertion
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
def test_ac3_a_reply_without_valid_text_is_refused(response_text, setup):
    """
    Summary: PATCH /events/<id>/clarification-response with a null, empty, blank, non-text or 1001-character reply answers 400 and no query is sent.
    AC3: The Event Organiser can reply with a response; no fields on the
        original request become editable as part of this flow.
    Double: Mock (cursor.execute asserted never called)
    """
    response = setup[0].patch(
        f"/events/{EVENT_ID}/clarification-response",
        json={"organiserId": ORGANISER_ID, "response": response_text},
    )
    assert response.status_code == 400
    setup[2].execute.assert_not_called()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


@pytest.mark.parametrize("endpoint, body", [
    ("clarification-request", {"coordinatorId": COORDINATOR_ID, "message": "Question"}),
    ("clarification-response", {"organiserId": ORGANISER_ID, "response": "Answer"}),
], ids=["clarification_request_coordinatorid_coordinator", "clarification_response_organiserid_organiser_id"])
def test_clarification_endpoints_answer_404_for_an_unknown_event(endpoint, body, setup):
    """
    Summary: PATCH /events/<id>/clarification-request and /clarification-response each answer 404 when the database finds no such event.
    Supporting design check: asking to clarify an event that does not exist is
        a 404
    Double: Stub (cursor.fetchone returns None)
    """
    # Arrange (Given)
    setup[2].fetchone.return_value = None

    # Act (When)
    response = setup[0].patch(f"/events/{EVENT_ID}/{endpoint}", json=body)

    # Assert (Then)
    assert response.status_code == 404

@pytest.mark.parametrize("endpoint, body", [
    ("clarification-request", {"coordinatorId": COORDINATOR_ID, "message": "Question"}),
    ("clarification-response", {"organiserId": ORGANISER_ID, "response": "Answer"}),
], ids=["clarification_request_coordinatorid_coordinator", "clarification_response_organiserid_organiser_id"])
def test_clarification_endpoints_answer_503_when_no_database_is_configured(endpoint, body):
    """
    Summary: With no DATABASE_URL set, PATCH /events/<id>/clarification-request and /clarification-response each answer 503.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None for the database, since the app has none configured; only the Supabase JWKS Stub, which verifies the signed token
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client())
    response = client.patch(f"/events/{EVENT_ID}/{endpoint}", json=body)
    assert response.status_code == 503
