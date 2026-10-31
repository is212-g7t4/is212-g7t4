"""SCRUM-48: Equipment Request Notification and Decision Alerts

User Story
----------
As an Event Coordinator and Technical Support Staff, I want to receive notifications about equipment requests and decisions, so that I can coordinate equipment arrangements efficiently.

Acceptance Criteria
-------------------
AC1: Given an Event Coordinator submits an equipment request, the system sends an in-app notification to Technical Support Staff with the event name, requested equipment list, and a link to review the request.
AC2: Given Technical Support Staff approves or rejects an Equipment Request, the system sends an in-app notification to the Event Coordinator assigned to that event with the event name, the equipment covered by the decision, and the decision status (Approved or Rejected).
AC3: Given a Technical Support Staff rejects the equipment request, the system sends an in-app notification to the Event Coordinator with the rejection message, event name, equipment request and link to the equipment request.

Real
----
- Flask routes, token signature/role checks, models/allocation SQL, separate real PostgreSQL connections in fixture-owned databases.

Doubled
-------
- Synthetic external Event/catalogue snapshots; JWKS key lookup only. No other service or broker runs.

Not proven
----------
- AC3 "rejection message" means a statement that the Equipment Request was rejected, not that the whole event was rejected and not the private rejectionReason/why. Existing reason-exclusion assertions are intentional; the private reason remains in the review workflow.
- Real owner transaction rollback, visibility and per-changed-request outbox contents are checked, not publication or inbox delivery. Exact atomicity/failure contracts are supporting reliability rules, not additional Jira ACs.
- `test_failed_first_or_later_outbox_insert_rolls_back_all_request_changes`: AC1 relates only to operation=submission; AC2 to single/bulk decisions; AC3 only to decision status=Rejected, never Approved or submission. This is rollback evidence, not a delivered rejection message.
- `test_bulk_decides_only_pending_records_and_emits_one_alert_per_changed_record`: AC2 applies to both statuses; AC3 only to status=Rejected. Event/equipment/decision/destination and private-reason exclusion are asserted, but the human-readable rejection message is not asserted here.
- `test_failed_and_non_decision_operations_create_no_new_alerts` is a supporting no-transition/no-alert regression, including safety reset; no new notification trigger is implied.
- Browser behaviour, real upstream snapshots, concurrent catalogue/schedule edits and notification delivery are not proved. Selected baseline FK tables plus the owner outbox migration remain a known fixture exception, not the full migration chain. Collection alone is not execution.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json

import psycopg2
import pytest

from tests.integration.equipment_request_db_helpers import uid, wait_for

pytestmark = pytest.mark.integration


# Case IDs read operation–failed INSERT position–status. Submission always
# creates Pending requests; its Approved status parameter is unused, not an AC2 case.
@pytest.mark.parametrize("operation,fail_at,status", [
    ("submission", 1, "Approved"), ("submission", 2, "Approved"),
    ("single", 1, "Approved"), ("bulk", 1, "Approved"), ("bulk", 2, "Approved"),
    ("single", 1, "Rejected"), ("bulk", 1, "Rejected"), ("bulk", 2, "Rejected"),
])
def test_failed_first_or_later_outbox_insert_rolls_back_all_request_changes(owner, operation, fail_at, status):
    """Summary: earlier request/decision writes and jobs must never partially commit.
    AC1: Given an Event Coordinator submits an equipment request, the system sends an in-app notification to Technical Support Staff with the event name, requested equipment list, and a link to review the request.
    AC2: Given Technical Support Staff approves or rejects an Equipment Request, the system sends an in-app notification to the Event Coordinator assigned to that event with the event name, the equipment covered by the decision, and the decision status (Approved or Rejected).
    AC3: Given a Technical Support Staff rejects the equipment request, the system sends an in-app notification to the Event Coordinator with the rejection message, event name, equipment request and link to the equipment request.
    Double: Stub (Supabase JWKS lookup supplies a test signing key); Stub (JWT clock fixed for local token verification); Stub (supplied external event/catalogue or notification context; no upstream service runs); PostgreSQL connections, SQL and transactions are real, not doubles
    """
    identifiers = owner.seed_requests() if operation != "submission" else []
    before = owner.db.snapshot()
    owner.db.fail_outbox_insert(fail_at)
    response = owner.submit() if operation == "submission" else owner.review(identifiers[0] if operation == "single" else None, status=status)
    assert response.status_code >= 500, response.json
    assert owner.db.execute("SELECT last_value FROM fault_calls")[0]["last_value"] == fail_at
    assert owner.db.snapshot() == before


@pytest.mark.parametrize("status", ["Approved", "Rejected"])
def test_bulk_decides_only_pending_records_and_emits_one_alert_per_changed_record(owner, status):
    """Summary: One frozen alert is saved per changed request, not per physical unit, batch or previously decided record; inbox delivery is not exercised.
    AC2: Given Technical Support Staff approves or rejects an Equipment Request, the system sends an in-app notification to the Event Coordinator assigned to that event with the event name, the equipment covered by the decision, and the decision status (Approved or Rejected).
    AC3: Given a Technical Support Staff rejects the equipment request, the system sends an in-app notification to the Event Coordinator with the rejection message, event name, equipment request and link to the equipment request.
    Double: Stub (Supabase JWKS lookup supplies a test signing key); Stub (JWT clock fixed for local token verification); Stub (supplied external event/catalogue or notification context; no upstream service runs); PostgreSQL connections, SQL and transactions are real, not doubles
    """
    first = owner.submit(recipients=[])
    second = owner.submit(recipients=[])
    assert first.status_code == second.status_code == 201
    identifiers = [row["id"] for response in (first, second) for row in response.json["requests"]]
    assert owner.review(identifiers[0], status="Rejected").status_code == 200
    baseline = owner.outbox()
    baseline_request = owner.db.execute('SELECT * FROM public."EquipmentRequest" WHERE equipment_request_id=%s', [identifiers[0]])
    response = owner.review(status=status)
    assert response.status_code == 200
    changed_ids = set(identifiers[1:])
    assert {row["id"] for row in response.json["requests"]} == changed_ids
    old_ids = {str(row["source_id"]) for row in baseline}
    new = [row for row in owner.outbox() if str(row["source_id"]) not in old_ids]
    assert len(new) == 3  # changed records, not quantities (5+2+2), nor one bulk alert
    assert {row["envelope"]["destination"]["requestIds"][0] for row in new} == changed_ids
    for row in new:
        envelope = row["envelope"]
        assert envelope["recipientId"] == owner.coordinator
        assert envelope["details"]["decision"] == status
        assert envelope["details"]["eventName"] == "Community Fair"
        assert len(envelope["details"]["items"]) == 1
        item = envelope["details"]["items"][0]
        assert item["equipmentName"] == owner.context["equipmentNames"][item["equipmentId"]]
        assert item["quantityRequested"] == (5 if item["equipmentId"] == owner.equipment[0] else 2)
        assert envelope["destination"] == dict(kind="equipment-requests", eventId=owner.event, requestIds=[item["requestId"]])
        assert "Private workflow reason" not in json.dumps(envelope)
        assert not ({"reason", "rejectionReason", "rejection_reason"} & envelope["details"].keys())
    assert owner.db.execute('SELECT * FROM public."EquipmentRequest" WHERE equipment_request_id=%s', [identifiers[0]]) == baseline_request
    after = owner.db.snapshot()
    assert owner.review(status=status).status_code == 409
    assert owner.db.snapshot() == after


# event = mismatched snapshot event; name = omitted equipment name.
@pytest.mark.parametrize("change", ["event", "name"])
def test_context_validation_after_update_rolls_back_decisions_and_jobs(owner, change):
    """Summary: late validation must roll back decisions and any earlier alert inserts.
    AC2: Given Technical Support Staff approves or rejects an Equipment Request, the system sends an in-app notification to the Event Coordinator assigned to that event with the event name, the equipment covered by the decision, and the decision status (Approved or Rejected).
    Double: Stub (Supabase JWKS lookup supplies a test signing key); Stub (JWT clock fixed for local token verification); Stub (supplied external event/catalogue or notification context; no upstream service runs); PostgreSQL connections, SQL and transactions are real, not doubles
    """
    owner.seed_requests()
    context = {**owner.context, "equipmentNames": dict(owner.context["equipmentNames"])}
    if change == "event":
        context["eventId"] = uid()
    else:
        context["equipmentNames"][owner.equipment[1]] = ""
    before = owner.db.snapshot()
    response = owner.review(context=context)
    assert response.status_code == 400, response.json
    assert owner.db.snapshot() == before


# IDs pair the operation/refusal scenario with its expected HTTP status.
# safety_reset–200 is a successful non-decision, not a notification trigger.
@pytest.mark.parametrize("case,expected", [("missing", 404), ("repeat", 409), ("bulk_no_pending", 409), ("bulk_empty_event", 404), ("unauthorized", 403), ("invalid", 400), ("safety_reset", 200)])
def test_failed_and_non_decision_operations_create_no_new_alerts(owner, case, expected):
    """Summary: no successful notifying business transition means no new alert, even when the non-decision safety-reset action itself returns 200.
    Double: Stub (Supabase JWKS lookup supplies a test signing key); Stub (JWT clock fixed for local token verification); Stub (supplied external event/catalogue or notification context; no upstream service runs); PostgreSQL connections, SQL and transactions are real, not doubles
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
    """
    identifiers = owner.seed_requests()
    if case in ("repeat", "bulk_no_pending", "safety_reset"):
        assert owner.review().status_code == 200
    before = owner.db.snapshot()
    if case == "missing":
        response = owner.review(uid())
    elif case == "repeat":
        response = owner.review(identifiers[0])
    elif case == "bulk_no_pending":
        response = owner.review()
    elif case == "bulk_empty_event":
        empty_event = uid()
        response = owner.client.patch(f"/events/{empty_event}/equipment-requests", headers=owner.identity(),
            json=dict(status="Approved", notificationContext={**owner.context, "eventId": empty_event},
                      approvalContext=owner.approval_context([], empty_event)))
    elif case == "unauthorized":
        response = owner.review(identifiers[0], headers=owner.identity("Event Organiser"))
    elif case == "invalid":
        response = owner.review(identifiers[0], status="Unknown")
    else:
        # As Safety Check Service sends it after a Safety Officer asks for changes (SCRUM-10): the
        # officer's forwarded token plus the service token.
        response = owner.client.post(f"/events/{owner.event}/equipment-requests/safety-reset", headers={**owner.identity("Safety Officer", trusted=False), "X-Internal-Token": "disposable-internal-token"}, json={"requestIds": identifiers})
    assert response.status_code == expected, response.json
    after = owner.db.snapshot()
    for table in ("EquipmentNotificationOutbox",):
        assert after[table] == before[table]
    if case != "safety_reset":
        assert after == before
    else:
        assert {row["status"] for row in after["EquipmentRequest"]} == {"Pending"}


def test_requests_and_entire_fanout_become_visible_only_together_after_commit(owner):
    """Summary: recipients must not observe partially committed business work or partially stored fanout.
    AC1: Given an Event Coordinator submits an equipment request, the system sends an in-app notification to Technical Support Staff with the event name, requested equipment list, and a link to review the request.
    Double: Stub (Supabase JWKS lookup supplies a test signing key); Stub (JWT clock fixed for local token verification); Stub (supplied external event/catalogue or notification context; no upstream service runs); PostgreSQL connections, SQL and transactions are real, not doubles
    """
    owner.db.execute('''CREATE SEQUENCE insert_visibility_calls;
    CREATE FUNCTION block_second_insert() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF nextval('insert_visibility_calls')=2 THEN
        PERFORM pg_advisory_xact_lock(480048);
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER block_second BEFORE INSERT ON public."EquipmentNotificationOutbox"
    FOR EACH ROW EXECUTE FUNCTION block_second_insert();''')
    before = owner.db.snapshot()
    with closing(psycopg2.connect(owner.db.dsn)) as lock:
        with lock.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_lock(480048)')
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(owner.submit)
                    try:
                        wait_for(lambda: owner.db.execute("SELECT pid FROM pg_stat_activity WHERE datname=current_database() AND wait_event='advisory'"), seconds=5)
                        assert owner.db.snapshot() == before
                        assert owner.db.execute('SELECT last_value FROM insert_visibility_calls') == [{"last_value": 2}]
                    finally:
                        cursor.execute('SELECT pg_advisory_unlock(480048)')
                    assert future.result(timeout=5).status_code == 201
            finally:
                cursor.execute('SELECT pg_advisory_unlock_all()')
    assert len(owner.db.snapshot()["EquipmentRequest"]) == 2
    assert len(owner.outbox()) == 2





from app.allocation import APPROVAL_LOCK

from tests.integration.equipment_request_db_helpers import uid, wait_for, TOKEN




def approval_payload(owner, ids, *, event_id=None, events=None, total=20) -> dict:
    """Trusted external Event/catalogue responses frozen before the owner mutation."""
    event_id = event_id or owner.event
    context = {**owner.context, "eventId": event_id}
    checked = owner.approval_context(ids, event_id)
    if events is not None:
        checked["events"] = events
    for item in checked["equipment"]:
        item["totalQuantity"] = total
    return dict(status="Approved", notificationContext=context, approvalContext=checked)

def decide(owner, payload, identifier=None, headers=None):
    """Each caller gets a separate Flask client and a real new PostgreSQL connection."""
    path = f"/equipment-requests/{identifier}" if identifier else f"/events/{payload['approvalContext']['eventId']}/equipment-requests"
    with owner.app.test_client() as client:
        return client.patch(path, headers=owner.identity() if headers is None else headers, json=payload)



# AC2 ----
def test_ac2_bulk_outbox_failure_rolls_back_all_allocations(owner):
    """Summary: Failure on the second outbox INSERT rolls back the first job and every decision.
    AC2: Given Technical Support Staff approves or rejects an Equipment Request, the system sends an in-app notification to the Event Coordinator assigned to that event with the event name, the equipment covered by the decision, and the decision status (Approved or Rejected).
    Double: Stub (Supabase JWKS lookup supplies a test signing key); Stub (JWT clock fixed for local token verification); Stub (supplied external event/catalogue or notification context; no upstream service runs); PostgreSQL connections, SQL and transactions are real, not doubles
    """
    ids = owner.seed_requests(3)
    before = owner.db.snapshot()
    owner.db.fail_outbox_insert(2)
    assert decide(owner, approval_payload(owner, ids)).status_code == 503
    assert owner.db.snapshot() == before
