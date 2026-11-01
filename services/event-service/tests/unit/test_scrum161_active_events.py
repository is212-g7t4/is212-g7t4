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

Scope of this file
------------------∏∏
The view itself is GET /workload in coordinator-assignment-service; its tests
are in that service (test_coordinator_workload.py). That route calls
this service's GET /events/active for the events, so this file covers only what
/events/active supplies:
AC2: name (eventName), organiser (organiserId, an id and not a display name),
     date/time (preferredStartDate, preferredEndDate) and status.
AC3: an unassigned event is returned with coordinatorId null. There is no
     separate "unassigned" flag, so null is the marker.
AC4: the query excludes Confirmed, Rejected and Cancelled with a parameter. The
     database is stubbed here, so the filtering itself is run in
     tests/integration/test_scrum161_active_events.py.

Real
----
- The Event Service route GET /events/active in app/__init__.py and
  list_active_events / serialize in app/models.py, run through a real
  create_app(): the token check, the 503 when no database is
  configured, and the response body.
- Assertions are on the HTTP status, the response body and the SQL and
  parameters the cursor received.

Doubled
-------
- psycopg2.connect: Stub (setup fixture in tests/unit/conftest.py) - a
  MagicMock connection whose cursor returns canned rows; Mock - its execute
  calls are asserted for the query and parameters sent.
- Supabase JWKS: Stub (tests/conftest.py) - tokens are signed with a throwaway
  ES256 key.

Not proven
----------
- Supabase sign-in itself: the caller is a token signed with a test key.

Proven elsewhere
----------------
- That the SQL runs against the real Postgres schema and returns only active
  events (AC2, AC3, AC4): tests/integration/test_scrum161_active_events.py against a
  throwaway postgres:17.6.
- AC1 (every coordinator with their events), AC5 (read-only) and AC6 (Lead only)
  are properties of GET /workload, tested in
  coordinator-assignment-service/tests/unit/test_coordinator_workload.py.
- That the UI shows no edit controls (AC5) is left to the frontend
  CoordinatorWorkloadPage.test.tsx.
"""

from app import create_app
from tests.unit.factories import COORDINATOR_ID, saved_row, signed_in

LEAD = "Event Coordinator Lead"
ORGANISER_ID = "33333333-3333-4333-8333-333333333333"


def assigned_row(coordinator_id=COORDINATOR_ID, **extra):
    return {**saved_row(), "status": "Under Review", "coordinator_id": coordinator_id, **extra}


def test_ac2_active_event_shows_name_organiser_date_time_and_status(setup):
    """
    Summary: Each event in the view carries its name, organiser, start and end date/time, and status.
    AC2: Each event shows: name, organiser, date/time, current status
    Double: Stub (cursor.fetchall returns one 'Under Review' row with organiser_id, start and end set)
    """
    client, _, cursor = setup
    signed_in(client, role=LEAD)
    cursor.fetchall.return_value = [assigned_row(organiser_id=ORGANISER_ID)]
    response = client.get("/events/active")
    assert response.status_code == 200
    (event,) = response.json["events"]
    assert event["eventName"] == "Community Workshop"
    assert event["organiserId"] == ORGANISER_ID
    assert event["preferredStartDate"].startswith("2026-10-01T09:00")
    assert event["preferredEndDate"].startswith("2026-10-01T17:00")
    assert event["status"] == "Under Review"


def test_ac3_active_events_include_unassigned_events_marked_with_no_coordinator(setup):
    """
    Summary: An unassigned event is listed beside assigned ones, with a null coordinatorId, and the query does not filter on coordinator.
    AC3: Unassigned events are visible and clearly marked as unassigned
    Double: Stub (cursor.fetchall returns one row with coordinator_id None and one with a coordinator),
        Mock (cursor.execute query text: no coordinator_id in the WHERE clause)
    """
    client, _, cursor = setup
    signed_in(client, role=LEAD)
    cursor.fetchall.return_value = [saved_row(), assigned_row()]
    response = client.get("/events/active")
    assert response.status_code == 200
    assert [event["coordinatorId"] for event in response.json["events"]] == [None, COORDINATOR_ID]
    query, _ = cursor.execute.call_args.args
    assert "coordinator_id" not in query.split("WHERE")[1].split("ORDER BY")[0]


def test_ac4_active_events_query_excludes_confirmed_rejected_and_cancelled(setup):
    """
    Summary: The query asks the database to leave out Confirmed, Rejected and Cancelled events.
    AC4: Confirmed, cancelled and rejected events are excluded
    Double: Stub (cursor.fetchall returns no rows),
        Mock (cursor.execute called with WHERE status NOT IN %s and the three closed statuses as params)
    """
    client, _, cursor = setup
    signed_in(client, role=LEAD)
    cursor.fetchall.return_value = []
    assert client.get("/events/active").status_code == 200
    query, params = cursor.execute.call_args.args
    assert "WHERE status NOT IN %s" in query
    assert params == [("Confirmed", "Rejected", "Cancelled")]


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# story relies on (configuration failure).


def test_active_events_answer_503_when_no_database_is_configured():
    """
    Summary: With no DATABASE_URL set, the route answers 503 for the Lead.
    Supporting design check: an Event Service with no database configured answers 503
    Double: None for the database, since the app has none configured; only the Supabase JWKS Stub,
        which verifies the Lead's signed token
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": ""}).test_client(), role=LEAD)
    response = client.get("/events/active")
    assert response.status_code == 503
    assert "DATABASE_URL" in response.json["message"]
