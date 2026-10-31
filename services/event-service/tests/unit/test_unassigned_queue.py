"""
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

from app import create_app
from tests.unit.factories import saved_row, signed_in


def test_ac1_unassigned_queue_lists_only_submitted_events_with_no_coordinator(setup):
    """
    Summary: The queue's SQL selects only 'Submitted' events whose coordinator_id is NULL (not 'Under Review'), oldest submission first, and an entry comes back with coordinatorId null.
    AC1: Queue shows only submitted events with no assigned coordinator
    Double: Stub (cursor.fetchall returns one saved_row() with no coordinator),
        Mock (cursor.execute query text asserted: WHERE status = 'Submitted' AND coordinator_id IS NULL, ORDER BY submission_date ASC NULLS LAST)
    """
    client, _, cursor = setup
    signed_in(client, role="Event Coordinator Lead")
    cursor.fetchall.return_value = [saved_row()]
    response = client.get("/events/unassigned")
    assert response.status_code == 200
    assert response.json["events"][0]["coordinatorId"] is None
    query = cursor.execute.call_args.args[0]
    assert "WHERE status = 'Submitted' AND coordinator_id IS NULL" in query
    assert "'Under Review'" not in query
    assert "ORDER BY submission_date ASC NULLS LAST" in query


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_unassigned_queue_answers_503_when_no_database_is_configured():
    """
    Summary: With no DATABASE_URL set, GET /events/unassigned answers 503 for the Lead.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None for the database, since the app has none configured; only the Supabase JWKS Stub,
        which verifies the Lead's signed token
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": ""}).test_client(), role="Event Coordinator Lead")
    assert client.get("/events/unassigned").status_code == 503
