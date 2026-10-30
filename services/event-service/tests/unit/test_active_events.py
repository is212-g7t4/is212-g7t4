"""
SCRUM-161: View Coordinator Assignments and Active Events

User Story
----------
As an Event Coordinator Lead, I want to view all coordinator assignments and
active events under my supervision, so that I can balance workload and decide
when to reassign.

Acceptance Criteria
-------------------
AC1: Lead sees every Event Coordinator with the active events currently
     assigned to them
AC2: Each event shows: name, organiser, date/time, current status
AC3: Unassigned events are visible and clearly marked as unassigned
AC4: Confirmed, cancelled and rejected events are excluded
AC5: The view is read-only: event details cannot be edited from it
AC6: Only the Lead can access this view

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
from tests.unit.factories import COORDINATOR_ID, saved_row, signed_in


def test_active_events_include_unassigned_and_exclude_confirmed_rejected_cancelled(setup):
    """
    Summary: The Lead's workload view lists active events, assigned or not, without closed ones.
    AC3: Unassigned events are visible and clearly marked as unassigned
    AC4: Confirmed, cancelled and rejected events are excluded
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    signed_in(client, role="Event Coordinator Lead")
    assigned = {**saved_row(), "status": "Under Review", "coordinator_id": COORDINATOR_ID}
    cursor.fetchall.return_value = [saved_row(), assigned]
    response = client.get("/events/active")
    assert response.status_code == 200
    assert [event["coordinatorId"] for event in response.json["events"]] == [None, COORDINATOR_ID]
    query, params = cursor.execute.call_args.args
    assert "WHERE status NOT IN %s" in query
    assert "coordinator_id" not in query.split("WHERE")[1]
    assert params == [("Confirmed", "Rejected", "Cancelled")]
    assert "ORDER BY preferred_start_date ASC NULLS LAST" in query


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_active_events_need_database(monkeypatch):
    """
    Summary: Active events need database.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": ""}).test_client(), role="Event Coordinator Lead")
    assert client.get("/events/active").status_code == 503
