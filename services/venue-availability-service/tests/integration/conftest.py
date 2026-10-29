"""Venue Availability integration fixtures: Flask against fixture-owned PostgreSQL 17.6.

Full migration chain, unmodified and filename-ordered; clean tables between tests.
Every database access requires the exact registered URL and live container identity,
not merely a loopback hostname. No shared .env or shared database is supported.
"""

import hashlib
import os
import subprocess
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

# The context owns cleanup; disabling Ryuk avoids Docker Desktop reaper startup races.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

import psycopg2  # noqa: E402
import pytest  # noqa: E402
from psycopg2.extras import RealDictCursor  # noqa: E402
from testcontainers.community.postgres import PostgresContainer  # noqa: E402

from app import create_app  # noqa: E402

MIGRATIONS = Path(__file__).resolve().parents[4] / "database" / "supabase" / "migrations"
LOCAL_HOSTS = {"localhost", "127.0.0.1"}
OWNED_DATABASES = {}
LABEL = "scrum47-availability-integration"


def assert_local(url):
    """Require this fixture's exact URL, container ID/name/label and loopback port."""
    parsed = urlparse(url)
    assert parsed.hostname in LOCAL_HOSTS, "Integration database must be loopback-only"
    assert url in OWNED_DATABASES, "Database URL is not owned by this session fixture"
    container, identifier, name = OWNED_DATABASES[url]
    container.reload()
    assert container.id == identifier
    assert container.attrs["Name"] == "/" + name
    assert container.attrs["Config"]["Labels"]["connectsphere.test"] == LABEL
    assert container.attrs["State"]["Running"]
    assert container.attrs["NetworkSettings"]["Ports"]["5432/tcp"] == [
        {"HostIp": "127.0.0.1", "HostPort": str(parsed.port)}
    ]


def assert_resources_absent(name, volumes):
    """Read back only exact owned resources; never remove a name-matched stranger."""
    remaining = subprocess.run(
        ["docker", "container", "ls", "-a", "--filter", f"name=^/{name}$", "--format", "{{.Names}}"],
        capture_output=True, text=True, timeout=30,
    )
    failures = []
    if remaining.returncode or remaining.stdout.strip():
        failures.append("Owned container absence unverified: " + name)
    for volume in volumes:
        check = subprocess.run(
            ["docker", "volume", "ls", "--filter", "name=" + volume, "--format", "{{.Name}}"],
            capture_output=True, text=True, timeout=30,
        )
        if check.returncode or volume in check.stdout.splitlines():
            failures.append("Owned volume absence unverified: " + volume)
    assert not failures, "; ".join(failures)
    print(f"CLEANUP {name}: exact container absent; owned volumes absent={volumes}", flush=True)


@pytest.fixture(scope="session")
def database_url():
    name = LABEL + "-" + uuid4().hex
    volumes = []
    try:
        postgres = PostgresContainer("postgres:17.6", driver=None, name=name,
                                     labels={"connectsphere.test": LABEL})
        # Docker SDK accepts (host IP, ephemeral port); with_bind_ports only accepts integers.
        postgres.ports["5432"] = ("127.0.0.1", None)  # type: ignore[assignment]
        with postgres:
            url = postgres.get_connection_url()
            container = postgres.get_wrapped_container()
            container.reload()
            volumes = [mount["Name"] for mount in container.attrs["Mounts"]
                       if mount["Type"] == "volume"]
            OWNED_DATABASES[url] = (container, container.id, name)
            try:
                assert_local(url)
                print(f"RESOURCE {name} id={container.id}", flush=True)
                with closing(psycopg2.connect(url, connect_timeout=10)) as connection:
                    # Migrations carrying BEGIN/COMMIT run exactly as written.
                    connection.autocommit = True
                    with connection.cursor() as cursor:
                        # Supabase predefines these; later migrations grant/revoke on them.
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
                # Check ownership before the context performs destructive container cleanup.
                try:
                    assert_local(url)
                finally:
                    del OWNED_DATABASES[url]
    finally:
        assert_resources_absent(name, volumes)


@pytest.fixture(autouse=True)
def empty_tables(database_url):
    yield
    assert_local(database_url)
    with closing(psycopg2.connect(database_url, connect_timeout=10)) as connection:
        with connection, connection.cursor() as cursor:
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            tables = ", ".join(f'public."{name}"' for (name,) in cursor.fetchall())
            cursor.execute(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")


@pytest.fixture
def client(database_url, monkeypatch):
    assert_local(database_url)
    monkeypatch.setenv("DATABASE_URL", database_url)
    return create_app({"TESTING": True, "DATABASE_URL": database_url}).test_client()


class Database:
    """Independent connections for arrange/assert; never used by the app."""

    def __init__(self, url):
        self.url = url

    def execute(self, sql, params=()):
        assert_local(self.url)
        with closing(psycopg2.connect(self.url, connect_timeout=10)) as connection:
            with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(sql, params)
                return cursor.fetchall() if cursor.description else None

    def bookings(self, venue_id=None):
        if venue_id is None:
            return self.execute('SELECT * FROM public."VenueBooking" ORDER BY requested_start_time')
        return self.execute(
            'SELECT * FROM public."VenueBooking" WHERE venue_id = %s ORDER BY requested_start_time',
            [venue_id],
        )

    def booking(self, booking_id):
        rows = self.execute('SELECT * FROM public."VenueBooking" WHERE booking_id = %s', [booking_id])
        return rows[0] if rows else None

    def now(self):
        return self.execute("SELECT now() AS now")[0]["now"]


@pytest.fixture
def db(database_url):
    assert_local(database_url)
    return Database(database_url)
