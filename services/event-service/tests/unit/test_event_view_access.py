"""
SCRUM-9: Role-Based Access Control for Events

User Story
----------
As a registered user, I want to view only information appropriate to my role
and relationship to an event, so that I can access the information relevant to
my responsibilities without viewing restricted information.

Acceptance Criteria
-------------------
AC1: Given an authenticated user is permitted to view information based on
     their role and relationship to the event, when they access that
     information, then the information is made available to them.
AC2: Given an authenticated user's role does not permit them to view particular
     information, when they attempt to access that information, then access is
     denied.
AC3: Given an authenticated user's relationship to an event does not permit
     them to view that event's information, when they attempt to access the
     information, then access is denied.
AC4: Given a user is permitted to view information for one event but does not
     have the required relationship to another event, when they attempt to view
     information for both events, then they can only view the information for
     which they have the required access.
AC5: Given two authenticated users have different roles or relationships to the
     same event, when they access information relating to that event, then each
     user can only view the information permitted by their own role and
     relationship to the event.

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
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.models import FIELDS
from tests.unit.factories import signed_in

EVENT_ID = "00000000-0000-0000-0000-000000000001"
OTHER_EVENT_ID = "00000000-0000-0000-0000-000000000002"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OTHER_COORDINATOR_ID = "22222222-2222-4222-8222-222222222222"
ORGANISER_ID = "33333333-3333-4333-8333-333333333333"
OTHER_ORGANISER_ID = "44444444-4444-4444-8444-444444444444"
LEAD = "Event Coordinator Lead"


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), cursor


def event_row(event_id=EVENT_ID, coordinator_id=COORDINATOR_ID):
    row = {column: "" for column in FIELDS.values()}
    row.update(
        event_id=event_id, status="Under Review", coordinator_id=coordinator_id,
        organiser_id=ORGANISER_ID, expected_attendance=25,
        submission_date=datetime(2026, 9, 15, tzinfo=UTC),
        preferred_start_date=datetime(2030, 10, 1, 9), preferred_end_date=datetime(2030, 10, 1, 17),
        description=json.dumps({
            "_connectsphere": "event-submission-v1", "description": "d", "purpose": "p",
            "actionHistory": [{"note": "internal"}],
        }),
    )
    return row


# AC1 ----

def test_assigned_coordinator_sees_their_event(setup):
    """
    Summary: The coordinator assigned to an event may open it.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: Stub (cursor returns an event assigned to this coordinator)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row()

    # Act (When)
    response = signed_in(client, COORDINATOR_ID, "Event Coordinator").get(f"/events/{EVENT_ID}")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["id"] == EVENT_ID


def test_lead_sees_the_unassigned_queue(setup):
    """
    Summary: The Lead's role permits the unassigned queue.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: Stub (cursor returns one unassigned event)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = [event_row(coordinator_id=None)]

    # Act (When)
    response = signed_in(client, role=LEAD).get("/events/unassigned")

    # Assert (Then)
    assert response.status_code == 200
    assert len(response.json["events"]) == 1


# AC2 ----

@pytest.mark.parametrize(
    "path, role",
    [
        ("/events/unassigned", "Event Coordinator"),
        ("/events/active", "Attendee"),
        ("/events/registration", "Event Organiser"),
        ("/events/summaries", "Attendee"),
        ("/events/attendee-summaries", "Event Organiser"),
        ("/events/overlapping", "Attendee"),
    ],
)
def test_a_role_outside_the_routes_allowlist_is_denied(setup, path, role):
    """
    Summary: Routes that were open to any signed-in user now refuse the wrong role.
    AC2: Given an authenticated user's role does not permit them to view
        particular information, when they attempt to access that information,
        then access is denied.
    Double: Mock (cursor.execute asserted not called, so no query is sent)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = signed_in(client, role=role).get(path)

    # Assert (Then)
    assert response.status_code == 403
    cursor.execute.assert_not_called()


# AC3 ----

def test_coordinator_not_assigned_to_the_event_is_denied(setup):
    """
    Summary: A coordinator's relationship to the event decides access.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to view that event's information, when they attempt to access the
        information, then access is denied.
    Double: Stub (cursor returns an event assigned to a different coordinator)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=OTHER_COORDINATOR_ID)

    # Act (When)
    response = signed_in(client, COORDINATOR_ID, "Event Coordinator").get(f"/events/{EVENT_ID}")

    # Assert (Then)
    assert response.status_code == 403


def test_organiser_cannot_open_an_event_someone_else_created(setup):
    """
    Summary: An organiser sees only the events they created.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to view that event's information, when they attempt to access the
        information, then access is denied.
    Double: Stub (cursor returns an event created by a different organiser)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row()

    # Act (When)
    response = signed_in(client, OTHER_ORGANISER_ID, "Event Organiser").get(
        f"/events/{EVENT_ID}?organiserId={OTHER_ORGANISER_ID}"
    )

    # Assert (Then)
    assert response.status_code == 403


# AC4 ----

def test_coordinator_gets_only_the_event_they_are_assigned_to(setup):
    """
    Summary: Asking for both events returns one and refuses the other.
    AC4: Given a user is permitted to view information for one event but does
        not have the required relationship to another event, when they attempt
        to view information for both events, then they can only view the
        information for which they have the required access.
    Double: Stub (cursor returns two events in turn: one assigned to this coordinator, one to another)
    """
    # Arrange (Given)
    client, cursor = setup
    coordinator = signed_in(client, COORDINATOR_ID, "Event Coordinator")
    cursor.fetchone.side_effect = [event_row(), event_row(OTHER_EVENT_ID, OTHER_COORDINATOR_ID)]

    allowed = coordinator.get(f"/events/{EVENT_ID}")

    # Act (When)
    refused = coordinator.get(f"/events/{OTHER_EVENT_ID}")

    # Assert (Then)
    assert (allowed.status_code, refused.status_code) == (200, 403)


# AC5 ----

def test_lead_and_venue_staff_get_different_views_of_the_same_event(setup):
    """
    Summary: Staff see the event but not the organiser or internal action history.
    AC5: Given two authenticated users have different roles or relationships to
        the same event, when they access information relating to that event,
        then each user can only view the information permitted by their own
        role and relationship to the event.
    Double: Stub (cursor returns one event; the Lead's and Venue Staff's response bodies are compared)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row()
    url = f"/events/{EVENT_ID}?viewerRole=1"

    lead = signed_in(client, role=LEAD).get(url).json

    # Act (When)
    staff = signed_in(client, role="Venue Staff").get(url).json

    # Assert (Then)
    assert lead["organiserId"] == ORGANISER_ID and lead["actionHistory"]
    assert staff["id"] == EVENT_ID
    for hidden in ("organiserId", "actionHistory", "decision", "decisionHistory"):
        assert hidden not in staff
