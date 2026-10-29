"""SCRUM-166 — Receive assignment notifications.

As an Event Coordinator, I want to receive in-app notifications when I am assigned to or removed from an event, so that I know which events I am responsible for.

- **AC1:** Given the Lead Coordinator successfully assigns an Event Coordinator to an event that previously had no assigned coordinator, the assigned coordinator receives an in-app assignment notification.
- **AC2:** Given the Lead Coordinator successfully reassigns an event from one coordinator to a different coordinator:
  - The new coordinator receives an in-app notification that they have been assigned.
  - The previous coordinator receives an in-app notification that they have been removed.
- **AC3:** Assignment notifications include the event name, Event Organiser name, proposed event date/time, and a link to view the newly assigned event.
- **AC4:** Removal notifications include the event name, Event Organiser name, proposed event date/time, and a clear statement that the recipient is no longer assigned to the event.
- **AC5:** Saving an assignment without changing the assigned coordinator does not create new assignment or removal notifications.

AC = acceptance criterion; DR = supporting design rule.
AC1/AC2: assignment SQL fanout is covered here; Event integration verifies
committed atomic obligations and Notification integration verifies inboxes.
AC3/AC4: owner freeze validation only; Workflow tests verify name enrichment and
frontend components verify presentation. AC5: covered here before SQL writes.

Real: Event assignment business decision. Doubled: PostgreSQL connection/cursor.
Not proven: transaction persistence, composite eligibility or inbox delivery.
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
def test_ac1_ac2_successful_assignment_records_exact_recipient_fanout(previous):
    """Initial assignment or reassignment retains organiser work and captured recipients.
    SQL receives distinct IDs and exact historical event facts for each obligation.
    """
    assigned = {column: "" for column in FIELDS.values()}
    assigned.update(event_id=EVENT, event_name="Community Workshop", status="Under Review",
                    coordinator_id=RECIPIENT, organiser_id=ORGANISER, submission_date=None,
                    preferred_start_date=datetime(2030, 3, 1, 1, tzinfo=UTC),
                    preferred_end_date=datetime(2030, 3, 1, 9, tzinfo=UTC))
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [dict(coordinator_id=previous, status="Submitted"), assigned]
    with patch("psycopg2.connect", return_value=connection):
        result = update_event_coordinator("synthetic", EVENT, RECIPIENT, ORGANISER)
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


def request_freeze(row, envelope):
    """Execute owner HTTP validation while doubling only the SQL connection."""
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [row, {**row, "envelope": envelope}]
    with patch("psycopg2.connect", return_value=connection):
        client = signed_in(create_app(dict(TESTING=True, DATABASE_URL="synthetic", INTERNAL_SERVICE_TOKEN="test-token")).test_client())
        response = client.post(f"/internal/notification-outbox/{JOB}/freeze",
                               headers={"X-Internal-Token": "test-token"},
                               json=dict(leaseToken=LEASE, envelope=envelope))
    return response, cursor


@pytest.mark.parametrize("removed,scheduled", [(False, True), (True, True), (False, False), (True, False)])
def test_ac3_ac4_owner_accepts_exact_coordinator_content_and_destination(removed, scheduled):
    """Freeze assignment/removal with full SGT or explicitly absent proposed schedule."""
    row, envelope = freeze_case(removed, scheduled)
    response, cursor = request_freeze(row, envelope)
    assert response.status_code == 200
    assert response.json["envelope"] == envelope
    writes = [call for call in cursor.execute.call_args_list if "SET envelope=" in call.args[0]]
    assert len(writes) == 1 and writes[0].args[1][0].adapted == envelope


@pytest.mark.parametrize("defect", ["details", "blank-name", "wrong-message", "changed-event", "removal-link", "assignment-null"])
def test_ac3_ac4_owner_rejects_unusable_or_changed_coordinator_content(defect):
    """Malformed display content or forbidden navigation never reaches a freeze UPDATE."""
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
    response, cursor = request_freeze(row, envelope)
    assert response.status_code == 400
    assert not any("SET envelope=" in call.args[0] for call in cursor.execute.call_args_list)


# AC5 — No-op suppression

def test_ac5_unchanged_coordinator_has_no_write_or_notification():
    """Attempt to save the locked event's existing coordinator.
    Real mutation logic rejects the no-op before any SQL write or notification insert.
    """
    coordinator = "10000000-0000-4000-8000-000000000002"
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = {"coordinator_id": coordinator, "status": "Under Review"}
    with patch("psycopg2.connect", return_value=connection):
        with pytest.raises(NoCoordinatorChangeError):
            update_event_coordinator("synthetic", "30000000-0000-4000-8000-000000000001", coordinator, coordinator)
    assert cursor.execute.call_count == 1
    assert "FOR UPDATE" in cursor.execute.call_args.args[0]



# Supporting design rule — explicit content-only removal contract

def test_dr_removal_without_destination_key_is_rejected():
    """A missing destination is malformed, not deliberate content-only removal.
    Reject it without saving a frozen envelope; explicit null remains valid above.
    """
    row, envelope = freeze_case(True, True)
    del envelope["destination"]
    response, cursor = request_freeze(row, envelope)
    assert response.status_code == 400
    assert not any("SET envelope=" in call.args[0] for call in cursor.execute.call_args_list)


# AC3/AC4 — Owner freeze retains the Singapore period across midnight

@pytest.mark.parametrize("removed", [False, True], ids=["assignment", "removal"])
@pytest.mark.parametrize("start,end", [
    ("2030-03-01T15:59:00+00:00", "2030-03-01T16:00:00+00:00"),
    ("2030-03-01T10:59:00-05:00", "2030-03-02T01:00:00+09:00"),
], ids=["utc-singapore-midnight", "equivalent-mixed-offsets"])
def test_ac3_ac4_owner_freezes_singapore_midnight_period(removed, start, end):
    """Equivalent offset intervals freeze the same Singapore dates without changing captured facts."""
    row, value = freeze_case(removed, True)
    row["source"].update(startDateTime=start, endDateTime=end)
    value["details"].update(startDateTime=start, endDateTime=end)
    action = "You are no longer assigned to" if removed else "You have been assigned to"
    value["message"] = (f"{action} Community Workshop. Event Organiser: Synthetic Organiser. "
        "Proposed: 01 Mar 2030, 23:59 SGT – 02 Mar 2030, 00:00 SGT.")
    response, cursor = request_freeze(row, value)
    assert response.status_code == 200
    assert response.json["envelope"] == value
    writes = [call for call in cursor.execute.call_args_list if "SET envelope=" in call.args[0]]
    assert len(writes) == 1 and writes[0].args[1][0].adapted == value
