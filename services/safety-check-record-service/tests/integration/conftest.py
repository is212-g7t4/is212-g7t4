"""Fixtures for Safety Check Record Service's integration tier: the real app against a throwaway Postgres.

See docs/testing/integration-testing.md. One postgres:17.6 container per session, loaded
with the full migration chain unmodified; every test starts from empty tables. Patterns
copied from services/venue-service/tests/integration/conftest.py (guide §12.4).
"""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier
from urllib.parse import urlparse

# Ryuk intermittently fails at startup on Docker Desktop (guide §4). The `with` block
# below stops the container. Read at import, so it must be set first.
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
        with closing(psycopg2.connect(url)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                # Supabase predefines these; later migrations grant/revoke on them.
                cursor.execute("CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN; "
                               "CREATE ROLE service_role NOLOGIN BYPASSRLS;")
                for migration in sorted(MIGRATIONS.glob("*.sql")):
                    cursor.execute(migration.read_text(encoding="utf-8"))
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
def app(database_url, monkeypatch):
    assert_local(database_url)
    # Both channels, in case a code path reads os.environ rather than app.config (§4).
    monkeypatch.setenv("DATABASE_URL", database_url)
    return create_app({"TESTING": True, "DATABASE_URL": database_url})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def at_once(app):
    """Send several requests at the same moment, each from its own test client and thread.

    Each request runs the real route and opens its own database connection, so the row
    locks and the UNIQUE backstop decide the winner, not the test. A barrier releases
    every thread together; the outcome asserted is the same whichever thread wins, so
    this doesn't depend on timing (guide §8).
    """

    def send(*requests):
        barrier = Barrier(len(requests))

        def run(request):
            method, path, kwargs = request
            test_client = app.test_client()
            barrier.wait(timeout=10)
            return getattr(test_client, method)(path, **kwargs)

        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return list(pool.map(run, requests))

    return send


class Database:
    """Direct reads and writes for the arrange and assert steps; never used by the app."""

    def __init__(self, url):
        self.url = url

    def execute(self, sql, params=()):
        with closing(psycopg2.connect(self.url)) as connection:
            with connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(sql, params)
                return cursor.fetchall() if cursor.description else None

    def round(self, safety_check_id):
        rows = self.execute(
            'SELECT * FROM public."SafetyCheck" WHERE safety_check_id = %s', [safety_check_id]
        )
        return rows[0] if rows else None

    def rounds(self, event_id):
        """Every round for the event, oldest first."""
        return self.execute(
            'SELECT * FROM public."SafetyCheck" WHERE event_id = %s ORDER BY round_number',
            [event_id],
        )

    def round_count(self):
        return self.execute('SELECT count(*) AS n FROM public."SafetyCheck"')[0]["n"]

    def flags(self, safety_check_id):
        return self.execute(
            'SELECT * FROM public."SafetyCheckFlag" WHERE safety_check_id = %s ORDER BY area',
            [safety_check_id],
        )

    def flag_count(self):
        return self.execute('SELECT count(*) AS n FROM public."SafetyCheckFlag"')[0]["n"]

    def now(self):
        return self.execute("SELECT now() AS now")[0]["now"]


@pytest.fixture
def db(database_url):
    assert_local(database_url)
    return Database(database_url)
