"""A missing internal token is called out at startup, since the Lead's edits depend on it."""
import logging

from app import clients, create_app


def test_warns_when_the_internal_token_is_not_set(monkeypatch, caplog):
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", None)
    with caplog.at_level(logging.WARNING):
        create_app()
    assert "INTERNAL_SERVICE_TOKEN is not set" in caplog.text


def test_is_quiet_when_the_internal_token_is_set(monkeypatch, caplog):
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", "secret")
    with caplog.at_level(logging.WARNING):
        create_app()
    assert "INTERNAL_SERVICE_TOKEN" not in caplog.text
