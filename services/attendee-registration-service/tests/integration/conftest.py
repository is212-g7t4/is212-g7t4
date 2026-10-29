"""Attendee Registration Service integration fixtures."""

import pytest

from app import create_app
from tests.integration.factories import ATTENDEE_ID
from tests.unit.factories import signed_in


@pytest.fixture
def client():
    return signed_in(create_app({"TESTING": True}).test_client(), ATTENDEE_ID, "Attendee")
