"""SCRUM-48: equipment submission and decision notifications.

Story: Technical Support Staff and Event Coordinators receive in-app equipment
alerts so they can coordinate equipment arrangements.
AC1: Submission alerts identify the event and full submitted equipment list.
AC2: Approval alerts identify the event, item and requested quantity.
AC3: Rejection alerts identify the same facts without the workflow reason.
DR means supporting design rule, never an additional acceptance criterion.

Public seam: real Flask HTTP routes and owner transaction/SQL construction.
PostgreSQL is doubled; assertions prove SQL intent and transaction exit, NOT
committed persistence, locks, delivery or browser navigation. Every test has
fresh connection/cursor/client doubles. No private production helpers are called.
"""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import psycopg2
import pytest

from app import create_app

EVENT, MIC, TABLE, ACTOR, COORDINATOR, TSS1, TSS2, R1, R2, SOURCE, LEASE = [
    f"10000000-0000-4000-8000-{i:012d}" for i in range(1, 12)]
INTERNAL = {"X-Internal-Token": "synthetic"}
STAFF = {**INTERNAL, "X-Dev-User-Id": ACTOR, "X-Dev-Role": "Technical Support"}
SUBMITTER = {**INTERNAL, "X-Dev-User-Id": COORDINATOR, "X-Dev-Role": "Event Coordinator"}


def request_row(identifier=R1, equipment=MIC, quantity=5, status="Approved"):
    """Return a synthetic row returned by PostgreSQL, not a persisted record."""
    return dict(equipment_request_id=identifier, event_id=EVENT,
                equipment_id=equipment, quantity_requested=quantity,
                technical_requirements=None, status=status, reviewed_by=ACTOR,
                rejection_reason="Private staffing reason")


def context():
    return dict(eventId=EVENT, eventName="Community Fair",
                equipmentNames={MIC: "Microphone", TABLE: "Table"},
                recipientIds=[TSS2, TSS1, TSS1], coordinatorId=COORDINATOR)


@pytest.fixture
def boundary(monkeypatch):
    """Arrange a real owner app with a new mocked native DB connection per test."""
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr(psycopg2, "connect", connect)
    client = create_app({"TESTING": True, "DATABASE_URL": "owner-double",
                         "INTERNAL_SERVICE_TOKEN": "synthetic"}).test_client()
    return SimpleNamespace(client=client, connection=connection, cursor=cursor, connect=connect)


def intents(boundary):
    """Extract requested outbox INSERTs; these are not independent DB readback."""
    return [call.args[1] for call in boundary.cursor.execute.call_args_list
            if call.args[0].lstrip().startswith('INSERT INTO public."EquipmentNotificationOutbox"')]


def decide(boundary, *, bulk=False, payload=None, headers=None):
    return boundary.client.patch(
        f"/events/{EVENT}/equipment-requests" if bulk else f"/equipment-requests/{R1}",
        headers=STAFF if headers is None else headers,
        json=payload if payload is not None else {"status": "Approved", "notificationContext": context()})


def test_ac1_submission_freezes_full_list_once_per_unique_tss(boundary):
    """AC1: Arrange two items/duplicate recipients; submit; assert two full-list
    intents (not seven units or four item-recipient alerts) before commit exit.

    Why: A regression would spam staff or omit equipment needed for review.
    """
    boundary.cursor.fetchone.side_effect = [request_row(status="Pending"),
        request_row(R2, TABLE, 2, "Pending")]
    response = boundary.client.post(f"/events/{EVENT}/equipment-requests", headers=SUBMITTER,
        json={"items": [{"equipmentId": MIC, "quantityRequested": 5},
                        {"equipmentId": TABLE, "quantityRequested": 2}],
              "notificationContext": context()})
    assert response.status_code == 201
    jobs = intents(boundary)
    assert len(jobs) == 2
    assert [p[3].adapted["recipientId"] for p in jobs] == [TSS1, TSS2]
    assert len({p[0] for p in jobs}) == 2
    for identifier, kind, source, frozen in jobs:
        assert str(UUID(identifier)) == identifier
        envelope = frozen.adapted
        assert kind == "equipment.request-submission"
        assert envelope["id"] == identifier
        assert envelope["message"] == "Community Fair: equipment requested: Microphone x5, Table x2. Review required."
        assert envelope["details"] == source.adapted
        assert source.adapted["items"] == [
            dict(requestId=R1, equipmentId=MIC, equipmentName="Microphone", quantityRequested=5),
            dict(requestId=R2, equipmentId=TABLE, equipmentName="Table", quantityRequested=2)]
        assert envelope["destination"] == dict(kind="equipment-requests", eventId=EVENT, requestIds=[R1, R2])
    boundary.connection.__exit__.assert_called_once_with(None, None, None)
    boundary.connection.close.assert_called_once()


@pytest.mark.parametrize("status", ["Approved", "Rejected"])
@pytest.mark.parametrize("bulk", [False, True], ids=["single", "bulk"])
def test_decision_alert_per_changed_record_not_quantity_or_action(boundary, status, bulk):
    """AC2/AC3 + bulk DR: Arrange changed rows with quantities >1; review;
    assert one exact reason-free intent per returned record and Pending-only SQL.
    The double does not prove which PostgreSQL rows match that SQL predicate.

    Why: A regression would miscount alerts or expose the private workflow reason.
    """
    rows = [request_row(status=status), request_row(R2, TABLE, 2, status)] if bulk else [request_row(status=status)]
    boundary.cursor.fetchall.return_value = rows
    boundary.cursor.fetchone.return_value = rows[0]
    response = decide(boundary, bulk=bulk, payload={"status": status,
        "rejectionReason": "Private staffing reason", "notificationContext": context()})
    assert response.status_code == 200
    sql, parameters = boundary.cursor.execute.call_args_list[0].args
    assert "status = 'Pending'" in sql
    assert parameters == [status, ACTOR, "Private staffing reason" if status == "Rejected" else None, EVENT if bulk else R1]
    jobs = intents(boundary)
    assert len(jobs) == len(rows)
    assert len({p[0] for p in jobs}) == len(rows)
    for (_, kind, source, frozen), row in zip(jobs, rows):
        name = "Microphone" if row["equipment_id"] == MIC else "Table"
        assert kind == "equipment.request-decision"
        assert frozen.adapted["recipientId"] == COORDINATOR
        assert frozen.adapted["message"] == f"Community Fair: equipment request for {name} x{row['quantity_requested']} {status.lower()}."
        assert frozen.adapted["details"] == source.adapted == dict(eventId=EVENT,
            eventName="Community Fair", recipientId=COORDINATOR, decision=status,
            items=[dict(requestId=row["equipment_request_id"], equipmentId=row["equipment_id"],
                        equipmentName=name, quantityRequested=row["quantity_requested"])])
        assert frozen.adapted["destination"] == dict(kind="equipment-requests", eventId=EVENT,
            requestIds=[row["equipment_request_id"]])
        assert "Private staffing reason" not in repr(frozen.adapted)
    boundary.connection.__exit__.assert_called_once_with(None, None, None)


@pytest.mark.parametrize("bulk", [False, True], ids=["single", "bulk"])
@pytest.mark.parametrize("exists,code", [(True, 409), (False, 404)])
def test_failed_or_noop_review_has_no_outbox_intent(boundary, bulk, exists, code):
    """DR: Arrange no changed row; review missing/already decided data; assert
    404/409 and no outbox INSERT, with exceptional transaction exit and close.

    Why: An unsuccessful decision must not appear successful in the inbox.
    """
    boundary.cursor.fetchall.return_value = []
    boundary.cursor.fetchone.side_effect = ([None, (1,) if exists else None] if not bulk else [(1,) if exists else None])
    assert decide(boundary, bulk=bulk).status_code == code
    assert intents(boundary) == []
    assert boundary.connection.__exit__.call_args.args[0] is not None
    boundary.connection.close.assert_called_once()


@pytest.mark.parametrize("stage,fail_at", [("create", 1), ("create", 2),
    ("single", 1), ("bulk", 1), ("bulk", 2)])
def test_outbox_failure_exits_whole_owner_transaction_with_error(boundary, stage, fail_at):
    """DR rollback observation: Arrange outbox INSERT failure, including after
    an earlier intent; mutate; assert 503, error exits SAME owner transaction,
    and close. Actual rollback/readback is verified only by disposable PG tests.

    Why: A decision without its notification intent would be unrecoverable by the dispatcher.
    """
    count = 0
    def execute(sql, params=()):
        nonlocal count
        if sql.lstrip().startswith('INSERT INTO public."EquipmentNotificationOutbox"'):
            count += 1
            if count == fail_at:
                raise psycopg2.OperationalError("private storage credentials")
    boundary.cursor.execute.side_effect = execute
    # INSERT RETURNING yields Pending; review UPDATE RETURNING yields Approved.
    status = "Pending" if stage == "create" else "Approved"
    rows = [request_row(status=status), request_row(R2, TABLE, 2, status)]
    boundary.cursor.fetchone.side_effect = rows
    boundary.cursor.fetchall.return_value = rows
    if stage == "create":
        response = boundary.client.post(f"/events/{EVENT}/equipment-requests", headers=SUBMITTER,
            json={"items": [{"equipmentId": MIC, "quantityRequested": 5},
                            {"equipmentId": TABLE, "quantityRequested": 2}], "notificationContext": context()})
    else:
        response = decide(boundary, bulk=stage == "bulk")
    assert response.status_code == 503
    assert "private" not in response.get_data(as_text=True)
    assert count == fail_at
    assert boundary.connect.call_count == 1
    assert boundary.connection.__exit__.call_args.args[0] is psycopg2.OperationalError
    boundary.connection.close.assert_called_once()


@pytest.mark.parametrize("change", [
    {"eventId": TSS1}, {"equipmentNames": {}}, {"equipmentNames": {MIC: " "}},
])
def test_inconsistent_decision_snapshot_aborts_after_update(boundary, change):
    """DR context integrity: Arrange changed row and wrong snapshot; review;
    assert 400/no intent and error exits mutation transaction, not success.

    Why: An unrelated event snapshot must not produce a misleading equipment alert.
    """
    boundary.cursor.fetchone.return_value = request_row()
    snapshot = context(); snapshot.update(change)
    assert decide(boundary, payload={"status": "Approved", "notificationContext": snapshot}).status_code == 400
    assert intents(boundary) == []
    assert boundary.connection.__exit__.call_args.args[0] is not None


@pytest.mark.parametrize("change", [
    None, {"eventId": TSS1}, {"eventName": " "}, {"eventName": 3},
    {"equipmentNames": []}, {"equipmentNames": {}},
    {"equipmentNames": {MIC: None}}, {"recipientIds": None},
    {"recipientIds": [None]}, {"recipientIds": ["bad"]},
])
def test_invalid_submission_context_rejected_before_database(boundary, change):
    """DR trusted snapshot: Arrange malformed context; submit; assert safe 400
    without connecting or saving request/outbox rows.

    Why: Malformed notification facts must not accompany a saved submission.
    """
    snapshot = context(); snapshot.update(change or {})
    response = boundary.client.post(f"/events/{EVENT}/equipment-requests", headers=SUBMITTER,
        json={"items": [{"equipmentId": MIC, "quantityRequested": 5}],
              "notificationContext": snapshot if change is not None else None})
    assert response.status_code == 400
    boundary.connect.assert_not_called()


@pytest.mark.parametrize("snapshot", [None, {}, {"eventId": 1},
    {"eventId": "bad"}, {"coordinatorId": "bad"}, {"coordinatorId": True}])
def test_invalid_review_context_rejected_before_database(boundary, snapshot):
    """DR trusted snapshot: Arrange invalid event/coordinator context; review;
    assert 400 before owner mutation, including non-string UUID input.

    Why: A bad recipient or event must not accompany a saved review.
    """
    if snapshot is not None and snapshot:
        snapshot = {**context(), **snapshot}
    response = decide(boundary, payload={"status": "Approved", "notificationContext": snapshot})
    assert response.status_code == 400
    boundary.connect.assert_not_called()


@pytest.mark.parametrize("configured,supplied", [(None, "synthetic"), ("", ""),
    ("synthetic", None), ("synthetic", "wrong")])
@pytest.mark.parametrize("operation", ["create", "review", "claim", "published", "retry"])
def test_role_headers_cannot_replace_internal_token(boundary, configured, supplied, operation):
    """DR authentication: Arrange valid role but missing/wrong internal token;
    call submission/review/worker API; assert rejection and zero DB access.

    Why: Public role claims must not grant trusted service access.
    """
    boundary.client.application.config["INTERNAL_SERVICE_TOKEN"] = configured
    headers = {k: v for k, v in (SUBMITTER if operation == "create" else STAFF).items() if k != "X-Internal-Token"}
    if supplied is not None:
        headers["X-Internal-Token"] = supplied
    if operation == "create":
        response = boundary.client.post(f"/events/{EVENT}/equipment-requests", headers=headers,
            json={"items": [{"equipmentId": MIC, "quantityRequested": 5}], "notificationContext": context()})
    elif operation == "review":
        response = decide(boundary, headers=headers)
    else:
        path = "/internal/notification-outbox/claim" if operation == "claim" else f"/internal/notification-outbox/{SOURCE}/{operation}"
        response = boundary.client.post(path, headers=headers, json={"leaseToken": LEASE})
    assert response.status_code == (400 if operation in {"create", "review"} else 401)
    boundary.connect.assert_not_called()


def test_unassigned_coordinator_creates_no_decision_intent(boundary):
    """DR missing recipient: Arrange no coordinator; approve; assert workflow
    succeeds without sending a decision to the requester or an invented user.

    Why: Missing assignment must not leak a decision to another user.
    """
    boundary.cursor.fetchone.return_value = request_row()
    snapshot = context(); snapshot["coordinatorId"] = None
    assert decide(boundary, payload={"status": "Approved", "notificationContext": snapshot}).status_code == 200
    assert intents(boundary) == []


def job_row(**changes):
    row = dict(source_id=SOURCE, type="equipment.request-decision", source={"eventId": EVENT},
        envelope={"id": SOURCE, "recipientId": COORDINATOR}, lease_token=LEASE,
        attempts=1, created_at=datetime(2026, 10, 28, tzinfo=timezone.utc), lease_valid=True)
    row.update(changes)
    return row


def test_claim_returns_frozen_identity_and_requests_single_eligible_locked_job(boundary):
    """DR leasing: Arrange one DB-returned job; claim over HTTP; assert frozen
    identity/lease response and eligibility/SKIP LOCKED SQL intent. Not lock proof.

    Why: The worker needs the owner identity and lease to retry safely.
    """
    boundary.cursor.fetchall.return_value = [job_row()]
    response = boundary.client.post("/internal/notification-outbox/claim", headers=INTERNAL, json={})
    assert response.status_code == 200
    assert response.json == {"jobs": [dict(id=SOURCE, type="equipment.request-decision",
        source={"eventId": EVENT}, envelope={"id": SOURCE, "recipientId": COORDINATOR},
        leaseToken=LEASE, attempts=1, createdAt="2026-10-28T00:00:00+00:00")]}
    sql, params = boundary.cursor.execute.call_args.args
    for fragment in ("published_at IS NULL", "available_at<=now()", "lease_until<=now()",
                     "FOR UPDATE SKIP LOCKED LIMIT 1", "attempts=attempts+1"):
        assert fragment in sql
    assert str(UUID(params[0])) == params[0]
    boundary.connect.assert_called_once_with("owner-double", connect_timeout=5,
        options="-c statement_timeout=5000 -c lock_timeout=2000")
    boundary.connection.__exit__.assert_called_once_with(None, None, None)
    boundary.connection.close.assert_called_once()


@pytest.mark.parametrize("row", [None, job_row(lease_valid=False)])
@pytest.mark.parametrize("action", ["published", "retry"])
def test_lost_or_expired_lease_does_not_write(boundary, row, action):
    """DR stale worker: Arrange absent/expired locked result; finalize/retry;
    assert 409 and only locking SELECT, never UPDATE or frozen-content changes.

    Why: A stale worker must not overwrite a newer worker's progress.
    """
    boundary.cursor.fetchone.return_value = deepcopy(row)
    response = boundary.client.post(f"/internal/notification-outbox/{SOURCE}/{action}",
        headers=INTERNAL, json={"leaseToken": LEASE, "error": "Failure"})
    assert response.status_code == 409
    assert boundary.cursor.execute.call_count == 1
    sql, params = boundary.cursor.execute.call_args.args
    assert "FOR UPDATE" in sql and "clock_timestamp()" in sql
    assert params == (SOURCE, LEASE)


@pytest.mark.parametrize("attempts,delay", [(0, 1), (1, 2), (8, 256), (9, 300), (10000, 300)])
def test_retry_uses_capped_delay_truncated_error_and_same_source(boundary, attempts, delay):
    """DR retry: Arrange a valid current lease; retry; assert delay cap and
    2000-character error limit, no replacement source/envelope or published mark.

    Why: Retries must stay bounded without replacing the alert identity.
    """
    boundary.cursor.fetchone.return_value = job_row(attempts=attempts)
    response = boundary.client.post(f"/internal/notification-outbox/{SOURCE}/retry", headers=INTERNAL,
        json={"leaseToken": LEASE, "error": "x" * 2100})
    assert response.status_code == 200
    assert response.json == {"id": SOURCE, "status": "retry"}
    sql, params = boundary.cursor.execute.call_args.args
    assert params == (delay, "x" * 2000, SOURCE)
    assert "lease_until=NULL,lease_token=NULL" in sql
    assert "envelope=" not in sql and "published_at=" not in sql


def test_published_clears_lease_only_after_frozen_envelope_exists(boundary):
    """DR finalization: Arrange frozen job/current lease; mark published;
    assert existing source is marked and lease/error cleared without rewriting it.

    Why: Finalization must preserve the exact alert that was delivered.
    """
    boundary.cursor.fetchone.return_value = job_row()
    response = boundary.client.post(f"/internal/notification-outbox/{SOURCE}/published",
        headers=INTERNAL, json={"leaseToken": LEASE})
    assert response.json == {"id": SOURCE, "status": "published"}
    sql, params = boundary.cursor.execute.call_args.args
    assert "published_at=now(),lease_until=NULL,lease_token=NULL,last_error=NULL" in sql
    assert params == (SOURCE,)


@pytest.mark.parametrize("action,payload,row", [
    ("published", {"leaseToken": LEASE}, job_row(envelope=None)),
    ("retry", {"leaseToken": LEASE}, job_row()),
    ("retry", {"leaseToken": LEASE, "error": 7}, job_row()),
    ("published", [], job_row()), ("published", None, job_row()),
    ("published", {"leaseToken": None}, job_row()),
    ("published", {"leaseToken": "bad"}, job_row()),
])
def test_invalid_worker_mutation_never_updates_job(boundary, action, payload, row):
    """DR input: Arrange malformed lease/body/error or unfrozen job; call HTTP;
    assert safe 400 with no UPDATE even if a locking SELECT was necessary.

    Why: Malformed worker calls must not corrupt retryable outbox state.
    """
    boundary.cursor.fetchone.return_value = row
    response = boundary.client.post(f"/internal/notification-outbox/{SOURCE}/{action}",
        headers=INTERNAL, json=payload)
    assert response.status_code == 400
    assert response.json == {"message": "Invalid outbox input."}
    assert all(not call.args[0].lstrip().startswith("UPDATE") for call in boundary.cursor.execute.call_args_list)


def test_worker_unknown_action_missing_database_and_storage_failure_are_safe(boundary):
    """DR infrastructure: Arrange unknown action, missing DSN, then DB error;
    call public routes; assert 404/503 with no leaked exception text and close.

    Why: Operational failures must not become false success or disclose storage details.
    """
    assert boundary.client.post(f"/internal/notification-outbox/{SOURCE}/freeze", headers=INTERNAL, json={}).status_code == 404
    boundary.connect.assert_not_called()
    boundary.client.application.config["DATABASE_URL"] = None
    assert boundary.client.post("/internal/notification-outbox/claim", headers=INTERNAL).status_code == 503
    boundary.connect.assert_not_called()
    boundary.client.application.config["DATABASE_URL"] = "owner-double"
    boundary.cursor.execute.side_effect = psycopg2.OperationalError("password=private")
    response = boundary.client.post("/internal/notification-outbox/claim", headers=INTERNAL)
    assert response.status_code == 503
    assert response.json == {"message": "Outbox storage unavailable."}
    boundary.connection.close.assert_called_once()


def test_empty_claim_does_not_invent_work(boundary):
    """DR no-op: Arrange no eligible row; claim; assert an empty job list.

    Why: An idle worker must not fabricate an alert.
    """
    boundary.cursor.fetchall.return_value = []
    assert boundary.client.post("/internal/notification-outbox/claim", headers=INTERNAL).json == {"jobs": []}


def test_disabled_frontend_origin_does_not_allow_browser_origin(boundary):
    """DR transport: Arrange no configured frontend origin; request health;
    assert service works without allowing arbitrary browser access.

    Why: Missing configuration must not silently broaden browser access.
    """
    boundary.client.application.config["FRONTEND_ORIGIN"] = None
    response = boundary.client.get("/health", headers={"Origin": "https://untrusted.invalid"})
    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers


def test_safety_reset_to_pending_does_not_enqueue_an_approval_or_rejection(boundary):
    """DR no-alert: Arrange an approved request; reset for safety revision;
    assert Pending response with no outbox intent (not a new review decision).

    Why: A safety revision is not an equipment decision and must not trigger a false alert.
    """
    boundary.cursor.fetchall.side_effect = [[request_row()], [request_row(status="Pending")]]
    response = boundary.client.post(f"/events/{EVENT}/equipment-requests/safety-reset",
        headers={"X-Internal-Service-Token": "synthetic"}, json={"requestIds": [R1]})
    assert response.status_code == 200
    assert response.json["requests"][0]["status"] == "Pending"
    assert intents(boundary) == []
    assert len(boundary.cursor.execute.call_args_list) == 2


def test_submission_with_no_eligible_tss_saves_request_without_invented_recipient(boundary):
    """AC1 supporting recipient rule: Arrange empty eligible recipients;
    submit; assert successful Pending save and no invented notification job.

    Why: Unavailable recipients must not cause delivery to an unrelated account.
    """
    boundary.cursor.fetchone.return_value = request_row(status="Pending")
    snapshot = context(); snapshot["recipientIds"] = []
    response = boundary.client.post(f"/events/{EVENT}/equipment-requests", headers=SUBMITTER,
        json={"items": [{"equipmentId": MIC, "quantityRequested": 5}], "notificationContext": snapshot})
    assert response.status_code == 201
    assert response.json["requests"][0]["status"] == "Pending"
    assert intents(boundary) == []
    boundary.connection.__exit__.assert_called_once_with(None, None, None)
