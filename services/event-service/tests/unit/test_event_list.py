"""
SCRUM-18: View Event Status

User Story
----------
As an Event Coordinator, I would like to be able to view the status (submitted,
approved, rejected) of an Event, so that I can understand the progress of an
Event and take subsequent actions if necessary.

Acceptance Criteria
-------------------
AC1: Event Coordinator should be able to view and filter his/her events and its
     status
AC2: Event Coordinator should be able to view the details of an Event and its
     status.

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
from app.models import SINGAPORE
from app.models import FIELDS
from tests.unit.factories import signed_in

VALID = {
    "eventName": "Community Workshop", "description": "A workshop", "purpose": "Learning",
    "preferredStartDate": "2026-10-01T09:00", "preferredEndDate": "2026-10-01T17:00",
    "expectedAttendance": "25",
}

COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client()), connection, cursor


def saved_row(**overrides):
    row = {column: VALID.get(key, "") for key, column in FIELDS.items()}
    row.update(event_id="00000000-0000-0000-0000-000000000001", status="Submitted",
               submission_date=datetime(2026, 9, 15, 1, 30, tzinfo=UTC),
               preferred_start_date=datetime(2026, 10, 1, 9),
               preferred_end_date=datetime(2026, 10, 1, 17), expected_attendance=25,
               coordinator_id=COORDINATOR_ID)
    row["description"] = json.dumps({"_connectsphere": "event-submission-v1",
                                     "description": VALID["description"], "purpose": VALID["purpose"]})
    row.update(overrides)
    return row


def test_event_list_returns_only_events_assigned_to_caller(setup):
    """
    Summary: Event list returns only events assigned to caller.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = [saved_row(), saved_row(event_id="00000000-0000-0000-0000-000000000002")]

    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}")

    assert response.status_code == 200
    assert len(response.json["events"]) == 2
    query, params = cursor.execute.call_args.args
    assert "coordinator_id = %s" in query
    assert params[0] == COORDINATOR_ID
    assert params == [COORDINATOR_ID]


def test_event_list_filters_by_status(setup):
    """
    Summary: Event list filters by status.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = [saved_row()]

    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}&status=Approved")

    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert "status = %s" in query
    assert params == [COORDINATOR_ID, "Approved"]


def test_event_list_filters_by_venue_substring(setup):
    """
    Summary: Event list filters by venue substring.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = [saved_row()]

    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}&venue=Main+Hall")

    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert "venue_requirements ILIKE %s ESCAPE '\\'" in query
    assert params == [COORDINATOR_ID, "%Main Hall%"]


def test_event_list_venue_filter_escapes_percent_and_underscore(setup):
    """
    Summary: Event list venue filter escapes percent and underscore.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = []

    response = client.get("/events", query_string={"coordinatorId": COORDINATOR_ID, "venue": "Room 50% A_B"})

    assert response.status_code == 200
    _, params = cursor.execute.call_args.args
    assert params == [COORDINATOR_ID, "%Room 50\\% A\\_B%"]


def test_event_list_filters_by_date_range(setup):
    """
    Summary: Event list filters by date range.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = [saved_row()]

    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}&dateFrom=2026-09-01&dateTo=2026-10-31")

    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert "preferred_start_date <= %s" in query
    assert "preferred_end_date >= %s" in query
    assert params[0] == COORDINATOR_ID
    assert params[1] == datetime(2026, 10, 31, 23, 59, 59, 999999, tzinfo=SINGAPORE)
    assert params[2] == datetime(2026, 9, 1, tzinfo=SINGAPORE)


def test_event_list_date_range_is_inclusive_of_end_date(setup):
    """
    Summary: Event list date range is inclusive of end date.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = []

    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}&dateTo=2026-10-31")

    assert response.status_code == 200
    _, params = cursor.execute.call_args.args
    assert params == [COORDINATOR_ID, datetime(2026, 10, 31, 23, 59, 59, 999999, tzinfo=SINGAPORE)]


def test_event_list_combined_filters(setup):
    """
    Summary: Event list combined filters.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = []

    response = client.get(
        f"/events?coordinatorId={COORDINATOR_ID}&status=Submitted&venue=Hall&dateFrom=2026-01-01"
    )

    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert "coordinator_id = %s" in query
    assert "status = %s" in query
    assert "venue_requirements ILIKE" in query
    assert "preferred_end_date >= %s" in query
    assert params == [COORDINATOR_ID, "Submitted", "%Hall%", datetime(2026, 1, 1, tzinfo=SINGAPORE)]


def test_event_list_no_filters_still_requires_and_scopes_by_coordinator(setup):
    """
    Summary: Event list no filters still requires and scopes by coordinator.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = []

    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}")

    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert query.strip().count("%s") == 1
    assert params == [COORDINATOR_ID]


@pytest.mark.parametrize("query_string", ["", f"?coordinatorId={COORDINATOR_ID}", "?organiserId=33333333-3333-4333-8333-333333333333"], ids=["empty", "f_coordinatorid_coordinator_id", "organiserid_33333333_3333_4333_8333_333333333333"])
def test_event_list_requires_a_signed_in_user(query_string, setup):
    """
    Summary: Whose events are listed comes from the token; a query id alone grants nothing.
    SCRUM-8 AC1: Given a system user has not been successfully authenticated,
        when they attempt to access protected information or functionality,
        then access is denied.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    _, _, cursor = setup
    client = setup[0].application.test_client()

    # Act (When)
    response = client.get(f"/events{query_string}")

    # Assert (Then)
    assert response.status_code == 401
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("query_string", [
    "dateFrom=not-a-date",
    "dateTo=not-a-date",
    "dateFrom=2026-10-01T09:00",
    "dateTo=2026-10-01T09:00",
    "dateFrom=2026-10-31&dateTo=2026-10-01",
])
def test_event_list_rejects_invalid_date_range(query_string, setup):
    """
    Summary: Event list rejects invalid date range.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}&{query_string}")
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_event_list_lead_sees_events_regardless_of_coordinator(setup):
    """
    Summary: Event list lead sees events regardless of coordinator.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = [saved_row(), saved_row(event_id="00000000-0000-0000-0000-000000000002", coordinator_id=None)]

    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}&viewerRole=Event+Coordinator+Lead")

    assert response.status_code == 200
    assert len(response.json["events"]) == 2
    query, params = cursor.execute.call_args.args
    assert "coordinator_id = %s" not in query
    # The only condition is the draft exclusion (drafts AC1).
    assert "WHERE status IS DISTINCT FROM 'Draft'\n" in query
    assert params == []


def test_event_list_lead_can_still_combine_with_optional_filters(setup):
    """
    Summary: Event list lead can still combine with optional filters.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = []

    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}&viewerRole=Event+Coordinator+Lead&status=Approved")

    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert "coordinator_id = %s" not in query
    assert "status = %s" in query
    assert params == ["Approved"]


@pytest.mark.parametrize("role", ["Venue Staff", "Technical Support", "Safety Officer"])
def test_event_list_internal_operational_staff_see_all_events_with_existing_filters(role, setup):
    """
    Summary: Event list internal operational staff see all events with existing filters.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = [saved_row()]

    response = client.get(
        "/events",
        query_string={
            "coordinatorId": COORDINATOR_ID,
            "viewerRole": role,
            "status": "Approved",
        },
    )

    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert "coordinator_id = %s" not in query
    assert "status = %s" in query
    assert params == ["Approved"]


def test_event_list_unrecognised_role_cannot_request_all_internal_events(setup):
    """
    Summary: Event list unrecognised role cannot request all internal events.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    response = client.get(
        "/events",
        query_string={"coordinatorId": COORDINATOR_ID, "viewerRole": "Attendee"},
    )
    assert response.status_code == 403
    cursor.execute.assert_not_called()


ORGANISER_ID = "33333333-3333-4333-8333-333333333333"


def test_organiser_lists_only_their_own_events_in_all_statuses(setup):
    """
    Summary: Organiser sees the events they created.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = [
        saved_row(organiser_id=ORGANISER_ID, status="Approved"),
        saved_row(organiser_id=ORGANISER_ID, status="Rejected",
                  event_id="00000000-0000-0000-0000-000000000002"),
    ]

    response = client.get(f"/events?organiserId={ORGANISER_ID}")

    assert response.status_code == 200
    assert [e["status"] for e in response.json["events"]] == ["Approved", "Rejected"]
    assert response.json["events"][0]["organiserId"] == ORGANISER_ID
    query, params = cursor.execute.call_args.args
    # Every status except their drafts, which have their own list (drafts AC2).
    where = query.split("WHERE")[1]
    assert "organiser_id = %s" in where
    assert where.replace("status IS DISTINCT FROM 'Draft'", "").count("status") == 0
    assert params == [ORGANISER_ID]


def test_event_list_retired_is_manager_flag_no_longer_widens_the_list(setup):
    """
    Summary: Event list retired is manager flag no longer widens the list.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = []

    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}&isManager=true")

    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert "coordinator_id = %s" in query
    assert params == [COORDINATOR_ID]


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_event_list_missing_database_configuration():
    """
    Summary: Event list missing database configuration.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client())
    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}")
    assert response.status_code == 503


def test_organiser_list_reports_missing_database_url(setup):
    """
    Summary: Organiser list reports missing database url.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None
    """
    client, _, _ = setup
    client.application.config["DATABASE_URL"] = None
    assert client.get(f"/events?organiserId={ORGANISER_ID}").status_code == 503
