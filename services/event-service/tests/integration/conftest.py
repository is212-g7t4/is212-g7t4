"""Fixtures for Event Service's integration tier: the real app against a throwaway Postgres.

See docs/testing/integration-testing.md. One postgres:17.6 container per session, loaded
with the full migration chain unmodified; every test starts from empty tables.
"""

import os
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

# Ryuk, testcontainers' reaper container, intermittently fails at startup with "Port mapping
# ... port 8080 is not available" (seen in about a third of back-to-back runs on Docker
# Desktop). The `with` block below already stops the container; without Ryuk only a hard
# kill of pytest can leave it running. Read at import, so it must be set first.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

import psycopg2  # noqa: E402
import pytest  # noqa: E402
from psycopg2.extras import RealDictCursor  # noqa: E402
from testcontainers.community.postgres import PostgresContainer  # noqa: E402

from app import create_app  # noqa: E402
from tests.integration.factories import SAFETY_TOKEN, make_safety_coordinator

TOKEN = SAFETY_TOKEN

MIGRATIONS = Path(__file__).resolve().parents[4] / "database" / "supabase" / "migrations"
LOCAL_HOSTS = {"localhost", "127.0.0.1"}
OWNED_URLS = set()
OWNED_IDENTITIES = {}


def assert_local(url):
    """Refuse to touch anything but a local container.

    load_dotenv() runs when `app` is imported and can put the live Supabase URL in the
    environment; a TRUNCATE ... CASCADE there would wipe the team's data.
    """
    host = urlparse(url).hostname
    assert host in LOCAL_HOSTS, f"Integration tests only run against a local database, not {host!r}."
    assert url in OWNED_IDENTITIES, "This session fixture must own the exact database"
    import docker
    identifier, name, port = OWNED_IDENTITIES[url]
    container = docker.from_env().containers.get(identifier)
    container.reload()
    assert container.id == identifier and container.name == name
    assert container.labels.get("connectsphere.test") == "scrum45-event-integration"
    assert container.attrs["NetworkSettings"]["Ports"]["5432/tcp"] == [{"HostIp": "127.0.0.1", "HostPort": port}]


@pytest.fixture(scope="session")
def database_url():
    import hashlib
    import json
    import subprocess
    name = 'scrum45-event-integration' + "-" + uuid4().hex
    volumes = []
    try:
        postgres = PostgresContainer("postgres:17.6", driver=None, name=name,
                                     labels={"connectsphere.test": "scrum45-event-integration"})
        postgres.ports = {"5432/tcp": ("127.0.0.1", None)}  # type: ignore  # Docker SDK binding; Testcontainers annotates only integer ports.
        with postgres:
            url = postgres.get_connection_url()
            OWNED_IDENTITIES[url] = (postgres.get_wrapped_container().id, name, str(urlparse(url).port))
            assert_local(url)
            inspected = subprocess.run(["docker", "inspect", "--format", "{{json .Mounts}}", name],
                                       capture_output=True, text=True, timeout=30)
            assert inspected.returncode == 0, inspected.stderr
            volumes = [mount["Name"] for mount in json.loads(inspected.stdout) if mount["Type"] == "volume"]
            print("RESOURCE " + name, flush=True)
            OWNED_URLS.add(url)
            try:
                assert_local(url)
                assert url in OWNED_URLS, "Bootstrap requires this session fixture's exact database URL"
                with closing(psycopg2.connect(url)) as connection:
                    connection.autocommit = True
                    with connection.cursor() as cursor:
                        # Synthetic Supabase API roles required by the unmodified migrations.
                        cursor.execute("CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN; "
                                       "CREATE ROLE service_role NOLOGIN BYPASSRLS;")
                        for migration in sorted(MIGRATIONS.glob("*.sql")):
                            payload = migration.read_bytes()
                            digest = hashlib.sha256(payload).hexdigest()
                            cursor.execute(payload.decode("utf-8"))
                            assert hashlib.sha256(migration.read_bytes()).hexdigest() == digest
                            print(f"APPLY {migration.name} sha256={digest}", flush=True)
                yield url
            finally:
                assert_local(url)
                OWNED_URLS.remove(url)
                del OWNED_IDENTITIES[url]
    finally:
        # The context removes the container/anonymous volumes; verify only exact owned resources.
        remaining = subprocess.run(["docker", "container", "ls", "-a", "--filter", f"name=^/{name}$",
                                    "--format", "{{.Names}}"], capture_output=True, text=True, timeout=30)
        failures = []
        if remaining.returncode or remaining.stdout.strip():
            failures.append("Owned container absence unverified: " + name)
        for volume in volumes:
            check = subprocess.run(["docker", "volume", "ls", "--filter", "name=" + volume,
                                    "--format", "{{.Name}}"], capture_output=True, text=True, timeout=30)
            if check.returncode or volume in check.stdout.splitlines():
                failures.append("Owned volume absence unverified: " + volume)
        assert not failures, "; ".join(failures)
        print(f"CLEANUP {name}: exact container absent; owned volumes absent={volumes}", flush=True)


@pytest.fixture(autouse=True)
def empty_tables(request):
    # Migration infrastructure deliberately owns independent clean/upgrade databases.
    if request.module.__name__.endswith(("test_infra_migrations", "test_safety_check_notifications")):
        yield
        return
    database_url = request.getfixturevalue("database_url")
    yield
    assert_local(database_url)
    assert database_url in OWNED_URLS, "Cleanup requires this session fixture's exact database URL"
    with closing(psycopg2.connect(database_url)) as connection:
        with connection, connection.cursor() as cursor:
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            tables = ", ".join(f'public."{name}"' for (name,) in cursor.fetchall())
            cursor.execute(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")


@pytest.fixture
def client(database_url, monkeypatch):
    assert_local(database_url)
    assert database_url in OWNED_URLS
    # Both channels, in case a code path reads os.environ rather than app.config (§4).
    monkeypatch.setenv("DATABASE_URL", database_url)
    return create_app({"TESTING": True, "DATABASE_URL": database_url}).test_client()


class Database:
    """Direct reads and writes for the arrange and assert steps; never used by the app."""

    def __init__(self, url):
        self.url = url

    def execute(self, sql, params=()):
        assert_local(self.url)
        assert self.url in OWNED_URLS, "Queries require this session fixture's exact database URL"
        with closing(psycopg2.connect(self.url)) as connection:
            with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(sql, params)
                return cursor.fetchall() if cursor.description else None

    def event(self, event_id):
        rows = self.execute('SELECT * FROM public."Event" WHERE event_id = %s', [event_id])
        return rows[0] if rows else None

    def change_request(self, change_id):
        rows = self.execute(
            'SELECT * FROM public."EventChangeReq" WHERE change_id = %s',
            [change_id],
        )
        return rows[0] if rows else None

    def event_count(self):
        return self.execute('SELECT count(*) AS n FROM public."Event"')[0]["n"]

    def now(self):
        return self.execute("SELECT now() AS now")[0]["now"]


@pytest.fixture
def db(database_url):
    assert_local(database_url)
    assert database_url in OWNED_URLS
    return Database(database_url)


# Infrastructure-only clean/upgrade databases; independent of the story fixture.
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import subprocess
import time
from uuid import uuid4
import psycopg2
from psycopg2 import sql

def migration_command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()

class MigrationDatabase:

    def __init__(self, connection):
        self.connection = connection
        self.connection.autocommit = True
        self.applied = []

    def query(self, statement, params=None):
        with self.connection.cursor() as cursor:
            cursor.execute(statement, params)
            return cursor.fetchall() if cursor.description else []

    def apply(self, paths):
        for path in paths:
            payload = path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            print(f'APPLY {path.name} sha256={digest}', flush=True)
            self.query(payload.decode('utf-8'))
            assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
            self.applied.append(path.name)

    def snapshot(self):
        tables = self.query("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        return {table: self.query(sql.SQL('SELECT to_jsonb(t) FROM public.{} t ORDER BY to_jsonb(t)::text').format(sql.Identifier(table))) for table, in tables}

@contextmanager
def disposable_database(bootstrap=False):
    """postgres:17.6, generated loopback binding, owned anonymous volumes removed.

    Optional bootstrap models only Supabase's documented default table grants
    and API roles/BYPASSRLS. It is NOT the complete hosted Supabase platform.
    No bootstrap is necessary to execute this repository's migration chain.
    """
    name = 'scrum45-migrations-' + uuid4().hex[:16]
    connection = None
    created = False
    volumes = []
    try:
        migration_command('docker', 'run', '-d', '--name', name, '--label', 'connectsphere.test=scrum45-migrations', '-p', '127.0.0.1::5432', '-e', 'POSTGRES_USER=isolated', '-e', 'POSTGRES_PASSWORD=synthetic-only', 'postgres:17.6')
        created = True
        mounts = json.loads(migration_command('docker', 'inspect', '--format', '{{json .Mounts}}', name))
        volumes = [mount['Name'] for mount in mounts if mount['Type'] == 'volume']
        binding = migration_command('docker', 'port', name, '5432/tcp')
        host, port = binding.rsplit(':', 1)
        assert host == '127.0.0.1', binding
        print(f'RESOURCE {name} binding={binding}', flush=True)
        deadline = time.monotonic() + 60
        while True:
            try:
                connection = psycopg2.connect(host=host, port=int(port), user='isolated', password='synthetic-only', dbname='isolated', connect_timeout=2)
                break
            except psycopg2.OperationalError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.15)
        db = MigrationDatabase(connection)
        print('SERVER ' + db.query('SELECT version()')[0][0], flush=True)
        if bootstrap:
            print('BOOTSTRAP: disposable Supabase-like roles/default grants ONLY (not hosted-platform parity)', flush=True)
            db.query('CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN;\n                CREATE ROLE service_role NOLOGIN BYPASSRLS;\n                GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;\n                ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role;\n                ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO anon, authenticated, service_role;')
        yield db
    finally:
        if connection is not None:
            connection.close()
        inspected = subprocess.run(['docker', 'container', 'ls', '-a', '--filter', f'name=^/{name}$', '--format', '{{.Names}}'], capture_output=True, text=True, timeout=30)
        assert inspected.returncode == 0, inspected.stderr
        if created or inspected.stdout.strip():
            migration_command('docker', 'rm', '-fv', name)
        remaining = migration_command('docker', 'container', 'ls', '-a', '--filter', f'name=^/{name}$', '--format', '{{.Names}}')
        assert not remaining, f'Owned container still exists: {remaining}'
        existing_volumes = migration_command('docker', 'volume', 'ls', '--format', '{{.Name}}').splitlines()
        assert not set(volumes).intersection(existing_volumes), f'Owned volumes remain: {volumes}'
        print(f'CLEANUP {name}: exact container absent; owned volumes absent={volumes}', flush=True)

@pytest.fixture
def migration_database():
    return disposable_database

@pytest.fixture
def event_change_notification_owner(database_url, monkeypatch):
    """SCRUM-49 uses the session database and the standard per-test truncation."""
    assert_local(database_url)
    assert database_url in OWNED_URLS, "Story setup requires the session fixture's exact URL"
    monkeypatch.setenv("DATABASE_URL", database_url)
    client = create_app({"TESTING": True, "DATABASE_URL": database_url,
                         "INTERNAL_SERVICE_TOKEN": TOKEN}).test_client()
    assert client.application.config["DATABASE_URL"] == os.environ["DATABASE_URL"] == database_url
    with closing(psycopg2.connect(database_url)) as connection:
        db = MigrationDatabase(connection)
        make_safety_coordinator(db)
        yield client, db


# SCRUM-168: explicitly requested fixture; no change to other stories' DB lifecycle.
@pytest.fixture
def safety_notification_owner(migration_database, monkeypatch):
    with migration_database(bootstrap=True) as db:
        # dotenv is disabled by the documented runner before app imports.
        assert os.environ.get('PYTHON_DOTENV_DISABLED') == '1'
        params = db.connection.get_dsn_parameters()
        # Resolve only the existing fixture's uniquely bound, labelled container.
        candidates = json.loads(migration_command('docker', 'inspect', *migration_command(
            'docker', 'ps', '-q', '--filter', 'label=connectsphere.test=scrum45-migrations').splitlines()))
        matches = [item for item in candidates
                   if item['NetworkSettings']['Ports'].get('5432/tcp') ==
                   [{'HostIp': '127.0.0.1', 'HostPort': params['port']}]]
        assert len(matches) == 1
        owned = matches[0]
        assert owned['Name'].startswith('/scrum45-migrations-')
        assert owned['Config']['Labels']['connectsphere.test'] == 'scrum45-migrations'
        identifier = owned['Id']

        def assert_owned():
            current = json.loads(migration_command('docker', 'inspect', identifier))[0]
            assert current['Id'] == identifier and current['Name'] == owned['Name']
            assert current['Config']['Labels'] == owned['Config']['Labels']
            assert current['NetworkSettings']['Ports']['5432/tcp'] == [
                {'HostIp': '127.0.0.1', 'HostPort': params['port']}]
            assert params['host'] == '127.0.0.1'
            assert params['user'] == params['dbname'] == 'isolated'

        assert_owned()
        db.apply(sorted(MIGRATIONS.glob('*.sql')))
        make_safety_coordinator(db)
        # psycopg2's .dsn masks passwords; reconstruct only this fixture's synthetic DSN.
        from psycopg2.extensions import make_dsn
        params = db.connection.get_dsn_parameters()
        dsn = make_dsn(**params, password='synthetic-only')
        monkeypatch.setenv('DATABASE_URL', dsn)
        assert_owned()
        client = create_app({'TESTING': True, 'DATABASE_URL': dsn,
                             'INTERNAL_SERVICE_TOKEN': TOKEN}).test_client()
        assert client.application.config["DATABASE_URL"] == os.environ["DATABASE_URL"] == dsn
        try:
            yield client, db
        finally:
            assert_owned()


@pytest.fixture
def attendee_notification_owner(event_change_notification_owner, database_url):
    """Yield the real Event client and independent SQL helper over the session-owned PostgreSQL.
    Add an exact live container/name/label/binding guard to every HTTP request and SQL
    access, including final teardown. Reuse the existing per-test reset, full migration
    chain and synthetic role bootstrap; never connect to a configured shared database.
    """
    import docker
    client, db = event_change_notification_owner
    port = str(urlparse(database_url).port)
    candidates = docker.from_env().containers.list(filters={"label": "connectsphere.test=scrum45-event-integration"})
    matches = [c for c in candidates if any(b["HostPort"] == port for b in c.attrs["NetworkSettings"]["Ports"]["5432/tcp"])]
    assert len(matches) == 1
    owner = matches[0]
    identifier, name = owner.id, owner.name
    original_query = db.query
    def guard():
        current = docker.from_env().containers.get(identifier)
        current.reload()
        assert current.id == identifier and current.name == name
        assert current.labels.get("connectsphere.test") == "scrum45-event-integration"
        assert any(b["HostPort"] == port for b in current.attrs["NetworkSettings"]["Ports"]["5432/tcp"])
        assert database_url in OWNED_URLS
    def query(*args, **kwargs):
        guard()
        return original_query(*args, **kwargs)
    db.query = query
    client.application.before_request(guard)
    try:
        guard()
        yield client, db
    finally:
        guard()
