"""Fixtures for Event Service's integration tier: the real app against a throwaway Postgres.

See docs/testing/integration-testing.md. One postgres:17.6 container per session, loaded
with the full migration chain unmodified; every test starts from empty tables.
"""

import os
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse

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

MIGRATIONS = Path(__file__).resolve().parents[4] / "database" / "supabase" / "migrations"
LOCAL_HOSTS = {"localhost", "127.0.0.1"}


def assert_local(url):
    """Refuse to touch anything but a local container.

    load_dotenv() runs when `app` is imported and can put the live Supabase URL in the
    environment; a TRUNCATE ... CASCADE there would wipe the team's data.
    """
    host = urlparse(url).hostname
    assert host in LOCAL_HOSTS, f"Integration tests only run against a local database, not {host!r}."


@pytest.fixture(scope="session")
def database_url():
    with PostgresContainer("postgres:17.6", driver=None) as postgres:
        url = postgres.get_connection_url()
        assert_local(url)
        # Autocommit so migrations with their own BEGIN/COMMIT run exactly as written.
        with closing(psycopg2.connect(url)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                for migration in sorted(MIGRATIONS.glob("*.sql")):
                    cursor.execute(migration.read_text())
        yield url


@pytest.fixture(autouse=True)
def empty_tables(database_url):
    yield
    assert_local(database_url)
    with closing(psycopg2.connect(database_url)) as connection:
        with connection, connection.cursor() as cursor:
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            tables = ", ".join(f'public."{name}"' for (name,) in cursor.fetchall())
            cursor.execute(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")


@pytest.fixture
def client(database_url, monkeypatch):
    # Both channels, in case a code path reads os.environ rather than app.config (§4).
    monkeypatch.setenv("DATABASE_URL", database_url)
    return create_app({"TESTING": True, "DATABASE_URL": database_url}).test_client()


class Database:
    """Direct reads and writes for the arrange and assert steps; never used by the app."""

    def __init__(self, url):
        self.url = url

    def execute(self, sql, params=()):
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
    return Database(database_url)
