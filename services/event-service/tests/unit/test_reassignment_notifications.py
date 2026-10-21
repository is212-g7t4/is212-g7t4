"""SCRUM-45 user story: As a submitting Event Organiser I want an in-app
update naming my replacement coordinator so I know who is now responsible.
AC4 reassignment; DR2 failed/no-op actions; DR4 saved per-change identity.
Exercise Event's mutation HTTP boundary with only the database driver mocked.
"""
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from app import create_app
from app.models import FIELDS

EVENT = "30000000-0000-0000-0000-000000000001"
ORGANISER = "10000000-0000-0000-0000-000000000001"
ALICE = "10000000-0000-0000-0000-000000000002"
BOB = "10000000-0000-0000-0000-000000000003"


@pytest.fixture
def boundary():
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    with patch("psycopg2.connect", return_value=connection):
        client = create_app({"TESTING": True, "DATABASE_URL": "synthetic",
                             "INTERNAL_SERVICE_TOKEN": "test-token"}).test_client()
        yield client, connection, cursor


def row(coordinator, organiser: str | None = ORGANISER):
    result: dict[str, object] = {column: "" for column in FIELDS.values()}
    result.update(event_id=EVENT, event_name="Community Workshop", status="Under Review",
                  coordinator_id=coordinator, organiser_id=organiser,
                  submission_date=datetime(2026, 10, 1, tzinfo=UTC),
                  preferred_start_date=None, preferred_end_date=None,
                  expected_attendance=30, description="Workshop")
    return result


def assign(client, coordinator):
    return client.patch(f"/events/{EVENT}", json={
        "assignedCoordinatorId": coordinator, "assignedBy": ORGANISER})


def intents(cursor):
    return [call.args[1] for call in cursor.execute.call_args_list
            if 'INSERT INTO public."EventNotificationOutbox"' in call.args[0]]


def test_reassignment_records_replacement_coordinator_for_submitting_organiser(boundary):
    """AC4/DR4: reassign Alice's event to Bob via HTTP; observe a new intent
    with Bob's saved identity and submitting organiser in the same transaction.
    """
    client, connection, cursor = boundary
    cursor.fetchone.side_effect = [dict(coordinator_id=ALICE, status="Under Review"), row(BOB)]
    response = assign(client, BOB)
    assert response.status_code == 200, response.json
    saved = intents(cursor)
    assert len(saved) == 1, "A successful reassignment must save notification work"
    assert saved[0][1] == "event.coordinator-assignment"
    assert saved[0][2].adapted == dict(eventId=EVENT, eventName="Community Workshop",
        recipientId=ORGANISER, coordinatorId=BOB)
    assert connection.__exit__.call_args.args[0] is None


@pytest.mark.parametrize("current,status", [(BOB, "Under Review"), (ALICE, "Rejected"),
    (ALICE, "Cancelled"), (ALICE, "Clarification Requested")])
def test_unchanged_or_closed_reassignment_creates_no_notification(boundary, current, status):
    """DR2: HTTP no-op or closed event rejects the action with no outbox insert."""
    client, _, cursor = boundary
    cursor.fetchone.return_value = dict(coordinator_id=current, status=status)
    assert assign(client, BOB).status_code == 409
    assert intents(cursor) == []


@pytest.mark.parametrize("unavailable_database", [False, True], ids=["invalid-coordinator", "database-unconfigured"])
def test_invalid_or_unavailable_reassignment_has_no_database_work(boundary, unavailable_database):
    """DR2: invalid coordinator or missing DB configuration rejects before any
    transaction, so failed action cannot create notification work.
    """
    client, connection, cursor = boundary
    if unavailable_database:
        client.application.config["DATABASE_URL"] = None
    result = assign(client, BOB if unavailable_database else "not-a-uuid")
    assert result.status_code == (503 if unavailable_database else 400)
    connection.cursor.assert_not_called()
    assert intents(cursor) == []


def test_ownerless_legacy_reassignment_is_diagnosed_without_recipient_guess(boundary, caplog):
    """DR5: ownerless legacy reassignment still succeeds, records diagnosis
    and creates no publishable work or guessed recipient.
    """
    client, _, cursor = boundary
    cursor.fetchone.side_effect = [dict(coordinator_id=ALICE, status="Under Review"), row(BOB, None)]
    assert assign(client, BOB).status_code == 200
    assert "missing organiser" in caplog.text
    assert intents(cursor) == []
