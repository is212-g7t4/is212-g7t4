"""
SCRUM-112: Assign Event Coordinator to Submitted Event

User Story
----------
As an Event Coordinator Lead, I want to assign an Event Coordinator to a
submitted event, so that the event has a main internal point of contact
responsible for coordinating it.

Acceptance Criteria
-------------------
AC1: Given an event request has status 'Submitted', when the Event Coordinator
     Lead views the list of submitted events, then the system displays each
     event with its name, Event Organiser name, proposed date, and current
     assignment status (Unassigned/Assigned).
AC2: Given an event request has status 'Submitted' and is unassigned, when the
     Event Coordinator Lead selects an Event Coordinator from the list of
     available coordinators and confirms the assignment, then the system:
     assigns the selected Event Coordinator to the event; changes the event's
     assignment status to 'Assigned'; records the Event Coordinator Manager's
     identity, the assigned Event Coordinator, and the assignment timestamp.
AC3: Given an event request already has an assigned Event Coordinator, when the
     Event Coordinator Lead selects a different Event Coordinator and confirms
     the reassignment, then the system: replaces the existing Event Coordinator
     with the newly selected one; updates the event's assignment to reflect the
     new Event Coordinator.

Real
----
- User Service's user list: the role filter and the coordinator details it
  returns for the Lead to choose from.
- We check the coordinators returned and that the lookup asked only for the
  requested role.

Doubled
-------
- User records (database): return the users we choose [Stub]; we check how they
  were searched [Mock].
- Sign-in: a test key signs the Lead's token (tests/unit/conftest.py) [Stub].

Not proven
----------
- That the real user table has these columns and role names (NOT COVERED
  ANYWHERE: User Service has no integration tests).
- That the Lead's assignment screen uses this list, and that the assignment
  itself is saved (-> coordinator-assignment-service and event-service tests).
"""

from unittest.mock import MagicMock

import pytest

from app import create_app
from tests.unit.factories import bearer

LEAD_ID = "e7334aa9-eb3a-4c45-84b5-280501b6c109"
ALICE_ID = "5b0b8d3e-1c8c-4c2e-9d6a-2f1e0c7a9b10"
MARCUS_ID = "7912075d-46f5-405b-9af3-05502f42f173"


def user_row(**overrides):
    row = {
        "user_id": ALICE_ID,
        "username": "Alice Tan",
        "email": "alice.tan@connectsphere.example",
        "role": "Event Coordinator",
        "organization": "ConnectSphere",
        "contact_details": "+65 8111 1111",
    }
    row.update(overrides)
    return row


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    client = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"}).test_client()
    client.environ_base["HTTP_AUTHORIZATION"] = bearer(LEAD_ID, "Event Coordinator Lead")["Authorization"]
    return client, cursor


def test_list_users_with_coordinator_role_returns_only_coordinators(setup):
    """
    Summary: The Lead's list of available coordinators contains only Event Coordinators, with the details needed to pick one.
    AC2: Given an event request has status 'Submitted' and is unassigned, when
        the Event Coordinator Lead selects an Event Coordinator from the list
        of available coordinators and confirms the assignment, then the system:
        assigns the selected Event Coordinator to the event; changes the
        event's assignment status to 'Assigned'; records the Event Coordinator
        Manager's identity, the assigned Event Coordinator, and the assignment
        timestamp.
    Double: The user records hold two Event Coordinators [Stub]; we check the
        lookup asked only for that role [Mock].
    """
    client, cursor = setup
    cursor.fetchall.return_value = [user_row(), user_row(user_id=MARCUS_ID, username="Marcus Lim")]

    response = client.get("/users?role=Event+Coordinator")

    assert response.status_code == 200
    assert response.json["users"] == [
        {
            "user_id": ALICE_ID,
            "username": "Alice Tan",
            "email": "alice.tan@connectsphere.example",
            "role": "Event Coordinator",
            "organization": "ConnectSphere",
            "contact_details": "+65 8111 1111",
        },
        {
            "user_id": MARCUS_ID,
            "username": "Marcus Lim",
            "email": "alice.tan@connectsphere.example",
            "role": "Event Coordinator",
            "organization": "ConnectSphere",
            "contact_details": "+65 8111 1111",
        },
    ]
    query, params = cursor.execute.call_args.args
    assert "role = %s" in query
    assert params == ["Event Coordinator"]


def test_list_users_with_missing_details_returns_blanks_not_nulls(setup):
    """
    Summary: A coordinator with no organisation or contact details still appears in the list, with those details blank.
    AC2: Given an event request has status 'Submitted' and is unassigned, when
        the Event Coordinator Lead selects an Event Coordinator from the list
        of available coordinators and confirms the assignment, then the system:
        assigns the selected Event Coordinator to the event; changes the
        event's assignment status to 'Assigned'; records the Event Coordinator
        Manager's identity, the assigned Event Coordinator, and the assignment
        timestamp.
    Double: The user records hold a coordinator with no organisation or
        contact details [Stub].
    """
    client, cursor = setup
    cursor.fetchall.return_value = [user_row(organization=None, contact_details=None)]

    response = client.get("/users?role=Event+Coordinator")

    assert response.json["users"][0]["organization"] == ""
    assert response.json["users"][0]["contact_details"] == ""


def test_list_users_without_role_returns_everyone(setup):
    """
    Summary: Without a role, every user is listed, so the role filter is what narrows the Lead's choice.
    AC2: Given an event request has status 'Submitted' and is unassigned, when
        the Event Coordinator Lead selects an Event Coordinator from the list
        of available coordinators and confirms the assignment, then the system:
        assigns the selected Event Coordinator to the event; changes the
        event's assignment status to 'Assigned'; records the Event Coordinator
        Manager's identity, the assigned Event Coordinator, and the assignment
        timestamp.
    Double: The user records hold a coordinator and a Lead [Stub]; we check
        the lookup applied no role filter [Mock].
    """
    client, cursor = setup
    cursor.fetchall.return_value = [user_row(), user_row(user_id=LEAD_ID, role="Event Coordinator Lead")]

    response = client.get("/users")

    assert [user["role"] for user in response.json["users"]] == ["Event Coordinator", "Event Coordinator Lead"]
    query, params = cursor.execute.call_args.args
    assert "WHERE" not in query
    assert params == []
