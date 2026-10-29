"""Venue Booking Service integration fixtures.

A composite has no database (docs/testing/integration-testing.md §1.2): the real app and
its real httpx client code run, and every downstream service is stubbed with respx.
"""

import pytest

from app import create_app
from tests.integration.factories import COORDINATOR_ID
from tests.unit.factories import bearer


@pytest.fixture
def client():
    # SCRUM-8: requests come from the signed-in coordinator unless a test sends another token.
    client = create_app().test_client()
    client.environ_base["HTTP_AUTHORIZATION"] = bearer(COORDINATOR_ID, "Event Coordinator")["Authorization"]
    return client
