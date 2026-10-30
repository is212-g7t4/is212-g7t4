"""Hermetic SCRUM-46 Registration unit storage fixture; normal pytest discovery collects it."""

from unittest.mock import MagicMock
import pytest

from app import create_app
from tests.unit.factories import ATTENDEE_ID, signed_in



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


@pytest.fixture
def setup(monkeypatch):
    """A signed-in attendee's client over a doubled database: returns (client, connection, cursor)."""
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({
        "TESTING": True,
        "DATABASE_URL": "unused-test-url",
        "FRONTEND_ORIGIN": "http://localhost:5174",
    })
    return signed_in(app.test_client(), ATTENDEE_ID), connection, cursor
