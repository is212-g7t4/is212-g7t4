"""SCRUM-152 B2: warn at startup when this service can't prove its identity
to Event Service's /safety-status lock, so an unlocked stack is visible
rather than silently open.
"""
from app import clients, create_app


def test_warns_when_token_is_unconfigured(monkeypatch, caplog):
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", "")

    with caplog.at_level("WARNING"):
        create_app()

    assert "INTERNAL_SERVICE_TOKEN is not set" in caplog.text


def test_does_not_warn_when_token_is_configured(monkeypatch, caplog):
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", "shared-secret")

    with caplog.at_level("WARNING"):
        create_app()

    assert "INTERNAL_SERVICE_TOKEN is not set" not in caplog.text
