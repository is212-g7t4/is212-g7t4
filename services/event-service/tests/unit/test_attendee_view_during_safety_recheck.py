"""
SCRUM-153: Re-check Safety After High-Impact Changes

User Story
----------
As an Event Coordinator, I want a safety approval to be withdrawn when a
high-impact detail changes afterwards, so that the event is never prepared on
the basis of an outdated safety review.

Acceptance Criteria
-------------------
AC1: Given an event is 'Confirmed', when its date/time, expected attendance,
     venue requirements, equipment requirements or accessibility needs change,
     then its status returns to 'Pending Safety Check' and the coordinator is
     told why.
AC2: Given only a low-impact field changes (name, description, purpose,
     registration needs), then the event stays 'Confirmed'.
AC3: Given a safety approval is withdrawn, then it stays visible in the event's
     safety history.
AC4: Given a high-impact change to a 'Confirmed' event is waiting for its new
     safety check, when a registered Attendee views the event, then they still
     see the previously approved details, and the changed details are shown to
     them only after the Safety Officer approves the new safety check.
AC5: Given the new safety check ends without approval (changes requested or the
     event is cancelled), then registered Attendees are never shown the
     unapproved change, and they continue to see the last approved details or
     the cancellation.

This file covers AC4 and AC5 only, through the attendee-facing summary read.
AC1-AC3 (the withdrawal itself) are in test_event_details_recheck.py

Real
----
- GET /events/attendee-summaries and GET /events/summaries in app/__init__.py
  and the attendee-baseline rules in app/models.py, run through a real
  create_app(): the ids validation, reading the event's action history to find
  the last approved schedule and venue, and the JSON returned.
- Assertions are on the HTTP status and the response body; the request test
  also asserts the SQL and parameters the cursor received.

Doubled
-------
- psycopg2.connect: Stub (fixture) - a MagicMock connection whose cursor
  returns canned rows. Only the request tests use it as a Mock (the execute
  call, or the absence of a connection, is asserted).
- Supabase JWKS: Stub (tests/conftest.py) - tokens are signed with a throwaway
  ES256 key.

Not proven
----------
- That the SQL runs against the real Postgres schema (-> tests/integration/
  against a throwaway postgres:17.6).
- That the history entries these tests hand in are the ones the edit path
  writes (-> test_event_details_recheck.py and test_attendee_notifications.py).
- Which roles may call the endpoint (-> test_event_view_access.py).
- That the registration composite passes the result on to Attendees.
"""
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.models import NOT_DRAFT
from tests.unit.factories import (
    signed_in,
    COORDINATOR,
    EVENT,
    ROUND,
    approval_entry,
    attendee_summary_row,
    baseline_entry,
)

OTHER = "10000000-0000-0000-0000-000000000099"
SECOND_ROUND = "10000000-0000-0000-0000-000000000033"
# The live row holds the coordinator's new, unapproved window (2030-03-02 09:00-18:00 SGT).
LIVE = {"startTime": "2030-03-02T09:00:00", "endTime": "2030-03-02T18:00:00"}
APPROVED = {"startTime": "2030-03-01T09:00:00", "endTime": "2030-03-01T17:00:00"}


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr("app.models.psycopg2.connect", connect)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client()), cursor, connect


def attendee_summary(client, *ids):
    response = client.get(f"/events/attendee-summaries?ids={','.join(ids or (EVENT,))}")
    assert response.status_code == 200, response.json
    return response.json["events"]


# --- AC4: while the new safety check is pending ------------------------------


def test_ac4_pending_recheck_shows_attendees_the_approved_schedule_and_venue(setup):
    """
    Summary: A Confirmed event took a high-impact time edit and now waits for round 2.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor.fetchall returns one 'Pending Safety Check' row: approval, then a baseline for 09:00-17:00 at Hall A; the live columns hold the new 03-02 window)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchall.return_value = [
        attendee_summary_row("Pending Safety Check", [approval_entry(), baseline_entry()])
    ]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert event["startTime"] == APPROVED["startTime"]
    assert event["endTime"] == APPROVED["endTime"]
    assert event["attendeeVenueName"] == "Hall A"
    assert event["status"] == "Pending Safety Check"


def test_ac4_utc_baseline_is_returned_in_the_summary_local_format(setup):
    """
    Summary: A baseline stored in UTC (01:00-09:00) comes back as 09:00-17:00 Singapore time, without an offset.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor.fetchall returns one 'Pending Safety Check' row whose baseline times are 01:00 and 09:00 UTC)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchall.return_value = [
        attendee_summary_row("Pending Safety Check", [approval_entry(), baseline_entry(start="2030-03-01T01:00:00+00:00", end="2030-03-01T09:00:00+00:00")])
    ]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert (event["startTime"], event["endTime"]) == ("2030-03-01T09:00:00", "2030-03-01T17:00:00")


def test_ac4_baseline_without_dates_keeps_live_dates_but_approved_venue(setup):
    """
    Summary: A baseline captured from an event with no dates holds only venueName, so the dates stay live while the venue is still the approved one.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor.fetchall returns one 'Pending Safety Check' row whose baseline holds only venueName 'Hall A')
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchall.return_value = [
        attendee_summary_row("Pending Safety Check", [approval_entry(), baseline_entry(start=None, end=None)])
    ]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert (event["startTime"], event["endTime"]) == (LIVE["startTime"], LIVE["endTime"])
    assert event["attendeeVenueName"] == "Hall A"


def test_ac4_attendee_response_exposes_no_pending_values_or_history(setup):
    """
    Summary: The row's metadata carries remarks, the action history, the changed fields and the new times; none of it may reach the attendee, whose payload is exactly the approved details.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor.fetchall returns one 'Pending Safety Check' row whose approval and baseline entries carry remarks, changedFields and pending times)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchall.return_value = [attendee_summary_row("Pending Safety Check", [
        approval_entry(remarks="Officer note"),
        baseline_entry(changedFields=["preferredStartDate", "preferredEndDate"],
                       highImpactFields=["preferredStartDate"], remarks="Internal remark",
                       pending={"preferredStartDate": "2030-03-02T09:00:00"}),
    ])]

    # Act + Assert (When / Then)
    assert attendee_summary(client) == [{
        "id": EVENT, "eventName": "Workshop", "status": "Pending Safety Check",
        "coordinatorId": COORDINATOR, **APPROVED, "attendeeVenueName": "Hall A",
    }]


def test_ac4_second_withdrawal_before_any_approval_keeps_the_earliest_baseline(setup):
    """
    Summary: A venue-change withdrawal (baseline A) is followed, before any new approval, by a time edit that records baseline B; attendees still see baseline A, the last approved details.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor.fetchall returns one 'Pending Safety Check' row with two baselines in its history: Hall A on 03-01, then Hall B on 03-05)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchall.return_value = [attendee_summary_row("Pending Safety Check", [
        approval_entry(),
        baseline_entry(status="Approved", withdrawnSafetyCheckId=ROUND),
        dict(status="Pending Safety Check", safetyCheckId=SECOND_ROUND),
        baseline_entry(start="2030-03-05T09:00:00+08:00", end="2030-03-05T17:00:00+08:00", venue="Hall B"),
    ])]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert {key: event[key] for key in ("startTime", "endTime", "attendeeVenueName")} == {
        **APPROVED, "attendeeVenueName": "Hall A"}


def test_ac4_venue_change_withdrawal_shows_the_approved_venue(setup):
    """
    Summary: The SCRUM-28 path withdraws the approval back to 'Approved' while Venue Staff re-review the booking; attendees still see the approved window and venue.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor.fetchall returns one 'Approved' row: approval, then a baseline marked withdrawnSafetyCheckId)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchall.return_value = [attendee_summary_row("Approved", [
        approval_entry(), baseline_entry(status="Approved", withdrawnSafetyCheckId=ROUND),
    ])]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert {key: event[key] for key in ("startTime", "endTime", "attendeeVenueName")} == {
        **APPROVED, "attendeeVenueName": "Hall A"}


def test_ac4_restored_approval_also_ends_the_overlay(setup):
    """
    Summary: A venue-change withdrawal is undone, restoring the same approval round (by Venue Staff, not a new Safety Officer approval), so the live details are shown again.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor.fetchall returns one 'Confirmed' row: approval, withdrawal baseline, then an approval with restoredSafetyCheckId)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchall.return_value = [attendee_summary_row("Confirmed", [
        approval_entry(),
        baseline_entry(status="Approved", withdrawnSafetyCheckId=ROUND),
        approval_entry(restoredSafetyCheckId=ROUND),
    ])]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert (event["startTime"], event["endTime"]) == (LIVE["startTime"], LIVE["endTime"])
    assert event["attendeeVenueName"] is None


@pytest.mark.parametrize("status,history,description", [
    ("Confirmed", [], None),
    ("Pending Safety Check", [dict(status="Pending Safety Check", safetyCheckId=ROUND)], None),
    ("Pending Safety Check", None, "plain legacy description"),
    ("Pending Safety Check", None,
     '{"_connectsphere": "event-submission-v1", "description": "Workshop", "purpose": "Learning"}'),
    ("Confirmed", [approval_entry(), baseline_entry(status="Approved")], None),
], ids=["no-history", "first-submission", "non-json", "no-action-history", "confirmed-row-wins"])
def test_ac4_event_never_withdrawn_or_legacy_metadata_shows_live_values(setup, status, history, description):
    """
    Summary: With no baseline to fall back to (never withdrawn, first-time submission, or legacy metadata) the live values are shown; so are they when the row is Confirmed, even though an older baseline is on record (confirmed-row-wins).
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor.fetchall returns one row per case: empty history, a first submission only, non-JSON or action-less metadata, or a Confirmed row with an old baseline)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchall.return_value = [attendee_summary_row(status, history, description=description)]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert (event["startTime"], event["endTime"]) == (LIVE["startTime"], LIVE["endTime"])
    assert event["attendeeVenueName"] is None


def test_ac4_staff_summaries_still_show_live_values_during_recheck(setup):
    """
    Summary: The same pending row read through GET /events/summaries (staff screens) shows the live values and no attendeeVenueName: the approved-details overlay is for attendees only.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor.fetchall returns one 'Pending Safety Check' row with an approval and a baseline), read through /events/summaries instead
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchall.return_value = [
        attendee_summary_row("Pending Safety Check", [approval_entry(), baseline_entry()])
    ]

    # Act (When)
    response = client.get(f"/events/summaries?ids={EVENT}")

    # Assert (Then)
    assert response.status_code == 200
    [event] = response.json["events"]
    assert (event["startTime"], event["endTime"]) == (LIVE["startTime"], LIVE["endTime"])
    assert "attendeeVenueName" not in event


def test_ac4_each_event_in_one_request_gets_its_own_view(setup):
    """
    Summary: One request names two events: one waiting for its new safety check, one Confirmed with no changes. Only the first falls back to the approved details.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor.fetchall returns two rows: a 'Pending Safety Check' one with a baseline, and a 'Confirmed' one with empty history)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchall.return_value = [
        attendee_summary_row("Pending Safety Check", [approval_entry(), baseline_entry()]),
        attendee_summary_row("Confirmed", [], event_id=OTHER),
    ]

    # Act (When)
    events = {event["id"]: event for event in attendee_summary(client, EVENT, OTHER)}

    # Assert (Then)
    assert (events[EVENT]["startTime"], events[EVENT]["attendeeVenueName"]) == (APPROVED["startTime"], "Hall A")
    assert (events[OTHER]["startTime"], events[OTHER]["attendeeVenueName"]) == (LIVE["startTime"], None)


# --- AC5: the new safety check ends without approval -------------------------


def test_ac5_changes_requested_keeps_the_first_baseline_across_later_edits(setup):
    """
    Summary: The Safety Officer requested changes and the coordinator kept editing; the later edit entries carry no baseline of their own, so attendees still see the one recorded before round 2.
    AC5: Given the new safety check ends without approval (changes requested or
        the event is cancelled), then registered Attendees are never shown the
        unapproved change, and they continue to see the last approved details
        or the cancellation.
    Double: Stub (cursor.fetchall returns one 'Safety Changes Requested' row: approval, baseline, the officer's request, then two edit entries with no baseline)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchall.return_value = [attendee_summary_row("Safety Changes Requested", [
        approval_entry(),
        baseline_entry(),
        dict(status="Safety Changes Requested", safetyCheckId=SECOND_ROUND, remarks="Fix exits"),
        dict(status="Safety Changes Requested", details="Event details updated: Name.", changedFields=["eventName"]),
        dict(status="Safety Changes Requested", details="Event details updated: Start.",
             changedFields=["preferredStartDate"]),
    ])]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert {key: event[key] for key in ("startTime", "endTime", "attendeeVenueName")} == {
        **APPROVED, "attendeeVenueName": "Hall A"}


def test_ac5_cancelled_after_recheck_shows_approved_details_with_cancellation(setup):
    """
    Summary: The re-check ends in rejection, so the event is Cancelled; attendees see the cancellation and the approved details, not the unapproved change.
    AC5: Given the new safety check ends without approval (changes requested or
        the event is cancelled), then registered Attendees are never shown the
        unapproved change, and they continue to see the last approved details
        or the cancellation.
    Double: Stub (cursor.fetchall returns one 'Cancelled' row: approval, baseline, then a Cancelled entry for round 2)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchall.return_value = [attendee_summary_row("Cancelled", [
        approval_entry(), baseline_entry(), dict(status="Cancelled", safetyCheckId=SECOND_ROUND, remarks="Unsafe"),
    ])]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert event["status"] == "Cancelled"
    assert {key: event[key] for key in ("startTime", "endTime", "attendeeVenueName")} == {
        **APPROVED, "attendeeVenueName": "Hall A"}


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (how the attendee read validates and queries its ids, and
# configuration failure handling).


def test_request_selects_description_excludes_drafts_and_passes_ids(setup):
    """
    Summary: A request for two ids runs one query that selects the description column (where the history lives), excludes drafts, and passes the ids as one list parameter; events come back in the order the database returned them.
    Supporting design check: the attendee read has to see the action history
        and must never expose drafts
    Double: Stub (cursor.fetchall returns two 'Confirmed' rows, other id first), Mock (the one cursor.execute call's SQL and parameters asserted)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchall.return_value = [
        attendee_summary_row("Confirmed", [], event_id=OTHER),
        attendee_summary_row("Confirmed", []),
    ]

    # Act (When)
    events = attendee_summary(client, EVENT, OTHER)

    # Assert (Then)
    sql, params = cursor.execute.call_args[0]
    assert "description" in sql and NOT_DRAFT in sql
    assert params == [[EVENT, OTHER]]
    assert [event["id"] for event in events] == [OTHER, EVENT]


@pytest.mark.parametrize("query", ["", "?ids=", "?ids=nope", f"?ids={EVENT},nope", "?ids=" + ",".join([EVENT] * 101)],
                         ids=["no_ids_param", "blank_ids", "not_a_uuid", "one_bad_in_list", "101_ids"])
def test_missing_or_invalid_ids_are_rejected_before_any_query(setup, query):
    """
    Summary: No ids, a non-UUID, a mixed list or more than 100 ids are all a 400, and the database is never connected to.
    Supporting design check: the id list is validated before any database work
    Double: Mock (the psycopg2.connect patch is asserted never called)
    """
    # Arrange (Given)
    client, _, connect = setup

    # Act + Assert (When / Then)
    assert client.get(f"/events/attendee-summaries{query}").status_code == 400
    connect.assert_not_called()


def test_missing_database_url_is_503():
    """
    Summary: Without DATABASE_URL the service reports itself unavailable.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None (the app is created with no DATABASE_URL, so no connection is attempted)
    """
    client = signed_in(create_app({"DATABASE_URL": None}).test_client())
    assert client.get(f"/events/attendee-summaries?ids={EVENT}").status_code == 503
