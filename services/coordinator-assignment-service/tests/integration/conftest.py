"""Coordinator Assignment Service integration fixtures.

This composite owns no database. The real Flask application and httpx client
run while respx controls the downstream User and Event Service boundaries.
"""

import pytest

from app import create_app


@pytest.fixture
def client():
    return create_app().test_client()
