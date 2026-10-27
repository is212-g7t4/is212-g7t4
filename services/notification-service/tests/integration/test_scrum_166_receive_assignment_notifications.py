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
AC1/AC2: covered here at committed recipient-scoped inbox boundaries; successful
Lead mutations and intent creation belong to Coordinator Assignment/Event tests.
AC3/AC4: input/persisted payload only; enriched content/link preparation belongs
to Workflow unit/adapter story tests and presentation to frontend components.
AC5: not covered here because Event prevents no-op notification work; its unit
and integration story modules test unchanged saves before delivery.

Real: consumer, SQL storage, recipient inbox routes and fixture-owned full-chain PostgreSQL.
Doubled: recording ACK channel; no broker or other service. No delivery or UI journey proof.
"""

import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4
import pytest
from app.consumer import process
from tests.integration.factories import ORGANISER, OTHER, COORDINATOR, EVENT, make_parents

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


@pytest.fixture(autouse=True)
def parents(db):
    make_parents(db)
    db.execute('INSERT INTO public."User" (user_id,username,email,role) VALUES (%s,%s,%s,%s)',
               [COORDINATOR, "Synthetic Coordinator", "coordinator@example.com", "Event Coordinator"])


def identity(recipient):
    return {"X-Dev-User-Id": recipient, "X-Dev-Role": "Event Coordinator"}


def envelope(kind="assigned", recipient=COORDINATOR):
    removed = kind == "removed"
    return dict(version=1, id=str(uuid4()), type="event.coordinator-" + kind,
        recipientId=recipient, createdAt="2030-01-01T00:00:00+00:00",
        destination=None if removed else dict(kind="event-details", eventId=EVENT),
        message=("You are no longer assigned to" if removed else "You have been assigned to") +
                " Community Workshop. Event Organiser: Synthetic Organiser. Proposed: "
                "01 Mar 2030, 09:00 SGT – 01 Mar 2030, 17:00 SGT.",
        details=dict(eventId=EVENT, eventName="Community Workshop", organiserId=ORGANISER,
                     organiserName="Synthetic Organiser", recipientId=recipient,
                     startDateTime="2030-03-01T09:00:00+08:00", endDateTime="2030-03-01T17:00:00+08:00"))


def consume(database_url, db, value, expected_payload=None):
    def committed(*, delivery_tag):
        # Independent connection: the current source, not an older unrelated row,
        # must already be committed at this exact ACK boundary.
        rows = db.execute('SELECT * FROM public."Notification" WHERE source_id=%s', [value["id"]])
        assert len(rows) == 1
        assert str(rows[0]["notification_id"]) == value["id"]
        assert str(rows[0]["recipient_id"]) == value["recipientId"]
        assert rows[0]["type"] == value["type"]
        assert rows[0]["payload"] == (value if expected_payload is None else expected_payload)
    channel = Mock()
    channel.basic_ack.side_effect = committed
    process(database_url, channel, SimpleNamespace(delivery_tag=7), json.dumps(value).encode())
    channel.basic_ack.assert_called_once_with(delivery_tag=7)


def inbox(client, recipient):
    response = client.get("/notifications", headers=identity(recipient))
    assert response.status_code == 200
    return response.json["notifications"]


# AC1 — Assignment persistence

def test_ac1_assignment_is_committed_and_only_its_recipient_can_retrieve(client, db, database_url):
    """Consume an independently constructed assignment through the real consumer.
    The exact committed content is returned only to its coordinator recipient.
    """
    value = envelope()
    consume(database_url, db, value)
    assert [item["payload"] for item in inbox(client, COORDINATOR)] == [value]
    assert inbox(client, OTHER) == []
    before = db.execute('SELECT * FROM public."Notification" WHERE source_id=%s', [value["id"]])
    denied = client.patch(f"/notifications/{value['id']}", headers=identity(OTHER), json={"read": True})
    assert denied.status_code == 404  # Conceal another recipient's notification.
    assert db.execute('SELECT * FROM public."Notification" WHERE source_id=%s', [value["id"]]) == before
    assert inbox(client, COORDINATOR)[0]["readAt"] is None
    rows = db.execute('SELECT * FROM public."Notification"')
    assert len(rows) == 1
    assert str(rows[0]["event_id"]) == EVENT
    assert rows[0]["payload"] == value

# AC2 — Two recipient reassignment delivery

def test_ac2_assignment_and_removal_are_private_to_their_respective_recipients(client, db, database_url):
    """Consume new-recipient assignment and old-recipient content-only removal.
    Each inbox returns its own exact message, never the other recipient's message.
    """
    assigned = envelope("assigned", COORDINATOR)
    removed = envelope("removed", OTHER)
    consume(database_url, db, assigned)
    consume(database_url, db, removed)
    assert [item["payload"] for item in inbox(client, COORDINATOR)] == [assigned]
    assert [item["payload"] for item in inbox(client, OTHER)] == [removed]
    rows = db.execute('SELECT * FROM public."Notification"')
    assert len(rows) == 2
    assert {str(row["source_id"]) for row in rows} == {assigned["id"], removed["id"]}
    assert all(str(row["event_id"]) == EVENT for row in rows)
    assert db.execute('SELECT * FROM public."NotificationFailure"') == []

# Supporting design rule — stable source identity/read state

def test_dr_replayed_coordinator_delivery_preserves_saved_message_and_read_state(client, db, database_url):
    """Mark a new coordinator assignment read, then replay its stable source ID.
    The first payload and read timestamp survive and unread count stays zero.
    """
    value = envelope()
    consume(database_url, db, value)
    marked = client.patch(f"/notifications/{value['id']}", headers=identity(COORDINATOR), json={"read": True})
    assert marked.status_code == 200
    before = db.execute('SELECT * FROM public."Notification"')
    assert before[0]["read_at"] is not None
    consume(database_url, db, {**value, "message": "Later replay must not overwrite history"}, expected_payload=value)
    assert db.execute('SELECT * FROM public."Notification"') == before
    assert client.get("/notifications/unread-count", headers=identity(COORDINATOR)).json == {"unreadCount": 0}

# Supporting design rule — permanent coordinator poison is durable before ACK

@pytest.mark.parametrize("kind", ["assigned", "removed"])
def test_dr_poison_coordinator_payload_is_quarantined_before_ack_then_valid_delivers(client, db, database_url, kind):
    """Reject an inconsistent assignment recipient or a removal with forbidden navigation.
    ACK sees exact committed poison bytes; a subsequent valid message reaches its inbox.
    """
    # Arrange: invalid type-specific content, with a valid message ready to follow.
    poison = envelope(kind)
    if kind == "assigned":
        poison["details"]["recipientId"] = OTHER
    else:
        poison["destination"] = dict(kind="event-details", eventId=EVENT)
    body = json.dumps(poison).encode()
    channel = Mock()
    def quarantined(*, delivery_tag):
        failures = db.execute('SELECT * FROM public."NotificationFailure"')
        assert len(failures) == 1
        assert bytes(failures[0]["body"]) == body
        assert failures[0]["error"] == ("Inconsistent coordinator recipient" if kind == "assigned"
                                          else "Removal must not link to the event")
        assert db.execute('SELECT * FROM public."Notification" WHERE source_id=%s', [poison["id"]]) == []
    channel.basic_ack.side_effect = quarantined
    # Act/Assert: the ACK callback independently reads committed quarantine state.
    process(database_url, channel, SimpleNamespace(delivery_tag=8), body)
    channel.basic_ack.assert_called_once_with(delivery_tag=8)
    saved_failure = db.execute('SELECT * FROM public."NotificationFailure"')
    # A later valid delivery is not starved by the permanently invalid payload.
    valid = envelope(kind)
    consume(database_url, db, valid)
    assert [item["payload"] for item in inbox(client, COORDINATOR)] == [valid]
    assert inbox(client, OTHER) == []
    assert db.execute('SELECT * FROM public."NotificationFailure"') == saved_failure
    assert {str(row["source_id"]) for row in db.execute('SELECT * FROM public."Notification"')} == {valid["id"]}



