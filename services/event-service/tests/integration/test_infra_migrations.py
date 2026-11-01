"""Infra: full-chain clean install and upgrades: Event Service integration tests.

Why: SCRUM-44, SCRUM-45, SCRUM-46, SCRUM-49 and SCRUM-166 schema changes must preserve installed rows, constraints and RLS.
Real: disposable postgres:17.6 and complete unmodified migrations.
Doubled: synthetic NOLOGIN SQL API roles; optional default grants, not hosted Supabase.
Not proven: service delivery, hosted-role parity or shared migration state.
Upgrade baselines are pinned below; SCRUM-166 uses main f0cd2c16ef56b5a4e15bc7d774d1b3ddb6b65f9e."""
import pytest
import psycopg2
import json
import re
from pathlib import Path
from uuid import uuid4
from psycopg2.extras import Json
from tests.integration.factories import seed_existing_data

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
MIGRATIONS = Path(__file__).resolve().parents[4] / "database/supabase/migrations"
FIRST_SCRUM45 = "20261021000000_event_notification_outbox.sql"
APPROVAL = "20261021000100_event_approval_notifications.sql"
PINNED_MAIN_MIGRATIONS = ['20261011140000_baseline_schema.sql', '20261012234245_require_venue_closure_metadata.sql', '20261016000000_booking_closure_rejection.sql', '20261016100000_add_hold_coordinator.sql', '20261016120000_validate_venue_buffer_times.sql', '20261016142813_safety_check_withdrawal.sql', '20261017000000_notification_inbox.sql', '20261017000001_venue_notification_outbox.sql', '20261023100000_event_change_requests.sql', '20261024120000_attendee_registration_withdrawal.sql']
# Exact intermediate inventory after approval/assignment, before later additive migrations.
HISTORICAL_TABLES = {'Equipment', 'EquipmentRequest', 'Event', 'EventChangeReq', 'Notification', 'Registration', 'SafetyCheck', 'SafetyCheckFlag', 'User', 'Venue', 'VenueBooking', 'VenueClosure', 'NotificationFailure', 'VenueNotificationOutbox', 'EventNotificationOutbox'}
# Current combined SCRUM-49/SCRUM-46 chain includes both additive owner outboxes.
EXPECTED_TABLES = HISTORICAL_TABLES | {'EquipmentNotificationOutbox', 'RegistrationNotificationOutbox'}
TYPES = ('event.rejection', 'event.approval', 'event.coordinator-assignment')
# Actual SCRUM-166 target inventory: f0cd2c16ef56b5a4e15bc7d774d1b3ddb6b65f9e.
SCRUM166_MAIN_MIGRATIONS = ['20261011140000_baseline_schema.sql', '20261012234245_require_venue_closure_metadata.sql', '20261016000000_booking_closure_rejection.sql', '20261016100000_add_hold_coordinator.sql', '20261016120000_validate_venue_buffer_times.sql', '20261016142813_safety_check_withdrawal.sql', '20261017000000_notification_inbox.sql', '20261017000001_venue_notification_outbox.sql', '20261021000000_event_notification_outbox.sql', '20261021000100_event_approval_notifications.sql', '20261021020000_event_notification_assignments.sql', '20261023100000_event_change_requests.sql', '20261024120000_attendee_registration_withdrawal.sql', '20261025000000_event_submission_notifications.sql']

def assert_schema_and_types(db, expected_tables=EXPECTED_TABLES):
    """Check the complete schema, allowed/rejected outbox writes, held timestamps, RLS and indexes
    against independent SQL expectations.
    """
    assert set(db.snapshot()) == expected_tables
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
    assert row_security == dict.fromkeys(expected_tables, True)
    assert db.query("SELECT count(*) FROM pg_policies WHERE schemaname='public' ") == [(0,)]
    indexes = dict(db.query("SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='public'\n                              AND tablename='EventNotificationOutbox' "))
    assert 'UNIQUE INDEX' in indexes['EventNotificationOutbox_pkey']
    assert 'WHERE (published_at IS NULL)' in indexes['event_outbox_pending']
    print('VERIFIED all tables, exact EventNotificationOutbox column types, three allowed types, invalid-type rejection, nullable/timezone-safe held_at, RLS and indexes', flush=True)

@pytest.mark.parametrize('installation', ['clean', 'pre-scrum45', 'rejection-only', 'latest-main-pre-scrum45', 'latest-main-pre-scrum166'])
def test_migrations_full_chain_preserves_schema_types_and_existing_data(installation, migration_database):
    """Normal: apply the complete chain from clean, pre-feature, rejection-only or either pinned-main
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
            if installation in ('latest-main-pre-scrum45', 'latest-main-pre-scrum166'):
                inventory = SCRUM166_MAIN_MIGRATIONS if installation == 'latest-main-pre-scrum166' else PINNED_MAIN_MIGRATIONS
                installed = [path for path in paths if path.name in inventory]
                assert {path.name for path in installed} == set(inventory)
                pending = [path for path in paths if path.name not in inventory]
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
        for kind in ('event.submission-fanout', 'event.submission',
                     'event.coordinator-assigned', 'event.coordinator-removed'):
            db.query('INSERT INTO public."EventNotificationOutbox" (type,source) VALUES (%s,%s::jsonb)', (kind, '{}'))
        print(f'COMPLETE installation={installation} migrations={len(db.applied)}', flush=True)

@pytest.mark.parametrize('bootstrap', [False, True], ids=['roles-only', 'default-grants'])
def test_migration_roles_exist_without_implicitly_enabling_default_grants(migration_database, bootstrap):
    """Boundary: migration-required NOLOGIN roles exist in both modes; hosted-like grants are opt-in."""
    with migration_database(bootstrap=bootstrap) as db:
        assert db.query("SELECT rolname, rolcanlogin, rolbypassrls FROM pg_roles "
                        "WHERE rolname IN ('anon', 'authenticated', 'service_role') ORDER BY rolname") == [
            ('anon', False, False), ('authenticated', False, False), ('service_role', False, True)]
        db.apply(sorted(MIGRATIONS.glob('*.sql')))
        for role in ('anon', 'authenticated', 'service_role'):
            assert db.query('SELECT has_table_privilege(%s,\'public."EventNotificationOutbox"\',\'SELECT,INSERT,UPDATE,DELETE\')', (role,)) == [(bootstrap,)]


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
        assert_schema_and_types(db, expected_tables=HISTORICAL_TABLES)
        # Later additive features are still applied in full-chain regression runs.
        db.apply([path for name, path in sorted(paths.items()) if name not in db.applied])
        assert set(db.applied) == set(paths)


def test_event_change_upgrade_preserves_existing_outbox_rows_and_types(migration_database):
    """Normal: additive SCRUM-49 upgrade retains all old delivery types and frozen/pending history."""
    # Arrange: exact pre-feature inventory is the full chain except this one pending migration.
    paths = sorted(MIGRATIONS.glob("*.sql"))
    pending = [path for path in paths if path.name == "20261028000200_event_change_notifications.sql"]
    assert len(pending) == 1
    with migration_database(bootstrap=True) as db:
        db.apply([path for path in paths if path not in pending])
        kinds = ("event.rejection", "event.approval", "event.coordinator-assignment", "event.submission-fanout",
                 "event.submission", "event.coordinator-assigned", "event.coordinator-removed",
                 "safety.review-fanout", "safety.review-submitted", "safety.review-decision")
        for kind in kinds:
            db.query('INSERT INTO public."EventNotificationOutbox"(type,source) VALUES (%s,%s::jsonb)', [kind, '{"pending":true}'])
        db.query('UPDATE public."EventNotificationOutbox" SET envelope=%s::jsonb,published_at=now() WHERE type=%s',
                 ['{"frozen":"historical"}', "event.rejection"])
        before = db.snapshot()
        # Act
        db.apply(pending)
        # Assert: all existing rows, columns, types, and non-target tables survive unchanged.
        assert db.snapshot() == before
        for kind in (*kinds, "event.change-request-submitted", "event.change-request-approved", "event.change-request-rejected", "event.cancelled"):
            db.query('INSERT INTO public."EventNotificationOutbox"(type,source) VALUES (%s,%s::jsonb)', [kind, '{}'])
        with pytest.raises(psycopg2.errors.CheckViolation):
            db.query('INSERT INTO public."EventNotificationOutbox"(type,source) VALUES (%s,%s::jsonb)', ["event.invalid", '{}'])


def test_submission_migration_upgrades_current_main_without_changing_existing_rows(migration_database):
    """Normal: the submission migration preserves existing rows and notification types.
    Both new submission types can be saved without changing the existing schema."""
    paths = sorted(MIGRATIONS.glob('*.sql'))
    pending = [path for path in paths if path.name == '20261025000000_event_submission_notifications.sql']
    assert len(pending) == 1
    with migration_database() as db:
        db.apply([path for path in paths if path not in pending])
        seed_existing_data(db)
        for kind in TYPES:
            db.query('INSERT INTO public."EventNotificationOutbox"(type,source) VALUES (%s,%s)', (kind, '{"preserved":true}'))
        before = db.snapshot()
        db.apply(pending)
        assert db.snapshot() == before
        assert_schema_and_types(db)
        for kind in ('event.submission-fanout', 'event.submission'):
            db.query('INSERT INTO public."EventNotificationOutbox"(type,source) VALUES (%s,%s)', (kind, '{"new":true}'))
        assert len(db.query('SELECT * FROM public."EventNotificationOutbox" WHERE type LIKE %s', ('event.submission%',))) == 2


@pytest.mark.parametrize("installation", ["clean", "upgrade-with-existing-data"])
def test_attendee_migration_preserves_existing_rows_and_prior_notification_types(
    migration_database, installation
):
    """Normal: install the full schema cleanly or add only the attendee migration after seeded older ones.
    In upgrade-with-existing-data, every existing table and prior Event type has data;
    expect all rows unchanged. Both cases require the empty RLS-enabled Registration
    outbox, revoked API-role grants, acceptance of new types and rejection of unknowns.
    These unmodified migrations run in owned PostgreSQL with synthetic roles, not
    hosted Supabase role parity.
    """
    paths = sorted(MIGRATIONS.glob("*.sql"))
    pending = [
        p for p in paths if p.name == "20261028000300_attendee_notifications.sql"
    ]
    assert len(pending) == 1
    # The fixture explicitly creates synthetic SQL roles; this is not hosted-permission parity.
    with migration_database(bootstrap=True) as db:
        if installation == "clean":
            db.apply(paths)
        else:
            db.apply([p for p in paths if p not in pending])
            seed_existing_data(db)
            db.query(
                'INSERT INTO public."EquipmentNotificationOutbox"(source_id,type,source,envelope) VALUES (%s,%s,%s,%s)',
                [
                    str(uuid4()),
                    "equipment.request-submission",
                    Json({"synthetic": True}),
                    Json({"frozen": True}),
                ],
            )
            # Save a row for each prior allowlisted type, including types added by stacked dependencies.
            expression = db.query(
                "SELECT pg_get_expr(conbin,conrelid) FROM pg_constraint WHERE conrelid='public.\"EventNotificationOutbox\"'::regclass AND conname='EventNotificationOutbox_type_check'"
            )[0][0]
            prior_types = set(re.findall(r"'([^']+)'::", expression))
            assert "event.rejection" in prior_types and "event.cancelled" in prior_types
            for kind in prior_types:
                db.query(
                    'INSERT INTO public."EventNotificationOutbox"(type,source) VALUES (%s,%s)',
                    [kind, Json({"synthetic": kind})],
                )
            before = db.snapshot()
            assert before and all(before.values()), (
                "Seed every existing table before upgrade"
            )
            db.apply(pending)
            after = db.snapshot()
            assert {table: after[table] for table in before} == before
        assert db.query(
            'SELECT count(*) FROM public."RegistrationNotificationOutbox"'
        ) == [(0,)]
        assert db.query(
            "SELECT relrowsecurity FROM pg_class WHERE oid='public.\"RegistrationNotificationOutbox\"'::regclass"
        ) == [(True,)]
        for role in ("anon", "authenticated", "service_role"):
            assert db.query(
                "SELECT has_table_privilege(%s, 'public.\"RegistrationNotificationOutbox\"', 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')",
                [role],
            ) == [(False,)]
        for kind in (
            "attendee.cancelled-fanout",
            "attendee.updated-fanout",
            "attendee.event-cancelled",
            "attendee.event-updated",
        ):
            db.query(
                'INSERT INTO public."EventNotificationOutbox"(type,source) VALUES (%s,%s)',
                [kind, Json({"synthetic": True})],
            )
        with pytest.raises(psycopg2.errors.CheckViolation):
            db.query(
                'INSERT INTO public."EventNotificationOutbox"(type,source) VALUES (%s,%s)',
                ["unknown-type", Json({})],
            )
