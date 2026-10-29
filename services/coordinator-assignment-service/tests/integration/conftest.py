"""Coordinator Assignment Service integration fixtures.

This composite owns no database. The real Flask application and httpx client
run while respx controls the downstream User and Event Service boundaries.
"""

import pytest

from app import create_app
from tests.integration.factories import LEAD_ID
from tests.unit.factories import signed_in


@pytest.fixture
def client():
    return signed_in(create_app().test_client(), LEAD_ID, "Event Coordinator Lead")
