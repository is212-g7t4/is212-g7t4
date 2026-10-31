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
- The Event Service approve route and its rules, run through the real app:
  who is calling, whether the request is theirs, whether it can still be
  approved, and the update sent to the database.
- We check the HTTP status, the response, and the queries the database received.

Doubled
-------
- Database (psycopg2.connect): a fake connection that returns rows we choose
  [Stub], and we check which queries it was sent [Mock].
- Supabase sign-in keys (tests/conftest.py): a throwaway test key signs the
  tokens [Stub].

Not proven
----------
- That the SQL works on the real Postgres tables (-> tests/integration/).
- That non-coordinators are blocked by role (-> test_event_modification_access.py).
"""

import json
from datetime import UTC, datetime, timedelta

from tests.unit.factories import (
    COORDINATOR_ID,
    OTHER_COORDINATOR_ID,
    VALID,
    approved_row,
    saved_row,
)

EVENT_ID = "00000000-0000-0000-0000-000000000001"


def assigned_row(**changes):
    """A saved request assigned to the signed-in coordinator."""
    row = saved_row()
    row.update({"coordinator_id": COORDINATOR_ID, **changes})
    return row


def approve(client):
    return client.patch(
        f"/events/{EVENT_ID}/approve",
        json={"coordinatorId": COORDINATOR_ID},
    )


def test_ac1_ac3_approval_changes_status_and_records_audit_metadata(setup):
    """
    Summary: Approving a submitted request sets it to Approved and saves who
        approved it and when.
    AC1: Given an Event Request has status 'Submitted' and is assigned to the
        current Event Coordinator, when they approve it, then the status
        changes to 'Approved'.
    AC3: The approving Event Coordinator's identity and timestamp are recorded
        for auditability.
    Double: cursor.fetchone returns a 'Submitted' event assigned to the
        caller (the lookup), then an 'Approved' row (the update's result)
        [Stub]. We read the UPDATE's parameters to check it saved status
        'Approved', this coordinator's id and a current UTC timestamp, and
        that the transaction was committed [Mock].
    """
    # Arrange (Given)
    client, connection, cursor = setup
    cursor.fetchone.side_effect = [assigned_row(), approved_row()]

    # Act (When)
    response = approve(client)

    # Assert (Then)
    # The decision fields in the response come from the canned approved row;
    # the update parameters below are the real evidence of what was saved.
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
    assert parameters[-1] == EVENT_ID
    decided_at = datetime.fromisoformat(parameters[5])
    assert decided_at.tzinfo is not None
    assert abs(datetime.now(UTC) - decided_at) < timedelta(seconds=5)
    assert json.loads(parameters[7])[-1]["decidedAt"] == parameters[5]
    connection.__exit__.assert_called_once()


def test_ac1_approval_is_rejected_when_event_is_not_submitted(setup):
    """
    Summary: A request that is already approved cannot be approved again.
    AC1: Given an Event Request has status 'Submitted' and is assigned to the
        current Event Coordinator, when they approve it, then the status
        changes to 'Approved'.
    Double: cursor.fetchone returns an event with status 'Approved' assigned
        to the caller [Stub]. We check execute ran once (the lookup only), so
        no UPDATE was sent [Mock].
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = assigned_row(status="Approved")

    # Act (When)
    response = approve(client)

    # Assert (Then)
    assert response.status_code == 409
    assert cursor.execute.call_count == 1


def test_ac2_approval_is_rejected_for_another_coordinators_assignment(setup):
    """
    Summary: A coordinator cannot approve a request assigned to someone else.
    AC2: Given an Event Request is not assigned to the current Event
        Coordinator, the approve action is not available to them.
    Double: cursor.fetchone returns a 'Submitted' event whose coordinator_id
        is a different coordinator [Stub]. We check execute ran once (the
        lookup only), so no UPDATE was sent [Mock].
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = assigned_row(coordinator_id=OTHER_COORDINATOR_ID)

    # Act (When)
    response = approve(client)

    # Assert (Then)
    assert response.status_code == 403
    assert cursor.execute.call_count == 1


def test_ac2_approval_is_rejected_for_an_unassigned_request(setup):
    """
    Summary: A request nobody is assigned to cannot be approved.
    AC2: Given an Event Request is not assigned to the current Event
        Coordinator, the approve action is not available to them.
    Double: cursor.fetchone returns a 'Submitted' event whose coordinator_id
        is empty (nobody assigned) [Stub]. We check execute ran once (the
        lookup only), so no UPDATE was sent [Mock].
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = saved_row()

    # Act (When)
    response = approve(client)

    # Assert (Then)
    assert response.status_code == 403
    assert cursor.execute.call_count == 1


def test_ac3_approval_keeps_earlier_decisions_in_history(setup):
    """
    Summary: Approving adds to the decision history; earlier entries stay.
    AC3: The approving Event Coordinator's identity and timestamp are recorded
        for auditability.
    Double: cursor.fetchone returns a 'Submitted' event assigned to the
        caller whose stored description already holds one earlier 'Rejected'
        decision, then an 'Approved' row [Stub]. We read the decisionHistory
        JSON passed to the UPDATE and check the old entry is first and the new
        'Approved' entry (this coordinator) is last [Mock].
    """
    # Arrange (Given)
    client, _, cursor = setup
    earlier = {
        "status": "Rejected",
        "coordinatorId": OTHER_COORDINATOR_ID,
        "decidedAt": "2026-09-01T00:00:00+00:00",
        "reason": "Dates clash.",
    }
    row = assigned_row()
    row["description"] = json.dumps({
        "_connectsphere": "event-submission-v1",
        "description": VALID["description"],
        "purpose": VALID["purpose"],
        "decisionHistory": [earlier],
    })
    cursor.fetchone.side_effect = [row, approved_row()]

    # Act (When)
    response = approve(client)

    # Assert (Then)
    assert response.status_code == 200
    history = json.loads(cursor.execute.call_args.args[1][7])
    assert history[0] == earlier
    assert history[-1]["status"] == "Approved"
    assert history[-1]["coordinatorId"] == COORDINATOR_ID


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check how the approve route
# behaves when the request is missing, the caller is not signed in, or the
# database is not configured.


def test_supporting_approval_returns_not_found_for_unknown_event(setup):
    """
    Summary: Approving a request that does not exist returns "not found".
    Supporting design check: an unknown event id answers 404
    Double: cursor.fetchone returns None, as if no event has this id [Stub].
        We check execute ran once (the lookup only), so no UPDATE was sent
        [Mock].
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    # Act (When)
    response = approve(client)

    # Assert (Then)
    assert response.status_code == 404
    assert cursor.execute.call_count == 1


def test_supporting_approval_requires_a_signed_in_user(setup):
    """
    Summary: Approving without signing in is refused.
    Supporting design check: a request with no token answers 401
    Double: nothing is stubbed. The PATCH goes through a fresh test client
        with no Authorization header, so it is stopped before reaching the
        database. We check cursor.execute was never called [Mock].
    """
    # Arrange (Given): setup, from fixtures
    client, _, cursor = setup

    # Act (When)
    response = client.application.test_client().patch(
        f"/events/{EVENT_ID}/approve",
        json={"coordinatorId": COORDINATOR_ID},
    )

    # Assert (Then)
    assert response.status_code == 401
    cursor.execute.assert_not_called()


def test_supporting_approval_without_database_configuration_returns_503(setup):
    """
    Summary: If the database is not configured, approve says the service is
        unavailable.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: nothing is stubbed. DATABASE_URL is set to None in the app config
        before an approve PATCH is sent. We check no cursor was opened and
        cursor.execute was never called [Mock].
    """
    client, connection, cursor = setup
    client.application.config["DATABASE_URL"] = None

    response = approve(client)

    assert response.status_code == 503
    assert response.json == {"message": "DATABASE_URL is not configured for Event Service."}
    connection.cursor.assert_not_called()
    cursor.execute.assert_not_called()
