"""SCRUM-45 user story: As an Event Organiser I want to know my assigned
coordinator through in-app notification. AC4: required event/name/details link;
DR3 persistence before acknowledgement. Consumer boundary with DB I/O mocked.
"""
import json
from unittest.mock import MagicMock, Mock, patch
import pytest
from app.consumer import process

EVENT = "30000000-0000-0000-0000-000000000001"
COORDINATOR = "10000000-0000-0000-0000-000000000002"
ENVELOPE = dict(version=1, id="20000000-0000-0000-0000-000000000001",
    recipientId="10000000-0000-0000-0000-000000000001", type="event.coordinator-assignment",
    createdAt="2026-10-21T00:00:00+00:00", message="Alice Tan has been assigned to coordinate Community Workshop.",
    destination=dict(kind="event-details", eventId=EVENT),
    details=dict(eventId=EVENT, eventName="Community Workshop", coordinatorId=COORDINATOR, coordinatorName="Alice Tan"))

@pytest.mark.parametrize("change", [
    {"details": {}}, {"details": None},
    {"details": {**ENVELOPE["details"], "coordinatorName": " "}},
    {"details": {**ENVELOPE["details"], "eventName": " "}},
    {"destination": dict(kind="event-venue-request", eventId=EVENT, bookingId=COORDINATOR)},
])
def test_assignment_without_required_display_content_is_quarantined(change):
    """AC4: consume malformed assignment through real validation/storage
    adapters; quarantine instead of inbox insertion before acknowledgement.
    """
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    channel = Mock()
    with patch("psycopg2.connect", return_value=connection):
        process("synthetic", channel, Mock(delivery_tag=10), json.dumps({**ENVELOPE, **change}).encode())
    assert not any(call.args[0].startswith('INSERT INTO public."Notification" ') for call in cursor.execute.call_args_list)
    assert any("NotificationFailure" in call.args[0] for call in cursor.execute.call_args_list)
    channel.basic_ack.assert_called_once_with(delivery_tag=10)


def test_named_assignment_is_persisted_before_acknowledgement():
    """AC4/DR3: real consumer/store adapter retains required named assignment;
    DB connection commit completes before broker acknowledgement.
    """
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    channel = Mock()
    order = []
    connection.__exit__.side_effect = lambda *args: order.append("commit")
    channel.basic_ack.side_effect = lambda **kwargs: order.append("ack")
    with patch("psycopg2.connect", return_value=connection):
        process("synthetic", channel, Mock(delivery_tag=10), json.dumps(ENVELOPE).encode())
    inserts = [call.args[1] for call in cursor.execute.call_args_list
               if call.args[0].startswith('INSERT INTO public."Notification" ')]
    assert len(inserts) == 1 and inserts[0][5].adapted == ENVELOPE
    assert order == ["commit", "ack"]
