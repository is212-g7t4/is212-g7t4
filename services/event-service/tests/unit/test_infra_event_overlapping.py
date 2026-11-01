"""
SUPPORTING DESIGN CHECKS: GET /events/overlapping (time-window lookup)

No user story owns this route, so none of these tests claims an acceptance
criterion. Event Service answers the question "which events overlap this
window?" for two callers, and each caller's own story is tested in that
caller's service:
- Equipment Reservation Service, to count equipment held by overlapping events
  (SCRUM-35 AC3, "other overlapping events whose reservations remain active").
- Event Workflow Service, to check that a date change still leaves the event's
  equipment available (SCRUM-20 AC3).
This file only proves Event Service's half: the window rule, the filters and
the refusals.

Real
----
- The Event Service route in app/__init__.py and the query in app/models.py,
  run through a real create_app(): request validation, the caller's role check
  from the signed token, and the SQL and parameters sent to the database.
- Assertions are on the HTTP status, the response body and the queries and
  parameters the cursor received.

Doubled
-------
- psycopg2.connect: Stub (fixture) - a MagicMock connection whose cursor
  returns canned rows; Mock - its execute calls are asserted to prove what was
  (or was not) read.
- Supabase JWKS: Stub (tests/conftest.py) - tokens are signed with a throwaway
  ES256 key.

Not proven
----------
- That the SQL runs against the real Postgres schema (-> tests/integration/
  against a throwaway postgres:17.6).
- That the callers use the result correctly (-> Equipment Reservation Service
  and Event Workflow Service tests).
- Which roles may call the route (-> test_scrum9_event_view_access.py).
"""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.models import SINGAPORE
from tests.unit.factories import signed_in

ID_A = "00000000-0000-4000-8000-000000000001"
ID_B = "00000000-0000-4000-8000-000000000002"
WINDOW = "start=2026-10-01T09:00&end=2026-10-01T17:00&statuses=Approved,Confirmed"


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr("app.models.psycopg2.connect", connect)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client()), cursor, connect


def test_overlapping_events_use_strict_overlap_and_exclude_the_target_event(setup):
    """
    Summary: GET /events/overlapping returns the events in the given statuses whose window overlaps 09:00-17:00 Singapore time strictly (start < window end AND end > window start), and the SQL excludes the target event id.
    Supporting design check: the equipment availability check needs the events
        that clash with a window, never counting the event being checked
    Double: Stub (cursor.fetchall returns one Confirmed event),
        Mock (cursor.execute SQL contains the strict-overlap and event_id <> %s clauses; parameters are the statuses, window end, window start, and excluded id)
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


def test_overlapping_events_without_excludeeventid_do_not_filter_on_event_id(setup):
    """
    Summary: GET /events/overlapping with no excludeEventId returns an empty list and the SQL has no event_id <> %s clause.
    Supporting design check: excludeEventId is optional; without it nothing is
        left out
    Double: Stub (cursor.fetchall returns no rows),
        Mock (cursor.execute SQL asserted to lack event_id <> %s)
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
def test_overlapping_events_reject_bad_window_statuses_or_exclude_id_before_any_connection(setup, query):
    """
    Summary: A missing statuses, an unknown status, a non-date start, a missing end, a non-UUID excludeEventId, or an end before the start all answer 400 and no database connection is opened.
    Supporting design check: the window and filters are validated before any
        database work
    Double: Mock (the psycopg2.connect patch is asserted never called)
    """
    client, _, connect = setup
    assert client.get(f"/events/overlapping?{query}").status_code == 400
    connect.assert_not_called()


@pytest.mark.parametrize(
    "status",
    ["Pending Safety Check", "Safety Changes Requested", "Cancelled", "Confirmed"],
)
def test_overlapping_events_accept_every_safety_lifecycle_status(setup, status):
    """
    Summary: For each of Pending Safety Check, Safety Changes Requested, Cancelled and Confirmed, GET /events/overlapping answers 200, so the status filter knows the whole lifecycle and not only the older statuses.
    Supporting design check: the status filter must accept every status an
        event can reach
    Double: Stub (cursor.fetchall returns no rows)
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = []

    response = client.get(f"/events/overlapping?start=2026-10-01T09:00&end=2026-10-01T17:00&statuses={status}")

    assert response.status_code == 200


def test_overlapping_events_answer_503_when_no_database_is_configured():
    """
    Summary: With no DATABASE_URL set, GET /events/overlapping answers 503.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None for the database, since the app has none configured; only the Supabase JWKS Stub, which verifies the signed token
    """
    client = signed_in(create_app({"DATABASE_URL": None}).test_client())
    assert client.get(f"/events/overlapping?{WINDOW}").status_code == 503
