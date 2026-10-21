"""SCRUM-45 user story: As an Event Organiser I want in-app updates about
who coordinates my event. AC4 initial assignment; DR2 atomic intent, DR4 saved
identity and DR5 legacy missing-organiser diagnosis. Test owning HTTP boundaries.
"""
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
import pytest
from app import create_app
from app.models import FIELDS

EVENT = "30000000-0000-0000-0000-000000000001"
COORDINATOR = "10000000-0000-0000-0000-000000000002"
ORGANISER = "10000000-0000-0000-0000-000000000001"
LEAD = "10000000-0000-0000-0000-000000000003"

@pytest.fixture
def boundary():
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    with patch("psycopg2.connect", return_value=connection):
        client = create_app({"TESTING": True, "DATABASE_URL": "synthetic",
                             "INTERNAL_SERVICE_TOKEN": "test-token"}).test_client()
        yield client, connection, cursor

def assigned_row(organiser=ORGANISER):
    result = {column: "" for column in FIELDS.values()}
    result.update(event_id=EVENT, event_name="Community Workshop", status="Under Review",
                  coordinator_id=COORDINATOR, organiser_id=organiser,
                  submission_date=datetime(2026, 10, 1, tzinfo=UTC),
                  preferred_start_date=None, preferred_end_date=None,
                  expected_attendance=30, description="Workshop")
    return result

def assign(client):
    return client.patch(f"/events/{EVENT}", json={
        "assignedCoordinatorId": COORDINATOR, "assignedBy": LEAD})

def intents(cursor):
    return [call.args[1] for call in cursor.execute.call_args_list
            if 'INSERT INTO public."EventNotificationOutbox"' in call.args[0]]

def test_initial_assignment_saves_historical_notification_on_same_transaction(boundary):
    """AC4/DR2/DR4: assign via HTTP with DB driver mocked; observe intent
    storing assigned ID, event name and submitting organiser before commit.
    """
    client, connection, cursor = boundary
    cursor.fetchone.side_effect = [dict(coordinator_id=None, status="Submitted"), assigned_row()]
    response = assign(client)
    assert response.status_code == 200, response.json
    saved = intents(cursor)
    assert len(saved) == 1, "Initial assignment must persist notification intent"
    assert saved[0][1] == "event.coordinator-assignment"
    assert saved[0][2].adapted == dict(eventId=EVENT, eventName="Community Workshop",
        recipientId=ORGANISER, coordinatorId=COORDINATOR)
    assert connection.__exit__.call_args.args[0] is None


def test_legacy_assignment_diagnoses_missing_organiser_without_guessing_recipient(boundary, caplog):
    """DR5: assign legacy ownerless event via HTTP; action succeeds with a
    diagnostic but no publishable intent or guessed recipient.
    """
    client, _, cursor = boundary
    cursor.fetchone.side_effect = [dict(coordinator_id=None, status="Submitted"), assigned_row(None)]
    assert assign(client).status_code == 200
    assert "missing organiser" in caplog.text
    assert intents(cursor) == []


@pytest.mark.parametrize("current,status,code", [(COORDINATOR, "Under Review", 409), (None, "Rejected", 409)])
def test_failed_or_unchanged_assignment_has_no_intent(boundary, current, status, code):
    """DR2 regression: failed/no-op assignment via HTTP leaves no pending work."""
    client, _, cursor = boundary
    cursor.fetchone.return_value = dict(coordinator_id=current, status=status)
    assert assign(client).status_code == code
    assert intents(cursor) == []


def test_outbox_failure_aborts_assignment_transaction(boundary):
    """DR2: DB failure at intent insertion reaches transaction rollback and 503."""
    import psycopg2
    client, connection, cursor = boundary
    cursor.fetchone.side_effect = [dict(coordinator_id=None, status="Submitted"), assigned_row()]
    def execute(sql, params):
        if 'INSERT INTO public."EventNotificationOutbox"' in sql:
            raise psycopg2.OperationalError("isolated injected failure")
    cursor.execute.side_effect = execute
    assert assign(client).status_code == 503
    assert connection.__exit__.call_args.args[0] is psycopg2.OperationalError


JOB_ID = "20000000-0000-0000-0000-000000000001"
LEASE = "40000000-0000-0000-0000-000000000001"
HEADERS = {"X-Internal-Token": "test-token"}
SOURCE = dict(eventId=EVENT, eventName="Community Workshop", recipientId=ORGANISER, coordinatorId=COORDINATOR)

def pending():
    return dict(source_id=JOB_ID, source=SOURCE, type="event.coordinator-assignment",
        envelope=None, attempts=1, lease_token=LEASE, lease_valid=True,
        created_at=datetime(2026, 10, 21, tzinfo=UTC))

def test_claim_exposes_assignment_type_and_freeze_accepts_named_saved_identity(boundary):
    """AC4/DR4: claim owning HTTP API exposes assignment type; freeze persists
    name while validating historical saved event/recipient/coordinator facts.
    """
    client, _, cursor = boundary
    cursor.fetchall.return_value = [pending()]
    job = client.post("/internal/notification-outbox/claim", headers=HEADERS, json={}).json["jobs"][0]
    assert job.get("type") == "event.coordinator-assignment"
    envelope = dict(version=1, id=JOB_ID, type="event.coordinator-assignment",
        recipientId=ORGANISER, createdAt=job["createdAt"],
        message="Alice Tan has been assigned to coordinate Community Workshop.",
        destination=dict(kind="event-details", eventId=EVENT),
        details={**SOURCE, "coordinatorName": "Alice Tan"})
    cursor.fetchone.side_effect = [pending(), {**pending(), "envelope": envelope}]
    result = client.post(f"/internal/notification-outbox/{JOB_ID}/freeze", headers=HEADERS,
        json=dict(leaseToken=LEASE, envelope=envelope))
    assert result.status_code == 200
    assert result.json["envelope"] == envelope


def test_name_hold_releases_lease_and_excludes_held_work_from_claims(boundary):
    """DR6: owning HTTP hold records durable diagnosis without retry schedule;
    claim boundary excludes held jobs so unrelated work remains eligible.
    """
    client, _, cursor = boundary
    cursor.fetchone.return_value = pending()
    response = client.post(f"/internal/notification-outbox/{JOB_ID}/hold", headers=HEADERS,
        json=dict(leaseToken=LEASE, error=f"CoordinatorNameUnavailable coordinatorId={COORDINATOR}"))
    assert response.status_code == 200
    writes = [call for call in cursor.execute.call_args_list if call.args[0].startswith("UPDATE")]
    assert len(writes) == 1
    assert "held_at=now()" in writes[0].args[0]
    assert "lease_until=NULL,lease_token=NULL" in writes[0].args[0]
    assert writes[0].args[1] == (f"CoordinatorNameUnavailable coordinatorId={COORDINATOR}", JOB_ID)
    cursor.fetchall.return_value = []
    assert client.post("/internal/notification-outbox/claim", headers=HEADERS, json={}).json == {"jobs": []}
    assert "held_at IS NULL" in cursor.execute.call_args.args[0]


def test_held_work_can_be_inspected_and_released_after_name_repair(boundary):
    """DR6: authenticated operator reads held source/diagnosis and explicitly
    releases it for retry after repairing User data; no event rewrite needed.
    """
    client, _, cursor = boundary
    held_at = datetime(2026, 10, 21, tzinfo=UTC)
    cursor.fetchall.return_value = [{**pending(), "held_at": held_at, "last_error": "CoordinatorNameUnavailable"}]
    response = client.get("/internal/notification-outbox/held", headers=HEADERS)
    assert response.status_code == 200
    assert response.json["jobs"] == [dict(id=JOB_ID, source=SOURCE, error="CoordinatorNameUnavailable", heldAt=held_at.isoformat())]
    cursor.fetchone.return_value = {"source_id": JOB_ID}
    release = client.post(f"/internal/notification-outbox/{JOB_ID}/release", headers=HEADERS, json={})
    assert release.status_code == 200
    assert release.json == {"id": JOB_ID, "status": "released"}
    assert "held_at IS NOT NULL" in cursor.execute.call_args.args[0]
    assert "held_at=NULL" in cursor.execute.call_args.args[0]
    assert "available_at=now()" in cursor.execute.call_args.args[0]


@pytest.mark.parametrize("details", [None, {}, {**SOURCE, "coordinatorName": " "}, {**SOURCE, "coordinatorName": 12},
    {**SOURCE, "coordinatorName": "Alice", "coordinatorId": ORGANISER}])
def test_freeze_refuses_nameless_or_substituted_assignment_identity(boundary, details):
    """AC4/DR4: owning freeze HTTP rejects missing name or substituted saved ID;
    malformed preparation must not overwrite the historical change.
    """
    client, _, cursor = boundary
    cursor.fetchone.return_value = pending()
    envelope = dict(version=1, id=JOB_ID, type="event.coordinator-assignment",
        recipientId=ORGANISER, createdAt="2026-10-21T00:00:00+00:00",
        message="Alice has been assigned to coordinate Community Workshop.",
        destination=dict(kind="event-details", eventId=EVENT), details=details)
    result = client.post(f"/internal/notification-outbox/{JOB_ID}/freeze", headers=HEADERS,
        json=dict(leaseToken=LEASE, envelope=envelope))
    assert result.status_code == 400
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("action", ["hold", "release"])
def test_hold_and_repair_require_internal_authentication(boundary, action):
    """DR6/DR8: outsider cannot hide or requeue work; no DB I/O before auth."""
    client, connection, _ = boundary
    assert client.post(f"/internal/notification-outbox/{JOB_ID}/{action}", json={}).status_code == 401
    assert client.get("/internal/notification-outbox/held").status_code == 401
    connection.cursor.assert_not_called()


def test_hold_refuses_invalid_diagnosis_or_stale_lease(boundary):
    """DR3/DR6: invalid hold has no write; stale worker cannot hold current work."""
    client, _, cursor = boundary
    cursor.fetchone.return_value = pending()
    assert client.post(f"/internal/notification-outbox/{JOB_ID}/hold", headers=HEADERS,
        json=dict(leaseToken=LEASE, error=None)).status_code == 400
    assert cursor.execute.call_count == 1
    cursor.fetchone.return_value = None
    assert client.post(f"/internal/notification-outbox/{JOB_ID}/hold", headers=HEADERS,
        json=dict(leaseToken=LEASE, error="missing name")).status_code == 409


def test_hold_diagnostics_reports_storage_failure_and_repair_requires_held_work(boundary):
    """DR6: operator APIs distinguish nonexistent hold and storage/config failure."""
    import psycopg2
    client, _, cursor = boundary
    cursor.fetchone.return_value = None
    assert client.post(f"/internal/notification-outbox/{JOB_ID}/release", headers=HEADERS, json={}).status_code == 409
    cursor.execute.side_effect = psycopg2.OperationalError("isolated failure")
    assert client.get("/internal/notification-outbox/held", headers=HEADERS).status_code == 503
    client.application.config["DATABASE_URL"] = None
    assert client.get("/internal/notification-outbox/held", headers=HEADERS).status_code == 503
