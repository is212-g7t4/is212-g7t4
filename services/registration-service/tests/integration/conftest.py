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

MIGRATIONS = Path(__file__).resolve().parents[4] / "database" / "supabase" / "migrations"
LOCAL_HOSTS = {"localhost", "127.0.0.1"}


def assert_local(url):
    """Refuse to read from or truncate a configured shared database."""
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
    monkeypatch.setenv("DATABASE_URL", database_url)
    return create_app({"TESTING": True, "DATABASE_URL": database_url}).test_client()


class Database:
    def __init__(self, url):
        self.url = url

    def execute(self, sql, params=()):
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
    assert_local(database_url)
    return Database(database_url)
