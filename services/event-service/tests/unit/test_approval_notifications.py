"""SCRUM-45 user story: As an Event Organiser, I want to receive an in-app
notification when the Lead Coordinator approves or rejects my event request,
so that I know the outcome and who is responsible for coordinating my event.
AC1/AC3 approval delivery and details; DR2 atomic intent; DR4 saved facts.
"""
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
import pytest
from app import create_app
from app.models import FIELDS

EVENT = "30000000-0000-0000-0000-000000000001"
ACTOR = "10000000-0000-0000-0000-000000000002"
ORGANISER = "10000000-0000-0000-0000-000000000001"


def row(status="Under Review", organiser=ORGANISER):
    result = {column: "" for column in FIELDS.values()}
    result.update(event_id=EVENT, event_name="Community Workshop", status=status,
                  coordinator_id=ACTOR, organiser_id=organiser,
                  submission_date=datetime(2026, 10, 1, tzinfo=UTC),
                  preferred_start_date=None, preferred_end_date=None,
                  expected_attendance=30, description="Workshop")
    return result


@pytest.fixture
def boundary():
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    with patch("psycopg2.connect", return_value=connection):
        client = create_app({"TESTING": True, "DATABASE_URL": "synthetic",
                             "INTERNAL_SERVICE_TOKEN": "test-token"}).test_client()
        yield client, connection, cursor


def approve(client, route, actor=ACTOR):
    body = {"coordinatorId": actor}
    if route == "progress":
        body.update(status="Approved", actionDetails="Ready for approval")
    return client.patch(f"/events/{EVENT}/{route}", json=body)


@pytest.mark.parametrize("route", ["approve", "progress"])
def test_approval_records_saved_organiser_and_event_facts(boundary, route):
    """AC1/AC3/DR4: HTTP mutation with DB I/O mocked saves original recipient/name,
    not the changed values returned by UPDATE, in its own transaction.
    """
    client, connection, cursor = boundary
    updated = {**row("Approved"), "event_name": "Renamed", "organiser_id": ACTOR}
    cursor.fetchone.side_effect = [row(), updated]
    assert approve(client, route).status_code == 200
    inserts = [call.args[1] for call in cursor.execute.call_args_list
               if 'INSERT INTO public."EventNotificationOutbox"' in call.args[0]]
    assert len(inserts) == 1, "Successful approval must save notification intent"
    assert inserts[0][1] == "event.approval"
    assert inserts[0][-1].adapted == {"eventId": EVENT, "eventName": "Community Workshop",
        "recipientId": ORGANISER, "decision": "Approved"}
    assert connection.__exit__.call_args.args[0] is None


@pytest.mark.parametrize("route", ["approve", "progress"])
def test_ownerless_approval_is_diagnosed_without_guessing_recipient(boundary, route, caplog):
    """DR5: approve legacy ownerless event via HTTP; observe diagnostic and no intent."""
    client, _, cursor = boundary
    cursor.fetchone.side_effect = [row(organiser=None), row("Approved", organiser=None)]
    assert approve(client, route).status_code == 200
    assert "missing organiser" in caplog.text
    assert not any('INSERT INTO public."EventNotificationOutbox"' in call.args[0]
                   for call in cursor.execute.call_args_list)


@pytest.mark.parametrize("route", ["approve", "progress"])
def test_repeated_approval_does_not_notify_again(boundary, route):
    """DR2: repeat approved HTTP request; conflict or unchanged progress saves no intent."""
    client, _, cursor = boundary
    cursor.fetchone.side_effect = [row("Approved"), row("Approved")]
    assert approve(client, route).status_code == (409 if route == "approve" else 200)
    assert not any('INSERT INTO public."EventNotificationOutbox"' in call.args[0]
                   for call in cursor.execute.call_args_list)


@pytest.mark.parametrize("route", ["approve", "progress"])
def test_approval_storage_failure_aborts_decision_transaction(boundary, route):
    """DR2: fail intent write at DB boundary; HTTP 503 and transaction exception prove abort."""
    import psycopg2
    client, connection, cursor = boundary
    cursor.fetchone.side_effect = [row(), row("Approved")]
    def execute(sql, params):
        if 'INSERT INTO public."EventNotificationOutbox"' in sql:
            raise psycopg2.OperationalError("isolated intent failure")
    cursor.execute.side_effect = execute
    assert approve(client, route).status_code == 503
    assert connection.__exit__.call_args.args[0] is psycopg2.OperationalError


@pytest.mark.parametrize("route", ["approve", "progress"])
def test_unassigned_actor_cannot_approve_or_notify(boundary, route):
    """DR2/DR8: wrong actor HTTP request returns 403 before mutation or intent."""
    client, _, cursor = boundary
    cursor.fetchone.return_value = row()
    assert approve(client, route, ORGANISER).status_code == 403
    assert cursor.execute.call_count == 1


JOB_ID = "20000000-0000-0000-0000-000000000001"
LEASE = "40000000-0000-0000-0000-000000000001"
HEADERS = {"X-Internal-Token": "test-token"}
SOURCE = {"eventId": EVENT, "eventName": "Community Workshop",
          "recipientId": ORGANISER, "decision": "Approved"}
ENVELOPE = dict(version=1, id=JOB_ID, recipientId=ORGANISER, type="event.approval",
                createdAt="2026-10-21T00:00:00+00:00", message="Community Workshop was approved",
                destination=dict(kind="event-details", eventId=EVENT), details=SOURCE)


def test_approval_envelope_can_be_frozen_and_read_back(boundary):
    """AC1/AC3/DR4: owner HTTP accepts approval facts and returns immutable envelope."""
    client, _, cursor = boundary
    pending = dict(source_id=JOB_ID, source=SOURCE, type="event.approval",
                   envelope=None, attempts=1, lease_token=LEASE, lease_valid=True,
                   created_at=datetime(2026, 10, 21, tzinfo=UTC))
    client.application.config["PROPAGATE_EXCEPTIONS"] = False
    cursor.fetchone.side_effect = [pending, {**pending, "envelope": ENVELOPE}]
    result = client.post(f"/internal/notification-outbox/{JOB_ID}/freeze", headers=HEADERS,
                         json={"leaseToken": LEASE, "envelope": ENVELOPE})
    assert result.status_code == 200
    assert result.json["envelope"] == ENVELOPE


@pytest.mark.parametrize("change", [
    {"recipientId": ACTOR}, {"type": "event.rejection"}, {"message": "Community Workshop was rejected"},
    {"details": {**SOURCE, "eventName": "Renamed"}},
    {"destination": {"kind": "event-details", "eventId": ORGANISER}},
    {"createdAt": "2026-10-22T00:00:00+00:00"},
])
def test_freeze_refuses_rewritten_approval_history(boundary, change):
    """DR4: altered approval crosses owner HTTP boundary; 400 before frozen content write."""
    client, _, cursor = boundary
    cursor.fetchone.return_value = dict(source_id=JOB_ID, source=SOURCE, type="event.approval",
        envelope=None, lease_valid=True, created_at=datetime(2026, 10, 21, tzinfo=UTC))
    result = client.post(f"/internal/notification-outbox/{JOB_ID}/freeze", headers=HEADERS,
        json={"leaseToken": LEASE, "envelope": {**ENVELOPE, **change}})
    assert result.status_code == 400
    assert cursor.execute.call_count == 1
