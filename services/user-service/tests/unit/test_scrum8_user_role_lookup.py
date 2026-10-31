"""
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
- Looking up one user: their role (which other services use to decide what the
  user may do), "not found" for unknown users, and malformed ids.
- We check the role returned and whether the user records were searched.

Doubled
-------
- User records (database): hold the user, or none [Stub]; we check the search
  [Mock].
- Sign-in: a test key signs the caller's token (tests/unit/conftest.py) [Stub].

Not proven
----------
- That other services act correctly on the role returned (-> each service's
  SCRUM-9 and SCRUM-10 access tests).
"""

from unittest.mock import MagicMock

import pytest

from app import create_app
from tests.unit.factories import bearer

CALLER_ID = "5b0b8d3e-1c8c-4c2e-9d6a-2f1e0c7a9b10"
LEAD_ID = "e7334aa9-eb3a-4c45-84b5-280501b6c109"


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    client = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"}).test_client()
    client.environ_base["HTTP_AUTHORIZATION"] = bearer(CALLER_ID, "Event Coordinator")["Authorization"]
    return client, cursor


def test_get_user_returns_their_role(setup):
    """
    Summary: Looking up a user returns their role, which other services use to decide what that user may do.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event.
    Double: The user records hold an Event Coordinator Lead [Stub]; we check
        the lookup asked for that user [Mock].
    """
    client, cursor = setup
    cursor.fetchone.return_value = {
        "user_id": LEAD_ID,
        "username": "Priya Nair",
        "email": "priya.nair@connectsphere.example",
        "role": "Event Coordinator Lead",
        "organization": "ConnectSphere",
        "contact_details": "+65 8222 2222",
    }

    response = client.get(f"/users/{LEAD_ID}")

    assert response.status_code == 200
    assert response.json["user_id"] == LEAD_ID
    assert response.json["role"] == "Event Coordinator Lead"
    assert cursor.execute.call_args.args[1] == [LEAD_ID]


def test_get_user_when_user_unknown_returns_404(setup):
    """
    Summary: An unknown user has no role, so the lookup says "not found" rather than guessing one.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event.
    Double: The user records have no such user [Stub].
    """
    client, cursor = setup
    cursor.fetchone.return_value = None

    response = client.get(f"/users/{LEAD_ID}")

    assert response.status_code == 404
    assert response.json == {"message": "User not found."}


def test_get_user_with_malformed_id_returns_404_without_lookup(setup):
    """
    Summary: A malformed user id is answered as "not found" without searching the user records.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event.
    Double: We check the user records are never searched [Mock].
    """
    client, cursor = setup

    response = client.get("/users/not-a-uuid")

    assert response.status_code == 404
    cursor.execute.assert_not_called()
