"""Infra: full-chain clean install and upgrades: Event Service integration tests.

Why: SCRUM-45 schema changes must preserve installed rows, constraints and RLS.
Real: disposable postgres:17.6 and complete unmodified migrations.
Doubled: optional synthetic SQL API roles, not hosted Supabase.
Not proven: service delivery, hosted-role parity or shared migration state.
Upgrade baseline is the exact migration inventory of main aee7bb0551bb739eee1063b680aadb980e00668c."""
import pytest
import psycopg2
import json
from pathlib import Path
from tests.integration.factories import seed_existing_data

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
MIGRATIONS = Path(__file__).resolve().parents[4] / "database/supabase/migrations"
FIRST_SCRUM45 = "20261021000000_event_notification_outbox.sql"
APPROVAL = "20261021000100_event_approval_notifications.sql"
PINNED_MAIN_MIGRATIONS = ['20261011140000_baseline_schema.sql', '20261012234245_require_venue_closure_metadata.sql', '20261016000000_booking_closure_rejection.sql', '20261016100000_add_hold_coordinator.sql', '20261016120000_validate_venue_buffer_times.sql', '20261016142813_safety_check_withdrawal.sql', '20261017000000_notification_inbox.sql', '20261017000001_venue_notification_outbox.sql', '20261023100000_event_change_requests.sql', '20261024120000_attendee_registration_withdrawal.sql']
EXPECTED_TABLES = {'Equipment', 'EquipmentRequest', 'Event', 'EventChangeReq', 'Notification', 'Registration', 'SafetyCheck', 'SafetyCheckFlag', 'User', 'Venue', 'VenueBooking', 'VenueClosure', 'NotificationFailure', 'VenueNotificationOutbox', 'EventNotificationOutbox'}
TYPES = ('event.rejection', 'event.approval', 'event.coordinator-assignment')

def assert_schema_and_types(db):
    """Check the complete schema, allowed/rejected outbox writes, held timestamps, RLS and indexes
    against independent SQL expectations.
    """
    assert set(db.snapshot()) == EXPECTED_TABLES
    columns = dict(db.query("SELECT column_name, data_type FROM information_schema.columns\n                              WHERE table_schema='public' AND table_name='EventNotificationOutbox' "))
    assert columns == {'source_id': 'uuid', 'type': 'character varying', 'source': 'jsonb', 'envelope': 'jsonb', 'created_at': 'timestamp with time zone', 'published_at': 'timestamp with time zone', 'attempts': 'integer', 'available_at': 'timestamp with time zone', 'lease_token': 'uuid', 'lease_until': 'timestamp with time zone', 'last_error': 'text', 'held_at': 'timestamp with time zone'}
    assert db.query("SELECT is_nullable FROM information_schema.columns\n                      WHERE table_schema='public' AND table_name='EventNotificationOutbox' AND column_name='held_at' ") == [('YES',)]
    for kind in TYPES:
        source_id, held_at = db.query('INSERT INTO public."EventNotificationOutbox"(type,source)\n                                        VALUES (%s,\'{"synthetic":true}\') RETURNING source_id, held_at', (kind,))[0]
        assert held_at is None
        db.query('UPDATE public."EventNotificationOutbox" SET held_at=\'2030-01-01T12:00:00+08:00\'\n                    WHERE source_id=%s', (str(source_id),))
        assert db.query('SELECT held_at=\'2030-01-01T04:00:00Z\'::timestamptz\n                           FROM public."EventNotificationOutbox" WHERE source_id=%s', (str(source_id),)) == [(True,)]
    with pytest.raises(psycopg2.errors.CheckViolation):
        db.query('INSERT INTO public."EventNotificationOutbox"(type,source) VALUES (\'event.invalid\',\'{}\')')
    with pytest.raises(psycopg2.errors.NotNullViolation):
        db.query('INSERT INTO public."EventNotificationOutbox"(type,source) VALUES (\'event.approval\',NULL)')
    row_security = dict(db.query("SELECT c.relname,c.relrowsecurity FROM pg_class c JOIN pg_namespace n\n                                   ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r' "))
    assert row_security == dict.fromkeys(EXPECTED_TABLES, True)
    assert db.query("SELECT count(*) FROM pg_policies WHERE schemaname='public' ") == [(0,)]
    indexes = dict(db.query("SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='public'\n                              AND tablename='EventNotificationOutbox' "))
    assert 'UNIQUE INDEX' in indexes['EventNotificationOutbox_pkey']
    assert 'WHERE (published_at IS NULL)' in indexes['event_outbox_pending']
    print('VERIFIED all tables, exact EventNotificationOutbox column types, three allowed types, invalid-type rejection, nullable/timezone-safe held_at, RLS and indexes', flush=True)

@pytest.mark.parametrize('installation', ['clean', 'pre-scrum45', 'rejection-only', 'latest-main-pre-scrum45'])
def test_migrations_full_chain_preserves_schema_types_and_existing_data(installation, migration_database):
    """Normal: apply the complete chain from clean, pre-feature, rejection-only or pinned-main
    state; SQL schema checks and seeded-row snapshots prove pending migrations preserve existing
    data, including backdated upgrades.
    """
    paths = sorted(MIGRATIONS.glob('*.sql'))
    assert paths and paths[0].name == '20261011140000_baseline_schema.sql'
    expected_history = [path.name for path in paths]
    with migration_database() as db:
        if installation == 'clean':
            db.apply(paths)
        else:
            cutoff = FIRST_SCRUM45 if installation == 'pre-scrum45' else APPROVAL
            if installation == 'latest-main-pre-scrum45':
                installed = [path for path in paths if path.name in PINNED_MAIN_MIGRATIONS]
                assert {path.name for path in installed} == set(PINNED_MAIN_MIGRATIONS)
                pending = [path for path in paths if path.name not in PINNED_MAIN_MIGRATIONS]
            else:
                installed = [path for path in paths if path.name < cutoff]
                pending = [path for path in paths if path.name >= cutoff]
            expected_history = [path.name for path in installed + pending]
            db.apply(installed)
            seed_existing_data(db)
            before = db.snapshot()
            assert before and all(before.values()), 'Every existing table must contain synthetic data'
            db.apply(pending)
            assert_snapshot_preserved(db, before)
            assert db.query('SELECT count(*) FROM public."EventNotificationOutbox" WHERE held_at IS NOT NULL') == [(0,)]
        assert db.applied == expected_history
        assert set(db.applied) == {path.name for path in paths}
        assert_schema_and_types(db)
        print(f'COMPLETE installation={installation} migrations={len(db.applied)}', flush=True)

def test_migrations_owner_and_supabase_like_role_access(migration_database):
    """Boundary: apply migrations with synthetic API-role grants and exercise each SQL role;
    owner/BYPASSRLS access works while policy-less client roles see no rows or writes,
    distinguishing table grants from RLS without claiming hosted authentication.
    """
    with migration_database(bootstrap=True) as db:
        db.apply(sorted(MIGRATIONS.glob('*.sql')))
        assert_schema_and_types(db)
        owner = db.query('SELECT current_user')[0][0]
        assert owner == 'isolated'
        for role in ('anon', 'authenticated', 'service_role'):
            assert db.query('SELECT has_table_privilege(%s,\'public."EventNotificationOutbox"\',\'SELECT,INSERT,UPDATE,DELETE\')', (role,)) == [(True,)]
            db.query('SET ROLE ' + role)
            try:
                count = db.query('SELECT count(*) FROM public."EventNotificationOutbox"')[0][0]
                if role == 'service_role':
                    assert count == len(TYPES)
                    db.query('INSERT INTO public."EventNotificationOutbox"(type,source) VALUES (\'event.approval\',\'{}\')')
                else:
                    assert count == 0
                    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                        db.query('INSERT INTO public."EventNotificationOutbox"(type,source) VALUES (\'event.approval\',\'{}\')')
                    assert db.query('UPDATE public."EventNotificationOutbox" SET held_at=now() RETURNING source_id') == []
                    assert db.query('DELETE FROM public."EventNotificationOutbox" RETURNING source_id') == []
            finally:
                db.query('RESET ROLE')
        assert db.query('SELECT count(*) FROM public."EventNotificationOutbox"') == [(len(TYPES) + 1,)]
        print('ACCESS owner allowed; service_role BYPASSRLS allowed; anon/authenticated SELECT empty, INSERT rejected, UPDATE/DELETE empty despite table grants', flush=True)

def assert_snapshot_preserved(db, before):
    """Compare every pre-upgrade row and old column value with a fresh snapshot; allow additive
    columns but no lost or changed existing data.
    """
    after = db.snapshot()
    for table, old_rows in before.items():
        old_keys = set(old_rows[0][0]) if old_rows else set()
        projected = [{key: row[0][key] for key in old_keys} for row in after[table]]
        expected = [row[0] for row in old_rows]
        key = lambda value: json.dumps(value, sort_keys=True)
        assert sorted(projected, key=key) == sorted(expected, key=key), table
    print('PRESERVED ' + ', '.join((f'{table}={len(rows)}' for table, rows in before.items())), flush=True)


@pytest.mark.parametrize("existing_rejection", [False, True], ids=["clean", "existing-rejection"])
@pytest.mark.parametrize("assignment_first", [False, True], ids=["chronological", "independent-order"])
def test_forward_migrations_preserve_rejection_and_all_three_types(migration_database, existing_rejection, assignment_first):
    """Conflict: apply approval and assignment migrations in either order, with or without pending
    rejection work; SQL checks preserve every old row and accept all three types, guarding
    independently deployed forward migrations.
    """
    with migration_database() as db:
        paths = {path.name: path for path in MIGRATIONS.glob("*.sql")}
        db.apply([paths[name] for name in PINNED_MAIN_MIGRATIONS])
        seed_existing_data(db)
        db.apply([paths[FIRST_SCRUM45]])
        if existing_rejection:
            db.query('''INSERT INTO public."EventNotificationOutbox" (type,source)
                       VALUES ('event.rejection','{"preserved":true}')''')
        before = db.snapshot()
        forwards = [APPROVAL, "20261021020000_event_notification_assignments.sql"]
        if assignment_first:
            forwards.reverse()
        db.apply([paths[name] for name in forwards])
        assert_snapshot_preserved(db, before)
        assert_schema_and_types(db)
        # Later additive features are still applied in full-chain regression runs.
        db.apply([path for name, path in sorted(paths.items()) if name not in db.applied])
        assert set(db.applied) == set(paths)
