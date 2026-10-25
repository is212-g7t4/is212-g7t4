"""SCRUM-45 Event Organiser Status and Update Notifications: notification-service unit tests.

Story: As an Event Organiser, I want to receive an in-app notification when the Lead Coordinator approves or rejects my event request, so that I know the outcome and who is responsible for coordinating my event.
Real: own consumer validation and SQL-building storage adapter.
Doubled: PostgreSQL connection/cursor and broker ACK channel.
Not proven: production authentication, hosted Supabase, cross-service delivery or browser navigation.
Owned: incoming display-contract validation and inbox/quarantine SQL requests. Not covered here: committed storage, inbox routes, Event mutation, Workflow publication or UI/E2E.
AC = acceptance criterion; DR = supporting design rule, not an extra AC.

AC1 A successfully recorded approval sends an in-app approval notification to the submitting Event Organiser.
  Owned: Approval validation and inbox INSERT/ACK contract; real SQL commit and upstream trigger/publication are not proven.
AC2 A successfully recorded rejection sends an in-app rejection notification to the submitting Event Organiser, including the rejection reason.
  Owned: Rejection validation and unchanged reason payload at the SQL boundary; real commit and upstream delivery are not proven.
AC3 Both decision notifications include event name, decision, and a link to the event request and its decision details.
  Owned: Decision display-content/destination validation; the target page and its navigation are frontend/Event concerns.
AC4 A successfully recorded initial assignment or reassignment sends the submitting Event Organiser an in-app notification with event name, newly assigned coordinator name, and an event-details link.
  Owned: Named assignment validation and INSERT/ACK contract; initial and replacement messages share this consumer contract. Event mutation, name lookup and real inbox persistence are not proven.
"""
import json

from unittest.mock import MagicMock, Mock, patch

import pytest

from app.consumer import process

approval_ENVELOPE = dict(version=1, id='20000000-0000-0000-0000-000000000001', recipientId='10000000-0000-0000-0000-000000000001', type='event.approval', createdAt='2026-10-21T00:00:00+00:00', message='Community Workshop was approved', destination=dict(kind='event-details', eventId='30000000-0000-0000-0000-000000000001'), details=dict(eventName='Community Workshop', decision='Approved'))

initial_assignment_EVENT = '30000000-0000-0000-0000-000000000001'

initial_assignment_COORDINATOR = '10000000-0000-0000-0000-000000000002'

initial_assignment_ENVELOPE = dict(version=1, id='20000000-0000-0000-0000-000000000001', recipientId='10000000-0000-0000-0000-000000000001', type='event.coordinator-assignment', createdAt='2026-10-21T00:00:00+00:00', message='Alice Tan has been assigned to coordinate Community Workshop.', destination=dict(kind='event-details', eventId=initial_assignment_EVENT), details=dict(eventId=initial_assignment_EVENT, eventName='Community Workshop', coordinatorId=initial_assignment_COORDINATOR, coordinatorName='Alice Tan'))


# AC1 — Approval

def test_ac1_valid_approval_is_persisted_without_losing_content():
    """Normal: consume approval; one inbox INSERT receives the unchanged payload and mocked
    transaction exit precedes ACK, guarding the storage-before-ack contract without claiming a
    real commit.
    """
    connection, channel = (MagicMock(), Mock())
    cursor = connection.cursor.return_value.__enter__.return_value
    events = Mock()
    events.attach_mock(connection, 'database')
    events.attach_mock(channel, 'broker')
    with patch('psycopg2.connect', return_value=connection):
        process('synthetic', channel, Mock(delivery_tag=12), json.dumps(approval_ENVELOPE).encode())
    inserts = [call.args[1] for call in cursor.execute.call_args_list if call.args[0].startswith('INSERT INTO public."Notification" ')]
    assert len(inserts) == 1
    assert inserts[0][5].adapted == approval_ENVELOPE
    names = [call[0] for call in events.mock_calls]
    assert names.index('database.__exit__') < names.index('broker.basic_ack')


# AC2 — Rejection and reason

def test_ac2_rejection_notification_with_event_details_destination_is_stored():
    """Normal: consume rejection with its reason and event-only destination; the unchanged envelope
    reaches an inbox INSERT and ACK rather than quarantine, preserving the organiser's
    explanation and link.
    """
    reason = 'The proposal does not meet the event requirements.'
    envelope = {'version': 1, 'id': '20000000-0000-0000-0000-000000000001', 'recipientId': '10000000-0000-0000-0000-000000000001', 'type': 'event.rejection', 'message': f'Community Workshop was rejected: {reason}', 'createdAt': '2026-10-21T01:00:00+00:00', 'destination': {'kind': 'event-details', 'eventId': '30000000-0000-0000-0000-000000000001'}, 'details': {'eventName': 'Community Workshop', 'reason': reason}}
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    channel = Mock()
    with patch('psycopg2.connect', return_value=connection):
        process('synthetic', channel, Mock(delivery_tag=9), json.dumps(envelope).encode())
    inbox_inserts = [call.args[1] for call in cursor.execute.call_args_list if call.args[0].startswith('INSERT INTO public."Notification" ')]
    assert len(inbox_inserts) == 1, 'Rejection must reach inbox storage, not quarantine'
    persisted_envelope = inbox_inserts[0][5].adapted
    assert persisted_envelope == envelope
    channel.basic_ack.assert_called_once_with(delivery_tag=9)


# AC3 — Decision content and link

@pytest.mark.parametrize('change', [{'details': {}}, {'details': {'eventName': ' ', 'decision': 'Approved'}}, {'details': {'eventName': 'Community Workshop', 'decision': 'Rejected'}}, {'destination': {'kind': 'event-venue-request', 'eventId': '30000000-0000-0000-0000-000000000001', 'bookingId': '40000000-0000-0000-0000-000000000001'}}])
def test_ac3_invalid_approval_display_contract_is_quarantined(change):
    """Failure: consume approval with missing or inconsistent display content/link; only quarantine
    SQL and ACK are requested, preventing unusable approval messages from entering the inbox.
    """
    connection, channel = (MagicMock(), Mock())
    cursor = connection.cursor.return_value.__enter__.return_value
    with patch('psycopg2.connect', return_value=connection):
        process('synthetic', channel, Mock(delivery_tag=11), json.dumps({**approval_ENVELOPE, **change}).encode())
    assert not any((call.args[0].startswith('INSERT INTO public."Notification" ') for call in cursor.execute.call_args_list))
    assert any(('NotificationFailure' in call.args[0] for call in cursor.execute.call_args_list))
    channel.basic_ack.assert_called_once_with(delivery_tag=11)

@pytest.mark.parametrize('change', [{'details': {}}, {'details': {'eventName': 'Workshop', 'reason': ' '}}, {'details': {'eventName': ' ', 'reason': 'No plan'}}, {'destination': {'kind': 'event-venue-request', 'eventId': '30000000-0000-0000-0000-000000000001', 'bookingId': '40000000-0000-0000-0000-000000000001'}}])
def test_ac3_rejection_missing_display_content_or_event_destination_is_quarantined(change):
    """Failure: consume rejection without usable event/reason content or an event-details link;
    quarantine SQL replaces inbox insertion and ACK follows, keeping malformed messages out of
    the organiser's inbox.
    """
    envelope = dict(version=1, id='20000000-0000-0000-0000-000000000001', recipientId='10000000-0000-0000-0000-000000000001', type='event.rejection', createdAt='2026-10-21T01:00:00+00:00', message='Workshop was rejected: No plan', destination=dict(kind='event-details', eventId='30000000-0000-0000-0000-000000000001'), details=dict(eventName='Workshop', reason='No plan'))
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    channel = Mock()
    with patch('psycopg2.connect', return_value=connection):
        process('synthetic', channel, Mock(delivery_tag=10), json.dumps({**envelope, **change}).encode())
    assert not any((call.args[0].startswith('INSERT INTO public."Notification" ') for call in cursor.execute.call_args_list))
    assert any(('NotificationFailure' in call.args[0] for call in cursor.execute.call_args_list))
    channel.basic_ack.assert_called_once_with(delivery_tag=10)


# AC4 — Initial assignment and reassignment

@pytest.mark.parametrize('change', [{'details': {}}, {'details': None}, {'details': {**initial_assignment_ENVELOPE['details'], 'coordinatorName': ' '}}, {'details': {**initial_assignment_ENVELOPE['details'], 'eventName': ' '}}, {'destination': dict(kind='event-venue-request', eventId=initial_assignment_EVENT, bookingId=initial_assignment_COORDINATOR)}])
def test_ac4_assignment_without_required_display_content_is_quarantined(change):
    """Failure: consume assignment without required display content or the correct destination;
    quarantine SQL and ACK replace inbox insertion, preventing nameless or unopenable assignment
    notifications.
    """
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    channel = Mock()
    with patch('psycopg2.connect', return_value=connection):
        process('synthetic', channel, Mock(delivery_tag=10), json.dumps({**initial_assignment_ENVELOPE, **change}).encode())
    assert not any((call.args[0].startswith('INSERT INTO public."Notification" ') for call in cursor.execute.call_args_list))
    assert any(('NotificationFailure' in call.args[0] for call in cursor.execute.call_args_list))
    channel.basic_ack.assert_called_once_with(delivery_tag=10)

def test_ac4_named_assignment_is_persisted_before_acknowledgement():
    """Normal: consume a named assignment; one inbox INSERT keeps the full envelope and mocked
    transaction exit precedes ACK, protecting the store-before-ack contract without proving a
    PostgreSQL commit.
    """
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    channel = Mock()
    order = []
    connection.__exit__.side_effect = lambda *args: order.append('commit')
    channel.basic_ack.side_effect = lambda **kwargs: order.append('ack')
    with patch('psycopg2.connect', return_value=connection):
        process('synthetic', channel, Mock(delivery_tag=10), json.dumps(initial_assignment_ENVELOPE).encode())
    inserts = [call.args[1] for call in cursor.execute.call_args_list if call.args[0].startswith('INSERT INTO public."Notification" ')]
    assert len(inserts) == 1 and inserts[0][5].adapted == initial_assignment_ENVELOPE
    assert order == ['commit', 'ack']


# DR3 storage-before-ACK checks accompany the AC1/AC4 cases above; other DRs are outside this module.
