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

from app.models import RejectionReasonError, reject_event
from tests.unit.factories import (
    COORDINATOR_ID,
    OTHER_COORDINATOR_ID,
    rejected_row,
    saved_row,
)


def test_rejection_changes_status_and_records_reason_and_audit_metadata(setup):
    """
    Summary: Rejecting records the reason, who and when.
    AC1: Given an Event Request has status 'Submitted' and is assigned to the
        current Event Coordinator, when they reject it, then the status changes
        to 'Rejected'.
    AC3: When rejecting, the Event Coordinator must provide a reason, which is
        stored with the request.
    AC4: The rejecting Event Coordinator's identity and timestamp are recorded
        for auditability
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_rejection_is_unavailable_for_another_coordinators_assignment(setup):
    """
    Summary: Another coordinator cannot reject the request.
    AC2: Given an Event Request is not assigned to the current Event
        Coordinator, the reject action is not available to them.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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
def test_rejection_requires_a_reason(reason, setup):
    """
    Summary: A rejection without a reason is refused.
    AC3: When rejecting, the Event Coordinator must provide a reason, which is
        stored with the request.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    response = setup[0].patch(
        "/events/00000000-0000-0000-0000-000000000001/reject",
        json={"coordinatorId": COORDINATOR_ID, "reason": reason},
    )
    assert response.status_code == 400
    setup[2].execute.assert_not_called()


def test_rejection_is_rejected_when_event_is_not_submitted(setup):
    """
    Summary: Only a submitted request can be rejected.
    AC1: Given an Event Request has status 'Submitted' and is assigned to the
        current Event Coordinator, when they reject it, then the status changes
        to 'Rejected'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_reject_unknown_event_does_not_write_a_decision(setup):
    """
    Summary: Rejecting a missing event returns 404 and writes nothing.
    AC1: Given an Event Request has status 'Submitted' and is assigned to the
        current Event Coordinator, when they reject it, then the status changes
        to 'Rejected'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_public_rejection_model_refuses_whitespace_reason_before_writing(setup):
    """
    Summary: A whitespace-only rejection reason is refused before anything is written.
    AC3: When rejecting, the Event Coordinator must provide a reason, which is
        stored with the request.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    _, connection, cursor = setup
    cursor.fetchone.return_value = {**saved_row(), "coordinator_id": COORDINATOR_ID}

    with pytest.raises(RejectionReasonError):
        reject_event("unused-test-url", "00000000-0000-0000-0000-000000000001", COORDINATOR_ID, " \t\n")

    assert cursor.execute.call_count == 1
    assert cursor.execute.call_args.args[0].lstrip().startswith("SELECT")
    assert connection.__exit__.call_args.args[0] is RejectionReasonError
    connection.close.assert_called_once()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_reject_preflight_is_allowed(setup):
    """
    Summary: The browser's preflight for rejecting is answered.
    Supporting design check: preflight requests answer without a token
    Double: None
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
