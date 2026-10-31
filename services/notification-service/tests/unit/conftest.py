"""Unit-only database safety: every SQL boundary must explicitly supply a double."""
import pytest



@pytest.fixture(autouse=True)
def no_live_database(monkeypatch):
    """Refuse libpq connections unless a test explicitly supplies its cursor double."""
    import psycopg2

    def blocked(*args, **kwargs):
        pytest.fail("Unexpected real PostgreSQL connection in the unit suite")

    monkeypatch.setattr(psycopg2, "connect", blocked)
