import pytest

from tests.unit.factories import TEST_SIGNING_KEY


@pytest.fixture(autouse=True)
def trusted_test_signing_key(monkeypatch):
    """Verify tokens against the test key instead of fetching Supabase's JWKS (SCRUM-8)."""
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.test")
    monkeypatch.setattr("app.auth.signing_key", lambda token: TEST_SIGNING_KEY.public_key())
