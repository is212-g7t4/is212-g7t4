from unittest.mock import MagicMock

import pytest

from tests.unit.factories import TEST_SIGNING_KEY, signed_in

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


@pytest.fixture(autouse=True)
def trusted_test_signing_key(monkeypatch):
    """Verify tokens against the test key instead of fetching Supabase's JWKS (SCRUM-8)."""
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.test")
    monkeypatch.setattr("app.auth.signing_key", lambda token: TEST_SIGNING_KEY.public_key())
