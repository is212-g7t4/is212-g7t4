"""
SCRUM-112: Assign Event Coordinator to Submitted Event

User Story
----------
As an Event Coordinator Manager, I want to assign an Event Coordinator to a
submitted event, so that the event has a main internal point of contact
responsible for coordinating it.

Acceptance Criteria
-------------------
AC1: Given an event request has status 'Submitted', when the Event Coordinator
     Manager views the list of submitted events, then the system displays each
     event with its name, Event Organiser name, proposed date, and current
     assignment status (Unassigned/Assigned).
AC2: Given an event request has status 'Submitted' and is unassigned, when the
     Event Coordinator Manager selects an Event Coordinator from the list of
     available coordinators and confirms the assignment, then the system:
     - Assigns the selected Event Coordinator to the event
     - Changes the event's assignment status to 'Assigned'
     - Records the Event Coordinator Manager's identity, the assigned Event
       Coordinator, and the assignment timestamp
AC3: Given an event request already has an assigned Event Coordinator, when the
     Event Coordinator Manager selects a different Event Coordinator and
     confirms the reassignment, then the system:
     - Replaces the existing Event Coordinator with the newly selected one
     - Updates the event's assignment to reflect the new Event Coordinator

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
- GET /users and GET /users/<id>: the role filter, the SQL each request builds,
  UUID validation and the profile serialisation run for real.
- Assertions are on the returned users and the query parameters sent to the
  database.

Doubled
-------
- psycopg2.connect: Stub - the cursor returns canned User rows; its execute()
  call is inspected to prove the role filter reaches the query.

Not proven
----------
- That the real public."User" table has these columns and the role filter
  matches stored role strings (NOT COVERED ANYWHERE: user-service has no
  integration tests).
- That Coordinator Assignment Service really uses this list as its "available
  coordinators" (-> coordinator-assignment-service unit tests).
"""
from unittest.mock import MagicMock

import pytest

from app import create_app
from tests.unit.factories import bearer

ALICE_ID = "e7334aa9-eb3a-4c45-84b5-280501b6c109"
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
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    client = app.test_client()
    client.environ_base["HTTP_AUTHORIZATION"] = bearer(ALICE_ID, "Event Coordinator")["Authorization"]
    return client, connection, cursor


def test_list_users_without_filter_returns_every_user(setup):
    """
    Summary: The full user list is returned when no role is asked for.
    AC2: the list of coordinators the Lead chooses from comes from this lookup
    Double: Stub (cursor returns two user rows)
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = [
        user_row(),
        user_row(user_id=MARCUS_ID, username="Marcus Lim"),
    ]

    response = client.get("/users")

    assert response.status_code == 200
    assert len(response.json["users"]) == 2
    assert "manager_id" not in response.json["users"][1]
    query, params = cursor.execute.call_args.args
    assert "WHERE" not in query
    assert params == []


def test_list_users_with_role_filter_queries_only_that_role(setup):
    """
    Summary: Asking for a role returns only users with that role, so the Lead picks from real coordinators.
    AC2: the list of available coordinators is the users with a coordinator
        role
    Double: Stub (cursor returns one coordinator row)
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = [user_row()]

    response = client.get("/users?role=Event+Coordinator")

    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert "role = %s" in query
    assert params == ["Event Coordinator"]


def test_get_user_when_user_is_lead_returns_lead_role(setup):
    """
    Summary: A single user lookup returns their role, which other services use to decide what they may do.
    SCRUM-8 AC2: Given a system user successfully authenticates, when they
        access protected information or functionality, then their access is
        evaluated according to their role and relationship to the relevant
        event.
    Double: Stub (cursor returns a Lead row)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = user_row(role="Event Coordinator Lead")

    # Act (When)
    response = client.get(f"/users/{ALICE_ID}")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["role"] == "Event Coordinator Lead"
    assert "manager_id" not in response.json


def test_get_user_when_user_unknown_returns_404(setup):
    """
    Summary: Looking up a user who does not exist says so.
    SCRUM-8 AC2: Given a system user successfully authenticates, when they
        access protected information or functionality, then their access is
        evaluated according to their role and relationship to the relevant
        event.
    Double: Stub (cursor returns no row)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    # Act (When)
    response = client.get(f"/users/{ALICE_ID}")

    # Assert (Then)
    assert response.status_code == 404


def test_get_user_with_malformed_id_returns_404_without_query(setup):
    """
    Summary: A malformed user id is answered as not found without touching the database.
    SCRUM-8 AC2: Given a system user successfully authenticates, when they
        access protected information or functionality, then their access is
        evaluated according to their role and relationship to the relevant
        event.
    Double: Mock (asserts the cursor is never executed)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = client.get("/users/not-a-uuid")

    # Assert (Then)
    assert response.status_code == 404
    cursor.execute.assert_not_called()
