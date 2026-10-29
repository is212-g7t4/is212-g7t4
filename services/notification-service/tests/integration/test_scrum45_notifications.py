"""SCRUM-45 Event Organiser Status and Update Notifications: Notification integration tests.

Story: As an Event Organiser, I want to receive an in-app notification when the Lead Coordinator approves or rejects my event request, so that I know the outcome and who is responsible for coordinating my event.
Real: own consumer, SQL storage, inbox Flask routes and disposable postgres:17.6 with full unmodified migrations.
Doubled: recording broker ACK channel; a database trigger injects storage failure. No other service runs.
Not proven: Event mutation, Workflow name lookup/publication, actual broker redelivery, UI/E2E or production authentication.
AC = acceptance criterion; DR = supporting design rule, not an extra AC.

AC1 A successfully recorded approval sends an in-app approval notification to the submitting Event Organiser.
  Owned: committed incoming approval/inbox. Event trigger and Workflow sending not covered here.
AC2 A successfully recorded rejection sends an in-app rejection notification to the submitting Event Organiser, including the rejection reason.
  Owned: committed incoming rejection/reason. Event trigger and Workflow sending not covered here.
AC3 Both decision notifications include event name, decision, and a link to the event request and its decision details.
  Owned: exact saved payload and destination; target-page rendering/navigation not covered here (frontend).
AC4 A successfully recorded initial assignment or reassignment sends the submitting Event Organiser an in-app notification with event name, newly assigned coordinator name, and an event-details link.
  Owned: two named assignment envelopes and display validation. User lookup and Event mutation not covered here.
"""
import json
from types import SimpleNamespace
from datetime import datetime, UTC

import psycopg2
import pytest
from app.consumer import process
from tests.integration.factories import ORGANISER, OTHER, EVENT, make_parents, make_envelope
from tests.unit.factories import bearer

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


def identity(user=ORGANISER):
    """Sign in as an organiser (a token signed with the test key, SCRUM-8) for recipient-scoping checks."""
    return bearer(user, "Event Organiser")


class RecordingChannel:
    """ACK observations use new transactions, independently proving commit visibility."""
    def __init__(self, db):
        self.db = db
        self.acks = []
        self.at_ack = []

    def basic_ack(self, *, delivery_tag):
        """Record the delivery tag and visible inbox/quarantine counts using new database
        transactions at ACK time.
        """
        self.at_ack.append((self.db.execute('SELECT count(*) AS n FROM public."Notification"')[0]["n"],
                            self.db.execute('SELECT count(*) AS n FROM public."NotificationFailure"')[0]["n"]))
        self.acks.append(delivery_tag)


@pytest.fixture(autouse=True)
def parents(db):
    """Insert synthetic foreign-key parents before each test; no other service is started."""
    make_parents(db)


def consume(database_url, db, envelope, tag=7, channel=None):
    """Pass envelope bytes through the consumer and return a recording ACK channel; no RabbitMQ
    broker runs.
    """
    channel = channel or RecordingChannel(db)
    process(database_url, channel, SimpleNamespace(delivery_tag=tag), json.dumps(envelope).encode())
    return channel


def rows(db):
    """Read persisted inbox rows in a fresh transaction for independent storage assertions."""
    return db.execute('SELECT * FROM public."Notification" ORDER BY notification_id')


def assert_delivered(client, db, envelope, channel):
    """Require one exact committed inbox payload before ACK and retrieve it only as its recipient
    through Flask.
    """
    saved = rows(db)
    assert len(saved) == 1
    assert saved[0]["payload"] == envelope
    assert str(saved[0]["source_id"]) == envelope["id"]
    assert str(saved[0]["recipient_id"]) == ORGANISER
    assert str(saved[0]["event_id"]) == EVENT
    assert saved[0]["type"] == envelope["type"]
    assert saved[0]["created_at"] == datetime.fromisoformat(envelope["createdAt"]).astimezone(UTC)
    assert channel.acks == [7]
    assert channel.at_ack == [(1, 0)]
    response = client.get("/notifications", headers=identity())
    assert response.status_code == 200
    assert response.json["notifications"][0]["payload"] == envelope
    assert client.get("/notifications", headers=identity(OTHER)).json["notifications"] == []


# AC1 — Approval

def test_ac1_approval_is_committed_before_ack_and_retrievable(client, db, database_url):
    """Normal: consume approval and query the inbox as two organisers; a fresh read at ACK sees the
    exact committed payload and only the recipient retrieves it, protecting durability and
    privacy.
    """
    envelope = make_envelope("approval")
    channel = consume(database_url, db, envelope)
    assert_delivered(client, db, envelope, channel)


# AC2 — Rejection and reason

def test_ac2_rejection_keeps_full_multiline_multibyte_reason(client, db, database_url):
    """Boundary: consume rejection with Unicode and newlines; PostgreSQL and inbox JSON preserve
    the exact reason before ACK, so the organiser does not lose part of the explanation.
    """
    envelope = make_envelope("rejection")
    channel = consume(database_url, db, envelope)
    assert_delivered(client, db, envelope, channel)
    assert rows(db)[0]["payload"]["details"]["reason"] == "Needs an accessibility plan.\n交通安排需完善。"


# AC3 — Shared decision content and link
@pytest.mark.parametrize("kind", ["approval", "rejection"])
def test_ac3_decision_payload_preserves_event_decision_and_destination(client, db, database_url, kind):
    """Normal: consume either decision and read the inbox; saved SQL and returned JSON retain event
    name, decision and event-only destination, giving the UI the required decision context.
    """
    envelope = make_envelope(kind)
    consume(database_url, db, envelope)
    payload = client.get("/notifications", headers=identity()).json["notifications"][0]["payload"]
    assert payload["details"]["eventName"] == "Accessible Community Workshop"
    assert payload["details"]["decision"] == ("Approved" if kind == "approval" else "Rejected")
    assert payload["destination"] == dict(kind="event-details", eventId=EVENT)
    assert rows(db)[0]["payload"] == envelope


@pytest.mark.parametrize("kind,change", [
    ("approval", {"details": {}}),
    ("approval", {"details": {"eventName": "Accessible Community Workshop", "decision": "Rejected"}}),
    ("rejection", {"details": {"eventName": "Accessible Community Workshop", "reason": " "}}),
    ("rejection", {"destination": {"kind": "event-venue-request", "eventId": EVENT,
                                  "bookingId": "40000000-0000-4000-8000-000000000001"}}),
])
def test_ac3_invalid_decision_contract_commits_quarantine_not_inbox(db, database_url, kind, change):
    """Failure: consume an invalid decision or link; a fresh read at ACK sees the original bytes
    and diagnosis in quarantine with no inbox row, isolating malformed delivery without losing
    evidence.
    """
    envelope = {**make_envelope(kind), **change}
    body = json.dumps(envelope).encode()
    channel = RecordingChannel(db)
    process(database_url, channel, SimpleNamespace(delivery_tag=12), body)
    assert rows(db) == []
    failure = db.execute('SELECT * FROM public."NotificationFailure"')
    assert len(failure) == 1
    assert bytes(failure[0]["body"]) == body
    assert failure[0]["error"]
    assert channel.acks == [12]
    assert channel.at_ack == [(0, 1)]


# AC4 — Initial assignment and reassignment

def test_ac4_initial_and_reassignment_remain_two_named_historical_notifications(client, db, database_url):
    """Normal: consume initial and replacement assignment envelopes; SQL and inbox retain both
    distinct identities, names and destinations, so reassignment does not erase who was first
    assigned.
    """
    initial = make_envelope("coordinator-assignment", coordinator="Synthetic Alice")
    replacement = make_envelope("coordinator-assignment", coordinator="Synthetic Bob")
    replacement["details"]["coordinatorId"] = "10000000-0000-4000-8000-000000000004"
    consume(database_url, db, initial)
    consume(database_url, db, replacement)
    saved = {row["payload"]["id"]: row["payload"] for row in rows(db)}
    assert saved == {initial["id"]: initial, replacement["id"]: replacement}
    assert saved[initial["id"]]["details"]["coordinatorName"] == "Synthetic Alice"
    assert saved[replacement["id"]]["details"]["coordinatorName"] == "Synthetic Bob"
    response = client.get("/notifications", headers=identity())
    assert response.status_code == 200
    assert len(response.json["notifications"]) == 2
    assert all(item["payload"]["destination"] == dict(kind="event-details", eventId=EVENT)
               for item in response.json["notifications"])


@pytest.mark.parametrize("name", [None, "", " "])
def test_ac4_missing_coordinator_name_is_quarantined(db, database_url, name):
    """Failure: consume assignment with a missing or blank name; a fresh read at ACK sees only
    committed quarantine, preventing an ID-only notification from reaching the organiser.
    """
    envelope = make_envelope("coordinator-assignment")
    envelope["details"]["coordinatorName"] = name
    channel = consume(database_url, db, envelope)
    assert rows(db) == []
    assert len(db.execute('SELECT * FROM public."NotificationFailure"')) == 1
    assert channel.at_ack == [(0, 1)]


# Supporting DR3/DR4/DR8/DR9 — storage recovery, deduplication and recipient read state
@pytest.mark.parametrize("kind", ["approval", "rejection", "coordinator-assignment"])
def test_ac3_dr_replay_preserves_first_payload_and_read_state(client, db, database_url, kind):
    """Conflict: mark a delivered message read, replay altered content and attempt another
    recipient's update; SQL stays unchanged and unread count stays zero, preserving history,
    read state and privacy (DR3/DR4/DR8/DR9).
    """
    envelope = make_envelope(kind)
    consume(database_url, db, envelope)
    marked = client.patch(f"/notifications/{envelope['id']}", json={"read": True}, headers=identity())
    assert marked.status_code == 200
    before = rows(db)[0]
    assert before["read_at"] is not None
    altered = {**envelope, "message": "Later replay must not rewrite history"}
    consume(database_url, db, altered)
    assert rows(db) == [before]
    assert client.get("/notifications/unread-count", headers=identity()).json == {"unreadCount": 0}
    forbidden = client.patch(f"/notifications/{envelope['id']}", json={"read": False}, headers=identity(OTHER))
    assert forbidden.status_code == 404
    assert rows(db) == [before]


@pytest.mark.parametrize("table", ["Notification", "NotificationFailure"])
def test_ac1_dr_storage_failure_does_not_ack_and_recovers_after_repair(db, database_url, table):
    """Failure: reject inbox or quarantine INSERT with a PostgreSQL trigger, then repair and
    reprocess; no first ACK or rows and one committed outcome at the later ACK prevent silent
    message loss (DR3).
    """
    envelope = make_envelope("approval")
    body = json.dumps(envelope if table == "Notification" else {"invalid": True}).encode()
    channel = RecordingChannel(db)
    db.execute('''CREATE FUNCTION scrum45_fail_store() RETURNS trigger LANGUAGE plpgsql AS $$
                  BEGIN RAISE EXCEPTION 'synthetic storage failure'; END $$''')
    db.execute(f'CREATE TRIGGER scrum45_fail_store BEFORE INSERT ON public."{table}" FOR EACH ROW EXECUTE FUNCTION scrum45_fail_store()')
    try:
        with pytest.raises(psycopg2.Error):
            process(database_url, channel, SimpleNamespace(delivery_tag=7), body)
        assert channel.acks == []
        assert rows(db) == []
        assert db.execute('SELECT * FROM public."NotificationFailure"') == []
    finally:
        db.execute(f'DROP TRIGGER scrum45_fail_store ON public."{table}"; DROP FUNCTION scrum45_fail_store()')
    process(database_url, channel, SimpleNamespace(delivery_tag=7), body)
    assert channel.acks == [7]
    assert channel.at_ack == ([(1, 0)] if table == "Notification" else [(0, 1)])
