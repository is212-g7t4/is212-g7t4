"""Fixtures for Notification Service's integration tier: the real app against a throwaway Postgres.

See docs/testing/integration-testing.md. One postgres:17.6 container per session, loaded
with the full migration chain unmodified; every test starts from empty tables.
"""
import os
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
os.environ.setdefault('TESTCONTAINERS_RYUK_DISABLED', 'true')
import psycopg2
import pytest
from psycopg2.extras import RealDictCursor
from testcontainers.community.postgres import PostgresContainer
from app import create_app
MIGRATIONS = Path(__file__).resolve().parents[4] / 'database' / 'supabase' / 'migrations'
LOCAL_HOSTS = {'localhost', '127.0.0.1'}
OWNED_URLS = set()

def assert_local(url):
    """Refuse to touch anything but a local container.

    load_dotenv() runs when `app` is imported and can put the live Supabase URL in the
    environment; a TRUNCATE ... CASCADE there would wipe the team's data.
    """
    host = urlparse(url).hostname
    assert host in LOCAL_HOSTS, f'Integration tests only run against a local database, not {host!r}.'

@pytest.fixture(scope="session")
def database_url():
    import hashlib
    import json
    import subprocess
    name = 'scrum45-notification-integration' + "-" + uuid4().hex
    volumes = []
    try:
        with PostgresContainer("postgres:17.6", driver=None, name=name,
                               labels={"connectsphere.test": 'scrum45-notification-integration'}) as postgres:
            url = postgres.get_connection_url()
            assert_local(url)
            inspected = subprocess.run(["docker", "inspect", "--format", "{{json .Mounts}}", name],
                                       capture_output=True, text=True, timeout=30)
            assert inspected.returncode == 0, inspected.stderr
            volumes = [mount["Name"] for mount in json.loads(inspected.stdout) if mount["Type"] == "volume"]
            print("RESOURCE " + name, flush=True)
            OWNED_URLS.add(url)
            try:
                with closing(psycopg2.connect(url)) as connection:
                    connection.autocommit = True
                    with connection.cursor() as cursor:
                        for migration in sorted(MIGRATIONS.glob("*.sql")):
                            payload = migration.read_bytes()
                            digest = hashlib.sha256(payload).hexdigest()
                            cursor.execute(payload.decode("utf-8"))
                            assert hashlib.sha256(migration.read_bytes()).hexdigest() == digest
                            print(f"APPLY {migration.name} sha256={digest}", flush=True)
                yield url
            finally:
                OWNED_URLS.remove(url)
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
    if request.module.__name__.endswith('test_infra_migrations'):
        yield
        return
    database_url = request.getfixturevalue('database_url')
    yield
    assert_local(database_url)
    assert database_url in OWNED_URLS, "Cleanup requires this session fixture's exact database URL"
    with closing(psycopg2.connect(database_url)) as connection:
        with connection, connection.cursor() as cursor:
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            tables = ', '.join((f'public."{name}"' for name, in cursor.fetchall()))
            cursor.execute(f'TRUNCATE {tables} RESTART IDENTITY CASCADE')

@pytest.fixture
def client(database_url, monkeypatch):
    assert_local(database_url)
    assert database_url in OWNED_URLS
    monkeypatch.setenv('DATABASE_URL', database_url)
    monkeypatch.setenv('NOTIFICATION_DEV_MODE', 'true')
    app = create_app()
    app.config['TESTING'] = True
    return app.test_client()

class Database:
    """Direct reads and writes for the arrange and assert steps; never used by the app."""

    def __init__(self, url):
        self.url = url

    def execute(self, sql, params=()):
        with closing(psycopg2.connect(self.url)) as connection:
            with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(sql, params)
                return cursor.fetchall() if cursor.description else None

@pytest.fixture
def db(database_url):
    assert_local(database_url)
    assert database_url in OWNED_URLS
    return Database(database_url)
