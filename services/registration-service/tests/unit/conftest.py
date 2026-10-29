"""Hermetic SCRUM-46 Registration unit storage fixture; normal pytest discovery collects it."""

from unittest.mock import MagicMock
import pytest

from tests.unit.factories import TEST_SIGNING_KEY


@pytest.fixture
def storage(monkeypatch):
    """Return a fresh mocked libpq connection and context-managed cursor per test.
    Patch the model lookup used by both mutation and outbox SQL so unit tests cannot
    connect to a database. Callers program returned rows; no persistence is simulated.
    """
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: connection)
    return connection, cursor


@pytest.fixture(autouse=True)
def trusted_test_signing_key(monkeypatch):
    """Verify tokens against the test key instead of fetching Supabase's JWKS (SCRUM-8)."""
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.test")
    monkeypatch.setattr("app.auth.signing_key", lambda token: TEST_SIGNING_KEY.public_key())
