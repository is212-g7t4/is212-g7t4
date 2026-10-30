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

SCRUM-160: Reassign an Event

User Story
----------
As an Event Coordinator Lead, I want to reassign an event to a different
coordinator, so that work can move when responsibilities or availability
change.

Acceptance Criteria
-------------------
AC1: Given an event with an assigned coordinator that is not completed or
     rejected, when the Lead selects a different coordinator and confirms:
     - the new coordinator replaces the previous one
     - the previous coordinator loses access to manage the event
     - the Lead, previous coordinator, new coordinator, and timestamp are
       recorded in the event's detail page
AC2: Given the Lead selects the current coordinator, then the system rejects it
     as no change.

SCRUM-158: View Unassigned Event Queue

User Story
----------
As an Event Coordinator Lead, I want to view a queue of submitted event
requests that have not yet been assigned, so that I can see which requests need
a coordinator.

Acceptance Criteria
-------------------
AC1: Queue shows only submitted events with no assigned coordinator
AC2: Each entry shows: event name, organiser name, proposed date/time, expected
     attendance, submission date
AC3: An event leaves the queue once a coordinator is assigned
AC4: Event Coordinators and other roles cannot access the queue

SCRUM-8: User Authentication and Authorization

User Story
----------
As a system user, I want to securely access the system, so that I can use the
information and functionality available to me.

Acceptance Criteria
-------------------
AC1: Given a system user has not been successfully authenticated, when they
     attempt to access protected information or functionality, then access is
     denied.
AC2: Given a system user successfully authenticates, when they access protected
     information or functionality, then their access is evaluated according to
     their role and relationship to the relevant event.
AC3: Given a system user's authentication attempt is unsuccessful, when the
     authentication attempt is completed, then they remain unable to access
     protected information or functionality.

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

from datetime import UTC, datetime

import pytest

from app.models import serialize
from tests.unit.factories import (
    COORDINATOR_ID,
    LEAD_ID,
    OTHER_COORDINATOR_ID,
    saved_row,
)


def test_assign_coordinator_updates_event(setup):
    """
    Summary: Assigning records the coordinator, the assigner and the time, and moves the event to 'Under Review'.
    AC1: Given an unassigned submitted event, when the Lead assigns a
        coordinator to the event, then the system:
        - assigns the selected coordinator to the event
        - removes the event from the unassigned queue
        - the current coordinator, who assigned them, and when the assignment
          was done are recorded in the event's detail page
    SCRUM-158 AC3: An event leaves the queue once a coordinator is assigned
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


@pytest.mark.parametrize("status", [
    "Under Review", "Approved", "Pending Safety Check", "Confirmed", "Safety Changes Requested",
])
def test_reassign_replaces_the_coordinator_and_records_the_previous_one(setup, status):
    """
    Summary: Reassigning an open event records the previous and new coordinators.
    SCRUM-160 AC1: Given an event with an assigned coordinator that is not
        completed or rejected, when the Lead selects a different coordinator
        and confirms:
        - the new coordinator replaces the previous one
        - the previous coordinator loses access to manage the event
        - the Lead, previous coordinator, new coordinator, and timestamp are
          recorded in the event's detail page
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    reassigned = saved_row()
    reassigned.update(
        status=status, coordinator_id=OTHER_COORDINATOR_ID, previous_coordinator_id=COORDINATOR_ID,
        assigned_by=LEAD_ID, assigned_at=datetime(2026, 10, 16, 13, 5, tzinfo=UTC),
    )
    cursor.fetchone.side_effect = [{"coordinator_id": COORDINATOR_ID, "status": status}, reassigned]

    # Act (When)
    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001",
        json={"assignedCoordinatorId": OTHER_COORDINATOR_ID, "assignedBy": LEAD_ID},
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["coordinatorId"] == OTHER_COORDINATOR_ID
    assert response.json["previousCoordinatorId"] == COORDINATOR_ID
    assert response.json["assignedBy"] == LEAD_ID
    assert response.json["assignedAt"] == "2026-10-16T13:05:00+00:00"
    assert response.json["status"] == status
    writes = [call for call in cursor.execute.call_args_list if 'UPDATE public."Event"' in call.args[0]]
    assert len(writes) == 1
    assert writes[0].args[1] == [OTHER_COORDINATOR_ID, LEAD_ID, "00000000-0000-0000-0000-000000000001"]


@pytest.mark.parametrize("status", ["Rejected", "Cancelled", "Clarification Requested"])
def test_reassign_is_blocked_for_closed_events(setup, status):
    """
    Summary: Closed events, and events with an open clarification, keep their coordinator.
    SCRUM-160 AC1: Given an event with an assigned coordinator that is not
        completed or rejected, when the Lead selects a different coordinator
        and confirms:
        - the new coordinator replaces the previous one
        - the previous coordinator loses access to manage the event
        - the Lead, previous coordinator, new coordinator, and timestamp are
          recorded in the event's detail page
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = {"coordinator_id": COORDINATOR_ID, "status": status}

    # Act (When)
    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001",
        json={"assignedCoordinatorId": OTHER_COORDINATOR_ID, "assignedBy": LEAD_ID},
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["message"] == f"A {status} event can't be reassigned."
    assert cursor.execute.call_count == 1  # the lock only; nothing updated


def test_reassign_to_the_current_coordinator_is_rejected_as_no_change(setup):
    """
    Summary: Reassigning to the current coordinator is refused as no change.
    SCRUM-160 AC2: Given the Lead selects the current coordinator, then the
        system rejects it as no change.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = {"coordinator_id": COORDINATOR_ID, "status": "Under Review"}

    # Act (When)
    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001",
        json={"assignedCoordinatorId": COORDINATOR_ID, "assignedBy": LEAD_ID},
    )

    # Assert (Then)
    assert response.status_code == 409
    assert "No change" in response.json["message"]
    assert cursor.execute.call_count == 1


def test_assign_coordinator_requires_a_signed_in_assigner(setup):
    """
    Summary: Assignment needs a signed-in assigner.
    SCRUM-8 AC1: Given a system user has not been successfully authenticated,
        when they attempt to access protected information or functionality,
        then access is denied.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    _, _, cursor = setup
    client = setup[0].application.test_client()

    # Act (When)
    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001",
        json={"assignedCoordinatorId": COORDINATOR_ID},
    )

    # Assert (Then)
    assert response.status_code == 401
    cursor.execute.assert_not_called()


def test_assign_coordinator_returns_not_found(setup):
    """
    Summary: Assigning a coordinator to a missing event returns 404.
    AC1: Given an unassigned submitted event, when the Lead assigns a
        coordinator to the event, then the system:
        - assigns the selected coordinator to the event
        - removes the event from the unassigned queue
        - the current coordinator, who assigned them, and when the assignment
          was done are recorded in the event's detail page
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_unassigned_event_serializes_without_assignment_record():
    """
    Summary: An event never assigned has no assigner or assignment time.
    AC1: Given an unassigned submitted event, when the Lead assigns a
        coordinator to the event, then the system:
        - assigns the selected coordinator to the event
        - removes the event from the unassigned queue
        - the current coordinator, who assigned them, and when the assignment
          was done are recorded in the event's detail page
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Act (When)
    body = serialize(saved_row())

    # Assert (Then)
    assert body["assignedBy"] is None
    assert body["assignedAt"] is None
    assert body["previousCoordinatorId"] is None
