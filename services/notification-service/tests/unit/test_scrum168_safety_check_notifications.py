"""SCRUM-168: Safety Check Notifications

User Story
----------
As an Event Coordinator, I want to be notified of the Safety Officer's decision on my event, so that I can act on it straight away.

Acceptance Criteria
-------------------
AC1: Given an event is submitted or resubmitted for a safety check, then Safety Officers receive an in-app notification with the event name, date and a link to the review.
AC2: Given a decision is recorded, then the assigned Event Coordinator receives an in-app notification with the event name, the decision and, for rejection or requested changes, the reason and affected areas.
AC3: Given notification delivery fails, then the decision remains recorded and is not rolled back.
AC4: Given a notification is sent, then it records the event, recipient, type and timestamp.

Real
----
- app.consumer.process() with safety-check envelopes: validation and the inbox
  INSERT, with the ACK only after storage.
- Assertions are on the stored row and the ACK.

Doubled
-------
- psycopg2.connect: Stub - MagicMock connection and cursor; SQL inspected.
- Broker channel: Mock - asserts basic_ack.

Not proven
----------
- AC1: Incoming safety-submission payload is passed through to inbox SQL.
- AC2: Incoming Changes Requested content is passed through; type-specific validation, all decision outcomes and PostgreSQL safety delivery are UNTESTED here.
- AC3: Outside this owner: Safety Check/Event keep business decisions despite delivery failure.
- AC4: SQL event/recipient/type/timestamp contract is checked; persisted safety records are UNTESTED here.
- Real PostgreSQL evidence exists only in the maintained SCRUM-45/47/49/166 integration modules; neither their success nor parser acceptance proves all notification types or producer fan-out.
- Broker delivery, other service code and browser navigation are NOT COVERED ANYWHERE in this module.
- Pagination, read/unread controls, legacy rows, quarantine diagnostics, process wiring and future-type compatibility are useful supporting contracts without their own AC. They are preserved and flagged for a Product Owner decision, not relabelled as new acceptance criteria.
"""
import json
from unittest.mock import MagicMock, Mock, patch

import pytest
from app.consumer import process

ID = '10000000-0000-0000-0000-000000000001'
RECIPIENT = '10000000-0000-0000-0000-000000000004'


@pytest.mark.parametrize('kind,details,message', [
    ('safety.review-submitted', dict(round=1, startDateTime='2030-03-01T09:00:00+08:00',
                                    endDateTime='2030-03-01T17:00:00+08:00'),
     'Workshop requires safety review (round 1). Proposed: 01 Mar 2030, 09:00 SGT – 01 Mar 2030, 17:00 SGT.'),
    ('safety.review-decision', dict(round=1, decision='Changes Requested', reason='Revise the plan.',
                                   areas=['venue arrangement', 'event details']),
     'Workshop safety review: Changes Requested (round 1). Revise the plan. Affected areas: venue arrangement, event details.'),
], ids=['officer-review', 'coordinator-decision'])
def test_process_safety_alert_stores_event_recipient_type_and_time_before_ack(kind, details, message, mocker):
    """Summary: Safety review and decision alerts are stored with event, recipient, type and time before acknowledging.
AC1: Given an event is submitted or resubmitted for a safety check, then Safety Officers receive an in-app notification with the event name, date and a link to the review.
AC2: Given a decision is recorded, then the assigned Event Coordinator receives an in-app notification with the event name, the decision and, for rejection or requested changes, the reason and affected areas.
AC4: Given a notification is sent, then it records the event, recipient, type and timestamp.
Double: Stub (connection), Mock (channel ACK)
"""
    # Arrange (Given)
    envelope = dict(version=1, id=ID, type=kind, recipientId=RECIPIENT,
                    createdAt='2026-10-28T00:00:00+00:00', message=message,
                    destination=dict(kind='event-details', eventId=ID),
                    details=dict(eventId=ID, eventName='Workshop', recipientId=RECIPIENT, **details))
    connection, channel = MagicMock(), Mock()
    cursor = connection.cursor.return_value.__enter__.return_value
    effects = []
    connection.__exit__.side_effect = lambda *args: effects.append('transaction-exit')
    channel.basic_ack.side_effect = lambda **kwargs: effects.append('ack')
    mocker.patch('psycopg2.connect', return_value=connection)
    process('unused', channel, Mock(delivery_tag=12), json.dumps(envelope).encode())

    # Act (When)
    inserts = [call.args[1] for call in cursor.execute.call_args_list
               if call.args[0].startswith('INSERT INTO public."Notification" ')]

    # Assert (Then)
    assert len(inserts) == 1
    assert inserts[0][:5] == (ID, ID, RECIPIENT, kind, ID)
    assert inserts[0][5].adapted == envelope
    assert inserts[0][6:] == (ID, "2026-10-28T00:00:00+00:00")
    channel.basic_ack.assert_called_once_with(delivery_tag=12)
    assert effects == ['transaction-exit', 'ack']
