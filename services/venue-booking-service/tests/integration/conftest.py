"""Venue Booking Service integration fixtures.

A composite has no database (docs/testing/integration-testing.md §1.2): the real app and
its real httpx client code run, and every downstream service is stubbed with respx.
"""

import pytest

from app import create_app


@pytest.fixture
def client():
    return create_app().test_client()
