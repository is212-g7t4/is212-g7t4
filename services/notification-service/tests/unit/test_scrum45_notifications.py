"""
SCRUM-45: Event Organiser Status and Update Notifications

User Story
----------
As an Event Organiser, I want to receive an in-app notification when the Lead
Coordinator approves or rejects my event request, so that I know the outcome
and and who is responsible for coordinating my event.

Acceptance Criteria
-------------------
AC1: Given the Lead Coordinator successfully records an approval of an event
     request, the Event Organiser who submitted it receives an in-app
     notification confirming the approval.
AC2: Given the Lead Coordinator successfully records a rejection of an event
     request, the Event Organiser who submitted it receives an in-app
     notification confirming the rejection and stating the rejection reason.
AC3: Both decision notifications include the event name, the decision, and a
     link to view the event request and its decision details.
AC4: Given an initial coordinator assignment or reassignment is successfully
     recorded, the Event Organiser receives an in-app notification with the
     event name, the newly assigned coordinator’s name, and a link to view the
     event details.

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

def test_process_approval_alert_stores_full_content_before_ack(mocker):
    """
    Summary: An approval notice is stored for the organiser with all its content before acknowledging.
    AC1: Given the Lead Coordinator successfully records an approval of an
        event request, the Event Organiser who submitted it receives an in-app
        notification confirming the approval.
    AC3: Both decision notifications include the event name, the decision, and
        a link to view the event request and its decision details.
    Double: Stub (connection), Mock (channel ACK)
    """
    # Arrange (Given)
    connection, channel = (MagicMock(), Mock())
    cursor = connection.cursor.return_value.__enter__.return_value
    events = Mock()
    events.attach_mock(connection, 'database')
    events.attach_mock(channel, 'broker')
    mocker.patch('psycopg2.connect', return_value=connection)
    process('synthetic', channel, Mock(delivery_tag=12), json.dumps(approval_ENVELOPE).encode())

    # Act (When)
    inserts = [call.args[1] for call in cursor.execute.call_args_list if call.args[0].startswith('INSERT INTO public."Notification" ')]

    # Assert (Then)
    assert len(inserts) == 1
    assert inserts[0][5].adapted == approval_ENVELOPE
    names = [call[0] for call in events.mock_calls]
    assert names.index('database.__exit__') < names.index('broker.basic_ack')


# AC2 — Rejection and reason

def test_process_rejection_alert_stores_reason_and_event_link(mocker):
    """
    Summary: A rejection notice is stored with its reason and a link to the event.
    AC2: Given the Lead Coordinator successfully records a rejection of an
        event request, the Event Organiser who submitted it receives an in-app
        notification confirming the rejection and stating the rejection reason.
    AC3: Both decision notifications include the event name, the decision, and
        a link to view the event request and its decision details.
    Double: Stub (connection), Mock (channel ACK)
    """
    # Arrange (Given)
    reason = 'The proposal does not meet the event requirements.'
    envelope = {'version': 1, 'id': '20000000-0000-0000-0000-000000000001', 'recipientId': '10000000-0000-0000-0000-000000000001', 'type': 'event.rejection', 'message': f'Community Workshop was rejected: {reason}', 'createdAt': '2026-10-21T01:00:00+00:00', 'destination': {'kind': 'event-details', 'eventId': '30000000-0000-0000-0000-000000000001'}, 'details': {'eventName': 'Community Workshop', 'reason': reason}}
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    channel = Mock()
    mocker.patch('psycopg2.connect', return_value=connection)
    process('synthetic', channel, Mock(delivery_tag=9), json.dumps(envelope).encode())

    # Act (When)
    inbox_inserts = [call.args[1] for call in cursor.execute.call_args_list if call.args[0].startswith('INSERT INTO public."Notification" ')]

    # Assert (Then)
    assert len(inbox_inserts) == 1, 'Rejection must reach inbox storage, not quarantine'
    persisted_envelope = inbox_inserts[0][5].adapted
    assert persisted_envelope == envelope
    channel.basic_ack.assert_called_once_with(delivery_tag=9)


# AC3 — Decision content and link

@pytest.mark.parametrize('change', [{'details': {}}, {'details': {'eventName': ' ', 'decision': 'Approved'}}, {'details': {'eventName': 'Community Workshop', 'decision': 'Rejected'}}, {'destination': {'kind': 'event-venue-request', 'eventId': '30000000-0000-0000-0000-000000000001', 'bookingId': '40000000-0000-0000-0000-000000000001'}}], ids=["no_details", "blank_event_name", "wrong_decision", "wrong_destination"])
def test_process_approval_alert_missing_content_is_quarantined(change, mocker):
    """
    Summary: An approval notice missing its event name, with the wrong decision or wrong link is kept aside.
    AC3: Both decision notifications include the event name, the decision, and
        a link to view the event request and its decision details.
    Double: Stub (connection), Mock (channel ACK)
    """
    connection, channel = (MagicMock(), Mock())
    cursor = connection.cursor.return_value.__enter__.return_value
    mocker.patch('psycopg2.connect', return_value=connection)
    process('synthetic', channel, Mock(delivery_tag=11), json.dumps({**approval_ENVELOPE, **change}).encode())
    assert not any((call.args[0].startswith('INSERT INTO public."Notification" ') for call in cursor.execute.call_args_list))
    assert any(('NotificationFailure' in call.args[0] for call in cursor.execute.call_args_list))
    channel.basic_ack.assert_called_once_with(delivery_tag=11)

@pytest.mark.parametrize('change', [{'details': {}}, {'details': {'eventName': 'Workshop', 'reason': ' '}}, {'details': {'eventName': ' ', 'reason': 'No plan'}}, {'destination': {'kind': 'event-venue-request', 'eventId': '30000000-0000-0000-0000-000000000001', 'bookingId': '40000000-0000-0000-0000-000000000001'}}], ids=["no_details", "blank_reason", "blank_event_name", "wrong_destination"])
def test_process_rejection_alert_missing_reason_or_link_is_quarantined(change, mocker):
    """
    Summary: A rejection notice without its reason, event name or event link is kept aside.
    AC2: Given the Lead Coordinator successfully records a rejection of an
        event request, the Event Organiser who submitted it receives an in-app
        notification confirming the rejection and stating the rejection reason.
    AC3: Both decision notifications include the event name, the decision, and
        a link to view the event request and its decision details.
    Double: Stub (connection), Mock (channel ACK)
    """
    # Arrange (Given)
    envelope = dict(version=1, id='20000000-0000-0000-0000-000000000001', recipientId='10000000-0000-0000-0000-000000000001', type='event.rejection', createdAt='2026-10-21T01:00:00+00:00', message='Workshop was rejected: No plan', destination=dict(kind='event-details', eventId='30000000-0000-0000-0000-000000000001'), details=dict(eventName='Workshop', reason='No plan'))
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    channel = Mock()

    # Act (When)
    mocker.patch('psycopg2.connect', return_value=connection)
    process('synthetic', channel, Mock(delivery_tag=10), json.dumps({**envelope, **change}).encode())

    # Assert (Then)
    assert not any((call.args[0].startswith('INSERT INTO public."Notification" ') for call in cursor.execute.call_args_list))
    assert any(('NotificationFailure' in call.args[0] for call in cursor.execute.call_args_list))
    channel.basic_ack.assert_called_once_with(delivery_tag=10)


# AC4 — Initial assignment and reassignment

@pytest.mark.parametrize('change', [{'details': {}}, {'details': None}, {'details': {**initial_assignment_ENVELOPE['details'], 'coordinatorName': ' '}}, {'details': {**initial_assignment_ENVELOPE['details'], 'eventName': ' '}}, {'destination': dict(kind='event-venue-request', eventId=initial_assignment_EVENT, bookingId=initial_assignment_COORDINATOR)}], ids=["empty_details", "null_details", "blank_coordinator_name", "blank_event_name", "wrong_destination"])
def test_process_assignment_alert_missing_coordinator_name_is_quarantined(change, mocker):
    """
    Summary: An assignment notice without the coordinator's name or event link is kept aside.
    AC4: Given an initial coordinator assignment or reassignment is
        successfully recorded, the Event Organiser receives an in-app
        notification with the event name, the newly assigned coordinator’s
        name, and a link to view the event details.
    Double: Stub (connection), Mock (channel ACK)
    """
    # Arrange (Given)
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    channel = Mock()

    # Act (When)
    mocker.patch('psycopg2.connect', return_value=connection)
    process('synthetic', channel, Mock(delivery_tag=10), json.dumps({**initial_assignment_ENVELOPE, **change}).encode())

    # Assert (Then)
    assert not any((call.args[0].startswith('INSERT INTO public."Notification" ') for call in cursor.execute.call_args_list))
    assert any(('NotificationFailure' in call.args[0] for call in cursor.execute.call_args_list))
    channel.basic_ack.assert_called_once_with(delivery_tag=10)

def test_process_assignment_alert_with_coordinator_name_stores_before_ack(mocker):
    """
    Summary: An assignment notice naming the new coordinator is stored for the organiser before acknowledging.
    AC4: Given an initial coordinator assignment or reassignment is
        successfully recorded, the Event Organiser receives an in-app
        notification with the event name, the newly assigned coordinator’s
        name, and a link to view the event details.
    Double: Stub (connection), Mock (channel ACK)
    """
    # Arrange (Given)
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    channel = Mock()
    order = []
    connection.__exit__.side_effect = lambda *args: order.append('commit')
    channel.basic_ack.side_effect = lambda **kwargs: order.append('ack')
    mocker.patch('psycopg2.connect', return_value=connection)
    process('synthetic', channel, Mock(delivery_tag=10), json.dumps(initial_assignment_ENVELOPE).encode())

    # Act (When)
    inserts = [call.args[1] for call in cursor.execute.call_args_list if call.args[0].startswith('INSERT INTO public."Notification" ')]

    # Assert (Then)
    assert len(inserts) == 1 and inserts[0][5].adapted == initial_assignment_ENVELOPE
    assert order == ['commit', 'ack']


# DR3 storage-before-ACK checks accompany the AC1/AC4 cases above; other DRs are outside this module.
