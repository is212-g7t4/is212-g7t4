"""
SCRUM-14: Reject Submitted Event Request

User Story
----------
As an Event Coordinator, I want to reject a submitted event request assigned to
me, so that the Event Organiser knows their event cannot proceed as submitted.

Acceptance Criteria
-------------------
AC1: Given an Event Request has status 'Submitted' and is assigned to the
     current Event Coordinator, when they reject it, then the status changes to
     'Rejected'.
AC2: Given an Event Request is not assigned to the current Event Coordinator,
     the reject action is not available to them.
AC3: When rejecting, the Event Coordinator must provide a reason, which is
     stored with the request.
AC4: The rejecting Event Coordinator's identity and timestamp are recorded for
     auditability

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

import pytest
from datetime import UTC, datetime

from app.models import RejectionReasonError, _aware, decide_event, reject_event
from tests.unit.factories import (
    COORDINATOR_ID,
    OTHER_COORDINATOR_ID,
    rejected_row,
    saved_row,
)


def test_ac1_ac3_ac4_rejecting_an_assigned_request_sets_rejected_and_records_reason_coordinator_and_time(setup):
    """
    Summary: The assigned coordinator rejects with a reason: the response is 'Rejected' with a decision holding that coordinator, the reason and a decidedAt time, and the UPDATE writes status 'Rejected' and the reason.
    AC1: Given an Event Request has status 'Submitted' and is assigned to the
        current Event Coordinator, when they reject it, then the status changes
        to 'Rejected'.
    AC3: When rejecting, the Event Coordinator must provide a reason, which is
        stored with the request.
    AC4: The rejecting Event Coordinator's identity and timestamp are recorded
        for auditability
    Double: Stub (cursor.fetchone returns the assigned Submitted row, then the rejected row),
        Mock (the UPDATE public."Event" call's SQL and parameters: SET status = %s, 'Rejected' and the reason)
    """
    # Arrange (Given)
    client, _, cursor = setup
    assigned = saved_row()
    assigned["coordinator_id"] = COORDINATOR_ID
    cursor.fetchone.side_effect = [assigned, rejected_row()]

    # Act (When)
    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001/reject",
        json={
            "coordinatorId": COORDINATOR_ID,
            "reason": "The selected venue is unavailable.",
        },
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Rejected"
    assert response.json["decision"]["status"] == "Rejected"
    assert response.json["decision"]["coordinatorId"] == COORDINATOR_ID
    assert response.json["decision"]["reason"] == "The selected venue is unavailable."
    assert response.json["decision"]["decidedAt"]
    # Notification INSERTs follow the mutation; inspect the UPDATE itself, not the last SQL call.
    update_query, parameters = next(call.args for call in cursor.execute.call_args_list
                                    if 'UPDATE public."Event"' in call.args[0])
    assert "SET status = %s" in update_query
    assert parameters[0] == "Rejected"
    assert parameters[6] == "The selected venue is unavailable."


def test_ac2_rejection_by_a_coordinator_the_request_is_not_assigned_to_answers_403(setup):
    """
    Summary: A request assigned to another coordinator answers 403 and only the lookup SELECT runs, so nothing is written.
    AC2: Given an Event Request is not assigned to the current Event
        Coordinator, the reject action is not available to them.
    Double: Stub (cursor.fetchone returns a Submitted row assigned to OTHER_COORDINATOR_ID),
        Mock (cursor.execute call_count is 1: the lookup only)
    """
    # Arrange (Given)
    client, _, cursor = setup
    assigned = saved_row()
    assigned["coordinator_id"] = OTHER_COORDINATOR_ID
    cursor.fetchone.return_value = assigned

    # Act (When)
    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001/reject",
        json={"coordinatorId": COORDINATOR_ID, "reason": "Not suitable."},
    )

    # Assert (Then)
    assert response.status_code == 403
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("reason", [None, "", "  "])
def test_ac3_rejection_with_a_null_empty_or_blank_reason_answers_400_before_any_query(reason, setup):
    """
    Summary: A reason that is null, empty or only spaces answers 400 at the route, and the database is never queried.
    AC3: When rejecting, the Event Coordinator must provide a reason, which is
        stored with the request.
    Double: Mock (cursor.execute asserted never called); no rows are stubbed because the route refuses first
    """
    response = setup[0].patch(
        "/events/00000000-0000-0000-0000-000000000001/reject",
        json={"coordinatorId": COORDINATOR_ID, "reason": reason},
    )
    assert response.status_code == 400
    setup[2].execute.assert_not_called()


def test_ac1_rejection_of_a_request_that_is_not_submitted_answers_409(setup):
    """
    Summary: A request assigned to the caller but already in status 'Approved' answers 409 and only the lookup SELECT runs, so nothing is written.
    AC1: Given an Event Request has status 'Submitted' and is assigned to the
        current Event Coordinator, when they reject it, then the status changes
        to 'Rejected'.
    Double: Stub (cursor.fetchone returns a row assigned to the caller with status 'Approved'),
        Mock (cursor.execute call_count is 1: the lookup only)
    """
    # Arrange (Given)
    client, _, cursor = setup
    assigned = saved_row()
    assigned.update(coordinator_id=COORDINATOR_ID, status="Approved")
    cursor.fetchone.return_value = assigned

    # Act (When)
    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001/reject",
        json={"coordinatorId": COORDINATOR_ID, "reason": "Not suitable."},
    )

    # Assert (Then)
    assert response.status_code == 409
    assert cursor.execute.call_count == 1


def test_reject_unknown_event_answers_404_and_writes_nothing(setup):
    """
    Summary: Rejecting an id that matches no event answers 404 'Event request not found.' and only the lookup SELECT runs.
    Supporting design check: no acceptance criterion covers a missing event;
        the route must answer 404 rather than write a decision
    Double: Stub (cursor.fetchone returns None),
        Mock (cursor.execute call_count is 1 and that call is a SELECT)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    # Act (When)
    response = client.patch("/events/00000000-0000-0000-0000-000000000001/reject",
                            json={"coordinatorId": COORDINATOR_ID, "reason": "Unsafe exits."})

    # Assert (Then)
    assert response.status_code == 404
    assert response.json == {"message": "Event request not found."}
    assert cursor.execute.call_count == 1
    assert cursor.execute.call_args.args[0].lstrip().startswith("SELECT")


def test_ac3_model_refuses_a_whitespace_reason_itself_and_rolls_back_without_writing(setup):
    """
    Summary: Calling reject_event directly (no route in front of it) with a whitespace-only reason raises RejectionReasonError after the lookup SELECT; the connection exits with that error and is closed, and no UPDATE runs.
    AC3: When rejecting, the Event Coordinator must provide a reason, which is
        stored with the request.
    Double: Stub (cursor.fetchone returns a row assigned to the caller),
        Mock (cursor.execute is the lookup only; connection.__exit__ saw RejectionReasonError; connection.close called once)
    """
    _, connection, cursor = setup
    cursor.fetchone.return_value = {**saved_row(), "coordinator_id": COORDINATOR_ID}

    with pytest.raises(RejectionReasonError):
        reject_event("unused-test-url", "00000000-0000-0000-0000-000000000001", COORDINATOR_ID, " \t\n")

    assert cursor.execute.call_count == 1
    assert cursor.execute.call_args.args[0].lstrip().startswith("SELECT")
    assert connection.__exit__.call_args.args[0] is RejectionReasonError
    connection.close.assert_called_once()


def test_ac3_decide_event_refuses_a_rejection_with_no_reason_before_opening_a_connection():
    """
    Summary: Calling decide_event(..., "Rejected", None) directly expects RejectionReasonError (no database is configured, so none is opened), and checks that _aware returns an already time-zone-aware datetime as it is. This is the only test that reaches that refusal in app/models.py, so it is kept although the route-level reason test is similar.
    AC3: When rejecting, the Event Coordinator must provide a reason, which is
        stored with the request.
    Double: None; decide_event and _aware are called directly, and the unused database URL is never connected to
    """
    aware = datetime(2026, 10, 20, tzinfo=UTC)
    assert _aware(aware) is aware
    with pytest.raises(RejectionReasonError):
        decide_event("unused-test-url", "00000000-0000-0000-0000-000000000001", COORDINATOR_ID, "Rejected", None)


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_reject_preflight_is_answered_without_a_token_for_the_frontend_origin(setup):
    """
    Summary: An OPTIONS preflight for PATCH on the reject route from http://localhost:5174 answers 200, echoes that origin and lists PATCH as an allowed method.
    Supporting design check: preflight requests answer without a token
    Double: Stub (setup fixture: psycopg2.connect returns a MagicMock connection, which the preflight never queries)
    """
    client = setup[0]
    response = client.options(
        "/events/00000000-0000-0000-0000-000000000001/reject",
        headers={
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert "PATCH" in response.headers["Access-Control-Allow-Methods"]


def test_reject_answers_503_when_no_database_is_configured(setup):
    """
    Summary: With DATABASE_URL set to None, a reject PATCH answers 503 "DATABASE_URL is not configured for Event Service." and no cursor is opened.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: Mock (connection.cursor asserted never called and cursor.execute never called); no rows are stubbed
    """
    client, connection, cursor = setup
    client.application.config["DATABASE_URL"] = None

    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001/reject",
        json={"coordinatorId": COORDINATOR_ID, "reason": "Unsafe exits."},
    )

    assert response.status_code == 503
    assert response.json == {"message": "DATABASE_URL is not configured for Event Service."}
    connection.cursor.assert_not_called()
    cursor.execute.assert_not_called()
