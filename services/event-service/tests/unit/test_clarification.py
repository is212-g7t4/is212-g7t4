"""Request Clarification on Event Submission acceptance criteria."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.models import FIELDS, RejectionReasonError, _aware, decide_event

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
    return app.test_client(), connection, cursor


def test_assigned_coordinator_requests_clarification_with_auditable_history(setup):
    client, connection, cursor = setup
    updated = event_row("Clarification Requested")
    cursor.fetchone.side_effect = [event_row(), updated]

    response = client.patch(
        f"/events/{EVENT_ID}/clarification-request",
        json={"coordinatorId": COORDINATOR_ID, "message": "  Which audience is invited?  "},
    )

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
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(starting_status), event_row("Clarification Requested")]
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-request",
        json={"coordinatorId": COORDINATOR_ID, "message": "Please clarify."},
    )
    assert response.status_code == 200


def test_only_assigned_coordinator_can_request_clarification(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=OTHER_COORDINATOR_ID)
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-request",
        json={"coordinatorId": COORDINATOR_ID, "message": "Please clarify."},
    )
    assert response.status_code == 403
    assert cursor.execute.call_count == 1


def test_unassigned_event_cannot_receive_a_clarification_request(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=None)
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-request",
        json={"coordinatorId": COORDINATOR_ID, "message": "Please clarify."},
    )
    assert response.status_code == 403


def test_cannot_request_another_clarification_while_one_is_open(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Clarification Requested")
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-request",
        json={"coordinatorId": COORDINATOR_ID, "message": "Another question."},
    )
    assert response.status_code == 409
    assert response.json["code"] == "CLARIFICATION_NOT_ALLOWED"


@pytest.mark.parametrize("message", [None, "", "   ", [], "x" * 1001])
def test_clarification_request_requires_a_valid_message(message, setup):
    response = setup[0].patch(
        f"/events/{EVENT_ID}/clarification-request",
        json={"coordinatorId": COORDINATOR_ID, "message": message},
    )
    assert response.status_code == 400
    setup[2].execute.assert_not_called()


def test_organiser_response_returns_to_submitted_and_keeps_assignment(setup):
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

    response = client.patch(
        f"/events/{EVENT_ID}/clarification-response",
        json={"organiserId": ORGANISER_ID, "response": "  All enrolled students.  "},
    )

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


def test_only_owning_organiser_can_respond(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Clarification Requested", organiser_id=OTHER_ORGANISER_ID)
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-response",
        json={"organiserId": ORGANISER_ID, "response": "Here is the answer."},
    )
    assert response.status_code == 403
    assert cursor.execute.call_count == 1


def test_event_without_an_organiser_cannot_be_answered(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Clarification Requested", organiser_id=None)
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-response",
        json={"organiserId": ORGANISER_ID, "response": "Here is the answer."},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("status", ["Submitted", "Under Review", "Approved"])
def test_response_requires_an_open_clarification_status(status, setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(status)
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-response",
        json={"organiserId": ORGANISER_ID, "response": "Here is the answer."},
    )
    assert response.status_code == 409
    assert response.json["code"] == "CLARIFICATION_NOT_OPEN"


def test_response_requires_an_open_history_entry_even_if_status_is_stale(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Clarification Requested")
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-response",
        json={"organiserId": ORGANISER_ID, "response": "Here is the answer."},
    )
    assert response.status_code == 409
    assert cursor.execute.call_count == 1


def test_response_requires_an_unanswered_history_entry(setup):
    client, _, cursor = setup
    current = event_row("Clarification Requested")
    metadata = json.loads(current["description"])
    metadata["clarificationHistory"] = [{"response": "Already answered."}]
    current["description"] = json.dumps(metadata)
    cursor.fetchone.return_value = current
    response = client.patch(
        f"/events/{EVENT_ID}/clarification-response",
        json={"organiserId": ORGANISER_ID, "response": "A second answer."},
    )
    assert response.status_code == 409


@pytest.mark.parametrize("response_text", [None, "", "   ", [], "x" * 1001])
def test_clarification_response_requires_valid_text(response_text, setup):
    response = setup[0].patch(
        f"/events/{EVENT_ID}/clarification-response",
        json={"organiserId": ORGANISER_ID, "response": response_text},
    )
    assert response.status_code == 400
    setup[2].execute.assert_not_called()


@pytest.mark.parametrize("endpoint, identity", [
    ("clarification-request", {"coordinatorId": "not-a-uuid", "message": "Question"}),
    ("clarification-response", {"organiserId": "not-a-uuid", "response": "Answer"}),
])
def test_clarification_endpoints_require_valid_identity(endpoint, identity, setup):
    response = setup[0].patch(f"/events/{EVENT_ID}/{endpoint}", json=identity)
    assert response.status_code == 400
    setup[2].execute.assert_not_called()


@pytest.mark.parametrize("endpoint, body", [
    ("clarification-request", {"coordinatorId": COORDINATOR_ID, "message": "Question"}),
    ("clarification-response", {"organiserId": ORGANISER_ID, "response": "Answer"}),
])
def test_clarification_endpoints_return_not_found(endpoint, body, setup):
    setup[2].fetchone.return_value = None
    response = setup[0].patch(f"/events/{EVENT_ID}/{endpoint}", json=body)
    assert response.status_code == 404


@pytest.mark.parametrize("endpoint, body", [
    ("clarification-request", {"coordinatorId": COORDINATOR_ID, "message": "Question"}),
    ("clarification-response", {"organiserId": ORGANISER_ID, "response": "Answer"}),
])
def test_clarification_endpoints_require_database_configuration(endpoint, body):
    client = create_app({"TESTING": True, "DATABASE_URL": None}).test_client()
    response = client.patch(f"/events/{EVENT_ID}/{endpoint}", json=body)
    assert response.status_code == 503


def test_existing_validation_helpers_keep_their_boundary_branches(setup):
    aware = datetime(2026, 10, 20, tzinfo=UTC)
    assert _aware(aware) is aware
    with pytest.raises(RejectionReasonError):
        decide_event("unused-test-url", EVENT_ID, COORDINATOR_ID, "Rejected", None)
