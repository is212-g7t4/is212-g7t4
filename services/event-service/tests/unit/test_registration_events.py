"""
SCRUM-36: View Events Open for Registration

User Story
----------
As an Attendee, I want to view information about confirmed events that are open
for registration, so that I can decide whether to register for an event.

Acceptance Criteria
-------------------
AC1: The Attendee can view a list of confirmed events that are open for
     registration.
AC2: For each event in the list, the Attendee can see Event name, date and
     time, venue, description/purpose, registration deadline (if applicable),
     current registration status (open/closed/full)
AC3: The Attendee can click on an event to view detailed information including
     full event description, programme/agenda, venue details (location,
     facilities, accessibility), registration requirements and instructions,
     contact information for enquiries
AC4: Given there are no confirmed events open for registration, when the
     Attendee views the event list, then the system displays a message
     notifying them of this

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


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client(), role="Attendee"), cursor


def confirmed_row():
    row = {column: "" for column in FIELDS.values()}
    row.update(
        event_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        event_name="Community Workshop",
        description=json.dumps({
            "_connectsphere": "event-submission-v1",
            "description": "A practical workshop",
            "purpose": "Learning",
        }),
        preferred_start_date=datetime(2026, 11, 10, 9),
        preferred_end_date=datetime(2026, 11, 10, 12),
        expected_attendance=30,
        status="Confirmed",
        submission_date=datetime(2026, 10, 1, 8, tzinfo=UTC),
        coordinator_id=None,
        organiser_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    )
    return row


def test_ac1_registration_list_returns_confirmed_events_whether_or_not_assigned(setup):
    """
    Summary: GET /events/registration returns a Confirmed event to an Attendee, and its SQL filters on status = 'Confirmed' only, never on coordinator.
    AC1: The Attendee can view a list of confirmed events that are open for
        registration.
    Double: Stub (cursor.fetchall returns one 'Confirmed' row with no coordinator),
        Mock (cursor.execute query text asserted: status = 'Confirmed' and no coordinator_id in the WHERE clause)
    """
    client, cursor = setup
    cursor.fetchall.return_value = [confirmed_row()]

    response = client.get("/events/registration")

    assert response.status_code == 200
    assert response.json["events"][0]["status"] == "Confirmed"
    query = cursor.execute.call_args.args[0]
    assert "status = 'Confirmed'" in query
    assert "coordinator_id" not in query.split("WHERE")[1]


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_registration_list_answers_503_when_no_database_is_configured():
    """
    Summary: With no DATABASE_URL set, GET /events/registration answers 503 for an Attendee.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None for the database, since the app has none configured; only the Supabase JWKS Stub,
        which verifies the Attendee's signed token
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client(), role="Attendee")
    assert client.get("/events/registration").status_code == 503
