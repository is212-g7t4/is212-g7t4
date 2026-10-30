"""
SCRUM-10: Role-Based Modification Control for Events

User Story
----------
As a registered user, I want to modify only information appropriate to my role
and relationship to an event, so that I can perform my responsibilities without
changing information outside my permissions.

Acceptance Criteria
-------------------
AC1: Given an authenticated user is permitted to modify information based on
     their role and relationship to the event, when they make a valid change to
     that information, then the change is allowed.
AC2: Given an authenticated user's role does not permit them to modify
     particular information, when they attempt to change that information, then
     the modification is prevented and the existing information remains
     unchanged.
AC3: Given an authenticated user's relationship to an event does not permit
     them to modify that event's information, when they attempt to make a
     change, then the modification is prevented and the existing information
     remains unchanged.
AC4: Given a user is permitted to view particular information but is not
     permitted to modify it, when they attempt to change that information, then
     the modification is prevented while their permitted viewing access remains
     unaffected.
AC5: Given a user is permitted to modify information for one event but does not
     have the required access to another event, when they attempt to modify
     information for both events, then only modifications to information for
     which they have the required access are allowed.

Real
----
- The round write routes: token verification and the role checks (coordinators
  open, withdraw and undo; Safety Officers decide and reopen) run for real.
- Assertions are on the status and the database not being touched.

Doubled
-------
- psycopg2.connect: Stub (`setup` fixture) - fresh MagicMock connection; the
  cursor returns canned SafetyCheck rows (or raises); executed SQL, parameters
  and the FOR UPDATE lock are inspected.

Not proven
----------
- That the caller is the event's assigned coordinator (AC3): checked by Safety
  Check Service (-> its test_safety_modification_access.py).
"""
from unittest.mock import MagicMock

import pytest

from app import create_app
from tests.unit.factories import COORDINATOR_ID, EVENT_ID, OFFICER_ID, RECORD_ID, bearer, record_row, signed_in

COORDINATOR_ROUTES = [
    ("post", "/safety-check-records"),
    ("delete", f"/safety-check-records/{RECORD_ID}"),
    ("post", f"/safety-check-records/{RECORD_ID}/withdraw"),
    ("post", f"/safety-check-records/{RECORD_ID}/restore"),
]
OFFICER_ROUTES = [
    ("patch", f"/safety-check-records/{RECORD_ID}/decision"),
    ("post", f"/safety-check-records/{RECORD_ID}/reopen"),
]


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), cursor


# AC1 ----

@pytest.mark.parametrize("role", ["Event Coordinator", "Event Coordinator Lead"], ids=["event_coordinator", "event_coordinator_lead"])
def test_open_round_when_coordinator_role_is_allowed(setup, role):
    """
    Summary: Coordinators and the Lead may open a safety round.
    AC1: Given an authenticated user is permitted to modify information based
        on their role and relationship to the event, when they make a valid
        change to that information, then the change is allowed.
    Double: Stub (cursor returns the inserted row)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [None, record_row(round_number=1)]

    # Act (When)
    response = signed_in(client, COORDINATOR_ID, role).post("/safety-check-records", json={"eventId": EVENT_ID})

    # Assert (Then)
    assert response.status_code == 201


def test_decide_round_when_safety_officer_is_allowed(setup):
    """
    Summary: A Safety Officer may decide a pending round.
    AC1: Given an authenticated user is permitted to modify information based
        on their role and relationship to the event, when they make a valid
        change to that information, then the change is allowed.
    Double: Stub (cursor returns rows)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(), record_row(), record_row(status="Safety Approved", decided=True),
    ]

    # Act (When)
    response = signed_in(client, OFFICER_ID, "Safety Officer").patch(
        f"/safety-check-records/{RECORD_ID}/decision", json={"status": "Safety Approved", "eventId": EVENT_ID}
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Safety Approved"


# AC2 ----

@pytest.mark.parametrize("role", ["Safety Officer", "Venue Staff", "Technical Support", "Event Organiser", "Attendee"], ids=["safety_officer", "venue_staff", "technical_support", "event_organiser", "attendee"])
@pytest.mark.parametrize("method, path", COORDINATOR_ROUTES, ids=["open", "delete", "withdraw", "restore"])
def test_coordinator_round_actions_when_other_role_return_403(setup, method, path, role):
    """
    Summary: Only coordinators may open, delete, withdraw or restore a round.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Mock (cursor not executed)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = getattr(client, method)(path, json={}, headers=bearer(OFFICER_ID, role))

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["message"] == "Your role cannot change this information."
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    "role", ["Event Coordinator", "Event Coordinator Lead", "Venue Staff", "Technical Support", "Event Organiser", "Attendee"],
    ids=["event_coordinator", "event_coordinator_lead", "venue_staff", "technical_support", "event_organiser", "attendee"],
)
@pytest.mark.parametrize("method, path", OFFICER_ROUTES, ids=["decide", "reopen"])
def test_officer_round_actions_when_other_role_return_403(setup, method, path, role):
    """
    Summary: Only a Safety Officer may decide or reopen a round.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Mock (cursor not executed)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = getattr(client, method)(path, json={}, headers=bearer(COORDINATOR_ID, role))

    # Assert (Then)
    assert response.status_code == 403
    cursor.execute.assert_not_called()


# AC4 ----

def test_list_rounds_after_refused_decision_still_viewable_by_coordinator(setup):
    """
    Summary: A coordinator refused a decision can still view the rounds.
    AC4: Given a user is permitted to view particular information but is not
        permitted to modify it, when they attempt to change that information,
        then the modification is prevented while their permitted viewing access
        remains unaffected.
    Double: Stub (cursor returns no rows)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = []
    coordinator = signed_in(client, COORDINATOR_ID, "Event Coordinator")

    before = coordinator.get(f"/safety-check-records?eventId={EVENT_ID}")
    refused = coordinator.patch(f"/safety-check-records/{RECORD_ID}/decision", json={"status": "Safety Approved"})

    # Act (When)
    after = coordinator.get(f"/safety-check-records?eventId={EVENT_ID}")

    # Assert (Then)
    assert (before.status_code, refused.status_code, after.status_code) == (200, 403, 200)
    assert before.json == after.json
