"""Attendee Registration Service integration fixtures."""

import pytest

from app import create_app


@pytest.fixture
def client():
    return create_app({"TESTING": True}).test_client()
