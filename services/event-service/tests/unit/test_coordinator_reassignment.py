"""
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
- psycopg2.connect: Stub (setup fixture in tests/unit/conftest.py) - a
  MagicMock connection whose cursor returns canned rows; Mock - its execute
  calls are asserted to prove what was (or was not) written.
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

from tests.unit.factories import (
    COORDINATOR_ID,
    LEAD_ID,
    OTHER_COORDINATOR_ID,
    saved_row,
)


@pytest.mark.parametrize("status", [
    "Under Review", "Approved", "Pending Safety Check", "Confirmed", "Safety Changes Requested",
])
def test_ac1_reassigning_an_open_event_replaces_the_coordinator_and_records_the_previous_one(setup, status):
    """
    Summary: For each open status, reassigning to a different coordinator answers 200 with the new coordinatorId, the previousCoordinatorId, the assigner and time, keeps the event's status, and runs exactly one UPDATE with the new coordinator, the Lead and the event id.
    AC1: Given an event with an assigned coordinator that is not completed or
        rejected, when the Lead selects a different coordinator and confirms:
        - the new coordinator replaces the previous one
        - the previous coordinator loses access to manage the event
        - the Lead, previous coordinator, new coordinator, and timestamp are
          recorded in the event's detail page
    Double: Stub (cursor.fetchone returns the locked row for the old coordinator in that status, then the reassigned row),
        Mock (the one UPDATE public."Event" call's parameters asserted)
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
def test_ac1_reassigning_a_rejected_cancelled_or_clarification_requested_event_answers_409(setup, status):
    """
    Summary: An event that is Rejected, Cancelled or waiting on a clarification answers 409 "A <status> event can't be reassigned." and only the locking lookup runs, so its coordinator is unchanged.
    AC1: Given an event with an assigned coordinator that is not completed or
        rejected, when the Lead selects a different coordinator and confirms:
        - the new coordinator replaces the previous one
        - the previous coordinator loses access to manage the event
        - the Lead, previous coordinator, new coordinator, and timestamp are
          recorded in the event's detail page
    Double: Stub (cursor.fetchone returns the locked row with a coordinator and the given status),
        Mock (cursor.execute call_count is 1: the lock only)
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


def test_ac2_reassigning_to_the_current_coordinator_answers_409_no_change(setup):
    """
    Summary: Choosing the coordinator the event already has answers 409 with a "No change" message and only the locking lookup runs.
    AC2: Given the Lead selects the current coordinator, then the system
        rejects it as no change.
    Double: Stub (cursor.fetchone returns the locked row already assigned to COORDINATOR_ID, 'Under Review'),
        Mock (cursor.execute call_count is 1: the lock only)
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
