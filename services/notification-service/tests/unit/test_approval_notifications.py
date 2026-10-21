"""SCRUM-45 user story: As an Event Organiser, I want to receive an in-app
notification when the Lead Coordinator approves or rejects my event request,
so that I know the outcome and who is responsible for coordinating my event.
AC1/AC3 approval delivery and details; DR2 atomic intent; DR4 saved facts.
"""
import json
from unittest.mock import MagicMock, Mock, patch
import pytest
from app.consumer import process

ENVELOPE = dict(version=1, id="20000000-0000-0000-0000-000000000001",
    recipientId="10000000-0000-0000-0000-000000000001", type="event.approval",
    createdAt="2026-10-21T00:00:00+00:00", message="Community Workshop was approved",
    destination=dict(kind="event-details", eventId="30000000-0000-0000-0000-000000000001"),
    details=dict(eventName="Community Workshop", decision="Approved"))

@pytest.mark.parametrize("change", [
    {"details": {}}, {"details": {"eventName": " ", "decision": "Approved"}},
    {"details": {"eventName": "Community Workshop", "decision": "Rejected"}},
    {"destination": {"kind": "event-venue-request", "eventId": "30000000-0000-0000-0000-000000000001", "bookingId": "40000000-0000-0000-0000-000000000001"}},
])
def test_invalid_approval_display_contract_is_quarantined(change):
    """AC1/AC3: malformed approval crosses real consumer boundary; DB-driver
    observation proves quarantine rather than inbox insertion, before acknowledgement.
    """
    connection, channel = MagicMock(), Mock()
    cursor = connection.cursor.return_value.__enter__.return_value
    with patch("psycopg2.connect", return_value=connection):
        process("synthetic", channel, Mock(delivery_tag=11), json.dumps({**ENVELOPE, **change}).encode())
    assert not any(call.args[0].startswith('INSERT INTO public."Notification" ')
                   for call in cursor.execute.call_args_list)
    assert any('NotificationFailure' in call.args[0] for call in cursor.execute.call_args_list)
    channel.basic_ack.assert_called_once_with(delivery_tag=11)


def test_valid_approval_is_persisted_without_losing_content():
    """AC1/AC3: consumer accepts complete approval, persists exact payload and commits before ack."""
    connection, channel = MagicMock(), Mock()
    cursor = connection.cursor.return_value.__enter__.return_value
    events = Mock()
    events.attach_mock(connection, "database")
    events.attach_mock(channel, "broker")
    with patch("psycopg2.connect", return_value=connection):
        process("synthetic", channel, Mock(delivery_tag=12), json.dumps(ENVELOPE).encode())
    inserts = [call.args[1] for call in cursor.execute.call_args_list
               if call.args[0].startswith('INSERT INTO public."Notification" ')]
    assert len(inserts) == 1
    assert inserts[0][5].adapted == ENVELOPE
    names = [call[0] for call in events.mock_calls]
    assert names.index("database.__exit__") < names.index("broker.basic_ack")
