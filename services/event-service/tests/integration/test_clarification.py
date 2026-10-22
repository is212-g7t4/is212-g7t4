"""SCRUM-15 Request Clarification on Event Submission: route-to-Postgres tests.

Real: the Flask routes, validation, app/models.py SQL, and postgres:17.6 loaded
with the production migration chain. Doubled: nothing, because Event Service is
an atomic service with no outbound calls. Identity is the coordinatorId or
organiserId supplied by the caller, so these tests prove ownership and
assignment checks given an asserted ID, not authentication.

AC1  An assigned coordinator can move a Submitted request to
     Clarification Requested.
AC2  The coordinator must provide a question/message, which is stored.
AC3  The organiser can respond without making the original request editable.
AC4  A response returns the request to Submitted with the same coordinator.
AC5  The requesting coordinator and timestamp are recorded for auditability.
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
    """The submitted request fields that clarification must never rewrite."""
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


def test_full_clarification_round_trip_is_audited_without_changing_the_request(client, db):
    """SCRUM-15 AC1-AC5 (normal): request, audit, answer, and return to the same coordinator."""
    event_id = submitted_event(db)
    before = db.event(event_id)
    original = original_fields(before)

    requested = open_clarification(client, event_id, f"  {QUESTION}  ")

    assert requested.status_code == 200
    assert requested.get_json()["status"] == "Clarification Requested"
    after_request = db.event(event_id)
    request_metadata = metadata(after_request)
    assert original_fields(after_request) == original
    assert request_metadata["description"] == "A hands-on workshop"
    assert request_metadata["purpose"] == "Learning"
    clarification = request_metadata["clarificationHistory"][0]
    assert clarification["question"] == QUESTION
    assert clarification["requestedBy"] == COORDINATOR_ID
    assert clarification["response"] is None
    assert_recent(clarification["requestedAt"], db)

    answered = answer_clarification(client, event_id, f"  {RESPONSE}  ")

    assert answered.status_code == 200
    assert answered.get_json()["status"] == "Submitted"
    assert answered.get_json()["coordinatorId"] == COORDINATOR_ID
    after_response = db.event(event_id)
    response_metadata = metadata(after_response)
    assert original_fields(after_response) == original
    clarification = response_metadata["clarificationHistory"][0]
    assert clarification["question"] == QUESTION
    assert clarification["response"] == RESPONSE
    assert clarification["respondedBy"] == ORGANISER_ID
    assert_recent(clarification["respondedAt"], db)


def test_original_request_fields_remain_locked_while_clarification_is_open(client, db):
    """SCRUM-15 AC3 (conflict): the clarification flow does not unlock event editing."""
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


def test_later_clarification_round_is_appended_without_overwriting_the_first(client, db):
    """SCRUM-15 AC2, AC3, AC5 (normal): every completed exchange remains auditable."""
    event_id = submitted_event(db)
    assert open_clarification(client, event_id, "First question").status_code == 200
    assert answer_clarification(client, event_id, "First answer").status_code == 200
    assert open_clarification(client, event_id, "Second question").status_code == 200
    assert answer_clarification(client, event_id, "Second answer").status_code == 200

    row = db.event(event_id)
    history = metadata(row)["clarificationHistory"]
    assert row["status"] == "Submitted"
    assert str(row["coordinator_id"]) == COORDINATOR_ID
    assert [(item["question"], item["response"]) for item in history] == [
        ("First question", "First answer"),
        ("Second question", "Second answer"),
    ]
    assert all(item["requestedBy"] == COORDINATOR_ID for item in history)
    assert all(item["respondedBy"] == ORGANISER_ID for item in history)


@pytest.mark.parametrize("message", [None, "", "   "], ids=["missing", "empty", "whitespace"])
def test_a_question_is_required_and_invalid_input_does_not_change_the_request(client, db, message):
    """SCRUM-15 AC2 (failure): a missing or blank question is refused without a write."""
    event_id = submitted_event(db)
    before = db.event(event_id)

    response = client.patch(
        f"/events/{event_id}/clarification-request",
        json={"coordinatorId": COORDINATOR_ID, "message": message},
    )

    assert response.status_code == 400
    assert db.event(event_id) == before


def test_question_length_boundary_is_enforced_without_partial_writes(client, db):
    """SCRUM-15 AC2 (boundary): 1000 characters are stored; 1001 are refused unchanged."""
    accepted_id = submitted_event(db, event_name="Accepted boundary")
    refused_id = submitted_event(db, event_name="Refused boundary")
    refused_before = db.event(refused_id)

    accepted = open_clarification(client, accepted_id, "q" * 1000)
    refused = open_clarification(client, refused_id, "q" * 1001)

    assert accepted.status_code == 200
    assert metadata(db.event(accepted_id))["clarificationHistory"][0]["question"] == "q" * 1000
    assert refused.status_code == 400
    assert db.event(refused_id) == refused_before


@pytest.mark.parametrize(
    ("assigned_coordinator", "current_coordinator"),
    [(None, COORDINATOR_ID), (LEAD_ID, COORDINATOR_ID)],
    ids=["unassigned", "assigned-to-someone-else"],
)
def test_only_the_assigned_coordinator_can_request_clarification(
    client, db, assigned_coordinator, current_coordinator
):
    """SCRUM-15 AC1 (failure): an unassigned or differently assigned request is unchanged."""
    event_id = submitted_event(db, coordinator_id=assigned_coordinator)
    before = db.event(event_id)

    response = client.patch(
        f"/events/{event_id}/clarification-request",
        json={"coordinatorId": current_coordinator, "message": QUESTION},
    )

    assert response.status_code == 403
    assert db.event(event_id) == before


@pytest.mark.parametrize("status", ["Approved", "Clarification Requested"])
def test_clarification_cannot_be_requested_outside_the_reviewable_states(client, db, status):
    """SCRUM-15 AC1 (conflict): invalid starting states do not create an audit entry."""
    event_id = submitted_event(db, status=status)
    before = db.event(event_id)

    response = open_clarification(client, event_id)

    assert response.status_code == 409
    assert response.get_json()["code"] == "CLARIFICATION_NOT_ALLOWED"
    assert db.event(event_id) == before


@pytest.mark.parametrize("response_text", [None, "", "   "], ids=["missing", "empty", "whitespace"])
def test_a_response_is_required_and_invalid_input_leaves_the_request_open(client, db, response_text):
    """SCRUM-15 AC3 (failure): a blank response cannot close the clarification."""
    event_id = submitted_event(db)
    assert open_clarification(client, event_id).status_code == 200
    before = db.event(event_id)

    response = answer_clarification(client, event_id, response=response_text)

    assert response.status_code == 400
    assert db.event(event_id) == before


def test_response_length_boundary_is_enforced_without_closing_a_refused_round(client, db):
    """SCRUM-15 AC3 (boundary): 1000 characters succeed; 1001 leave the round open."""
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


def test_only_the_event_organiser_can_respond(client, db):
    """SCRUM-15 AC3 (failure): another organiser cannot answer or close the request."""
    event_id = submitted_event(db)
    assert open_clarification(client, event_id).status_code == 200
    before = db.event(event_id)

    response = answer_clarification(client, event_id, organiser_id=OTHER_ORGANISER_ID)

    assert response.status_code == 403
    assert db.event(event_id) == before


def test_response_requires_an_open_clarification(client, db):
    """SCRUM-15 AC3, AC4 (conflict): an ordinary Submitted request cannot be answered."""
    event_id = submitted_event(db)
    before = db.event(event_id)

    response = answer_clarification(client, event_id)

    assert response.status_code == 409
    assert response.get_json()["code"] == "CLARIFICATION_NOT_OPEN"
    assert db.event(event_id) == before


@pytest.mark.parametrize(
    ("endpoint", "body"),
    [
        ("clarification-request", {"coordinatorId": COORDINATOR_ID, "message": QUESTION}),
        ("clarification-response", {"organiserId": ORGANISER_ID, "response": RESPONSE}),
    ],
    ids=["request", "response"],
)
def test_clarification_for_a_missing_event_returns_not_found(client, db, endpoint, body):
    """SCRUM-15 AC1, AC3 (failure): neither operation can create a missing request."""
    response = client.patch(f"/events/{UNKNOWN_ID}/{endpoint}", json=body)

    assert response.status_code == 404
    assert db.event_count() == 0
