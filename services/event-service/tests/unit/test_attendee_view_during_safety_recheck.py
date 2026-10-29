"""SCRUM-153 Re-check Safety After High-Impact Changes and SCRUM-150 Approve Operational Safety Check: Event Service unit tests.

Story (SCRUM-153): As an Event Coordinator, I want a safety approval to be withdrawn when a high-impact detail changes afterwards, so that the event is never prepared on the basis of an outdated safety review.
Story (SCRUM-150): As a Safety Officer, I want to approve an event's operational safety arrangements, so that the event can proceed to preparation.
Real:       the Flask route GET /events/attendee-summaries, attendee_view, attendee_baseline and the SQL text.
Doubled:    the PostgreSQL cursor (psycopg2.connect is a MagicMock).
Not proven: SQL execution, the Attendee Registration composite and browser rendering.

SCRUM-153
AC1  Given an event is 'Confirmed', when its date/time, expected attendance, venue requirements, equipment requirements or accessibility needs change, then its status returns to 'Pending Safety Check' and the coordinator is told why.
     Not covered here: owned by test_event_details_recheck.py.
AC2  Given only a low-impact field changes (name, description, purpose, registration needs), then the event stays 'Confirmed'.
     Not covered here: owned by test_event_details_recheck.py.
AC3  Given a safety approval is withdrawn, then it stays visible in the event's safety history.
     Not covered here: owned by test_event_details_recheck.py.
AC4  Given a high-impact change to a 'Confirmed' event is waiting for its new safety check, when a registered Attendee views the event, then they still see the previously approved details, and the changed details are shown to them only after the Safety Officer approves the new safety check.
AC5  Given the new safety check ends without approval (changes requested or the event is cancelled), then registered Attendees are never shown the unapproved change, and they continue to see the last approved details or the cancellation.
SCRUM-150
AC1  Given an event is 'Pending Safety Check', when I approve it, then its status changes to 'Confirmed'.
     Not covered here: owned by test_safety_approve_status.py.
AC2  Given I approve an event, then the safety check is recorded with the status 'Safety Approved', together with my identity, the approval timestamp and any optional remarks, in the event's history.
     Not covered here: owned by test_safety_approve_status.py.
AC3  Given an event is not 'Pending Safety Check', then the approve action is not available and an API call is rejected without changing the event.
     Not covered here: owned by test_safety_approve_status.py.
AC4  Given the safety check I approve follows a high-impact change, when I approve it, then the changed details become visible to registered Attendees.
AC = acceptance criterion; DR = supporting design rule.
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


# AC4 ----
def test_ac4_pending_recheck_shows_attendees_the_approved_schedule_and_venue(setup):
    """Normal: a Confirmed event took a high-impact time edit and now waits for round 2.
    The live row already holds the new 2030-03-02 window; attendees must still get the
    approved 2030-03-01 window and the venue they registered for.
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = [
        attendee_summary_row("Pending Safety Check", [approval_entry(), baseline_entry()])
    ]

    [event] = attendee_summary(client)

    assert event["startTime"] == APPROVED["startTime"]
    assert event["endTime"] == APPROVED["endTime"]
    assert event["attendeeVenueName"] == "Hall A"
    assert event["status"] == "Pending Safety Check"


@pytest.mark.parametrize("start,end", [
    ("2030-03-01T09:00:00+08:00", "2030-03-01T17:00:00+08:00"),
    ("2030-03-01T01:00:00+00:00", "2030-03-01T09:00:00+00:00"),
])
def test_ac4_baseline_offset_is_returned_in_the_summary_local_format(setup, start, end):
    """Boundary: the baseline is stored with an offset (normally +08:00, here also UTC).
    Both must come back as naive Singapore local time, exactly _summary's format, or a
    pending event would show attendees a time eight hours off.
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = [
        attendee_summary_row("Pending Safety Check", [approval_entry(), baseline_entry(start=start, end=end)])
    ]

    [event] = attendee_summary(client)

    assert (event["startTime"], event["endTime"]) == ("2030-03-01T09:00:00", "2030-03-01T17:00:00")


def test_ac4_baseline_without_dates_keeps_live_dates_but_approved_venue(setup):
    """Boundary: a baseline captured from an event with no dates holds only venueName.
    The live window is shown (there is no approved one to fall back to); the venue is the approved one.
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = [
        attendee_summary_row("Pending Safety Check", [approval_entry(), baseline_entry(start=None, end=None)])
    ]

    [event] = attendee_summary(client)

    assert (event["startTime"], event["endTime"]) == (LIVE["startTime"], LIVE["endTime"])
    assert event["attendeeVenueName"] == "Hall A"


def test_ac4_attendee_response_exposes_no_pending_values_or_history(setup):
    """Conflict: the metadata carries remarks, the action history, changed fields and the
    new times. Attendees get exactly the summary keys plus attendeeVenueName, nothing else.
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = [attendee_summary_row("Pending Safety Check", [
        approval_entry(remarks="Officer note"),
        baseline_entry(changedFields=["preferredStartDate", "preferredEndDate"],
                       highImpactFields=["preferredStartDate"], remarks="Internal remark",
                       pending={"preferredStartDate": "2030-03-02T09:00:00"}),
    ])]

    assert attendee_summary(client) == [{
        "id": EVENT, "eventName": "Workshop", "status": "Pending Safety Check",
        "coordinatorId": COORDINATOR, **APPROVED, "attendeeVenueName": "Hall A",
    }]


# AC5 ----
def test_ac5_changes_requested_keeps_the_first_baseline_across_later_edits(setup):
    """Normal: the Safety Officer requested changes and the coordinator kept editing.
    Later edit entries carry no baseline, so baseline A (the approved facts) still applies.
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = [attendee_summary_row("Safety Changes Requested", [
        approval_entry(),
        baseline_entry(),
        dict(status="Safety Changes Requested", safetyCheckId=SECOND_ROUND, remarks="Fix exits"),
        dict(status="Safety Changes Requested", details="Event details updated: Name.", changedFields=["eventName"]),
        dict(status="Safety Changes Requested", details="Event details updated: Start.",
             changedFields=["preferredStartDate"]),
    ])]

    [event] = attendee_summary(client)

    assert {key: event[key] for key in ("startTime", "endTime", "attendeeVenueName")} == {
        **APPROVED, "attendeeVenueName": "Hall A"}


def test_ac5_second_withdrawal_before_any_approval_keeps_the_earliest_baseline(setup):
    """Boundary: a venue-change withdrawal (baseline A) is followed, before any new approval,
    by a time edit that records baseline B. A is what attendees last saw approved; never B.
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = [attendee_summary_row("Pending Safety Check", [
        approval_entry(),
        baseline_entry(status="Approved", withdrawnSafetyCheckId=ROUND),
        dict(status="Pending Safety Check", safetyCheckId=SECOND_ROUND),
        baseline_entry(start="2030-03-05T09:00:00+08:00", end="2030-03-05T17:00:00+08:00", venue="Hall B"),
    ])]

    [event] = attendee_summary(client)

    assert {key: event[key] for key in ("startTime", "endTime", "attendeeVenueName")} == {
        **APPROVED, "attendeeVenueName": "Hall A"}


def test_ac5_cancelled_after_recheck_shows_approved_details_with_cancellation(setup):
    """Normal: the re-check ends in rejection, so the event is Cancelled. Attendees see the
    cancellation together with the approved details, never the rejected change.
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = [attendee_summary_row("Cancelled", [
        approval_entry(), baseline_entry(), dict(status="Cancelled", safetyCheckId=SECOND_ROUND, remarks="Unsafe"),
    ])]

    [event] = attendee_summary(client)

    assert event["status"] == "Cancelled"
    assert {key: event[key] for key in ("startTime", "endTime", "attendeeVenueName")} == {
        **APPROVED, "attendeeVenueName": "Hall A"}


def test_ac5_venue_change_withdrawal_shows_the_approved_venue(setup):
    """Normal: the SCRUM-28 path withdraws the approval back to 'Approved' while Venue Staff
    re-review the booking. Attendees keep the approved venue and window.
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = [attendee_summary_row("Approved", [
        approval_entry(), baseline_entry(status="Approved", withdrawnSafetyCheckId=ROUND),
    ])]

    [event] = attendee_summary(client)

    assert {key: event[key] for key in ("startTime", "endTime", "attendeeVenueName")} == {
        **APPROVED, "attendeeVenueName": "Hall A"}


# SCRUM-150 AC4 ----
def test_scrum150_ac4_approval_after_recheck_releases_the_new_details(setup):
    """Normal: the Safety Officer approves round 2. The new Confirmed entry ends the
    baseline, so attendees now get the live (changed) window and no venue override.
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = [attendee_summary_row("Confirmed", [
        approval_entry(), baseline_entry(), approval_entry(round_id=SECOND_ROUND),
    ])]

    [event] = attendee_summary(client)

    assert (event["startTime"], event["endTime"]) == (LIVE["startTime"], LIVE["endTime"])
    assert event["attendeeVenueName"] is None


def test_scrum150_ac4_restored_approval_also_ends_the_overlay(setup):
    """Boundary: a venue-change withdrawal is undone, restoring the same approval round.
    The restore entry is 'Confirmed', so the overlay ends exactly as for a fresh approval.
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = [attendee_summary_row("Confirmed", [
        approval_entry(),
        baseline_entry(status="Approved", withdrawnSafetyCheckId=ROUND),
        approval_entry(restoredSafetyCheckId=ROUND),
    ])]

    [event] = attendee_summary(client)

    assert (event["startTime"], event["endTime"]) == (LIVE["startTime"], LIVE["endTime"])
    assert event["attendeeVenueName"] is None


# DR ----
@pytest.mark.parametrize("status,history,description", [
    ("Confirmed", [], None),
    ("Pending Safety Check", [dict(status="Pending Safety Check", safetyCheckId=ROUND)], None),
    ("Pending Safety Check", None, "plain legacy description"),
    ("Pending Safety Check", None,
     '{"_connectsphere": "event-submission-v1", "description": "Workshop", "purpose": "Learning"}'),
    ("Confirmed", [approval_entry(), baseline_entry(status="Approved")], None),
], ids=["no-history", "first-submission", "non-json", "no-action-history", "confirmed-row-wins"])
def test_dr_event_never_withdrawn_or_legacy_metadata_shows_live_values(setup, status, history, description):
    """Boundary: with no recorded baseline (never withdrawn, first-time submission, or
    legacy metadata) there is nothing to fall back to, so the live values are shown.
    A Confirmed row also wins over a stray baseline its history never closed.
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = [attendee_summary_row(status, history, description=description)]

    [event] = attendee_summary(client)

    assert (event["startTime"], event["endTime"]) == (LIVE["startTime"], LIVE["endTime"])
    assert event["attendeeVenueName"] is None


def test_dr_request_selects_description_excludes_drafts_and_passes_ids(setup):
    """Normal: two ids. The query reads the metadata column, never returns drafts, and
    the response keeps the database row order.
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = [
        attendee_summary_row("Confirmed", [], event_id=OTHER),
        attendee_summary_row("Confirmed", []),
    ]

    events = attendee_summary(client, EVENT, OTHER)

    sql, params = cursor.execute.call_args[0]
    assert "description" in sql and NOT_DRAFT in sql
    assert params == [[EVENT, OTHER]]
    assert [event["id"] for event in events] == [OTHER, EVENT]


@pytest.mark.parametrize("query", ["", "?ids=", "?ids=nope", f"?ids={EVENT},nope", "?ids=" + ",".join([EVENT] * 101)])
def test_dr_missing_or_invalid_ids_are_rejected_before_any_query(setup, query):
    """Failure: no ids, a non-UUID, a mixed list or more than 100 ids are all a 400."""
    client, _, connect = setup
    assert client.get(f"/events/attendee-summaries{query}").status_code == 400
    connect.assert_not_called()


def test_dr_missing_database_url_is_503():
    """Failure: without DATABASE_URL the service reports itself unavailable."""
    client = signed_in(create_app({"DATABASE_URL": None}).test_client())
    assert client.get(f"/events/attendee-summaries?ids={EVENT}").status_code == 503


def test_dr_staff_summaries_still_show_live_values_during_recheck(setup):
    """Conflict: the same pending row read through GET /events/summaries (staff screens).
    Staff keep the live, changed values and never receive attendeeVenueName.
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = [
        attendee_summary_row("Pending Safety Check", [approval_entry(), baseline_entry()])
    ]

    response = client.get(f"/events/summaries?ids={EVENT}")

    assert response.status_code == 200
    [event] = response.json["events"]
    assert (event["startTime"], event["endTime"]) == (LIVE["startTime"], LIVE["endTime"])
    assert "attendeeVenueName" not in event
