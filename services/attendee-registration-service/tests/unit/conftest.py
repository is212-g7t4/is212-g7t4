import pytest

from app import create_app
from tests.unit.factories import signed_in


@pytest.fixture
def client():
    """A signed-in client for the real Attendee Registration app; tests double its downstream calls."""
    return signed_in(create_app({"TESTING": True, "FRONTEND_ORIGIN": "http://localhost:5174"}).test_client(), role="Attendee")
