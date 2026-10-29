"""Opt-in fixtures for Event story unit tests; no autouse behavior."""
from unittest.mock import MagicMock
import pytest

from tests.unit.factories import signed_in
from app import create_app
from tests.unit.factories import safety_notification_row

@pytest.fixture
def safety_notification_boundary(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr('app.models.psycopg2.connect', lambda *a, **kw: connection)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://synthetic:synthetic@127.0.0.1:1/unused')
    client = signed_in(create_app({'TESTING': True, 'DATABASE_URL': 'postgresql://synthetic:synthetic@127.0.0.1:1/unused',
                         'INTERNAL_SERVICE_TOKEN': 'synthetic'}).test_client())
    row = safety_notification_row()
    return client, cursor, row
