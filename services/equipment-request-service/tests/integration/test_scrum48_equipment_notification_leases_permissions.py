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
- Owner routes, SQL, PostgreSQL leases, row locks and disposable database ACL/RLS.

Doubled
-------
- Supabase signing-key lookup and supplied event/catalogue context only.

Not proven
----------
- AC3 "rejection message" means a statement that the Equipment Request was rejected, not that the whole event was rejected and not the private rejectionReason/why. Existing reason-exclusion assertions are intentional; the private reason remains in the review workflow.
- These are supporting worker/lease, retry, authentication, SQL privilege (ACL) and row-level security (RLS) regressions, with no explicit Jira AC for their exact contracts. They do not prove any AC delivery or exactly-once sending; Product Owner ownership/acceptance remains pending.
- A lease is a temporary worker claim on an outbox job. The outbox is saved work awaiting publication; it is not an inbox delivery.
- PostgreSQL is real; other services, RabbitMQ, inbox storage and browser navigation are not exercised. Selected baseline FK tables plus the owner migration remain a fixture exception, not the full migration chain.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import threading

import psycopg2
from psycopg2.extensions import parse_dsn
import pytest

from tests.integration.equipment_request_db_helpers import TOKEN, uid, wait_for

pytestmark = pytest.mark.integration


def test_two_concurrent_workers_claim_different_jobs_once(owner):
    """Summary: competing dispatchers must not own the same delivery simultaneously.
    Double: Stub (Supabase JWKS lookup supplies a test signing key); Stub (JWT clock fixed for local token verification); Stub (supplied external event/catalogue or notification context; no upstream service runs); PostgreSQL connections, SQL and transactions are real, not doubles
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
    """
    assert owner.submit().status_code == 201
    barrier = threading.Barrier(2)
    def claim():
        barrier.wait(timeout=5)
        response = owner.app.test_client().post('/internal/notification-outbox/claim', headers={"X-Internal-Token": TOKEN}, json={})
        assert response.status_code == 200
        return response.json["jobs"][0]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(claim) for _ in range(2)]
        jobs = [future.result(timeout=10) for future in futures]
    assert len({job["id"] for job in jobs}) == 2
    assert len({job["leaseToken"] for job in jobs}) == 2
    assert {job["attempts"] for job in jobs} == {1}
    assert {row["attempts"] for row in owner.outbox()} == {1}
    assert owner.claim() == []


def test_claim_skips_locked_unavailable_published_and_live_leases(owner):
    """Summary: skip unavailable work without starving other deliveries.
    Double: Stub (Supabase JWKS lookup supplies a test signing key); Stub (JWT clock fixed for local token verification); Stub (supplied external event/catalogue or notification context; no upstream service runs); PostgreSQL connections, SQL and transactions are real, not doubles
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
    """
    assert owner.submit(recipients=[uid() for _ in range(5)]).status_code == 201
    rows = owner.outbox()
    ids = [str(row["source_id"]) for row in rows]
    owner.db.execute('UPDATE public."EquipmentNotificationOutbox" SET published_at=now() WHERE source_id=%s', [ids[1]])
    owner.db.execute("""UPDATE public."EquipmentNotificationOutbox" SET available_at=now()+interval '1 hour' WHERE source_id=%s""", [ids[2]])
    owner.db.execute("""UPDATE public."EquipmentNotificationOutbox" SET lease_token=%s,lease_until=now()+interval '1 hour' WHERE source_id=%s""", [uid(), ids[3]])
    with closing(psycopg2.connect(owner.db.dsn)) as connection:
        with connection, connection.cursor() as cursor:
            cursor.execute('SELECT 1 FROM public."EquipmentNotificationOutbox" WHERE source_id=%s FOR UPDATE', [ids[0]])
            jobs = owner.claim()
            assert [job["id"] for job in jobs] == [ids[4]]
            assert owner.claim() == []
    assert [job["id"] for job in owner.claim()] == [ids[0]]


@pytest.mark.parametrize("action", ["published", "retry"])
def test_expired_and_stale_tokens_return_conflict_without_effects(owner, action):
    """Summary: a delayed worker must not overwrite another worker’s delivery state.
    Double: Stub (Supabase JWKS lookup supplies a test signing key); Stub (JWT clock fixed for local token verification); Stub (supplied external event/catalogue or notification context; no upstream service runs); PostgreSQL connections, SQL and transactions are real, not doubles
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
    """
    assert owner.submit(recipients=[owner.reviewer]).status_code == 201
    first = owner.claim()[0]
    owner.expire(first["id"])
    before = owner.db.snapshot()
    assert owner.operation(first, action, error="lost").status_code == 409
    assert owner.db.snapshot() == before
    second = owner.claim()[0]
    assert second["id"] == first["id"]
    assert second["envelope"] == first["envelope"]
    assert second["leaseToken"] != first["leaseToken"]
    assert second["attempts"] == 2
    before = owner.db.snapshot()
    for stale in (first, {**second, "leaseToken": uid()}):
        assert owner.operation(stale, action, error="lost").status_code == 409
        assert owner.db.snapshot() == before
    assert owner.operation(second, action, error="recovered").status_code == 200
    assert owner.outbox()[0]["envelope"] == first["envelope"]


@pytest.mark.parametrize("action", ["published", "retry"])
def test_lock_wait_that_crosses_lease_expiry_cannot_finalize(owner, action):
    """Summary: starting before expiry does not authorize a write after a lock wait.
    Double: Stub (Supabase JWKS lookup supplies a test signing key); Stub (JWT clock fixed for local token verification); Stub (supplied external event/catalogue or notification context; no upstream service runs); PostgreSQL connections, SQL and transactions are real, not doubles
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
    """
    assert owner.submit(recipients=[owner.reviewer]).status_code == 201
    job = owner.claim()[0]
    owner.db.execute("""UPDATE public."EquipmentNotificationOutbox" SET lease_until=clock_timestamp()+interval '800 milliseconds' WHERE source_id=%s""", [job["id"]])
    before = owner.db.snapshot()
    with closing(psycopg2.connect(owner.db.dsn)) as lock:
        with lock.cursor() as cursor:
            cursor.execute('SELECT 1 FROM public."EquipmentNotificationOutbox" WHERE source_id=%s FOR UPDATE', [job["id"]])
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(owner.operation, job, action, error="late")
                try:
                    wait_for(lambda: owner.db.execute("SELECT pid FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE 'WITH locked AS MATERIALIZED%'"), seconds=2)
                    wait_for(lambda: owner.db.execute('SELECT lease_until<=clock_timestamp() AS expired FROM public."EquipmentNotificationOutbox" WHERE source_id=%s', [job["id"]])[0]["expired"], seconds=2)
                finally:
                    lock.commit()
                assert future.result(timeout=5).status_code == 409
    assert owner.db.snapshot() == before


@pytest.mark.parametrize("action", ["claim", "published", "retry"])
@pytest.mark.parametrize("case", ["missing", "wrong", "empty_config", "spoofed_role"])
def test_internal_token_rejection_happens_before_database_access(owner, monkeypatch, action, case):
    """Summary: public identities cannot operate jobs.
    Double: Stub (Supabase JWKS lookup supplies a test signing key); Stub (JWT clock fixed for local token verification); Stub (supplied external event/catalogue or notification context; no upstream service runs); PostgreSQL connections, SQL and transactions are real, not doubles
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
    """
    owner.seed_requests()
    before = owner.db.snapshot()
    path = '/internal/notification-outbox/claim' if action == "claim" else f'/internal/notification-outbox/{uid()}/{action}'
    headers = {} if case == "missing" else {"X-Internal-Token": "wrong"}
    if case == "empty_config":
        owner.app.config["INTERNAL_SERVICE_TOKEN"] = ""
        headers = {"X-Internal-Token": TOKEN}
    if case == "spoofed_role":
        headers = owner.identity("Technical Support", trusted=False)
    def forbidden(*args, **kwargs):
        pytest.fail("unauthorized internal request touched PostgreSQL")
    with monkeypatch.context() as guard:
        guard.setattr(psycopg2, "connect", forbidden)
        response = owner.client.post(path, headers=headers, json=dict(leaseToken=uid(), error="ignored"))
    assert response.status_code == 401
    assert owner.db.snapshot() == before


SQL_OPERATIONS = {
    "SELECT": 'SELECT * FROM public."EquipmentNotificationOutbox"',
    "INSERT": '''INSERT INTO public."EquipmentNotificationOutbox" (source_id,type,source,envelope) VALUES (gen_random_uuid(),'equipment.request-submission','{}','{}')''',
    "UPDATE": 'UPDATE public."EquipmentNotificationOutbox" SET attempts=99',
    "DELETE": 'DELETE FROM public."EquipmentNotificationOutbox"',
    "TRUNCATE": 'TRUNCATE public."EquipmentNotificationOutbox"',
}


# IDs pair SQL operation–login role; public_probe inherits only PUBLIC,
# while service_role bypasses RLS and must still be blocked by revoked ACLs.
@pytest.mark.parametrize("role", ["public_probe", "anon", "authenticated", "service_role"])
@pytest.mark.parametrize("operation", list(SQL_OPERATIONS))
def test_client_roles_cannot_read_or_mutate_outbox_even_truncate(owner, role, operation):
    """Summary: ACLs must also block BYPASSRLS service_role and TRUNCATE, not just RLS.
    Double: Stub (Supabase JWKS lookup supplies a test signing key); Stub (JWT clock fixed for local token verification); Stub (supplied external event/catalogue or notification context; no upstream service runs); PostgreSQL connections, SQL and transactions are real, not doubles
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
    """
    assert owner.submit(recipients=[owner.reviewer]).status_code == 201
    before = owner.db.snapshot()
    values = {**parse_dsn(owner.db.dsn), "user": role}
    with closing(psycopg2.connect(**values)) as connection:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege) as error:
            with connection, connection.cursor() as cursor:
                cursor.execute(SQL_OPERATIONS[operation])
        assert error.value.pgcode == "42501"
    assert owner.db.snapshot() == before
    privileges = owner.db.execute("SELECT has_table_privilege(%s, 'public.\"EquipmentNotificationOutbox\"', 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,MAINTAIN') AS allowed", [role])
    assert privileges == [{"allowed": False}]


@pytest.mark.parametrize("role", ["public_probe", "anon", "authenticated"])
def test_rls_still_hides_jobs_if_select_grant_is_accidentally_added(owner, role):
    """Summary: defense survives SELECT grant drift; not BYPASSRLS or TRUNCATE proof.
    Double: Stub (Supabase JWKS lookup supplies a test signing key); Stub (JWT clock fixed for local token verification); Stub (supplied external event/catalogue or notification context; no upstream service runs); PostgreSQL connections, SQL and transactions are real, not doubles
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
    """
    assert owner.submit(recipients=[owner.reviewer]).status_code == 201
    assert len(owner.outbox()) == 1
    owner.db.execute(f'GRANT SELECT ON public."EquipmentNotificationOutbox" TO {role}')
    with closing(psycopg2.connect(**{**parse_dsn(owner.db.dsn), "user": role})) as connection:
        with connection, connection.cursor() as cursor:
            cursor.execute('SELECT * FROM public."EquipmentNotificationOutbox"')
            assert cursor.fetchall() == []
    assert owner.db.execute("SELECT relrowsecurity AS enabled FROM pg_class WHERE oid='public.\"EquipmentNotificationOutbox\"'::regclass") == [{"enabled": True}]
    assert owner.db.execute("SELECT count(*) AS n FROM pg_policy WHERE polrelid='public.\"EquipmentNotificationOutbox\"'::regclass") == [{"n": 0}]


def test_privileged_postgres_owner_retains_all_required_operations(owner):
    """Summary: hardening client access must not break the transactional service owner.
    Double: Stub (Supabase JWKS lookup supplies a test signing key); Stub (JWT clock fixed for local token verification); Stub (supplied external event/catalogue or notification context; no upstream service runs); PostgreSQL connections, SQL and transactions are real, not doubles
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
    """
    assert owner.db.execute('SELECT current_user AS role')[0]["role"] == "postgres"
    owner.db.execute(SQL_OPERATIONS["INSERT"])
    assert len(owner.outbox()) == 1
    owner.db.execute(SQL_OPERATIONS["UPDATE"])
    assert owner.outbox()[0]["attempts"] == 99
    owner.db.execute(SQL_OPERATIONS["DELETE"])
    assert owner.outbox() == []
    owner.db.execute(SQL_OPERATIONS["INSERT"])
    owner.db.execute(SQL_OPERATIONS["TRUNCATE"])
    assert owner.outbox() == []


# Read IDs as attempt-count–delay-seconds: 1→2s, 8→256s, 9/1000→300s cap.
@pytest.mark.parametrize("attempts,delay", [(1, 2), (8, 256), (9, 300), (1000, 300)])
def test_retry_delay_is_bounded_error_is_truncated_and_envelope_stays_frozen(owner, attempts, delay):
    """Summary: recovery must be bounded without changing facts.
    Double: Stub (Supabase JWKS lookup supplies a test signing key); Stub (JWT clock fixed for local token verification); Stub (supplied external event/catalogue or notification context; no upstream service runs); PostgreSQL connections, SQL and transactions are real, not doubles
    Exception: Supporting reliability/security/non-decision contract; no explicit Jira AC specifies this exact rule, and delivery is not proved. PO ownership/acceptance decision remains pending.
    """
    from datetime import timedelta
    assert owner.submit(recipients=[owner.reviewer]).status_code == 201
    job = owner.claim()[0]
    owner.db.execute('UPDATE public."EquipmentNotificationOutbox" SET attempts=%s WHERE source_id=%s', [attempts, job["id"]])
    before = owner.db.execute('SELECT clock_timestamp() AS stamp')[0]["stamp"]
    assert owner.operation(job, "retry", error="x" * 2100).status_code == 200
    after = owner.db.execute('SELECT clock_timestamp() AS stamp')[0]["stamp"]
    row = owner.outbox()[0]
    assert before + timedelta(seconds=delay) <= row["available_at"] <= after + timedelta(seconds=delay)
    assert row["last_error"] == "x" * 2000
    assert row["lease_token"] is row["lease_until"] is None
    assert row["published_at"] is None
    assert row["envelope"] == job["envelope"]
    assert owner.claim() == []
