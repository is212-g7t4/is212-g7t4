"""SCRUM-49 Event Change and Modification Notifications: Notification integration tests.

Story: As an Event Organiser and Event Coordinator, I want to receive notifications about event changes that affect me, so that I can respond to changes promptly.
Real: consumer validation, SQL storage and Flask inbox, disposable postgres:17.6 full unmodified migrations.
Doubled: recording ACK channel (no RabbitMQ).
Not proven: cross-service E2E, live broker delivery, authentication or browser navigation.
AC = acceptance criterion; DR = supporting design rule, not an extra AC.

AC1 Given an Event Organiser submits a change request, the system sends an in-app notification to the Event Coordinator with the event name, proposed changes, and a link to review the request.
AC2 Given an approval or rejection of a change request is successfully recorded, the Event Organiser receives an in-app notification with the event name, decision, and reason if rejected.
AC3 Given an event is cancelled or rejected, the system sends an in-app notification to both the Event Coordinator and Event Organiser confirming the cancellation or rejection respectively with the event name.
Coverage: AC1-3 incoming envelopes committed before ACK and recipient inbox retrieval; producer/workflow belong to their owner suites.
"""
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.consumer import process
from tests.unit.factories import bearer
from tests.integration.factories import (
    ORGANISER, OTHER, make_parents, make_change_envelope, make_envelope, make_notification_coordinator,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


def deliver(client, db, database_url, envelope):
    make_parents(db)
    saved_at_ack = []
    class Channel:
        def basic_ack(self, *, delivery_tag):
            assert delivery_tag == 7
            # A new independent DB connection observes this exact source ID at ACK, not old counts.
            saved_at_ack.extend(db.execute('SELECT * FROM public."Notification" WHERE source_id=%s', [envelope["id"]]))
    # Act
    process(database_url, Channel(), SimpleNamespace(delivery_tag=7), json.dumps(envelope).encode())
    # Assert
    assert len(saved_at_ack) == 1
    row = saved_at_ack[0]
    assert row["payload"] == envelope
    assert str(row["recipient_id"]) == envelope["recipientId"]
    assert row["type"] == envelope["type"]
    response = client.get("/notifications", headers=bearer(envelope["recipientId"], "Event Organiser"))
    assert response.status_code == 200
    assert response.json["notifications"][0]["payload"] == envelope
    assert db.execute('SELECT * FROM public."NotificationFailure"') == []


# AC1 ---- supported review destination and complete content

def test_ac1_submitted_change_is_committed_before_ack_and_visible_in_recipient_inbox(client, db, database_url):
    """Normal: submitted change and exact request link persist before ACK and appear in the recipient inbox."""
    # Arrange
    envelope = make_change_envelope()
    deliver(client, db, database_url, envelope)

# AC2 ---- independent wire examples for decisions
@pytest.mark.parametrize("kind", ["approved", "rejected"])
def test_ac2_decision_content_is_committed_and_retrievable(client, db, database_url, kind):
    """Normal: decision name, former name or exact reason reaches the owner's stored inbox."""
    # Arrange
    envelope = make_change_envelope(kind)
    deliver(client, db, database_url, envelope)


# AC3 ---- distinct source IDs for both independent recipient deliveries

def test_ac3_event_rejection_keeps_one_inbox_alert_per_recipient_on_replay(client, db, database_url):
    """Normal: both roles receive the existing rejection reason/link; replay never duplicates the organiser alert."""
    # Arrange: real consumer/store/inbox/PostgreSQL, recording ACK boundary only.
    make_parents(db)
    coordinator = make_notification_coordinator(db)
    organiser_envelope = make_envelope("rejection")
    coordinator_envelope = {**organiser_envelope, "id": str(uuid4()), "recipientId": coordinator,
        "details": {**organiser_envelope["details"], "recipientId": coordinator}}
    envelopes = [organiser_envelope, coordinator_envelope]
    acknowledgements = []
    class Channel:
        def basic_ack(self, *, delivery_tag):
            current = envelopes[delivery_tag]
            rows = db.execute('SELECT * FROM public."Notification" WHERE source_id=%s', [current["id"]])
            assert len(rows) == 1
            assert rows[0]["payload"] == current
            assert str(rows[0]["recipient_id"]) == current["recipientId"]
            acknowledgements.append(delivery_tag)
    # Act: repeat both exact source messages to prove inbox deduplication independently of producer guards.
    for _ in range(2):
        for tag, envelope in enumerate(envelopes):
            process(database_url, Channel(), SimpleNamespace(delivery_tag=tag), json.dumps(envelope).encode())
    # Assert: recipient isolation, exact name/reason/message/details destination and no quarantine.
    assert acknowledgements == [0, 1, 0, 1]
    assert len(db.execute('SELECT * FROM public."Notification"')) == 2
    assert db.execute('SELECT * FROM public."NotificationFailure"') == []
    for envelope, role in zip(envelopes, ("Event Organiser", "Event Coordinator")):
        response = client.get("/notifications", headers=bearer(envelope["recipientId"], role))
        assert response.status_code == 200
        assert [item["payload"] for item in response.json["notifications"]] == [envelope]



def test_ac3_cancellation_keeps_two_recipient_records(client, db, database_url):
    """Normal: independent cancellation deliveries retain both recipient records and links."""
    # Arrange
    make_parents(db)
    envelopes = [make_change_envelope("cancelled", recipient) for recipient in (ORGANISER, OTHER)]
    acknowledged = []
    class Channel:
        def basic_ack(self, *, delivery_tag):
            current = envelopes[delivery_tag]
            row = db.execute('SELECT * FROM public."Notification" WHERE source_id=%s', [current["id"]])
            assert len(row) == 1
            assert row[0]["payload"] == current
            acknowledged.append(delivery_tag)
    # Act
    for tag, envelope in enumerate(envelopes):
        process(database_url, Channel(), SimpleNamespace(delivery_tag=tag), json.dumps(envelope).encode())
    # Assert
    assert acknowledged == [0, 1]
    assert len(db.execute('SELECT * FROM public."Notification"')) == 2
    for envelope in envelopes:
        response = client.get("/notifications", headers=bearer(envelope["recipientId"], "Event Organiser"))
        assert response.status_code == 200
        assert [item["payload"] for item in response.json["notifications"]] == [envelope]
