"""Default unit isolation: never load dotenv or use real network/native DB I/O."""
import os
import socket

os.environ["PYTHON_DOTENV_DISABLED"] = "1"

import pytest

from tests.unit.factories import AUTH_NOW, TEST_SIGNING_KEY


@pytest.fixture(autouse=True)
def no_live_io(monkeypatch, request):
    """Unit adapters are doubles; opt-in integration installs its own strict guard."""
    if request.node.get_closest_marker("integration"):
        return
    def blocked(*args, **kwargs):
        pytest.fail("Unexpected live network/database call in isolated unit suite")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    import psycopg2
    monkeypatch.setattr(psycopg2, "connect", blocked)


@pytest.fixture(autouse=True)
def trusted_test_signing_key(monkeypatch):
    """Verify tokens against the test key instead of fetching Supabase's JWKS (SCRUM-8)."""
    from datetime import datetime

    class TokenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return AUTH_NOW.astimezone(tz) if tz else AUTH_NOW.replace(tzinfo=None)

    monkeypatch.setattr("jwt.api_jwt.datetime", TokenClock)
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.test")
    monkeypatch.setattr("app.auth.signing_key", lambda token: TEST_SIGNING_KEY.public_key())
