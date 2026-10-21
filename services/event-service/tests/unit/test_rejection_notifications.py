"""User story (SCRUM-45): As an Event Organiser, I want in-app notification
when the Lead Coordinator rejects my event request, so I know the outcome
and who coordinates it. AC2/AC3: rejection reason, event name and details link.
DR2/DR3/DR4/DR5: atomic intent, retry identity, frozen facts and legacy diagnosis.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
import pytest
from app import create_app
from app.models import FIELDS

EVENT = "30000000-0000-0000-0000-000000000001"
ACTOR = "10000000-0000-0000-0000-000000000002"
ORGANISER = "10000000-0000-0000-0000-000000000001"
REASON = "The proposal does not meet the event requirements."


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


def reject(client, route):
    body = {"coordinatorId": ACTOR}
    body.update({"reason": REASON} if route == "reject" else
                {"status": "Rejected", "actionDetails": REASON})
    return client.patch(f"/events/{EVENT}/{route}", json=body)


@pytest.mark.parametrize("route", ["reject", "progress"])
def test_rejection_records_notification_with_reason(boundary, route):
    """AC2/AC3/DR2: execute each mutation HTTP route with DB I/O mocked;
    observe same-transaction insertion with independent organiser/event facts.
    """
    client, connection, cursor = boundary
    cursor.fetchone.side_effect = [row(), row("Rejected")]
    response = reject(client, route)
    assert response.status_code == 200
    inserts = [call.args[1] for call in cursor.execute.call_args_list
               if 'INSERT INTO public."EventNotificationOutbox"' in call.args[0]]
    assert len(inserts) == 1, "Successful rejection must save durable notification intent"
    source = inserts[0][-1].adapted
    assert source == {"eventId": EVENT, "eventName": "Community Workshop",
                      "recipientId": ORGANISER, "decision": "Rejected", "reason": REASON}
    assert connection.__exit__.call_args.args[0] is None


@pytest.mark.parametrize("route", ["reject", "progress"])
def test_legacy_event_without_organiser_is_diagnosed_without_delivery(boundary, route, caplog):
    """DR5: reject ownerless legacy records through HTTP; observe success,
    diagnostic and absence of publishable outbox intent without guessing owner.
    """
    client, _, cursor = boundary
    cursor.fetchone.side_effect = [row(organiser=None), row("Rejected", organiser=None)]
    assert reject(client, route).status_code == 200
    assert "missing organiser" in caplog.text
    assert not any('INSERT INTO public."EventNotificationOutbox"' in call.args[0]
                   for call in cursor.execute.call_args_list)

HEADERS = {"X-Internal-Token": "test-token"}
SOURCE = {"eventId": EVENT, "eventName": "Community Workshop",
          "recipientId": ORGANISER, "decision": "Rejected", "reason": REASON}
JOB_ID = "20000000-0000-0000-0000-000000000001"
LEASE = "40000000-0000-0000-0000-000000000001"


def test_pending_rejection_can_be_claimed_frozen_and_completed(boundary):
    """DR3/DR4: exercise authenticated owning-service claim/freeze/published
    HTTP lifecycle against DB-driver fixtures, observing the frozen readback.
    """
    client, _, cursor = boundary
    pending = dict(source_id=JOB_ID, source=SOURCE, type="event.rejection",
                   envelope=None, attempts=1, lease_token=LEASE, lease_valid=True,
                   created_at=datetime(2026, 10, 21, tzinfo=UTC))
    cursor.fetchall.return_value = [pending]
    claim = client.post("/internal/notification-outbox/claim", json={}, headers=HEADERS)
    assert claim.status_code == 200, "Event must expose durable pending work to its worker"
    assert claim.json["jobs"][0]["source"] == SOURCE
    envelope = dict(version=1, id=JOB_ID, recipientId=ORGANISER, type="event.rejection",
                    createdAt="2026-10-21T00:00:00+00:00",
                    message=f"Community Workshop was rejected: {REASON}",
                    destination=dict(kind="event-details", eventId=EVENT), details=SOURCE)
    frozen = {**pending, "envelope": envelope}
    cursor.fetchone.side_effect = [pending, frozen, frozen]
    freeze = client.post(f"/internal/notification-outbox/{JOB_ID}/freeze",
                         json={"leaseToken": LEASE, "envelope": envelope}, headers=HEADERS)
    assert freeze.status_code == 200
    assert freeze.json["envelope"] == envelope
    complete = client.post(f"/internal/notification-outbox/{JOB_ID}/published",
                           json={"leaseToken": LEASE}, headers=HEADERS)
    assert complete.status_code == 200
    assert complete.json["status"] == "published"


def test_publish_outage_releases_claim_for_retry_without_erasing_frozen_content(boundary):
    """DR3: retry HTTP operation records backoff and releases lease; observe
    SQL boundary retains envelope and never marks undelivered work published.
    """
    client, _, cursor = boundary
    cursor.fetchone.return_value = dict(lease_valid=True, attempts=1)
    response = client.post(f"/internal/notification-outbox/{JOB_ID}/retry",
                           json={"leaseToken": LEASE, "error": "BrokerUnavailable"}, headers=HEADERS)
    assert response.status_code == 200
    sql, values = cursor.execute.call_args.args
    assert "available_at" in sql and "lease_token=NULL" in sql
    assert "envelope=" not in sql and "published_at=" not in sql
    assert values == (2, "BrokerUnavailable", JOB_ID)

@pytest.mark.parametrize("route", ["reject", "progress"])
def test_outbox_failure_aborts_event_transaction(boundary, route):
    """DR2: inject DB error at intent write; observe 503 and exceptional
    transaction exit (unit rollback contract; real rollback needs integration).
    """
    import psycopg2
    client, connection, cursor = boundary
    cursor.fetchone.side_effect = [row(), row("Rejected")]
    def execute(sql, params):
        if 'INSERT INTO public."EventNotificationOutbox"' in sql:
            raise psycopg2.OperationalError("injected intent failure")
    cursor.execute.side_effect = execute
    assert reject(client, route).status_code == 503
    assert connection.__exit__.call_args.args[0] is psycopg2.OperationalError


@pytest.mark.parametrize("route", ["reject", "progress"])
def test_repeated_rejection_does_not_create_more_intent(boundary, route):
    """DR2: repeat already rejected request at HTTP boundary; observe no new
    intent on conflict or unchanged-status progress update.
    """
    client, _, cursor = boundary
    cursor.fetchone.side_effect = [row("Rejected"), row("Rejected")]
    assert reject(client, route).status_code == (409 if route == "reject" else 200)
    assert not any('INSERT INTO public."EventNotificationOutbox"' in call.args[0]
                   for call in cursor.execute.call_args_list)


@pytest.mark.parametrize("token", [None, "wrong", "é"])
def test_outbox_rejects_unauthenticated_calls_without_db_access(boundary, token):
    """DR8: call internal API without matching token; reject before DB I/O."""
    client, connection, _ = boundary
    headers = {} if token is None else {"X-Internal-Token": token}
    assert client.post("/internal/notification-outbox/claim", headers=headers).status_code == 401
    connection.cursor.assert_not_called()


@pytest.mark.parametrize("missing", [True, False])
def test_expired_or_missing_lease_cannot_complete_work(boundary, missing):
    """DR3: stale completion returns conflict; driver never receives UPDATE."""
    client, _, cursor = boundary
    cursor.fetchone.return_value = None if missing else dict(lease_valid=False)
    result = client.post(f"/internal/notification-outbox/{JOB_ID}/published",
                         headers=HEADERS, json={"leaseToken": LEASE})
    assert result.status_code == 409
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("change", [
    {"version": True}, {"id": ORGANISER}, {"type": "event.approval"},
    {"recipientId": ACTOR}, {"createdAt": "2026-10-22T00:00:00+00:00"},
    {"destination": {"kind": "event-details", "eventId": ORGANISER}},
    {"details": {}}, {"message": "replacement history"},
])
def test_freeze_refuses_changes_to_historical_rejection(boundary, change):
    """DR4/DR8: altered prepared facts/recipient are refused by owning HTTP
    boundary before any frozen-content write. No consumer/worker logic mocked.
    """
    client, _, cursor = boundary
    pending = dict(source_id=JOB_ID, source=SOURCE, type="event.rejection",
                   envelope=None, attempts=1, lease_token=LEASE, lease_valid=True,
                   created_at=datetime(2026, 10, 21, tzinfo=UTC))
    cursor.fetchone.return_value = pending
    envelope = dict(version=1, id=JOB_ID, recipientId=ORGANISER, type="event.rejection",
                    createdAt="2026-10-21T00:00:00+00:00",
                    message=f"Community Workshop was rejected: {REASON}",
                    destination=dict(kind="event-details", eventId=EVENT), details=SOURCE)
    result = client.post(f"/internal/notification-outbox/{JOB_ID}/freeze", headers=HEADERS,
                         json={"leaseToken": LEASE, "envelope": {**envelope, **change}})
    assert result.status_code == 400
    assert cursor.execute.call_count == 1


def test_second_freeze_reads_back_first_frozen_content(boundary):
    """DR4: repeated freeze cannot overwrite prior content; API returns first."""
    client, _, cursor = boundary
    cursor.fetchone.return_value = dict(source_id=JOB_ID, source=SOURCE, envelope={"first": True},
        lease_token=LEASE, lease_valid=True, attempts=2, created_at=datetime(2026, 10, 21, tzinfo=UTC))
    result = client.post(f"/internal/notification-outbox/{JOB_ID}/freeze", headers=HEADERS,
                         json={"leaseToken": LEASE, "envelope": {"second": True}})
    assert result.json["envelope"] == {"first": True}
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("action,body", [("published", {"leaseToken": LEASE}),
    ("retry", {"leaseToken": LEASE, "error": 17}), ("retry", None), ("retry", {"leaseToken": "bad"})])
def test_outbox_refuses_unprepared_completion_and_invalid_inputs(boundary, action, body):
    """DR3: malformed requests and completion before freeze produce 400."""
    client, _, cursor = boundary
    cursor.fetchone.return_value = dict(lease_valid=True, envelope=None)
    assert client.post(f"/internal/notification-outbox/{JOB_ID}/{action}", headers=HEADERS,
                       json=body).status_code == 400


def test_outbox_reports_storage_and_configuration_failures(boundary):
    """DR3: unavailable DB and unknown operations return explicit HTTP errors."""
    import psycopg2
    client, _, cursor = boundary
    assert client.post(f"/internal/notification-outbox/{JOB_ID}/unknown", headers=HEADERS).status_code == 404
    cursor.execute.side_effect = psycopg2.OperationalError("down")
    assert client.post("/internal/notification-outbox/claim", headers=HEADERS).status_code == 503
    client.application.config["DATABASE_URL"] = None
    assert client.post("/internal/notification-outbox/claim", headers=HEADERS).status_code == 503
