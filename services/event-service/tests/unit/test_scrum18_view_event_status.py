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
from app.models import FIELDS, SINGAPORE
from tests.unit.factories import signed_in

VALID = {
    "eventName": "Community Workshop", "description": "A workshop", "purpose": "Learning",
    "preferredStartDate": "2026-10-01T09:00", "preferredEndDate": "2026-10-01T17:00",
    "expectedAttendance": "25",
}

EVENT_ID = "00000000-0000-0000-0000-000000000001"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
ORGANISER_ID = "33333333-3333-4333-8333-333333333333"


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client()), connection, cursor


def saved_row(**overrides):
    row = {column: VALID.get(key, "") for key, column in FIELDS.items()}
    row.update(event_id=EVENT_ID, status="Submitted",
               submission_date=datetime(2026, 9, 15, 1, 30, tzinfo=UTC),
               preferred_start_date=datetime(2026, 10, 1, 9),
               preferred_end_date=datetime(2026, 10, 1, 17), expected_attendance=25,
               coordinator_id=COORDINATOR_ID)
    row["description"] = json.dumps({"_connectsphere": "event-submission-v1",
                                     "description": VALID["description"], "purpose": VALID["purpose"]})
    row.update(overrides)
    return row


def test_ac1_list_asks_the_database_only_for_events_assigned_to_the_signed_in_coordinator(setup):
    """
    Summary: GET /events?coordinatorId=C answers 200 with the two events the database returned, and the SQL is scoped by coordinator_id = %s with the coordinator's id as its only parameter.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor.fetchall returns two submitted events),
        Mock (cursor.execute SQL contains coordinator_id = %s and its parameters are exactly [coordinator id])
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


def test_ac1_list_filters_by_status(setup):
    """
    Summary: GET /events?coordinatorId=C&status=Approved answers 200 and the SQL adds status = %s, with the parameters being the coordinator id then "Approved".
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor.fetchall returns one submitted event),
        Mock (cursor.execute SQL contains status = %s and its parameters are [coordinator id, "Approved"])
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = [saved_row()]

    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}&status=Approved")

    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert "status = %s" in query
    assert params == [COORDINATOR_ID, "Approved"]


def test_ac1_list_filters_by_venue_substring(setup):
    """
    Summary: GET /events?coordinatorId=C&venue=Main Hall answers 200 and the SQL adds a case-insensitive venue_requirements ILIKE match whose parameter is "%Main Hall%".
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor.fetchall returns one submitted event),
        Mock (cursor.execute SQL contains the escaped ILIKE clause and its parameters are [coordinator id, "%Main Hall%"])
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = [saved_row()]

    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}&venue=Main+Hall")

    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert "venue_requirements ILIKE %s ESCAPE '\\'" in query
    assert params == [COORDINATOR_ID, "%Main Hall%"]


def test_ac1_list_venue_filter_treats_percent_and_underscore_as_plain_text(setup):
    """
    Summary: GET /events with venue "Room 50% A_B" answers 200 and the LIKE parameter has the % and _ escaped with backslashes ("%Room 50\\% A\\_B%"), so they match literally and not as wildcards.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor.fetchall returns no rows),
        Mock (cursor.execute parameters are [coordinator id, the escaped pattern])
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = []

    response = client.get("/events", query_string={"coordinatorId": COORDINATOR_ID, "venue": "Room 50% A_B"})

    assert response.status_code == 200
    _, params = cursor.execute.call_args.args
    assert params == [COORDINATOR_ID, "%Room 50\\% A\\_B%"]


def test_ac1_list_filters_by_date_range(setup):
    """
    Summary: GET /events with dateFrom=2026-09-01 and dateTo=2026-10-31 answers 200 and the SQL keeps events that start on or before the end of 31 Oct and end on or after 1 Sep, both in Singapore time.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor.fetchall returns one submitted event),
        Mock (cursor.execute SQL has the preferred_start_date <= %s and preferred_end_date >= %s clauses; parameters are the coordinator id, 31 Oct 23:59:59.999999 SGT, 1 Sep 00:00 SGT)
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


def test_ac1_list_date_range_includes_the_whole_end_date(setup):
    """
    Summary: GET /events with only dateTo=2026-10-31 answers 200 and the end bound sent to the database is 23:59:59.999999 Singapore time on 31 Oct, so events on that day are included.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor.fetchall returns no rows),
        Mock (cursor.execute parameters are [coordinator id, 31 Oct 23:59:59.999999 SGT])
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = []

    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}&dateTo=2026-10-31")

    assert response.status_code == 200
    _, params = cursor.execute.call_args.args
    assert params == [COORDINATOR_ID, datetime(2026, 10, 31, 23, 59, 59, 999999, tzinfo=SINGAPORE)]


def test_ac1_list_applies_status_venue_and_date_filters_together(setup):
    """
    Summary: GET /events with status=Submitted, venue=Hall and dateFrom=2026-01-01 answers 200 and the SQL has the coordinator, status, venue and end-date clauses, with parameters in that order.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Stub (cursor.fetchall returns no rows),
        Mock (cursor.execute SQL contains all four clauses and its parameters are [coordinator id, "Submitted", "%Hall%", 1 Jan 2026 00:00 SGT])
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


@pytest.mark.parametrize("query_string", [
    "dateFrom=not-a-date",
    "dateTo=not-a-date",
    "dateFrom=2026-10-01T09:00",
    "dateTo=2026-10-01T09:00",
    "dateFrom=2026-10-31&dateTo=2026-10-01",
])
def test_ac1_list_rejects_an_invalid_or_backwards_date_range_without_querying(query_string, setup):
    """
    Summary: GET /events with a non-date dateFrom or dateTo, a date-time instead of a date, or dateFrom after dateTo answers 400 and the database is never queried.
    AC1: Event Coordinator should be able to view and filter his/her events and
        its status
    Double: Mock (cursor.execute asserted never called)
    """
    client, _, cursor = setup
    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}&{query_string}")
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_ac2_assigned_coordinator_opens_an_event_and_sees_its_full_details_and_status(setup):
    """
    Summary: GET /events/<id>?coordinatorId=C for an event assigned to C answers 200 with every event field, the status "Submitted", the description and purpose unwrapped from the stored metadata, the submission time and the coordinator id, read with a plain SELECT (no FOR UPDATE) by event id.
    AC2: Event Coordinator should be able to view the details of an Event and
        its status.
    Double: Stub (cursor.fetchone returns one submitted event assigned to the coordinator),
        Mock (cursor.execute SQL is a SELECT from public."Event" without FOR UPDATE and its parameters are [event id])
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = saved_row()

    response = client.get(f"/events/{EVENT_ID}?coordinatorId={COORDINATOR_ID}")

    assert response.status_code == 200
    body = response.json
    for key in FIELDS:
        assert key in body
    assert body["id"] == EVENT_ID
    assert body["status"] == "Submitted"
    assert body["purpose"] == "Learning"
    assert body["description"] == "A workshop"
    assert body["submittedAt"] == "2026-09-15T01:30:00+00:00"
    assert body["coordinatorId"] == COORDINATOR_ID
    query, parameters = cursor.execute.call_args.args
    assert "SELECT event_id" in query
    assert 'FROM public."Event"' in query
    assert "FOR UPDATE" not in query
    assert parameters == [EVENT_ID]


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_coordinator_opening_an_unknown_event_gets_404(setup):
    """
    Summary: GET /events/<id>?coordinatorId=C answers 404 when the database finds no such event.
    Supporting design check: asking for an event that does not exist is a 404,
        not an empty 200
    Double: Stub (cursor.fetchone returns None)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = None
    response = client.get(f"/events/{EVENT_ID}?coordinatorId={COORDINATOR_ID}")
    assert response.status_code == 404


def test_organiser_opening_an_unknown_event_gets_404(setup):
    """
    Summary: GET /events/<id>?organiserId=O (the organiser's own view) answers 404 when the database finds no such event.
    Supporting design check: the organiser view of an event that does not exist
        is a 404 as well
    Double: Stub (cursor.fetchone returns None)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = None
    assert client.get(f"/events/{EVENT_ID}?organiserId={ORGANISER_ID}").status_code == 404


def test_event_list_answers_503_when_no_database_is_configured():
    """
    Summary: With no DATABASE_URL set, GET /events?coordinatorId=C answers 503.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None for the database, since the app has none configured; only the Supabase JWKS Stub, which verifies the signed token
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client())
    response = client.get(f"/events?coordinatorId={COORDINATOR_ID}")
    assert response.status_code == 503


def test_organiser_list_answers_503_when_no_database_is_configured(setup):
    """
    Summary: After clearing DATABASE_URL, GET /events?organiserId=O answers 503.
    Supporting design check: an Event Service with no database configured
        answers 503, also for the organiser's list
    Double: None for the database, since DATABASE_URL is cleared; only the Supabase JWKS Stub, which verifies the signed token
    """
    client, _, _ = setup
    client.application.config["DATABASE_URL"] = None
    assert client.get(f"/events?organiserId={ORGANISER_ID}").status_code == 503


def test_coordinator_event_details_answer_503_when_no_database_is_configured():
    """
    Summary: With no DATABASE_URL set, GET /events/<id>?coordinatorId=C answers 503.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None for the database, since the app has none configured; only the Supabase JWKS Stub, which verifies the signed token
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client())
    response = client.get(f"/events/{EVENT_ID}?coordinatorId={COORDINATOR_ID}")
    assert response.status_code == 503


def test_organiser_event_details_answer_503_when_no_database_is_configured(setup):
    """
    Summary: After clearing DATABASE_URL, GET /events/<id>?organiserId=O answers 503.
    Supporting design check: an Event Service with no database configured
        answers 503, also for the organiser's event view
    Double: None for the database, since DATABASE_URL is cleared; only the Supabase JWKS Stub, which verifies the signed token
    """
    client, _, _ = setup
    client.application.config["DATABASE_URL"] = None
    assert client.get(f"/events/{EVENT_ID}?organiserId={ORGANISER_ID}").status_code == 503
