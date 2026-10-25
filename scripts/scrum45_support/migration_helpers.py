"""Database adapter for scripts/scrum45_manual_sandbox.py.

Clean/upgrade migration fixtures, legacy seeding and assertions now live in
Event Service's integration tier. Database/MIGRATIONS support the optional
manual launcher; this module provisions nothing itself.
"""
import hashlib
from pathlib import Path
from psycopg2 import sql

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "database/supabase/migrations"

class Database:

    def __init__(self, connection):
        self.connection = connection
        self.connection.autocommit = True
        self.applied = []

    def query(self, statement, params=None):
        """Execute SQL with optional parameters and return fetched rows, or an empty list for
        statements without results.
        """
        with self.connection.cursor() as cursor:
            cursor.execute(statement, params)
            return cursor.fetchall() if cursor.description else []

    def apply(self, paths):
        """Apply supplied migration paths in caller order, log and verify each file hash, and
        record applied names without rewriting SQL.
        """
        for path in paths:
            payload = path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            print(f'APPLY {path.name} sha256={digest}', flush=True)
            self.query(payload.decode('utf-8'))
            assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
            self.applied.append(path.name)

    def snapshot(self):
        """Return every public table's rows as ordered JSON values for before/after migration
        comparisons.
        """
        tables = self.query("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        return {table: self.query(sql.SQL('SELECT to_jsonb(t) FROM public.{} t ORDER BY to_jsonb(t)::text').format(sql.Identifier(table))) for table, in tables}
