"""SCRUM-168 Safety Check Notifications: notification-service unit tests.

Story:      As a Safety Officer or Event Coordinator, I want to receive notifications when a safety review requires my action or a safety decision is recorded, so that I can respond promptly.
Real:       Notification consumer, envelope validation and storage SQL.
Doubled:    PostgreSQL connection/cursor and broker ACK channel.
Not proven: authentication, hosted permissions, live inbox delivery or browser navigation.

AC1  Given an event is submitted or resubmitted for a safety check, then Safety Officers receive an in-app notification with the event name, date and a link to the review.
Coverage: Inbox INSERT/ACK contract only; Event/Workflow tests verify triggering and preparation.
AC2  Given a decision is recorded, the assigned Event Coordinator receives an in-app notification containing the event name and decision (approval, rejection, or requested changes). Rejection and requested-changes notifications include the reason. Requested-changes notifications include the affected areas. Approval notifications include remarks when provided.
Coverage: Supplied decision payload only; Event/Workflow tests verify construction and recipient.
AC3  Given notification delivery fails, then the decision remains recorded and is not rolled back.
Coverage: Not covered here: Event integration and Workflow unit tests verify persistence and retry.
AC4  Given a notification is sent, then it records the event, recipient, type and timestamp.
Coverage: Inbox SQL parameters retain the envelope; no PostgreSQL commit is proven here.

AC = acceptance criterion; DR = supporting design rule. Automatic rechecks and
fixed coordinator recipients are agreed DRs, not extra ACs or switching scenarios.
"""
import json
from unittest.mock import MagicMock, Mock, patch

import pytest
from app.consumer import process

ID = '10000000-0000-0000-0000-000000000001'
RECIPIENT = '10000000-0000-0000-0000-000000000004'


# AC1 / AC2 / AC4 ---- inbox storage contract
@pytest.mark.parametrize('kind,details,message', [
    ('safety.review-submitted', dict(round=1, startDateTime='2030-03-01T09:00:00+08:00',
                                    endDateTime='2030-03-01T17:00:00+08:00'),
     'Workshop requires safety review (round 1). Proposed: 01 Mar 2030, 09:00 SGT – 01 Mar 2030, 17:00 SGT.'),
    ('safety.review-decision', dict(round=1, decision='Changes Requested', reason='Revise the plan.',
                                   areas=['venue arrangement', 'event details']),
     'Workshop safety review: Changes Requested (round 1). Revise the plan. Affected areas: venue arrangement, event details.'),
], ids=['officer-review', 'coordinator-decision'])
def test_ac1_ac2_ac4_existing_consumer_keeps_safety_payload_before_ack(kind, details, message):
    """Normal: AC1/AC2/AC4: both safety types keep their complete envelope in inbox INSERT before ACK."""
    envelope = dict(version=1, id=ID, type=kind, recipientId=RECIPIENT,
                    createdAt='2026-10-28T00:00:00+00:00', message=message,
                    destination=dict(kind='event-details', eventId=ID),
                    details=dict(eventId=ID, eventName='Workshop', recipientId=RECIPIENT, **details))
    connection, channel = MagicMock(), Mock()
    cursor = connection.cursor.return_value.__enter__.return_value
    effects = []
    connection.__exit__.side_effect = lambda *args: effects.append('transaction-exit')
    channel.basic_ack.side_effect = lambda **kwargs: effects.append('ack')
    with patch('psycopg2.connect', return_value=connection):
        process('unused', channel, Mock(delivery_tag=12), json.dumps(envelope).encode())
    inserts = [call.args[1] for call in cursor.execute.call_args_list
               if call.args[0].startswith('INSERT INTO public."Notification" ')]
    assert len(inserts) == 1
    assert inserts[0][5].adapted == envelope
    assert effects == ['transaction-exit', 'ack']
