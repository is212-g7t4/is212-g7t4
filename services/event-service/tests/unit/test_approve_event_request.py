"""
SCRUM-13: Approve Submitted Event Request

User Story
----------
As an Event Coordinator, I want to approve a submitted event request assigned
to me, so that the Event Organiser knows their event can proceed to planning.

Acceptance Criteria
-------------------
AC1: Given an Event Request has status 'Submitted' and is assigned to the
     current Event Coordinator, when they approve it, then the status changes
     to 'Approved'.
AC2: Given an Event Request is not assigned to the current Event Coordinator,
     the approve action is not available to them.
AC3: The approving Event Coordinator's identity and timestamp are recorded for
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

import pytest

from tests.unit.factories import (
    COORDINATOR_ID,
    OTHER_COORDINATOR_ID,
    VALID,
    approved_row,
    saved_row,
)


def test_approval_changes_status_and_records_audit_metadata(setup):
    """
    Summary: Approving moves the request to 'Approved' and records who and when.
    AC1: Given an Event Request has status 'Submitted' and is assigned to the
        current Event Coordinator, when they approve it, then the status
        changes to 'Approved'.
    AC3: The approving Event Coordinator's identity and timestamp are recorded
        for auditability.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, connection, cursor = setup
    assigned = saved_row()
    assigned["coordinator_id"] = COORDINATOR_ID
    cursor.fetchone.side_effect = [assigned, approved_row()]

    # Act (When)
    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001/approve",
        json={"coordinatorId": COORDINATOR_ID},
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Approved"
    assert response.json["decision"]["status"] == "Approved"
    assert response.json["decision"]["coordinatorId"] == COORDINATOR_ID
    assert response.json["decision"]["reason"] is None
    assert response.json["decisionHistory"] == [response.json["decision"]]
    assert cursor.execute.call_count == 2
    update_query, parameters = cursor.execute.call_args.args
    assert "SET status = %s" in update_query
    assert parameters[0:3] == ["Approved", VALID["description"], VALID["purpose"]]
    assert parameters[3:5] == ["Approved", COORDINATOR_ID]
    assert parameters[-1] == "00000000-0000-0000-0000-000000000001"
    connection.__exit__.assert_called_once()


def test_approval_is_rejected_for_another_coordinators_assignment(setup):
    """
    Summary: Another coordinator cannot approve the request.
    AC2: Given an Event Request is not assigned to the current Event
        Coordinator, the approve action is not available to them.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    assigned = saved_row()
    assigned["coordinator_id"] = OTHER_COORDINATOR_ID
    cursor.fetchone.return_value = assigned

    # Act (When)
    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001/approve",
        json={"coordinatorId": COORDINATOR_ID},
    )

    # Assert (Then)
    assert response.status_code == 403
    assert cursor.execute.call_count == 1


def test_approval_is_rejected_when_event_is_not_submitted(setup):
    """
    Summary: Only a submitted request can be approved.
    AC1: Given an Event Request has status 'Submitted' and is assigned to the
        current Event Coordinator, when they approve it, then the status
        changes to 'Approved'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    assigned = saved_row()
    assigned.update(coordinator_id=COORDINATOR_ID, status="Approved")
    cursor.fetchone.return_value = assigned

    # Act (When)
    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001/approve",
        json={"coordinatorId": COORDINATOR_ID},
    )

    # Assert (Then)
    assert response.status_code == 409
    assert cursor.execute.call_count == 1


def test_approval_returns_not_found_for_unknown_event(setup):
    """
    Summary: Approving a missing event returns 404.
    AC1: Given an Event Request has status 'Submitted' and is assigned to the
        current Event Coordinator, when they approve it, then the status
        changes to 'Approved'.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    # Act (When)
    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001/approve",
        json={"coordinatorId": COORDINATOR_ID},
    )

    # Assert (Then)
    assert response.status_code == 404


def test_approval_requires_a_signed_in_coordinator(setup):
    """
    Summary: Approval needs a signed-in coordinator.
    AC2: Given an Event Request is not assigned to the current Event
        Coordinator, the approve action is not available to them.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given): setup, from fixtures

    # Act (When)
    response = setup[0].application.test_client().patch(
        "/events/00000000-0000-0000-0000-000000000001/approve",
        json={"coordinatorId": COORDINATOR_ID},
    )

    # Assert (Then)
    assert response.status_code == 401
    setup[2].execute.assert_not_called()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


@pytest.mark.parametrize("route,body", [
    ("approve", {"coordinatorId": COORDINATOR_ID}),
    ("reject", {"coordinatorId": COORDINATOR_ID, "reason": "Unsafe exits."}),
], ids=["approve-without-database-503", "reject-without-database-503"])
def test_decision_without_database_configuration_never_connects(setup, route, body):
    """
    Summary: Approval and rejection cannot report success without Event storage.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None
    """
    client, connection, cursor = setup
    client.application.config["DATABASE_URL"] = None

    response = client.patch(f"/events/00000000-0000-0000-0000-000000000001/{route}", json=body)

    assert response.status_code == 503
    assert response.json == {"message": "DATABASE_URL is not configured for Event Service."}
    connection.cursor.assert_not_called()
    cursor.execute.assert_not_called()
