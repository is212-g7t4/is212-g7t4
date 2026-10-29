"""Registration Service integration fixtures backed by throwaway Postgres."""

import os
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse

os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

import psycopg2  # noqa: E402
import pytest  # noqa: E402
from psycopg2.extras import RealDictCursor  # noqa: E402
from testcontainers.community.postgres import PostgresContainer  # noqa: E402

from app import create_app  # noqa: E402
from tests.integration.factories import ATTENDEE_ID  # noqa: E402
from tests.unit.factories import signed_in  # noqa: E402

MIGRATIONS = Path(__file__).resolve().parents[4] / "database" / "supabase" / "migrations"
LOCAL_HOSTS = {"localhost", "127.0.0.1"}
OWNED = {}


def assert_local(url):
    """Refuse to read from or truncate a configured shared database."""
    host = urlparse(url).hostname
    assert host in LOCAL_HOSTS, f"Integration tests only run against a local database, not {host!r}."
    assert url in OWNED, "Only this session fixture's exact database is permitted"
    identifier, name, port = OWNED[url]
    import docker
    container = docker.from_env().containers.get(identifier)
    container.reload()
    assert container.id == identifier and container.name == name
    assert container.labels.get("connectsphere.test") == "scrum46-registration"
    assert container.attrs["NetworkSettings"]["Ports"]["5432/tcp"] == [{"HostIp": "127.0.0.1", "HostPort": port}]


@pytest.fixture(scope="session")
def database_url():
    """Yield one session-owned PostgreSQL 17.6 URL after loading every migration unmodified.
    Create only synthetic API roles, register exact loopback container ownership, and
    verify it before bootstrap/teardown. The container context removes owned resources.
    """
    from uuid import uuid4
    name = "scrum46-registration-" + uuid4().hex
    postgres = PostgresContainer("postgres:17.6", driver=None, name=name,
                                 labels={"connectsphere.test": "scrum46-registration"})
    postgres.ports = {"5432/tcp": ("127.0.0.1", None)}  # type: ignore  # Docker SDK binding; Testcontainers annotates only integer ports.
    with postgres:
        url = postgres.get_connection_url()
        identifier = postgres.get_wrapped_container().id
        OWNED[url] = (identifier, name, str(urlparse(url).port))
        assert_local(url)
        with closing(psycopg2.connect(url)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute("CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN; CREATE ROLE service_role NOLOGIN BYPASSRLS;")
                for migration in sorted(MIGRATIONS.glob("*.sql")):
                    cursor.execute(migration.read_text())
        try:
            yield url
        finally:
            assert_local(url)
            del OWNED[url]


@pytest.fixture(autouse=True)
def empty_tables(database_url):
    """Reset every public table after each case, not just the rows it happened to assert.
    Verify exact live fixture ownership before truncation to prevent shared-data loss.
    """
    yield
    assert_local(database_url)
    with closing(psycopg2.connect(database_url)) as connection:
        with connection, connection.cursor() as cursor:
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            tables = ", ".join(f'public."{name}"' for (name,) in cursor.fetchall())
            cursor.execute(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")


@pytest.fixture
def client(database_url, monkeypatch):
    """Return the real Registration Flask test client pointed only at the owned database.
    Set both app config and the fixture-restored environment for consistent SQL routing.
    """
    assert_local(database_url)
    monkeypatch.setenv("DATABASE_URL", database_url)
    return signed_in(create_app({"TESTING": True, "DATABASE_URL": database_url}).test_client(), ATTENDEE_ID)


class Database:
    """Independent arrange/assert SQL reader for fixture-owned Registration data.
    It does not replace application SQL; each operation opens its own real connection.
    """
    def __init__(self, url):
        self.url = url

    def execute(self, sql, params=()):
        """Execute parameterized arrange/assert SQL after an exact live ownership check.
        Commit successful work and return dictionary rows, or None for statements without rows.
        """
        assert_local(self.url)
        with closing(psycopg2.connect(self.url)) as connection:
            with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(sql, params)
                return cursor.fetchall() if cursor.description else None

    def registration(self, registration_id):
        rows = self.execute(
            'SELECT * FROM public."Registration" WHERE registration_id = %s',
            [registration_id],
        )
        return rows[0] if rows else None

    def counts(self, event_id):
        return self.execute(
            '''SELECT COUNT(*) AS total,
                      COUNT(*) FILTER (WHERE status = 'Confirmed') AS confirmed
               FROM public."Registration" WHERE event_id = %s''',
            [event_id],
        )[0]


@pytest.fixture
def db(database_url):
    """Return an independently connecting SQL helper for the owned PostgreSQL URL.
    Ownership is checked now and again on each use, not inferred from loopback alone.
    """
    assert_local(database_url)
    return Database(database_url)
