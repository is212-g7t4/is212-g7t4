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

SCRUM-150: Approve Operational Safety Check

User Story
----------
As a Safety Officer, I want to approve an event's operational safety
arrangements, so that the event can proceed to preparation.

Acceptance Criteria
-------------------
AC1: Given an event is 'Pending Safety Check', when I approve it, then its
     status changes to 'Confirmed'.
AC2: Given I approve an event, then the safety check is recorded with the
     status 'Safety Approved', together with my identity, the approval
     timestamp and any optional remarks, in the event's history.
AC3: Given an event is not 'Pending Safety Check', then the approve action is
     not available and an API call is rejected without changing the event.
AC4: Given the safety check I approve follows a high-impact change, when I
     approve it, then the changed details become visible to registered
     Attendees.

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


def test_pending_recheck_shows_attendees_the_approved_schedule_and_venue(setup):
    """
    Summary: A Confirmed event took a high-impact time edit and now waits for round 2.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


@pytest.mark.parametrize("start,end", [
    ("2030-03-01T09:00:00+08:00", "2030-03-01T17:00:00+08:00"),
    ("2030-03-01T01:00:00+00:00", "2030-03-01T09:00:00+00:00"),
])
def test_baseline_offset_is_returned_in_the_summary_local_format(setup, start, end):
    """
    Summary: The baseline is stored with an offset (normally +08:00, here also UTC).
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchall.return_value = [
        attendee_summary_row("Pending Safety Check", [approval_entry(), baseline_entry(start=start, end=end)])
    ]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert (event["startTime"], event["endTime"]) == ("2030-03-01T09:00:00", "2030-03-01T17:00:00")


def test_baseline_without_dates_keeps_live_dates_but_approved_venue(setup):
    """
    Summary: A baseline captured from an event with no dates holds only venueName.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_attendee_response_exposes_no_pending_values_or_history(setup):
    """
    Summary: The metadata carries remarks, the action history, changed fields and the new times.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_changes_requested_keeps_the_first_baseline_across_later_edits(setup):
    """
    Summary: The Safety Officer requested changes and the coordinator kept editing.
    AC5: Given the new safety check ends without approval (changes requested or
        the event is cancelled), then registered Attendees are never shown the
        unapproved change, and they continue to see the last approved details
        or the cancellation.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_second_withdrawal_before_any_approval_keeps_the_earliest_baseline(setup):
    """
    Summary: A venue-change withdrawal (baseline A) is followed, before any new approval, by a time edit that records baseline B.
    AC5: Given the new safety check ends without approval (changes requested or
        the event is cancelled), then registered Attendees are never shown the
        unapproved change, and they continue to see the last approved details
        or the cancellation.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_cancelled_after_recheck_shows_approved_details_with_cancellation(setup):
    """
    Summary: The re-check ends in rejection, so the event is Cancelled.
    AC5: Given the new safety check ends without approval (changes requested or
        the event is cancelled), then registered Attendees are never shown the
        unapproved change, and they continue to see the last approved details
        or the cancellation.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_venue_change_withdrawal_shows_the_approved_venue(setup):
    """
    Summary: The SCRUM-28 path withdraws the approval back to 'Approved' while Venue Staff re-review the booking.
    AC5: Given the new safety check ends without approval (changes requested or
        the event is cancelled), then registered Attendees are never shown the
        unapproved change, and they continue to see the last approved details
        or the cancellation.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_approval_after_recheck_releases_the_new_details(setup):
    """
    Summary: The Safety Officer approves round 2.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchall.return_value = [attendee_summary_row("Confirmed", [
        approval_entry(), baseline_entry(), approval_entry(round_id=SECOND_ROUND),
    ])]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert (event["startTime"], event["endTime"]) == (LIVE["startTime"], LIVE["endTime"])
    assert event["attendeeVenueName"] is None


def test_restored_approval_also_ends_the_overlay(setup):
    """
    Summary: A venue-change withdrawal is undone, restoring the same approval round.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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
def test_event_never_withdrawn_or_legacy_metadata_shows_live_values(setup, status, history, description):
    """
    Summary: With no recorded baseline (never withdrawn, first-time submission, or legacy metadata) there is nothing to fall back to, so the live values are shown.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchall.return_value = [attendee_summary_row(status, history, description=description)]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert (event["startTime"], event["endTime"]) == (LIVE["startTime"], LIVE["endTime"])
    assert event["attendeeVenueName"] is None


def test_request_selects_description_excludes_drafts_and_passes_ids(setup):
    """
    Summary: Two ids.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchall.return_value = [
        attendee_summary_row("Confirmed", [], event_id=OTHER),
        attendee_summary_row("Confirmed", []),
    ]

    events = attendee_summary(client, EVENT, OTHER)

    sql, params = cursor.execute.call_args[0]

    # Act + Assert (When / Then)
    assert "description" in sql and NOT_DRAFT in sql
    assert params == [[EVENT, OTHER]]
    assert [event["id"] for event in events] == [OTHER, EVENT]


@pytest.mark.parametrize("query", ["", "?ids=", "?ids=nope", f"?ids={EVENT},nope", "?ids=" + ",".join([EVENT] * 101)], ids=["empty", "ids", "ids_nope", "f_ids_event_nope", "ids_join_event_101"])
def test_missing_or_invalid_ids_are_rejected_before_any_query(setup, query):
    """
    Summary: No ids, a non-UUID, a mixed list or more than 100 ids are all a 400.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, connect = setup

    # Act + Assert (When / Then)
    assert client.get(f"/events/attendee-summaries{query}").status_code == 400
    connect.assert_not_called()


def test_staff_summaries_still_show_live_values_during_recheck(setup):
    """
    Summary: The same pending row read through GET /events/summaries (staff screens).
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_missing_database_url_is_503():
    """
    Summary: Without DATABASE_URL the service reports itself unavailable.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None
    """
    client = signed_in(create_app({"DATABASE_URL": None}).test_client())
    assert client.get(f"/events/attendee-summaries?ids={EVENT}").status_code == 503
