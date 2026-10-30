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
- app.consumer.process(): JSON validation, the story's display-contract
  validator and the inbox/quarantine SQL, with the broker ACK only after the
  database commit.
- Assertions are on the SQL and parameters sent, and the ACK and its order.

Doubled
-------
- psycopg2.connect: Stub - fresh MagicMock connection and cursor per test; SQL
  inspected.
- Broker channel: Mock - asserts basic_ack after the commit.

Not proven
----------
- That the inbox row is committed and de-duplicated in real PostgreSQL (->
  tests/integration/, throwaway postgres:17.6).
- That the producer publishes this envelope and the UI shows it with a working
  link (-> the producing service dispatcher tests and the frontend
  NotificationCenter tests).
- That no notice is created when the assignment does not change (AC5) (->
  event-service unit tests for SCRUM-166).
"""

import json
from unittest.mock import MagicMock, Mock, patch
import pytest
from app.consumer import process

EVENT = "30000000-0000-4000-8000-000000000001"
RECIPIENT = "10000000-0000-4000-8000-000000000002"
ORGANISER = "10000000-0000-4000-8000-000000000001"
OTHER = "10000000-0000-4000-8000-000000000003"


def envelope(removed=False, scheduled=True):
    """Build synthetic producer input independently of the consumer implementation."""
    return dict(version=1, id="40000000-0000-4000-8000-000000000001",
                type="event.coordinator-removed" if removed else "event.coordinator-assigned",
                recipientId=RECIPIENT, createdAt="2030-01-01T00:00:00+00:00",
                message="You are no longer assigned to Community Workshop." if removed else "You have been assigned to Community Workshop.",
                destination=None if removed else dict(kind="event-details", eventId=EVENT),
                details=dict(eventId=EVENT, recipientId=RECIPIENT, organiserId=ORGANISER,
                             eventName="Community Workshop", organiserName="Synthetic Organiser",
                             startDateTime="2030-03-01T01:00:00+00:00" if scheduled else None,
                             endDateTime="2030-03-01T09:00:00+00:00" if scheduled else None))


def consume(value):
    """Consume at the public callback seam; capture SQL and commit-before-ACK order."""
    connection, channel = MagicMock(), Mock()
    cursor = connection.cursor.return_value.__enter__.return_value
    order = []
    connection.__exit__.side_effect = lambda *args: order.append("commit")
    channel.basic_ack.side_effect = lambda **kwargs: order.append("ack")
    with patch("psycopg2.connect", return_value=connection):
        process("synthetic", channel, Mock(delivery_tag=42), json.dumps(value).encode())
    channel.basic_ack.assert_called_once_with(delivery_tag=42)
    assert order == ["commit", "ack"]
    return cursor.execute.call_args_list


# AC1/AC2 — Both coordinator delivery types retain their recipient and event reference

@pytest.mark.parametrize("removed,scheduled", [(False, True), (True, True), (False, False), (True, False)], ids=["assigned_scheduled", "removed_scheduled", "assigned_unscheduled", "removed_unscheduled"])
def test_process_assignment_or_removal_alert_stores_before_ack(removed, scheduled):
    """
    Summary: Assignment and removal notices, with or without a scheduled date, are stored for the coordinator before acknowledging.
    AC1: Given the Lead Coordinator successfully assigns an Event Coordinator
        to an event that previously had no assigned coordinator, the assigned
        coordinator receives an in-app assignment notification.
    AC2: Given the Lead Coordinator successfully reassigns an event from one
        coordinator to a different coordinator:
        1. The new coordinator receives an in-app notification that they have
        been assigned.
        2. The previous coordinator receives an in-app notification that they
        have been removed.
    Double: Stub (connection), Mock (channel ACK)
    """
    # Arrange (Given)
    value = envelope(removed, scheduled)
    calls = consume(value)

    # Act (When)
    inserts = [call.args[1] for call in calls if call.args[0].startswith('INSERT INTO public."Notification" ')]

    # Assert (Then)
    assert len(inserts) == 1
    assert inserts[0][2] == RECIPIENT
    assert inserts[0][4] == EVENT
    assert inserts[0][5].adapted == value
    assert not any('NotificationFailure' in call.args[0] for call in calls)


# AC3/AC4 — Malformed content/navigation must quarantine rather than enter the inbox

@pytest.mark.parametrize("defect", [
    "details", "event-name", "organiser-name", "recipient", "event-link", "assignment-null",
    "removal-link", "naive-start", "naive-end", "reversed-period", "half-period", "invalid-id",
], ids=["no_details", "no_event_name", "no_organiser_name", "wrong_recipient", "no_event_link", "null_assignment", "removal_with_link", "naive_start", "naive_end", "reversed_period", "half_period", "invalid_id"])
def test_process_assignment_alert_missing_required_content_is_quarantined(defect):
    """
    Summary: A notice missing the event, organiser, recipient, link or a valid period is kept aside.
    AC3: Assignment notifications include the event name, Event Organiser name,
        proposed event date/time, and a link to view the newly assigned event.
    AC4: Removal notifications include the event name, Event Organiser name,
        proposed event date/time, and a clear statement that the recipient is
        no longer assigned to the event.
    Double: Stub (connection), Mock (channel ACK)
    """
    value = envelope(removed=defect == "removal-link")
    if defect == "details":
        value["details"] = None
    elif defect == "event-name":
        value["details"]["eventName"] = " "
    elif defect == "organiser-name":
        value["details"]["organiserName"] = 7
    elif defect == "recipient":
        value["details"]["recipientId"] = OTHER
    elif defect == "event-link":
        value["destination"]["eventId"] = OTHER
    elif defect == "assignment-null":
        value["destination"] = None
    elif defect == "removal-link":
        value["destination"] = dict(kind="event-details", eventId=EVENT)
    elif defect == "naive-start":
        value["details"]["startDateTime"] = "2030-03-01T01:00:00"
    elif defect == "naive-end":
        value["details"]["endDateTime"] = "2030-03-01T09:00:00"
    elif defect == "reversed-period":
        value["details"]["endDateTime"] = "2030-03-01T00:00:00+00:00"
    elif defect == "half-period":
        value["details"]["startDateTime"] = None
    else:
        value["details"]["organiserId"] = "not-a-uuid"
    calls = consume(value)
    assert not any(call.args[0].startswith('INSERT INTO public."Notification" ') for call in calls)
    failures = [call for call in calls if 'INSERT INTO public."NotificationFailure"' in call.args[0]]
    assert len(failures) == 1


# AC3/AC4 — Compare proposed periods by actual instants, not local clock text

@pytest.mark.parametrize("removed", [False, True], ids=["assignment", "removal"])
@pytest.mark.parametrize("start,end,accepted", [
    ("2030-03-01T23:30:00+08:00", "2030-03-01T16:00:00+00:00", True),
    ("2030-03-01T10:00:00+00:00", "2030-03-01T11:00:00+08:00", False),
    ("2030-03-01T08:00:00+08:00", "2030-03-01T00:00:00+00:00", False),
], ids=["local-text-reversed-but-instants-increase", "local-text-increases-but-instants-reverse",
        "different-offsets-same-instant"])
def test_process_assignment_alert_compares_period_by_actual_instant(removed, start, end, accepted):
    """
    Summary: A start and end in different time zones are ordered by the real moment, not the clock text.
    AC3: Assignment notifications include the event name, Event Organiser name,
        proposed event date/time, and a link to view the newly assigned event.
    AC4: Removal notifications include the event name, Event Organiser name,
        proposed event date/time, and a clear statement that the recipient is
        no longer assigned to the event.
    Double: Stub (connection), Mock (channel ACK)
    """
    value = envelope(removed)
    value["details"].update(startDateTime=start, endDateTime=end)
    calls = consume(value)
    inbox = [call.args[1] for call in calls
             if call.args[0].startswith('INSERT INTO public."Notification" ')]
    failures = [call for call in calls if 'INSERT INTO public."NotificationFailure"' in call.args[0]]
    assert len(inbox) == (1 if accepted else 0)
    assert len(failures) == (0 if accepted else 1)
    if accepted:
        assert inbox[0][5].adapted == value
