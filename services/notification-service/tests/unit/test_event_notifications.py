"""User story (SCRUM-45: Event Organiser Status and Update Notifications):
As an Event Organiser, I want to receive an in-app notification when the
Lead Coordinator approves or rejects my event request, so that I know the
outcome and who is responsible for coordinating my event.

AC2: Successful rejection notifies the submitting organiser with its reason.
AC3: Decision notifications include event name, decision and a details link.

This first TDD slice tests consumer acceptance and the inbox-storage payload,
not real database persistence, producer recipient selection or browser links.
The proposed SCRUM-45 wire contract uses event.rejection and event-details;
these are new contract values, not previously supported application behaviour.
"""

import json
from unittest.mock import MagicMock, Mock, patch

from app.consumer import process


def test_rejection_notification_with_event_details_destination_is_stored():
    """AC2/AC3: consume a rejection with a reason and event-only destination;
    inspect the database-driver boundary to verify inbox insertion rather than
    quarantine, preserving the required content. PostgreSQL and broker I/O
    are mocked; validation and storage-adapter logic execute normally.
    """
    reason = "The proposal does not meet the event requirements."
    envelope = {
        "version": 1,
        "id": "20000000-0000-0000-0000-000000000001",
        "recipientId": "10000000-0000-0000-0000-000000000001",
        "type": "event.rejection",
        "message": f"Community Workshop was rejected: {reason}",
        "createdAt": "2026-10-21T01:00:00+00:00",
        "destination": {
            "kind": "event-details",
            "eventId": "30000000-0000-0000-0000-000000000001",
        },
        "details": {"eventName": "Community Workshop", "reason": reason},
    }
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    channel = Mock()

    with patch("psycopg2.connect", return_value=connection):
        process(
            "synthetic", channel, Mock(delivery_tag=9),
            json.dumps(envelope).encode(),
        )

    inbox_inserts = [
        call.args[1]
        for call in cursor.execute.call_args_list
        if call.args[0].startswith('INSERT INTO public."Notification" ')
    ]
    assert len(inbox_inserts) == 1, (
        "Rejection must reach inbox storage, not quarantine"
    )
    persisted_envelope = inbox_inserts[0][5].adapted
    assert persisted_envelope == envelope
    channel.basic_ack.assert_called_once_with(delivery_tag=9)


import pytest


@pytest.mark.parametrize("change", [
    {"details": {}}, {"details": {"eventName": "Workshop", "reason": " "}},
    {"details": {"eventName": " ", "reason": "No plan"}},
    {"destination": {"kind": "event-venue-request", "eventId": "30000000-0000-0000-0000-000000000001", "bookingId": "40000000-0000-0000-0000-000000000001"}},
])
def test_rejection_missing_display_content_or_event_destination_is_quarantined(change):
    """AC2/AC3: malformed rejection must not enter inbox; submit through real
    consumer validation and inspect quarantine persistence with DB I/O mocked.
    """
    envelope = dict(version=1, id="20000000-0000-0000-0000-000000000001",
        recipientId="10000000-0000-0000-0000-000000000001", type="event.rejection",
        createdAt="2026-10-21T01:00:00+00:00", message="Workshop was rejected: No plan",
        destination=dict(kind="event-details", eventId="30000000-0000-0000-0000-000000000001"),
        details=dict(eventName="Workshop", reason="No plan"))
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    channel = Mock()
    with patch("psycopg2.connect", return_value=connection):
        process("synthetic", channel, Mock(delivery_tag=10), json.dumps({**envelope, **change}).encode())
    assert not any(call.args[0].startswith('INSERT INTO public."Notification" ') for call in cursor.execute.call_args_list)
    assert any('NotificationFailure' in call.args[0] for call in cursor.execute.call_args_list)
    channel.basic_ack.assert_called_once_with(delivery_tag=10)
