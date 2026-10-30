"""
SCRUM-33: Equipment Request Review

User Story
----------
As a Technical Support Staff, I want to review and update the status of an
equipment request so that the Event Coordinator knows the technical
arrangements are approved.

Acceptance Criteria
-------------------
AC1: Technical Support Staff can view the requested equipment, equipment type,
     quantity, and technical requirements for a given event.
AC2: System allows the Technical Support Staff to change the request status
     (eg: to "Approved", "Rejected").
AC3: Ensure the newly updated status is visible to the assigned Event
     Coordinator.

SCRUM-32: Create Event Equipment Request

User Story
----------
As an Event Coordinator and Event Coordinator Lead, I want to record the
equipment required for an event so that the technical team is informed of the
resources needed as requested.

Acceptance Criteria
-------------------
AC1: The system allows the Event Coordinator and Event Coordinator Lead to
     record the equipment, equipment type, quantity, and relevant technical
     requirements for an event.
AC2: Recorded equipment request accurately reflects the date and time of the
     corresponding event
AC3: Ensure newly recorded equipment requests default to an initial status such
     as "Pending"

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
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.models import SINGAPORE
from tests.unit.factories import signed_in

ID_A = "00000000-0000-4000-8000-000000000001"
ID_B = "00000000-0000-4000-8000-000000000002"


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr("app.models.psycopg2.connect", connect)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client()), cursor, connect


def test_summaries_returns_name_status_coordinator_and_window_for_requested_ids(setup):
    """
    Summary: Summaries returns name status coordinator and window for requested ids.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = [
        {"event_id": ID_A, "event_name": "Hackday", "status": "Approved", "coordinator_id": ID_B,
         "preferred_start_date": datetime(2026, 10, 1, 9), "preferred_end_date": datetime(2026, 10, 1, 17)},
        {"event_id": ID_B, "event_name": "Gala", "status": "Submitted", "coordinator_id": None,
         "preferred_start_date": None, "preferred_end_date": None},
    ]

    response = client.get(f"/events/summaries?ids={ID_A},{ID_B}")

    assert response.status_code == 200
    assert response.json["events"] == [
        {"id": ID_A, "eventName": "Hackday", "status": "Approved", "coordinatorId": ID_B,
         "startTime": "2026-10-01T09:00:00", "endTime": "2026-10-01T17:00:00"},
        {"id": ID_B, "eventName": "Gala", "status": "Submitted", "coordinatorId": None,
         "startTime": None, "endTime": None},
    ]
    assert cursor.execute.call_args[0][1] == [[ID_A, ID_B]]


@pytest.mark.parametrize("query", ["", "?ids=", "?ids=nope", f"?ids={ID_A},nope", "?ids=" + ",".join([ID_A] * 101)], ids=["empty", "ids", "ids_nope", "f_ids_id_a_nope", "ids_join_id_a_101"])
def test_summaries_rejects_missing_or_invalid_ids(setup, query):
    """
    Summary: Summaries rejects missing or invalid ids.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, connect = setup
    assert client.get(f"/events/summaries{query}").status_code == 400
    connect.assert_not_called()


WINDOW = "start=2026-10-01T09:00&end=2026-10-01T17:00&statuses=Approved,Confirmed"


def test_overlapping_events_use_strict_overlap_and_exclude_the_target(setup):
    """
    Summary: Overlapping events use strict overlap and exclude the target.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = [
        {"event_id": ID_A, "event_name": "Hackday", "status": "Confirmed", "coordinator_id": None,
         "preferred_start_date": datetime(2026, 10, 1, 16), "preferred_end_date": datetime(2026, 10, 1, 20)},
    ]

    response = client.get(f"/events/overlapping?{WINDOW}&excludeEventId={ID_B}")

    assert response.status_code == 200
    assert response.json["events"][0]["id"] == ID_A
    sql, params = cursor.execute.call_args[0]
    assert "preferred_start_date < %s AND preferred_end_date > %s" in sql and "event_id <> %s" in sql
    assert params == [["Approved", "Confirmed"], datetime(2026, 10, 1, 17, tzinfo=SINGAPORE), datetime(2026, 10, 1, 9, tzinfo=SINGAPORE), ID_B]


def test_overlapping_events_without_exclusion(setup):
    """
    Summary: Overlapping events without exclusion.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = []

    assert client.get(f"/events/overlapping?{WINDOW}").json == {"events": []}
    assert "event_id <> %s" not in cursor.execute.call_args[0][0]


@pytest.mark.parametrize(
    "query",
    [
        "start=2026-10-01T09:00&end=2026-10-01T17:00",
        "start=2026-10-01T09:00&end=2026-10-01T17:00&statuses=Bogus",
        "start=nope&end=2026-10-01T17:00&statuses=Approved",
        "start=2026-10-01T09:00&statuses=Approved",
        f"start=2026-10-01T09:00&end=2026-10-01T17:00&statuses=Approved&excludeEventId=nope",
        "start=2026-10-01T17:00&end=2026-10-01T09:00&statuses=Approved",
    ],
    ids=["start_2026_10_01t09_00_end_2026_10_01t17_00", "start_2026_10_01t09_00_end_2026_10_01t17_00_stat", "start_nope_end_2026_10_01t17_00_statuses_approve", "start_2026_10_01t09_00_statuses_approved", "f_start_2026_10_01t09_00_end_2026_10_01t17_00_st", "start_2026_10_01t17_00_end_2026_10_01t09_00_stat"],
)
def test_overlapping_events_reject_bad_input(setup, query):
    """
    Summary: Overlapping events reject bad input.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, connect = setup
    assert client.get(f"/events/overlapping?{query}").status_code == 400
    connect.assert_not_called()


@pytest.mark.parametrize(
    "status",
    ["Pending Safety Check", "Safety Changes Requested", "Cancelled", "Confirmed"],
)
def test_overlapping_events_accepts_every_safety_status(setup, status):
    """
    Summary: The whole lifecycle, not just the pre-Week-7 five values.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = []

    response = client.get(f"/events/overlapping?start=2026-10-01T09:00&end=2026-10-01T17:00&statuses={status}")

    assert response.status_code == 200


def test_overlapping_events_still_rejects_an_unknown_status(setup):
    """
    Summary: Overlapping events still rejects an unknown status.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, connect = setup
    assert client.get(f"/events/overlapping?start=2026-10-01T09:00&end=2026-10-01T17:00&statuses=Bogus").status_code == 400
    connect.assert_not_called()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_summaries_missing_database_url_is_503():
    """
    Summary: Summaries missing database url is 503.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None
    """
    client = signed_in(create_app({"DATABASE_URL": None}).test_client())
    assert client.get(f"/events/summaries?ids={ID_A}").status_code == 503


def test_overlapping_events_missing_database_url_is_503():
    """
    Summary: Overlapping events missing database url is 503.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None
    """
    client = signed_in(create_app({"DATABASE_URL": None}).test_client())
    assert client.get(f"/events/overlapping?{WINDOW}").status_code == 503
