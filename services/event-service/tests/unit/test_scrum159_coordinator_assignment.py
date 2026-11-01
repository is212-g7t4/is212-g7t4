"""
SCRUM-159: Assign Coordinator to an Event

User Story
----------
As an Event Coordinator Lead, I want to assign an Event Coordinator to an
unassigned event, so that the event has a main point of contact.

Acceptance Criteria
-------------------
AC1: Given an unassigned submitted event, when the Lead assigns a coordinator
     to the event, then the system:
     - assigns the selected coordinator to the event
     - removes the event from the unassigned queue
     - the current coordinator, who assigned them, and when the assignment was
       done are recorded in the event's detail page
AC2: Given an Event Coordinator who is not the Lead, they should not be able to
     see any 'Reassign' option or button

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
- AC2 (no 'Reassign' button for a non-Lead) is a UI property, left to the
  frontend tests.
- That the notification outbox rows are delivered (-> Notification Service
  tests and the E2E journeys).
"""

from datetime import UTC, datetime

from app.models import serialize
from tests.unit.factories import (
    COORDINATOR_ID,
    LEAD_ID,
    saved_row,
)


def test_ac1_assigning_a_coordinator_records_coordinator_assigner_and_time_and_moves_the_event_to_under_review(setup):
    """
    Summary: Assigning a coordinator to a Submitted, unassigned event locks the row, then one UPDATE sets coordinator_id, assigned_by, assigned_at = now() and moves the status to 'Under Review' (which takes it out of the unassigned queue); the response carries the coordinator, assigner, time and a null previousCoordinatorId.
    AC1: Given an unassigned submitted event, when the Lead assigns a
        coordinator to the event, then the system:
        - assigns the selected coordinator to the event
        - removes the event from the unassigned queue
        - the current coordinator, who assigned them, and when the assignment
          was done are recorded in the event's detail page
    Double: Stub (cursor.fetchone returns the locked row {coordinator_id None, status 'Submitted'}, then the updated 'Under Review' row),
        Mock (the FOR UPDATE lookup and the UPDATE's SQL and parameters asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    assigned = saved_row()
    assigned["coordinator_id"] = COORDINATOR_ID
    assigned["status"] = "Under Review"
    assigned["assigned_by"] = LEAD_ID
    assigned["assigned_at"] = datetime(2026, 10, 16, 2, 15, tzinfo=UTC)
    cursor.fetchone.side_effect = [{"coordinator_id": None, "status": "Submitted"}, assigned]

    # Act (When)
    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001",
        json={"assignedCoordinatorId": COORDINATOR_ID, "assignedBy": LEAD_ID},
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["coordinatorId"] == COORDINATOR_ID
    assert response.json["status"] == "Under Review"
    assert response.json["assignedBy"] == LEAD_ID
    assert response.json["assignedAt"] == "2026-10-16T02:15:00+00:00"
    assert response.json["previousCoordinatorId"] is None
    lock_query, lock_parameters = cursor.execute.call_args_list[0].args
    assert "FOR UPDATE" in lock_query
    assert lock_parameters == ["00000000-0000-0000-0000-000000000001"]
    query, parameters = cursor.execute.call_args_list[1].args
    assert "previous_coordinator_id = coordinator_id" in query
    assert "coordinator_id = %s" in query
    assert "assigned_by = %s" in query
    assert "assigned_at = now()" in query
    assert "status = CASE WHEN status = 'Submitted' THEN 'Under Review'" in query
    assert "RETURNING" in query and "assigned_by, assigned_at, previous_coordinator_id" in query
    assert parameters == [COORDINATOR_ID, LEAD_ID, "00000000-0000-0000-0000-000000000001"]


def test_assign_coordinator_to_an_unknown_event_answers_404(setup):
    """
    Summary: Assigning a coordinator to an id that matches no event answers 404.
    Supporting design check: no acceptance criterion covers a missing event;
        the route must answer 404 rather than assign
    Double: Stub (cursor.fetchone returns None for the locking lookup)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    # Act (When)
    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001",
        json={"assignedCoordinatorId": COORDINATOR_ID, "assignedBy": LEAD_ID},
    )

    # Assert (Then)
    assert response.status_code == 404


def test_unassigned_event_serializes_with_no_assigner_assignment_time_or_previous_coordinator():
    """
    Summary: serialize() on a row that was never assigned returns null assignedBy, assignedAt and previousCoordinatorId, so an unassigned event shows no assignment record.
    Supporting design check: the assignment fields shown on the detail page
        are empty, not made up, until a Lead assigns someone
    Double: None (serialize is called directly on saved_row(); no route, cursor or token is involved)
    """
    # Act (When)
    body = serialize(saved_row())

    # Assert (Then)
    assert body["assignedBy"] is None
    assert body["assignedAt"] is None
    assert body["previousCoordinatorId"] is None
