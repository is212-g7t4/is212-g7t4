from unittest.mock import MagicMock

import pytest

from tests.unit.factories import signed_in

from app import create_app


@pytest.fixture
def setup(monkeypatch):
    # Legacy booking tests isolate the new, independently tested closure read.
    monkeypatch.setattr("app.list_window_closures", lambda *args: [])
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.connection = connection  # Match psycopg2's cursor-to-transaction relationship.
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client()), cursor
