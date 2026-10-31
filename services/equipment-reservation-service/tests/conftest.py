"""Reservation unit isolation: dotenv disabled and external sockets blocked."""
import os
import socket

os.environ["PYTHON_DOTENV_DISABLED"] = "1"

import pytest

from tests.unit.factories import TEST_SIGNING_KEY


@pytest.fixture(autouse=True)
def no_live_io(monkeypatch):
    """Tests must explicitly replace every external adapter with a local double."""
    def blocked(*args, **kwargs):
        pytest.fail("Unexpected live network/database call in isolated unit suite")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)


@pytest.fixture(autouse=True)
def trusted_test_signing_key(monkeypatch):
    """Verify tokens against the test key instead of fetching Supabase's JWKS (SCRUM-8)."""
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.test")
    monkeypatch.setattr("app.auth.signing_key", lambda token: TEST_SIGNING_KEY.public_key())


@pytest.fixture(autouse=True)
def fixed_token_verification_clock(monkeypatch):
    """Keep signed fixture tokens and expiry boundaries independent of today's date."""
    from datetime import datetime, timezone
    import jwt.api_jwt

    class FixedJWTDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = cls(2030, 1, 1, tzinfo=timezone.utc)
            return instant if tz is not None else instant.replace(tzinfo=None)

    monkeypatch.setattr(jwt.api_jwt, "datetime", FixedJWTDateTime)
