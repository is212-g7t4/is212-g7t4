"""
SUPPORTING DESIGN CHECKS: Safety Check Service startup warning

User Story
----------
Supporting/supplementary design checks. No story or acceptance
criterion describes the behaviour these tests check; it is plumbing
that every story of this service relies on.

Real
----
- create_app()'s startup check for INTERNAL_SERVICE_TOKEN runs for real.
- Assertions are on the log records.

Doubled
-------
- Nothing: the environment variable is set or removed with monkeypatch.

Not proven
----------
- That the warning is visible in the deployed container's logs (NOT COVERED
  ANYWHERE).
"""
from app import clients, create_app


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_create_app_without_internal_token_logs_warning(monkeypatch, caplog):
    """
    Summary: Starting without the internal token logs a warning, since Event Service will refuse safety moves.
    Supporting design check: a misconfigured service warns at startup
    Double: None
    """
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", "")

    with caplog.at_level("WARNING"):
        create_app()

    assert "INTERNAL_SERVICE_TOKEN is not set" in caplog.text


def test_create_app_with_internal_token_logs_nothing(monkeypatch, caplog):
    """
    Summary: Starting with the internal token logs no warning.
    Supporting design check: a misconfigured service warns at startup
    Double: None
    """
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", "shared-secret")

    with caplog.at_level("WARNING"):
        create_app()

    assert "INTERNAL_SERVICE_TOKEN is not set" not in caplog.text
