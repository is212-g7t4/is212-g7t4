"""
SCRUM-48: Equipment Request Notification and Decision Alerts

User Story
----------
As an Event Coordinator and Technical Support Staff, I want to receive
notifications about equipment requests and decisions, so that I can coordinate
equipment arrangements efficiently.

Acceptance Criteria
-------------------
AC1: Given an Event Coordinator submits an equipment request, the system sends
     an in-app notification to Technical Support Staff with the event name,
     requested equipment list, and a link to review the request.
AC2: Given equipment is confirmed as available or found to be unavailable, the
     system sends an in-app notification to the Event Coordinator with the
     event name, equipment list, and availability status.
AC3: Given an equipment request is submitted and pending review, the system
     sends an in-app notification to Technical Support Staff that a request
     requires their review.

SCRUM-8: User Authentication and Authorization

User Story
----------
As a system user, I want to securely access the system, so that I can use the
information and functionality available to me.

Acceptance Criteria
-------------------
AC1: Given a system user has not been successfully authenticated, when they
     attempt to access protected information or functionality, then access is
     denied.
AC2: Given a system user successfully authenticates, when they access protected
     information or functionality, then their access is evaluated according to
     their role and relationship to the relevant event.
AC3: Given a system user's authentication attempt is unsuccessful, when the
     authentication attempt is completed, then they remain unable to access
     protected information or functionality.

Real
----
- The real Flask routes for submission, single and bulk review and the safety
  reset, plus the /internal/notification-outbox claim, published and retry
  endpoints: notification-context validation, the one outbox INSERT per
  recipient or changed record inside the owner's transaction, the lease checks,
  retry back-off and error truncation run for real.
- Assertions are on the status, the outbox INSERT parameters (the frozen
  notification) and how the transaction context exits.

Doubled
-------
- psycopg2.connect: Stub / Mock (`boundary` fixture) - a fresh MagicMock
  connection per test; the cursor returns canned rows (or raises on the outbox
  INSERT); executed SQL is inspected to prove intent, not committed rows.

Not proven
----------
- That the outbox rows commit or roll back with the request in real PostgreSQL,
  and that SKIP LOCKED leasing works under concurrency (-> tests/integration/,
  throwaway postgres:17.6).
- That the dispatcher publishes to RabbitMQ and Notification Service stores the
  inbox item (-> equipment-reservation-service dispatcher tests and
  notification-service consumer tests).
- That the alert links to the request in the UI (AC1 "link to review") (->
  frontend EquipmentRequestsPage.scrum48.test.tsx).
- The availability-status part of AC2: this service only knows
  Approved/Rejected decisions; availability is computed by Equipment
  Reservation Service (NOT COVERED ANYWHERE as a notification field).
"""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import psycopg2
import pytest

from app import create_app
from tests.unit.factories import bearer, approval_context

EVENT, MIC, TABLE, ACTOR, COORDINATOR, TSS1, TSS2, R1, R2, SOURCE, LEASE = [
    f"10000000-0000-4000-8000-{i:012d}" for i in range(1, 12)]
INTERNAL = {"X-Internal-Token": "synthetic"}
STAFF = {**INTERNAL, **bearer(ACTOR, "Technical Support")}
SUBMITTER = {**INTERNAL, **bearer(COORDINATOR, "Event Coordinator")}


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
    payload = dict(payload if payload is not None else {"status": "Approved", "notificationContext": context()})
    if payload["status"] == "Approved":
        payload["approvalContext"] = approval_context(EVENT, [R1, R2] if bulk else [R1], [MIC, TABLE])
    return boundary.client.patch(
        f"/events/{EVENT}/equipment-requests" if bulk else f"/equipment-requests/{R1}",
        headers=STAFF if headers is None else headers, json=payload)


def test_submit_request_notifies_each_technical_support_once_with_full_list(boundary):
    """
    Summary: A submission alerts every Technical Support user once, with the event and the whole equipment list.
    AC1: Given an Event Coordinator submits an equipment request, the system
        sends an in-app notification to Technical Support Staff with the event
        name, requested equipment list, and a link to review the request.
    AC3: Given an equipment request is submitted and pending review, the system
        sends an in-app notification to Technical Support Staff that a request
        requires their review.
    Double: Mock (connect; outbox INSERTs inspected)
    """
    # Arrange (Given)
    boundary.cursor.fetchone.side_effect = [request_row(status="Pending"),
        request_row(R2, TABLE, 2, "Pending")]

    # Act (When)
    response = boundary.client.post(f"/events/{EVENT}/equipment-requests", headers=SUBMITTER,
        json={"items": [{"equipmentId": MIC, "quantityRequested": 5},
                        {"equipmentId": TABLE, "quantityRequested": 2}],
              "notificationContext": context()})

    # Assert (Then)
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


@pytest.mark.parametrize("status", ["Approved", "Rejected"], ids=["approved", "rejected"])
@pytest.mark.parametrize("bulk", [False, True], ids=["single", "bulk"])
def test_review_decision_notifies_coordinator_once_per_changed_request_without_reason(boundary, status, bulk):
    """
    Summary: Each approved or rejected request gives the coordinator one alert naming the event and item, without the private reason.
    AC2: Given equipment is confirmed as available or found to be unavailable,
        the system sends an in-app notification to the Event Coordinator with
        the event name, equipment list, and availability status.
    Double: Mock (connect; outbox INSERTs inspected)
    """
    # Arrange (Given)
    rows = [request_row(status=status), request_row(R2, TABLE, 2, status)] if bulk else [request_row(status=status)]
    boundary.cursor.fetchall.return_value = rows
    boundary.cursor.fetchone.return_value = rows[0]
    if status == "Approved":
        boundary.cursor.fetchall.side_effect = [[{**row, "status": "Pending"} for row in rows], [], rows]

    # Act (When)
    response = decide(boundary, bulk=bulk, payload={"status": status,
        "rejectionReason": "Private staffing reason", "notificationContext": context()})

    # Assert (Then)
    assert response.status_code == 200
    writes = [call for call in boundary.cursor.execute.call_args_list if call.args[0].lstrip().startswith('UPDATE public."EquipmentRequest"')]
    sql, parameters = writes[0].args
    assert "status = 'Pending'" in sql
    assert parameters == ([ACTOR, [R1, R2] if bulk else [R1]] if status == "Approved" else [status, ACTOR, "Private staffing reason", EVENT if bulk else R1])
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
@pytest.mark.parametrize("exists,code", [(True, 409), (False, 404)], ids=["already_decided", "unknown"])
def test_review_when_nothing_changes_sends_no_alert(boundary, bulk, exists, code):
    """
    Summary: A review that changes nothing (unknown or already decided) sends no alert.
    AC2: Given equipment is confirmed as available or found to be unavailable,
        the system sends an in-app notification to the Event Coordinator with
        the event name, equipment list, and availability status.
    Double: Mock (connect; no outbox INSERT)
    """
    # Arrange (Given)
    boundary.cursor.fetchall.return_value = []

    boundary.cursor.fetchone.return_value = (1,) if exists else None

    # Act + Assert (When / Then)
    assert decide(boundary, bulk=bulk).status_code == code
    assert intents(boundary) == []
    assert boundary.connection.__exit__.call_args.args[0] is not None
    boundary.connection.close.assert_called_once()


@pytest.mark.parametrize("stage,fail_at", [("create", 1), ("create", 2),
    ("single", 1), ("bulk", 1), ("bulk", 2)], ids=["create_first_alert", "create_second_alert", "single_review", "bulk_first_alert", "bulk_second_alert"])
def test_submit_or_review_when_alert_cannot_be_queued_fails_whole_change(boundary, stage, fail_at):
    """
    Summary: If an alert cannot be queued, the submission or decision fails too instead of happening silently.
    AC1: Given an Event Coordinator submits an equipment request, the system
        sends an in-app notification to Technical Support Staff with the event
        name, requested equipment list, and a link to review the request.
    AC2: Given equipment is confirmed as available or found to be unavailable,
        the system sends an in-app notification to the Event Coordinator with
        the event name, equipment list, and availability status.
    Double: Stub (outbox INSERT raises on the nth call), Mock (transaction
        exit)
    """
    # Arrange (Given)
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
    if stage != "create":
        selected = rows if stage == "bulk" else rows[:1]
        boundary.cursor.fetchall.side_effect = [[{**row, "status": "Pending"} for row in selected], [], selected]

    # Act (When)
    if stage == "create":
        response = boundary.client.post(f"/events/{EVENT}/equipment-requests", headers=SUBMITTER,
            json={"items": [{"equipmentId": MIC, "quantityRequested": 5},
                            {"equipmentId": TABLE, "quantityRequested": 2}], "notificationContext": context()})
    else:
        response = decide(boundary, bulk=stage == "bulk")

    # Assert (Then)
    assert response.status_code == 503
    assert "private" not in response.get_data(as_text=True)
    assert count == fail_at
    assert boundary.connect.call_count == 1
    assert boundary.connection.__exit__.call_args.args[0] is psycopg2.OperationalError
    boundary.connection.close.assert_called_once()


@pytest.mark.parametrize("change", [
    {"eventId": TSS1}, {"equipmentNames": {}}, {"equipmentNames": {MIC: " "}},
], ids=["other_event", "no_equipment_names", "blank_equipment_name"])
def test_review_with_mismatched_alert_details_returns_400_without_alert(boundary, change):
    """
    Summary: A decision whose alert details do not match the request is refused rather than sending a misleading alert.
    AC2: Given equipment is confirmed as available or found to be unavailable,
        the system sends an in-app notification to the Event Coordinator with
        the event name, equipment list, and availability status.
    Double: Stub (cursor returns the changed row), Mock (transaction exit)
    """
    # Arrange (Given)
    boundary.cursor.fetchone.return_value = request_row()
    boundary.cursor.fetchall.side_effect = [[request_row(status="Pending")], [], [request_row()]]

    snapshot = context(); snapshot.update(change)

    # Act + Assert (When / Then)
    assert decide(boundary, payload={"status": "Approved", "notificationContext": snapshot}).status_code == 400
    assert intents(boundary) == []
    assert boundary.connection.__exit__.call_args.args[0] is not None


@pytest.mark.parametrize("change", [
    None, {"eventId": TSS1}, {"eventName": " "}, {"eventName": 3},
    {"equipmentNames": []}, {"equipmentNames": {}},
    {"equipmentNames": {MIC: None}}, {"recipientIds": None},
    {"recipientIds": [None]}, {"recipientIds": ["bad"]},
], ids=["no_context", "other_event", "blank_event_name", "non_text_event_name", "names_as_list", "no_equipment_names", "missing_equipment_name", "no_recipients", "null_recipient", "bad_recipient"])
def test_submit_request_with_malformed_alert_details_returns_400_before_database(boundary, change):
    """
    Summary: A submission with missing or malformed alert details is refused before anything is saved.
    AC1: Given an Event Coordinator submits an equipment request, the system
        sends an in-app notification to Technical Support Staff with the event
        name, requested equipment list, and a link to review the request.
    Double: Mock (connect not called)
    """
    # Arrange (Given)
    snapshot = context(); snapshot.update(change or {})

    # Act (When)
    response = boundary.client.post(f"/events/{EVENT}/equipment-requests", headers=SUBMITTER,
        json={"items": [{"equipmentId": MIC, "quantityRequested": 5}],
              "notificationContext": snapshot if change is not None else None})

    # Assert (Then)
    assert response.status_code == 400
    boundary.connect.assert_not_called()


@pytest.mark.parametrize("snapshot", [None, {}, {"eventId": 1},
    {"eventId": "bad"}, {"coordinatorId": "bad"}, {"coordinatorId": True}], ids=["no_context", "empty_context", "numeric_event_id", "bad_event_id", "bad_coordinator_id", "non_text_coordinator_id"])
def test_review_with_malformed_alert_details_returns_400_before_database(boundary, snapshot):
    """
    Summary: A decision with missing or malformed alert details is refused before anything is changed.
    AC2: Given equipment is confirmed as available or found to be unavailable,
        the system sends an in-app notification to the Event Coordinator with
        the event name, equipment list, and availability status.
    Double: Mock (connect not called)
    """
    # Arrange (Given)
    if snapshot is not None and snapshot:
        snapshot = {**context(), **snapshot}

    # Act (When)
    response = decide(boundary, payload={"status": "Approved", "notificationContext": snapshot})

    # Assert (Then)
    assert response.status_code == 400
    boundary.connect.assert_not_called()


@pytest.mark.parametrize("configured,supplied", [(None, "synthetic"), ("", ""),
    ("synthetic", None), ("synthetic", "wrong")], ids=["token_not_configured", "token_blank", "token_missing", "token_wrong"])
@pytest.mark.parametrize("operation", ["create", "review", "claim", "published", "retry"], ids=["create", "review", "claim", "published", "retry"])
def test_internal_endpoints_without_valid_internal_token_are_refused_before_database(boundary, configured, supplied, operation):
    """
    Summary: A user's role alone cannot reach the service-only submission, review or delivery endpoints.
    SCRUM-8 AC1: Given a system user has not been successfully authenticated,
        when they attempt to access protected information or functionality,
        then access is denied.
    Double: Mock (connect not called)
    """
    # Arrange (Given)
    boundary.client.application.config["INTERNAL_SERVICE_TOKEN"] = configured
    headers = {k: v for k, v in (SUBMITTER if operation == "create" else STAFF).items() if k != "X-Internal-Token"}
    if supplied is not None:
        headers["X-Internal-Token"] = supplied

    # Act (When)
    if operation == "create":
        response = boundary.client.post(f"/events/{EVENT}/equipment-requests", headers=headers,
            json={"items": [{"equipmentId": MIC, "quantityRequested": 5}], "notificationContext": context()})
    elif operation == "review":
        response = decide(boundary, headers=headers)
    else:
        path = "/internal/notification-outbox/claim" if operation == "claim" else f"/internal/notification-outbox/{SOURCE}/{operation}"
        response = boundary.client.post(path, headers=headers, json={"leaseToken": LEASE})

    # Assert (Then)
    assert response.status_code == (400 if operation in {"create", "review"} else 401)
    boundary.connect.assert_not_called()


def test_review_when_event_has_no_coordinator_decides_without_alert(boundary):
    """
    Summary: With no assigned coordinator, a decision is still saved but no one is sent the alert.
    AC2: Given equipment is confirmed as available or found to be unavailable,
        the system sends an in-app notification to the Event Coordinator with
        the event name, equipment list, and availability status.
    Double: Stub (cursor returns the changed row), Mock (no outbox INSERT)
    """
    # Arrange (Given)
    boundary.cursor.fetchone.return_value = request_row()
    boundary.cursor.fetchall.side_effect = [[request_row(status="Pending")], [], [request_row()]]

    snapshot = context(); snapshot["coordinatorId"] = None

    # Act + Assert (When / Then)
    assert decide(boundary, payload={"status": "Approved", "notificationContext": snapshot}).status_code == 200
    assert intents(boundary) == []


def job_row(**changes):
    row = dict(source_id=SOURCE, type="equipment.request-decision", source={"eventId": EVENT},
        envelope={"id": SOURCE, "recipientId": COORDINATOR}, lease_token=LEASE,
        attempts=1, created_at=datetime(2026, 10, 28, tzinfo=timezone.utc), lease_valid=True)
    row.update(changes)
    return row


def test_claim_alert_job_returns_frozen_alert_and_lease(boundary):
    """
    Summary: The delivery worker can claim one waiting alert with its frozen content and a lease.
    AC2: (delivery: the queued alert is handed to the dispatcher unchanged)
    Double: Stub (cursor returns one job), Mock (claim SQL inspected)
    """
    # Arrange (Given)
    boundary.cursor.fetchall.return_value = [job_row()]

    # Act (When)
    response = boundary.client.post("/internal/notification-outbox/claim", headers=INTERNAL, json={})

    # Assert (Then)
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


@pytest.mark.parametrize("row", [None, job_row(lease_valid=False)], ids=["lost_lease", "expired_lease"])
@pytest.mark.parametrize("action", ["published", "retry"], ids=["published", "retry"])
def test_finish_alert_job_with_lost_or_expired_lease_returns_409_without_update(boundary, row, action):
    """
    Summary: A delivery worker that lost its lease cannot overwrite another worker's progress.
    AC2: (delivery: each alert is sent once)
    Double: Stub (lock finds no job or an expired lease)
    """
    # Arrange (Given)
    boundary.cursor.fetchone.return_value = deepcopy(row)

    # Act (When)
    response = boundary.client.post(f"/internal/notification-outbox/{SOURCE}/{action}",
        headers=INTERNAL, json={"leaseToken": LEASE, "error": "Failure"})

    # Assert (Then)
    assert response.status_code == 409
    assert boundary.cursor.execute.call_count == 1
    sql, params = boundary.cursor.execute.call_args.args
    assert "FOR UPDATE" in sql and "clock_timestamp()" in sql
    assert params == (SOURCE, LEASE)


@pytest.mark.parametrize("attempts,delay", [(0, 1), (1, 2), (8, 256), (9, 300), (10000, 300)], ids=["first_attempt", "second_attempt", "below_cap", "reaches_cap", "far_past_cap"])
def test_retry_alert_job_backs_off_up_to_five_minutes_and_keeps_alert(boundary, attempts, delay):
    """
    Summary: A failed delivery is retried later, never more than five minutes apart, with the same alert.
    AC2: (delivery: a failed send is retried) (boundary: attempts = 0, 1, 8, 9,
        10000)
    Double: Stub (cursor returns a job with N attempts; update inspected)
    """
    # Arrange (Given)
    boundary.cursor.fetchone.return_value = job_row(attempts=attempts)

    # Act (When)
    response = boundary.client.post(f"/internal/notification-outbox/{SOURCE}/retry", headers=INTERNAL,
        json={"leaseToken": LEASE, "error": "x" * 2100})

    # Assert (Then)
    assert response.status_code == 200
    assert response.json == {"id": SOURCE, "status": "retry"}
    sql, params = boundary.cursor.execute.call_args.args
    assert params == (delay, "x" * 2000, SOURCE)
    assert "lease_until=NULL,lease_token=NULL" in sql
    assert "envelope=" not in sql and "published_at=" not in sql


def test_mark_alert_published_clears_lease_and_keeps_alert(boundary):
    """
    Summary: Marking an alert as delivered keeps exactly the alert that was sent.
    AC2: (delivery: each alert is sent once)
    Double: Stub (cursor returns the leased job; update inspected)
    """
    # Arrange (Given)
    boundary.cursor.fetchone.return_value = job_row()

    # Act (When)
    response = boundary.client.post(f"/internal/notification-outbox/{SOURCE}/published",
        headers=INTERNAL, json={"leaseToken": LEASE})

    # Assert (Then)
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
], ids=["unfrozen_alert", "retry_without_error", "non_text_error", "list_body", "no_body", "null_lease", "bad_lease"])
def test_finish_alert_job_with_malformed_request_returns_400_without_update(boundary, action, payload, row):
    """
    Summary: A malformed delivery-worker call cannot corrupt a queued alert.
    AC2: (delivery: each alert is sent once)
    Double: Stub (cursor returns the job)
    """
    # Arrange (Given)
    boundary.cursor.fetchone.return_value = row

    # Act (When)
    response = boundary.client.post(f"/internal/notification-outbox/{SOURCE}/{action}",
        headers=INTERNAL, json=payload)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json == {"message": "Invalid outbox input."}
    assert all(not call.args[0].lstrip().startswith("UPDATE") for call in boundary.cursor.execute.call_args_list)


def test_claim_alert_job_when_none_waiting_returns_no_jobs(boundary):
    """
    Summary: An idle delivery worker is given no alert to send.
    AC2: (delivery: only real alerts are sent)
    Double: Stub (cursor returns no jobs)
    """
    # Arrange (Given)
    boundary.cursor.fetchall.return_value = []

    # Act + Assert (When / Then)
    assert boundary.client.post("/internal/notification-outbox/claim", headers=INTERNAL).json == {"jobs": []}


def test_safety_reset_to_pending_sends_no_decision_alert(boundary):
    """
    Summary: Sending requests back to Pending for a safety revision does not alert anyone of a decision.
    AC2: Given equipment is confirmed as available or found to be unavailable,
        the system sends an in-app notification to the Event Coordinator with
        the event name, equipment list, and availability status.
    Double: Stub (cursor returns the rows), Mock (no outbox INSERT)
    """
    # Arrange (Given)
    boundary.cursor.fetchall.side_effect = [[request_row()], [request_row(status="Pending")]]

    # Act (When)
    response = boundary.client.post(f"/events/{EVENT}/equipment-requests/safety-reset",
        headers={**bearer(ACTOR, "Safety Officer"), "X-Internal-Token": "synthetic"}, json={"requestIds": [R1]})

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["requests"][0]["status"] == "Pending"
    assert intents(boundary) == []
    assert len(boundary.cursor.execute.call_args_list) == 2


def test_submit_request_when_no_technical_support_exists_saves_without_alert(boundary):
    """
    Summary: With no Technical Support users to alert, the request is still saved and no one else is alerted.
    AC1: Given an Event Coordinator submits an equipment request, the system
        sends an in-app notification to Technical Support Staff with the event
        name, requested equipment list, and a link to review the request.
    Double: Stub (cursor returns the saved row), Mock (no outbox INSERT)
    """
    # Arrange (Given)
    boundary.cursor.fetchone.return_value = request_row(status="Pending")
    snapshot = context(); snapshot["recipientIds"] = []

    # Act (When)
    response = boundary.client.post(f"/events/{EVENT}/equipment-requests", headers=SUBMITTER,
        json={"items": [{"equipmentId": MIC, "quantityRequested": 5}], "notificationContext": snapshot})

    # Assert (Then)
    assert response.status_code == 201
    assert response.json["requests"][0]["status"] == "Pending"
    assert intents(boundary) == []
    boundary.connection.__exit__.assert_called_once_with(None, None, None)


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_alert_worker_with_unknown_action_or_storage_failure_fails_safely(boundary):
    """
    Summary: Unknown delivery actions, a missing database and storage errors fail safely without leaking details.
    Supporting design check: delivery endpoints fail safely on bad actions and
        storage errors
    Double: Stub (connect raises OperationalError), Mock (connect not called)
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


def test_health_when_frontend_origin_unset_allows_no_browser_origin(boundary):
    """
    Summary: With no frontend origin configured, no website gets browser access.
    Supporting design check: an unset FRONTEND_ORIGIN grants no origin
    Double: None
    """
    boundary.client.application.config["FRONTEND_ORIGIN"] = None
    response = boundary.client.get("/health", headers={"Origin": "https://untrusted.invalid"})
    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers
