"""SCRUM-47: Venue Booking Notification and Decision Alerts

User Story
----------
As an Event Coordinator and Venue Staff, I want to receive notifications about venue booking requests and decisions, so that I can coordinate venue arrangements efficiently.

Acceptance Criteria
-------------------
AC1: Given an Event Coordinator submits a venue booking request, the system sends an in-app notification to Venue Staff with the event name, requested venue, date/time, and a link to review the request.
AC2: Given a venue booking request is approved or rejected, the system sends an in-app notification to the Event Coordinator with the event name, venue, and decision.

Real
----
- Notification consumer validation, transaction/store SQL, own-inbox Flask routes and independently queried fixture-owned PostgreSQL run unchanged. Assertions check exact stored payloads, recipients, read state, quarantine and committed visibility before ACK.

Doubled
-------
- Mock (recording broker channel verifies ACK after a committed result); Stub (Supabase signing-key lookup trusts the test key while JWT verification runs unchanged). No broker or other service is started.

Not proven
----------
- AC1: Incoming staff-submission content, commit-before-ACK and recipient-scoped inbox are checked.
- AC2: Incoming Approved/Rejected decision content and historical replay/read state are checked. Venue Booking owns business trigger, enrichment and addressing.
- The fixture applies the full unmodified migration chain in a disposable PostgreSQL session with per-test table cleanup and exact container identity guards; this proves a clean install, not an upgrade or hosted role-policy parity.
- Producer triggers, recipient/name resolution, an actual RabbitMQ broker and browser navigation are NOT COVERED ANYWHERE in this module.
- Replay/read state, no-ACK on storage failure and quarantine retention are supporting reliability/privacy contracts, not additional business ACs.
"""
from copy import deepcopy
from datetime import datetime
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.consumer import process
from tests.integration.factories import EVENT, ORGANISER, OTHER, make_parents
from tests.unit.factories import bearer

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
STAFF = "20000000-0000-4000-8000-000000000001"
BOOKING = "40000000-0000-4000-8000-000000000001"
VENUE = "50000000-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def parents(db):
    make_parents(db)
    db.execute('UPDATE public."User" SET role=%s WHERE user_id=%s', ["Event Coordinator", ORGANISER])
    db.execute('INSERT INTO public."User" (user_id,username,email,role) VALUES (%s,%s,%s,%s)',
               [STAFF, "Synthetic staff", "staff@example.com", "Venue Staff"])


def envelope(outcome) -> dict:
    submission = outcome == "submission"
    details = dict(eventId=EVENT, bookingId=BOOKING, venueId=VENUE, requestedBy=ORGANISER,
                   eventName="Accessible Community Workshop", venueName="Grand Hall",
                   startDateTime="2030-03-01T13:00:00+08:00", endDateTime="2030-03-01T15:00:00+08:00")
    details.update({"recipientId": STAFF} if submission else {"decision": outcome})
    return dict(version=1, id=str(uuid4()), type="venue.booking-submission" if submission else "venue.booking-decision",
                recipientId=STAFF if submission else ORGANISER, createdAt="2030-01-01T12:34:56+08:00",
                message="Accessible Community Workshop venue booking " + outcome,
                destination={"kind": "venue-requests"} if submission else
                {"kind": "event-venue-request", "eventId": EVENT, "bookingId": BOOKING}, details=details)


def identity(user):
    return bearer(user, "Venue Staff" if user == STAFF else "Event Coordinator")


def source_rows(db, identifier):
    # Database.execute opens an independent connection every time, including at ACK.
    return db.execute('SELECT * FROM public."Notification" WHERE source_id=%s', [identifier])


def assert_exact_delivery(rows, expected, read_at=None):
    [row] = rows
    assert str(row["source_id"]) == str(row["notification_id"]) == row["dedupe_key"] == expected["id"]
    assert str(row["recipient_id"]) == expected["recipientId"]
    assert row["type"] == expected["type"] and str(row["event_id"]) == EVENT
    assert row["payload"] == expected
    assert row["created_at"] == datetime.fromisoformat(expected["createdAt"])
    assert row["read_at"] == read_at


class CommittedChannel:
    """Require exact current-source persisted state, not a preexisting positive inbox count."""
    def __init__(self, db, expected, read_at=None, quarantined=None):
        self.db, self.expected, self.read_at = db, expected, read_at
        self.quarantined = quarantined
        self.acks = []

    def basic_ack(self, *, delivery_tag):
        if self.quarantined is None:
            assert_exact_delivery(source_rows(self.db, self.expected["id"]), self.expected, self.read_at)
        else:
            assert source_rows(self.db, self.expected["id"]) == []
            [failure] = self.db.execute('SELECT * FROM public."NotificationFailure" WHERE body=%s',
                                       [self.quarantined])
            assert bytes(failure["body"]) == self.quarantined and failure["error"]
        self.acks.append(delivery_tag)


def consume(url, channel, value, tag):
    process(url, channel, SimpleNamespace(delivery_tag=tag), json.dumps(value).encode())


# AC1/AC2 — three legitimate booking outcomes; DR: replay preserves history/read state.
@pytest.mark.parametrize("outcome", ["submission", "Approved", "Rejected"],
                         ids=["staff-submission", "coordinator-approved", "coordinator-rejected"])
def test_ac1_booking_alert_is_committed_scoped_and_replay_preserves_read_history(client, db, database_url, outcome):
    """Summary: Each booking outcome is durable at ACK, private to its recipient and unchanged by replay.
AC1: Given an Event Coordinator submits a venue booking request, the system sends an in-app notification to Venue Staff with the event name, requested venue, date/time, and a link to review the request.
AC2: Given a venue booking request is approved or rejected, the system sends an in-app notification to the Event Coordinator with the event name, venue, and decision.
Double: Mock (recording broker ACK channel observes independent committed database reads), Stub (local Supabase signing-key lookup).
"""
    original = envelope(outcome)
    channel = CommittedChannel(db, original)
    consume(database_url, channel, original, 7)
    assert channel.acks == [7]
    assert_exact_delivery(source_rows(db, original["id"]), original)
    recipient = identity(original["recipientId"])
    inbox = client.get("/notifications", headers=recipient)
    assert inbox.status_code == 200
    [item] = inbox.json["notifications"]
    assert item["id"] == original["id"] and item["payload"] == original and item["readAt"] is None
    assert client.get("/notifications", headers=identity(OTHER)).json["notifications"] == []
    assert client.get("/notifications/unread-count", headers=recipient).json == {"unreadCount": 1}

    marked = client.patch(f"/notifications/{original['id']}", json={"read": True}, headers=recipient)
    assert marked.status_code == 200 and marked.json["notification"]["readAt"] is not None
    before = source_rows(db, original["id"])
    read_at = before[0]["read_at"]
    replay = deepcopy(original)
    replay["message"] = "Later replay must never overwrite original content"
    replay["details"]["eventName"] = "Renamed after first receipt"
    repeated = CommittedChannel(db, original, read_at=read_at)
    consume(database_url, repeated, replay, 8)
    assert repeated.acks == [8]
    assert source_rows(db, original["id"]) == before
    assert_exact_delivery(source_rows(db, original["id"]), original, read_at)
    [after] = client.get("/notifications", headers=recipient).json["notifications"]
    assert after["payload"] == original and after["readAt"] == marked.json["notification"]["readAt"]
    assert client.get("/notifications/unread-count", headers=recipient).json == {"unreadCount": 0}
    assert client.patch(f"/notifications/{original['id']}", json={"read": False}, headers=identity(OTHER)).status_code == 404
    assert source_rows(db, original["id"]) == before


# DR supporting AC1/AC2 — poison receipt must not block valid following receipt.
def test_ac1_malformed_booking_is_quarantined_before_valid_following_receipt(client, db, database_url):
    """Summary: Malformed booking contract commits quarantine, then the following valid alert reaches its inbox.
AC1: Given an Event Coordinator submits a venue booking request, the system sends an in-app notification to Venue Staff with the event name, requested venue, date/time, and a link to review the request.
AC2: Given a venue booking request is approved or rejected, the system sends an in-app notification to the Event Coordinator with the event name, venue, and decision.
Double: Mock (recording broker ACK channel observes independent committed database reads), Stub (local Supabase signing-key lookup).
"""
    invalid = envelope("submission")
    invalid["details"]["recipientId"] = OTHER
    body = json.dumps(invalid).encode()
    poison_channel = CommittedChannel(db, invalid, quarantined=body)
    process(database_url, poison_channel, SimpleNamespace(delivery_tag=11), body)
    assert poison_channel.acks == [11]
    assert source_rows(db, invalid["id"]) == []
    [quarantine] = db.execute('SELECT * FROM public."NotificationFailure"')
    assert bytes(quarantine["body"]) == body and quarantine["error"]

    valid = envelope("Approved")
    channel = CommittedChannel(db, valid)
    consume(database_url, channel, valid, 12)
    assert channel.acks == [12]
    assert_exact_delivery(source_rows(db, valid["id"]), valid)
    assert source_rows(db, invalid["id"]) == []
    assert db.execute('SELECT * FROM public."NotificationFailure"') == [quarantine]
    inbox = client.get("/notifications", headers=identity(valid["recipientId"]))
    assert inbox.status_code == 200
    assert [item["payload"] for item in inbox.json["notifications"]] == [valid]
