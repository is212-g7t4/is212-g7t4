"""Safety Check Service integration fixtures.

A composite: no database. The real Flask app and the real httpx calls in app/clients.py
run; every downstream atomic is stubbed at the HTTP layer with respx (guide §1.2, §7).
"""

import pytest
import respx

from app import create_app


@pytest.fixture
def client():
    return create_app().test_client()


@pytest.fixture
def stubs():
    # Unmatched requests fail, and every stub registered must actually be hit.
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as router:
        yield router
