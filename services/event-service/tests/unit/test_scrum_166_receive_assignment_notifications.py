"""
SCRUM-166: Receive assignment notifications

User Story
----------
As an Event Coordinator, I want to receive in-app notifications when I am
assigned to or removed from an event, so that I know which events I am
responsible for.

Acceptance Criteria
-------------------
AC1: Given the Lead Coordinator successfully assigns an Event Coordinator to an
     event that previously had no assigned coordinator, the assigned
     coordinator receives an in-app assignment notification.
AC2: Given the Lead Coordinator successfully reassigns an event from one
     coordinator to a different coordinator:
     1. The new coordinator receives an in-app notification that they have been
     assigned.
     2. The previous coordinator receives an in-app notification that they have
     been removed.
AC3: Assignment notifications include the event name, Event Organiser name,
     proposed event date/time, and a link to view the newly assigned event.
AC4: Removal notifications include the event name, Event Organiser name,
     proposed event date/time, and a clear statement that the recipient is no
     longer assigned to the event.
AC5: Saving an assignment without changing the assigned coordinator does not
     create new assignment or removal notifications.

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

from datetime import datetime, UTC
from app import create_app
from unittest.mock import MagicMock, patch
import pytest
from app.models import FIELDS, update_event_coordinator, NoCoordinatorChangeError
from tests.unit.factories import signed_in


EVENT = "30000000-0000-4000-8000-000000000001"
RECIPIENT = "10000000-0000-4000-8000-000000000002"
PREVIOUS = "10000000-0000-4000-8000-000000000003"
ORGANISER = "10000000-0000-4000-8000-000000000001"
JOB = "40000000-0000-4000-8000-000000000001"
LEASE = "50000000-0000-4000-8000-000000000001"


# AC1/AC2 — Successful assignment creates exact independent recipient obligations

@pytest.mark.parametrize("previous", [None, PREVIOUS], ids=["initial", "reassignment"])
def test_ac1_ac2_assignment_queues_notifications_for_the_new_coordinator_and_on_reassignment_the_previous_one(previous, mocker):
    """
    Summary: update_event_coordinator, for an event with no coordinator (initial) or with PREVIOUS (reassignment), inserts outbox rows in order: an organiser notice, an "event.coordinator-assigned" row for the new coordinator and, only on reassignment, an "event.coordinator-removed" row for the previous one. The assigned and removed rows capture event name, organiser id and the start/end shown in Singapore time; every row has its own id, and exactly one UPDATE sets the coordinator.
    AC1: Given the Lead Coordinator successfully assigns an Event Coordinator
        to an event that previously had no assigned coordinator, the assigned
        coordinator receives an in-app assignment notification.
    AC2: Given the Lead Coordinator successfully reassigns an event from one
        coordinator to a different coordinator:
        1. The new coordinator receives an in-app notification that they have
        been assigned.
        2. The previous coordinator receives an in-app notification that they
        have been removed.
    Double: Stub (psycopg2.connect patched to a MagicMock connection; cursor.fetchone returns the locked row, then the updated row),
        Mock (the INSERT INTO EventNotificationOutbox and UPDATE public."Event" calls' parameters asserted)
    """
    # Arrange (Given)
    assigned = {column: "" for column in FIELDS.values()}
    assigned.update(event_id=EVENT, event_name="Community Workshop", status="Under Review",
                    coordinator_id=RECIPIENT, organiser_id=ORGANISER, submission_date=None,
                    preferred_start_date=datetime(2030, 3, 1, 1, tzinfo=UTC),
                    preferred_end_date=datetime(2030, 3, 1, 9, tzinfo=UTC))
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [dict(coordinator_id=previous, status="Submitted"), assigned]

    # Act (When)
    mocker.patch("psycopg2.connect", return_value=connection)
    result = update_event_coordinator("synthetic", EVENT, RECIPIENT, ORGANISER)

    # Assert (Then)
    assert result["coordinatorId"] == RECIPIENT
    inserts = [call.args[1] for call in cursor.execute.call_args_list
               if 'INSERT INTO public."EventNotificationOutbox"' in call.args[0]]
    expected = [("event.coordinator-assignment", dict(eventId=EVENT, eventName="Community Workshop",
                 recipientId=ORGANISER, coordinatorId=RECIPIENT)),
                ("event.coordinator-assigned", dict(eventId=EVENT, eventName="Community Workshop",
                 organiserId=ORGANISER, recipientId=RECIPIENT,
                 startDateTime="2030-03-01T09:00:00+08:00", endDateTime="2030-03-01T17:00:00+08:00"))]
    if previous:
        expected.append(("event.coordinator-removed", dict(eventId=EVENT, eventName="Community Workshop",
                         organiserId=ORGANISER, recipientId=PREVIOUS,
                         startDateTime="2030-03-01T09:00:00+08:00", endDateTime="2030-03-01T17:00:00+08:00")))
    assert [(kind, facts.adapted) for _, kind, facts in inserts] == expected
    assert len({identifier for identifier, _, _ in inserts}) == len(expected)
    updates = [call for call in cursor.execute.call_args_list if 'UPDATE public."Event"' in call.args[0]]
    assert len(updates) == 1 and updates[0].args[1] == [RECIPIENT, ORGANISER, EVENT]


# AC3/AC4 — Owner freeze validates captured display content and destination

def freeze_case(removed, scheduled):
    """Independent owner row and client envelope for the freeze boundary."""
    source = dict(eventId=EVENT, recipientId=RECIPIENT, organiserId=ORGANISER,
                  eventName="Community Workshop",
                  startDateTime="2030-03-01T01:00:00+00:00" if scheduled else None,
                  endDateTime="2030-03-01T09:00:00+00:00" if scheduled else None)
    kind = "event.coordinator-removed" if removed else "event.coordinator-assigned"
    period = "01 Mar 2030, 09:00 SGT – 01 Mar 2030, 17:00 SGT" if scheduled else "Not provided"
    action = "You are no longer assigned to" if removed else "You have been assigned to"
    row = dict(source_id=JOB, source=source, type=kind, envelope=None,
               attempts=1, lease_token=LEASE, lease_valid=True, created_at=datetime(2030, 1, 1, tzinfo=UTC))
    envelope = dict(version=1, id=JOB, type=kind, recipientId=RECIPIENT,
                    createdAt="2030-01-01T00:00:00+00:00",
                    message=f"{action} Community Workshop. Event Organiser: Synthetic Organiser. Proposed: {period}.",
                    details={**source, "organiserName": "Synthetic Organiser"},
                    destination=None if removed else dict(kind="event-details", eventId=EVENT))
    return row, envelope


def request_freeze(row, envelope, mocker):
    """Execute owner HTTP validation while doubling only the SQL connection."""
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [row, {**row, "envelope": envelope}]
    mocker.patch("psycopg2.connect", return_value=connection)
    client = signed_in(create_app(dict(TESTING=True, DATABASE_URL="synthetic", INTERNAL_SERVICE_TOKEN="test-token")).test_client())
    response = client.post(f"/internal/notification-outbox/{JOB}/freeze",
                           headers={"X-Internal-Token": "test-token"},
                           json=dict(leaseToken=LEASE, envelope=envelope))
    return response, cursor


@pytest.mark.parametrize("removed,scheduled", [(False, True), (True, True), (False, False), (True, False)])
def test_ac3_ac4_freeze_accepts_assignment_and_removal_envelopes_with_their_content_and_link_rules(removed, scheduled, mocker):
    """
    Summary: Freezing an "event.coordinator-assigned" envelope (message "You have been assigned to ...", event-details link) or an "event.coordinator-removed" envelope (message "You are no longer assigned to ...", no link), each with a full Singapore-time period or "Not provided", answers 200 and stores the envelope unchanged in one "SET envelope=" write.
    AC3: Assignment notifications include the event name, Event Organiser name,
        proposed event date/time, and a link to view the newly assigned event.
    AC4: Removal notifications include the event name, Event Organiser name,
        proposed event date/time, and a clear statement that the recipient is
        no longer assigned to the event.
    Double: Stub (psycopg2.connect patched to a MagicMock connection; cursor.fetchone returns the claimed outbox row, then the same row with the envelope),
        Mock (the "SET envelope=" call's stored envelope asserted equal to the one sent)
    """
    row, envelope = freeze_case(removed, scheduled)
    response, cursor = request_freeze(row, envelope, mocker)
    assert response.status_code == 200
    assert response.json["envelope"] == envelope
    writes = [call for call in cursor.execute.call_args_list if "SET envelope=" in call.args[0]]
    assert len(writes) == 1 and writes[0].args[1][0].adapted == envelope


@pytest.mark.parametrize("defect", ["details", "blank-name", "wrong-message", "changed-event", "removal-link", "assignment-null"])
def test_ac3_ac4_freeze_refuses_envelopes_with_missing_details_blank_organiser_wrong_message_changed_event_or_wrong_link(defect, mocker):
    """
    Summary: A freeze whose details are null, whose organiserName is blank, whose message is unrelated, whose event name differs from the saved one, whose removal envelope carries a link, or whose assignment envelope has no link answers 400 and no "SET envelope=" write runs.
    AC3: Assignment notifications include the event name, Event Organiser name,
        proposed event date/time, and a link to view the newly assigned event.
    AC4: Removal notifications include the event name, Event Organiser name,
        proposed event date/time, and a clear statement that the recipient is
        no longer assigned to the event.
    Double: Stub (psycopg2.connect patched to a MagicMock connection; cursor.fetchone returns the claimed outbox row),
        Mock (no cursor.execute call contains "SET envelope=")
    """
    row, envelope = freeze_case(defect == "removal-link", True)
    if defect == "details":
        envelope["details"] = None
    elif defect == "blank-name":
        envelope["details"]["organiserName"] = " "
    elif defect == "wrong-message":
        envelope["message"] = "Unrelated content"
    elif defect == "changed-event":
        envelope["details"]["eventName"] = "Later event"
    elif defect == "removal-link":
        envelope["destination"] = dict(kind="event-details", eventId=EVENT)
    else:
        envelope["destination"] = None
    response, cursor = request_freeze(row, envelope, mocker)
    assert response.status_code == 400
    assert not any("SET envelope=" in call.args[0] for call in cursor.execute.call_args_list)


# AC5 — No-op suppression

def test_ac5_saving_the_current_coordinator_raises_no_change_and_writes_nothing(mocker):
    """
    Summary: update_event_coordinator, given the coordinator the event already has, raises NoCoordinatorChangeError after the locking SELECT ... FOR UPDATE, so no UPDATE and no outbox row are written.
    AC5: Saving an assignment without changing the assigned coordinator does
        not create new assignment or removal notifications.
    Double: Stub (psycopg2.connect patched to a MagicMock connection; cursor.fetchone returns the locked row already holding that coordinator),
        Mock (cursor.execute call_count is 1 and that call contains FOR UPDATE)
    """
    coordinator = "10000000-0000-4000-8000-000000000002"
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = {"coordinator_id": coordinator, "status": "Under Review"}
    mocker.patch("psycopg2.connect", return_value=connection)
    with pytest.raises(NoCoordinatorChangeError):
        update_event_coordinator("synthetic", "30000000-0000-4000-8000-000000000001", coordinator, coordinator)
    assert cursor.execute.call_count == 1
    assert "FOR UPDATE" in cursor.execute.call_args.args[0]



# Supporting design rule — explicit content-only removal contract

def test_removal_envelope_without_a_destination_key_is_refused(mocker):
    """
    Summary: A removal envelope that omits the destination key altogether (rather than setting it to null) answers 400 and no "SET envelope=" write runs.
    Supporting design check: a removal that deliberately has no link must say so with destination
        null; a missing key is malformed, not a link-free removal
    Double: Stub (psycopg2.connect patched to a MagicMock connection; cursor.fetchone returns the claimed outbox row),
        Mock (no cursor.execute call contains "SET envelope=")
    """
    # Arrange (Given)
    row, envelope = freeze_case(True, True)
    del envelope["destination"]

    # Act (When)
    response, cursor = request_freeze(row, envelope, mocker)

    # Assert (Then)
    assert response.status_code == 400
    assert not any("SET envelope=" in call.args[0] for call in cursor.execute.call_args_list)


# AC3/AC4 — Owner freeze retains the Singapore period across midnight

@pytest.mark.parametrize("removed", [False, True], ids=["assignment", "removal"])
@pytest.mark.parametrize("start,end", [
    ("2030-03-01T15:59:00+00:00", "2030-03-01T16:00:00+00:00"),
    ("2030-03-01T10:59:00-05:00", "2030-03-02T01:00:00+09:00"),
], ids=["utc-singapore-midnight", "equivalent-mixed-offsets"])
def test_ac3_ac4_freeze_keeps_the_singapore_period_across_midnight_for_equivalent_offsets(removed, start, end, mocker):
    """
    Summary: For assignment and removal envelopes, a period of 23:59-00:00 Singapore time given as UTC or as mixed offsets is frozen as "01 Mar 2030, 23:59 SGT – 02 Mar 2030, 00:00 SGT" with the captured details unchanged: answers 200 and stores one "SET envelope=" write.
    AC3: Assignment notifications include the event name, Event Organiser name,
        proposed event date/time, and a link to view the newly assigned event.
    AC4: Removal notifications include the event name, Event Organiser name,
        proposed event date/time, and a clear statement that the recipient is
        no longer assigned to the event.
    Double: Stub (psycopg2.connect patched to a MagicMock connection; cursor.fetchone returns the claimed outbox row, then the same row with the envelope),
        Mock (the "SET envelope=" call's stored envelope asserted equal to the one sent)
    """
    row, value = freeze_case(removed, True)
    row["source"].update(startDateTime=start, endDateTime=end)
    value["details"].update(startDateTime=start, endDateTime=end)
    action = "You are no longer assigned to" if removed else "You have been assigned to"
    value["message"] = (f"{action} Community Workshop. Event Organiser: Synthetic Organiser. "
        "Proposed: 01 Mar 2030, 23:59 SGT – 02 Mar 2030, 00:00 SGT.")
    response, cursor = request_freeze(row, value, mocker)
    assert response.status_code == 200
    assert response.json["envelope"] == value
    writes = [call for call in cursor.execute.call_args_list if "SET envelope=" in call.args[0]]
    assert len(writes) == 1 and writes[0].args[1][0].adapted == value
