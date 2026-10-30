from types import SimpleNamespace

import pytest

from tests.unit.factories import TEST_SIGNING_KEY


@pytest.fixture(autouse=True)
def trusted_test_signing_key(monkeypatch):
    """Verify tokens against the test key instead of fetching Supabase's JWKS (SCRUM-8)."""
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.test")
    monkeypatch.setattr("app.auth.signing_key", lambda token: TEST_SIGNING_KEY.public_key())


@pytest.fixture
def downstream(mocker):
    """Every downstream call app.routes makes, replaced so no request leaves the process.

    Each attribute is a MagicMock: a test sets return_value / side_effect to use it
    as a stub, or asserts on its calls when the interaction is the requirement.
    """
    return SimpleNamespace(
        get_user=mocker.patch("app.routes.get_user"),
        coordinators=mocker.patch("app.routes.get_available_coordinators", return_value=[]),
        assign=mocker.patch("app.routes.assign_event_coordinator"),
        queue=mocker.patch("app.routes.get_assignment_events", return_value=[]),
        active=mocker.patch("app.routes.get_active_events", return_value=[]),
    )
