"""SCRUM48 owner-only PostgreSQL claims and ACL integration.
Supports AC1 submission, AC2 approval, AC3 reason-free rejection; reliability and
security rules are not new ACs. No other service or broker production code runs.
Disposable PostgreSQL proves locks/expiry/ACL/RLS, not hosted Supabase parity.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import threading

import psycopg2
from psycopg2.extensions import parse_dsn
import pytest

from tests.integration.owner_postgres import TOKEN, uid, wait_for

pytestmark = pytest.mark.integration


def test_two_concurrent_workers_claim_different_jobs_once(owner):
    """DR concurrency; supports AC1–AC3.
    Given two ready jobs and synchronized workers, when both claim at once,
    then each gets a different job/token and each attempt count is one.
    Why: competing dispatchers must not own the same delivery simultaneously.
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
    """DR eligibility; supports AC1–AC3.
    Given locked, delayed, published, leased and ready jobs, when claiming,
    then only ready work is returned; the locked job becomes eligible on unlock.
    Why: skip unavailable work without starving other deliveries.
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
    """DR lease ownership; supports AC1–AC3.
    Given an expired then reclaimed job, when expired, old or random tokens act,
    then each gets 409 with unchanged SQL state; only the new owner succeeds.
    Why: a delayed worker must not overwrite another worker’s delivery state.
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
    """DR clock-at-lock; supports AC1–AC3.
    Given a valid lease blocked on a row lock, when the DB clock passes expiry,
    then releasing the lock yields HTTP 409 and no saved changes.
    Why: starting before expiry does not authorize a write after a lock wait.
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
    """DR internal authorization; supports AC1–AC3.
    Given missing/wrong credentials, empty config or a spoofed ordinary role,
    when any internal outbox route is called, then it returns 401 before connect
    and leaves stored state intact. Why: public identities cannot operate jobs.
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
    """DR SQL privileges; supports AC1–AC3.
    Given owner-visible work, when each restricted login runs each SQL operation,
    then PostgreSQL refuses it with 42501 and the owner sees unchanged state.
    Why: ACLs must also block BYPASSRLS service_role and TRUNCATE, not just RLS.
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
    """DR RLS defense in depth; supports AC1–AC3.
    Given a stored job and an accidental disposable SELECT grant, when an
    ordinary login reads, then no rows are visible under enabled/no-policy RLS.
    Why: defense survives SELECT grant drift; not BYPASSRLS or TRUNCATE proof.
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
    """DR service-owner access; supports AC1–AC3.
    Given the restrictive migration, when postgres inserts/selects/updates/
    deletes/truncates, then each operation succeeds with the expected saved state.
    Why: hardening client access must not break the transactional service owner.
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
    """DR bounded recovery; supports AC1–AC3.
    Given a claimed job at each attempt boundary, when retry records a long error,
    then fresh SQL shows the expected delay/cap, truncated error, released lease
    and unchanged envelope. Why: recovery must be bounded without changing facts.
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
