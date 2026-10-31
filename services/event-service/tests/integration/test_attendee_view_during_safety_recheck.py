"""SCRUM-153 Re-check Safety After High-Impact Changes and SCRUM-150 Approve Operational Safety Check: Event Service integration tests.

Story (SCRUM-153): As an Event Coordinator, I want a safety approval to be withdrawn when a high-impact detail changes afterwards, so that the event is never prepared on the basis of an outdated safety review.
Story (SCRUM-150): As a Safety Officer, I want to approve an event's operational safety arrangements, so that the event can proceed to preparation.
Real:       the Flask app and routes, app/models.py SQL, and postgres:17.6 with the full unmodified migration chain.
Doubled:    the venue names the Safety Check composite would supply (venueBefore, attendeeVenue), passed as request inputs.
Not proven: the Safety Check composite's venue lookup, the Attendee Registration composite, the browser, and authentication.

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
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from tests.integration.factories import SAFETY_COORDINATOR, make_event_change_event, make_safety_event

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
BUSINESS = {"X-Internal-Token": "synthetic"}
APPROVED = ("2030-03-01T09:00:00", "2030-03-01T17:00:00")
NEW = ("2030-03-02T09:00:00", "2030-03-02T18:00:00")


def recheck_pending(client, db):
    """Arrange: confirm round 1 through the real HTTP API, then make a high-impact time edit
    that withdraws it and opens round 2, exactly as Safety Check Service sends it.
    Returns `(event, safety, second_round)`.
    """
    event = make_event_change_event(db)
    first, second = str(uuid4()), str(uuid4())

    def safety(status, round_id, **extra):
        return client.patch(f"/events/{event}/safety-status", headers=BUSINESS, json=dict(
            status=status, safetyCheckId=round_id, roundNumber=1 if round_id == first else 2, **extra))

    assert safety("Pending Safety Check", first, coordinatorId=SAFETY_COORDINATOR).status_code == 200
    assert safety("Confirmed", first, decidedBy=SAFETY_COORDINATOR).status_code == 200
    edited = client.patch(f"/events/{event}/details", headers=BUSINESS, json=dict(
        coordinatorId=SAFETY_COORDINATOR,
        changes={"preferredStartDate": NEW[0], "preferredEndDate": NEW[1]},
        safetyRecheck=dict(withdrawnSafetyCheckId=first, safetyCheckId=second, roundNumber=2,
                           venueBefore="Hall A")))
    assert edited.status_code == 200, edited.json
    assert edited.json["status"] == "Pending Safety Check"
    return event, safety, second


def attendee_summary(client, *ids):
    response = client.get(f"/events/attendee-summaries?ids={','.join(ids)}")
    assert response.status_code == 200, response.json
    return response.json["events"]


def stored(db, event):
    return db.query('SELECT status, preferred_start_date, preferred_end_date FROM public."Event" WHERE event_id=%s',
                    [event])[0]


# AC4 ----
def test_ac4_attendees_see_approved_time_while_recheck_is_pending(event_change_notification_owner):
    """Normal: the time edit is saved and round 2 is open. Attendees get the approved
    window and venue, while the row and the coordinator view hold the new time, which
    proves the overlay is read-side only.
    """
    client, db = event_change_notification_owner
    event, _, _ = recheck_pending(client, db)

    [summary] = attendee_summary(client, event)

    assert (summary["startTime"], summary["endTime"]) == APPROVED
    assert summary["attendeeVenueName"] == "Hall A"
    assert summary["status"] == "Pending Safety Check"
    assert stored(db, event) == ("Pending Safety Check", datetime(2030, 3, 2, 1, tzinfo=UTC),
                                 datetime(2030, 3, 2, 10, tzinfo=UTC))
    coordinator = client.get(f"/events/{event}?coordinatorId={SAFETY_COORDINATOR}")
    assert coordinator.status_code == 200
    assert (coordinator.json["preferredStartDate"], coordinator.json["preferredEndDate"]) == NEW


# AC5 ----
def test_ac5_changes_requested_then_more_edits_never_reach_attendees(event_change_notification_owner):
    """Normal: the Safety Officer requests changes and the coordinator edits the time again.
    Neither edit reaches attendees; the row holds the latest 2030-03-03 time.
    """
    client, db = event_change_notification_owner
    event, safety, second = recheck_pending(client, db)
    requested = safety("Safety Changes Requested", second, decidedBy=SAFETY_COORDINATOR,
                       remarks="Add marshals", areas=["event details"])
    assert requested.status_code == 200, requested.json
    edited = client.patch(f"/events/{event}/details", headers=BUSINESS, json=dict(
        coordinatorId=SAFETY_COORDINATOR, changes={"preferredStartDate": "2030-03-03T09:00:00",
                                                   "preferredEndDate": "2030-03-03T18:00:00"}))
    assert edited.status_code == 200, edited.json

    [summary] = attendee_summary(client, event)

    assert (summary["startTime"], summary["endTime"], summary["attendeeVenueName"]) == (*APPROVED, "Hall A")
    status, start, _ = stored(db, event)
    assert (status, start) == ("Safety Changes Requested", datetime(2030, 3, 3, 1, tzinfo=UTC))


def test_ac5_cancelled_recheck_shows_approved_details_and_cancellation(event_change_notification_owner):
    """Normal: the re-check is rejected and the event is cancelled. Attendees see the
    cancellation with the approved details; SCRUM-46 still queues one cancellation fanout.
    """
    client, db = event_change_notification_owner
    event, safety, second = recheck_pending(client, db)
    db.query('DELETE FROM public."EventNotificationOutbox"')
    cancelled = safety("Cancelled", second, decidedBy=SAFETY_COORDINATOR, remarks="Unsafe")
    assert cancelled.status_code == 200, cancelled.json

    [summary] = attendee_summary(client, event)

    assert summary["status"] == "Cancelled"
    assert (summary["startTime"], summary["endTime"], summary["attendeeVenueName"]) == (*APPROVED, "Hall A")
    assert stored(db, event)[0] == "Cancelled"
    assert db.query('SELECT type FROM public."EventNotificationOutbox" WHERE type LIKE %s',
                    ["attendee.%"]) == [("attendee.cancelled-fanout",)]


# SCRUM-150 AC4 ----
def test_scrum150_ac4_approving_the_recheck_releases_new_time_to_attendees(event_change_notification_owner):
    """Normal: the Safety Officer approves round 2. Attendees now get the new window and
    no venue override, and SCRUM-46's update fanout carries the same before/after pair.
    """
    client, db = event_change_notification_owner
    event, safety, second = recheck_pending(client, db)
    db.query('DELETE FROM public."EventNotificationOutbox"')
    approved = safety("Confirmed", second, decidedBy=SAFETY_COORDINATOR, attendeeVenue="Hall A")
    assert approved.status_code == 200, approved.json

    [summary] = attendee_summary(client, event)

    assert (summary["startTime"], summary["endTime"]) == NEW
    assert summary["attendeeVenueName"] is None
    assert stored(db, event)[0] == "Confirmed"
    rows = db.query('SELECT type, source FROM public."EventNotificationOutbox" WHERE type LIKE %s', ["attendee.%"])
    assert len(rows) == 1 and rows[0][0] == "attendee.updated-fanout"
    assert rows[0][1]["changes"] == dict(
        startDateTime=["2030-03-01T09:00:00+08:00", "2030-03-02T09:00:00+08:00"],
        endDateTime=["2030-03-01T17:00:00+08:00", "2030-03-02T18:00:00+08:00"])


# DR ----
def test_dr_drafts_are_never_returned(event_change_notification_owner):
    """Boundary: a Draft is asked for alongside a pending event; only the pending one returns."""
    client, db = event_change_notification_owner
    event, _, _ = recheck_pending(client, db)
    draft = make_safety_event(db, status="Draft")

    assert [summary["id"] for summary in attendee_summary(client, event, draft)] == [event]
