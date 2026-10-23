"""SCRUM-15 Request Clarification on Event Submission: Event Service integration tests.

Story:      As an Event Coordinator, I want to request clarification on a submitted event
            request assigned to me, so that I can get the information I need to decide
            without altering the request itself.
Real:       Flask app and routes, validation, app/models.py SQL, postgres:17.6 with the
            full migration chain.
Doubled:    nothing (Event Service makes no outbound calls).
Not proven: JWT authentication; identity is the coordinatorId / organiserId the caller
            sends. Frontend behaviour and cross-service communication are also not proven.

AC1  Given an Event Request has status 'Submitted' and is assigned to the current Event
     Coordinator, when they request clarification, then the status changes to
     'Clarification Requested'.
AC2  The Event Coordinator must provide a question/message, which is stored with the
     request.
AC3  The Event Organiser can reply with a response; no fields on the original request
     become editable as part of this flow.
AC4  Given the Event Organiser responds, the status reverts to 'Submitted' and the request
     remains assigned to the same Event Coordinator.
AC5  The requesting Event Coordinator's identity and timestamp are recorded for
     auditability.
"""

import json
from datetime import datetime, timedelta

import pytest

from tests.integration.factories import (
    COORDINATOR_ID,
    LEAD_ID,
    ORGANISER_ID,
    OTHER_ORGANISER_ID,
    SINGAPORE,
    UNKNOWN_ID,
    make_event,
    make_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

QUESTION = "Which audience is invited?"
RESPONSE = "All enrolled students."


@pytest.fixture(autouse=True)
def users(db):
    make_user(db, ORGANISER_ID)
    make_user(db, OTHER_ORGANISER_ID)
    make_user(db, COORDINATOR_ID, role="Event Coordinator")
    make_user(db, LEAD_ID, role="Event Coordinator")


def submitted_event(db, **overrides):
    values = {
        "status": "Submitted",
        "coordinator_id": COORDINATOR_ID,
        "event_name": "Community Workshop",
        "description": "A hands-on workshop",
        "purpose": "Learning",
        "start": datetime(2030, 3, 1, 9, tzinfo=SINGAPORE),
        "end": datetime(2030, 3, 1, 17, tzinfo=SINGAPORE),
        "expected_attendance": 25,
        "venue_requirements": "Seminar room",
    }
    values.update(overrides)
    return make_event(db, **values)


def metadata(row):
    return json.loads(row["description"])


def open_clarification(client, event_id, question=QUESTION):
    return client.patch(
        f"/events/{event_id}/clarification-request",
        json={"coordinatorId": COORDINATOR_ID, "message": question},
    )


def answer_clarification(client, event_id, response=RESPONSE, organiser_id=ORGANISER_ID):
    return client.patch(
        f"/events/{event_id}/clarification-response",
        json={"organiserId": organiser_id, "response": response},
    )


def assert_recent(timestamp, db):
    recorded = datetime.fromisoformat(timestamp)
    assert timedelta(0) <= db.now() - recorded < timedelta(minutes=1)


def original_fields(row):
    return {
        key: row[key]
        for key in (
            "event_name",
            "preferred_start_date",
            "preferred_end_date",
            "expected_attendance",
            "venue_requirements",
            "organiser_id",
            "coordinator_id",
            "submission_date",
        )
    }


# AC1 ---------------------------------------------------------------------


def test_ac1_assigned_coordinator_request_changes_status_to_clarification_requested(client, db):
    """Normal: an assigned Submitted request enters the clarification state."""
    event_id = submitted_event(db)

    response = open_clarification(client, event_id)

    assert response.status_code == 200
    assert response.get_json()["status"] == "Clarification Requested"
    assert db.event(event_id)["status"] == "Clarification Requested"


@pytest.mark.parametrize(
    ("assigned_coordinator", "current_coordinator"),
    [(None, COORDINATOR_ID), (LEAD_ID, COORDINATOR_ID)],
    ids=["unassigned", "assigned-to-someone-else"],
)
def test_ac1_only_the_assigned_coordinator_can_request_clarification(
    client, db, assigned_coordinator, current_coordinator
):
    """Failure: an unassigned or differently assigned request remains unchanged."""
    event_id = submitted_event(db, coordinator_id=assigned_coordinator)
    before = db.event(event_id)

    response = client.patch(
        f"/events/{event_id}/clarification-request",
        json={"coordinatorId": current_coordinator, "message": QUESTION},
    )

    assert response.status_code == 403
    assert db.event(event_id) == before


@pytest.mark.parametrize("status", ["Approved", "Clarification Requested"])
def test_ac1_clarification_cannot_be_requested_outside_reviewable_states(client, db, status):
    """Conflict: invalid starting states do not create a clarification entry."""
    event_id = submitted_event(db, status=status)
    before = db.event(event_id)

    response = open_clarification(client, event_id)

    assert response.status_code == 409
    assert response.get_json()["code"] == "CLARIFICATION_NOT_ALLOWED"
    assert db.event(event_id) == before


def test_ac1_clarification_request_for_a_missing_event_returns_not_found(client, db):
    """Failure: requesting clarification cannot create an event that does not exist."""
    response = open_clarification(client, UNKNOWN_ID)

    assert response.status_code == 404
    assert db.event_count() == 0


# AC2 ---------------------------------------------------------------------


@pytest.mark.parametrize("message", [None, "", "   "], ids=["missing", "empty", "whitespace"])
def test_ac2_a_question_is_required_and_invalid_input_does_not_change_the_request(client, db, message):
    """Failure: a missing or blank question is refused without a database write."""
    event_id = submitted_event(db)
    before = db.event(event_id)

    response = client.patch(
        f"/events/{event_id}/clarification-request",
        json={"coordinatorId": COORDINATOR_ID, "message": message},
    )

    assert response.status_code == 400
    assert db.event(event_id) == before


def test_ac2_question_length_boundary_is_enforced_without_partial_writes(client, db):
    """Boundary: 1000 characters are stored while 1001 are refused unchanged."""
    accepted_id = submitted_event(db, event_name="Accepted boundary")
    refused_id = submitted_event(db, event_name="Refused boundary")
    refused_before = db.event(refused_id)

    accepted = open_clarification(client, accepted_id, "q" * 1000)
    refused = open_clarification(client, refused_id, "q" * 1001)

    assert accepted.status_code == 200
    assert metadata(db.event(accepted_id))["clarificationHistory"][0]["question"] == "q" * 1000
    assert refused.status_code == 400
    assert db.event(refused_id) == refused_before


# AC3 ---------------------------------------------------------------------


def test_ac3_original_request_fields_remain_locked_while_clarification_is_open(client, db):
    """Conflict: entering clarification does not unlock the original request fields."""
    event_id = submitted_event(db)
    assert open_clarification(client, event_id).status_code == 200
    before_edit = db.event(event_id)

    response = client.patch(
        f"/events/{event_id}/details",
        json={
            "coordinatorId": COORDINATOR_ID,
            "changes": {"description": "Changed during clarification"},
        },
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "EVENT_NOT_EDITABLE"
    assert db.event(event_id) == before_edit


@pytest.mark.parametrize("response_text", [None, "", "   "], ids=["missing", "empty", "whitespace"])
def test_ac3_a_response_is_required_and_invalid_input_leaves_the_request_open(client, db, response_text):
    """Failure: a blank response cannot close an open clarification."""
    event_id = submitted_event(db)
    assert open_clarification(client, event_id).status_code == 200
    before = db.event(event_id)

    response = answer_clarification(client, event_id, response=response_text)

    assert response.status_code == 400
    assert db.event(event_id) == before


def test_ac3_response_length_boundary_is_enforced_without_closing_a_refused_round(client, db):
    """Boundary: 1000 characters succeed while 1001 leave the clarification open."""
    accepted_id = submitted_event(db, event_name="Accepted boundary")
    refused_id = submitted_event(db, event_name="Refused boundary")
    assert open_clarification(client, accepted_id).status_code == 200
    assert open_clarification(client, refused_id).status_code == 200
    refused_before = db.event(refused_id)

    accepted = answer_clarification(client, accepted_id, "a" * 1000)
    refused = answer_clarification(client, refused_id, "a" * 1001)

    assert accepted.status_code == 200
    assert metadata(db.event(accepted_id))["clarificationHistory"][0]["response"] == "a" * 1000
    assert refused.status_code == 400
    assert db.event(refused_id) == refused_before


def test_ac3_only_the_event_organiser_can_respond(client, db):
    """Failure: another organiser cannot answer or close the clarification."""
    event_id = submitted_event(db)
    assert open_clarification(client, event_id).status_code == 200
    before = db.event(event_id)

    response = answer_clarification(client, event_id, organiser_id=OTHER_ORGANISER_ID)

    assert response.status_code == 403
    assert db.event(event_id) == before


def test_ac3_response_requires_an_open_clarification(client, db):
    """Conflict: an ordinary Submitted request cannot receive a clarification response."""
    event_id = submitted_event(db)
    before = db.event(event_id)

    response = answer_clarification(client, event_id)

    assert response.status_code == 409
    assert response.get_json()["code"] == "CLARIFICATION_NOT_OPEN"
    assert db.event(event_id) == before


def test_ac3_clarification_response_for_a_missing_event_returns_not_found(client, db):
    """Failure: responding cannot create an event that does not exist."""
    response = answer_clarification(client, UNKNOWN_ID)

    assert response.status_code == 404
    assert db.event_count() == 0


# AC4 ---------------------------------------------------------------------


def test_ac4_response_returns_to_submitted_with_the_same_coordinator(client, db):
    """Normal: the organiser's response returns the unchanged request to its coordinator."""
    event_id = submitted_event(db)
    before = db.event(event_id)
    original = original_fields(before)
    assert open_clarification(client, event_id, f"  {QUESTION}  ").status_code == 200

    response = answer_clarification(client, event_id, f"  {RESPONSE}  ")

    assert response.status_code == 200
    assert response.get_json()["status"] == "Submitted"
    assert response.get_json()["coordinatorId"] == COORDINATOR_ID
    after = db.event(event_id)
    assert after["status"] == "Submitted"
    assert str(after["coordinator_id"]) == COORDINATOR_ID
    assert original_fields(after) == original
    stored = metadata(after)
    assert stored["description"] == "A hands-on workshop"
    assert stored["purpose"] == "Learning"
    clarification = stored["clarificationHistory"][0]
    assert clarification["question"] == QUESTION
    assert clarification["response"] == RESPONSE
    assert clarification["respondedBy"] == ORGANISER_ID


# AC5 ---------------------------------------------------------------------


def test_ac5_each_clarification_round_keeps_requester_identity_and_timestamp(client, db):
    """Normal: later rounds append complete audit records without overwriting earlier ones."""
    event_id = submitted_event(db)
    assert open_clarification(client, event_id, "First question").status_code == 200
    assert answer_clarification(client, event_id, "First answer").status_code == 200
    assert open_clarification(client, event_id, "Second question").status_code == 200
    assert answer_clarification(client, event_id, "Second answer").status_code == 200

    row = db.event(event_id)
    history = metadata(row)["clarificationHistory"]
    assert [(item["question"], item["response"]) for item in history] == [
        ("First question", "First answer"),
        ("Second question", "Second answer"),
    ]
    assert all(item["requestedBy"] == COORDINATOR_ID for item in history)
    assert all(item["respondedBy"] == ORGANISER_ID for item in history)
    for item in history:
        assert_recent(item["requestedAt"], db)
