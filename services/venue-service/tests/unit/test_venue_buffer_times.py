"""Configure Venue Buffer Times — create/edit persistence and validation."""

from unittest.mock import MagicMock

import pytest

from app import create_app
from tests.unit.factories import VALID_PAYLOAD, VENUE_ID, saved_row, signed_in


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client(), role="Venue Staff"), cursor


def test_each_venue_returns_its_own_saved_buffer_times(setup):
    """AC1-3: buffers are persisted on, and read back from, the venue row."""
    client, cursor = setup
    cursor.fetchone.side_effect = [None, saved_row()]

    response = client.post("/venues", json=VALID_PAYLOAD)

    assert response.status_code == 201
    assert response.json["venue"]["setupTimeMinutes"] == 30
    assert response.json["venue"]["turnaroundTimeMinutes"] == 45
    query, params = cursor.execute.call_args_list[-1].args
    assert "setup_time_minutes, turnaround_time_minutes" in query
    assert params[-2:] == [30, 45]


@pytest.mark.parametrize(
    ("field", "value", "label"),
    [
        ("setupTimeMinutes", "-1", "Setup Time"),
        ("setupTimeMinutes", "1.5", "Setup Time"),
        ("turnaroundTimeMinutes", True, "Turnaround Time"),
        ("turnaroundTimeMinutes", "2147483648", "Turnaround Time"),
        ("turnaroundTimeMinutes", "9" * 5000, "Turnaround Time"),
    ],
)
def test_invalid_buffer_duration_is_rejected(field, value, label, setup):
    client, cursor = setup

    response = client.post("/venues", json={**VALID_PAYLOAD, field: value})

    assert response.status_code == 400
    assert any(message.startswith(label) for message in response.json["errors"])
    cursor.execute.assert_not_called()


def test_zero_minute_buffers_are_valid(setup):
    client, cursor = setup
    cursor.fetchone.side_effect = [None, saved_row(setup_time_minutes=0, turnaround_time_minutes=0)]

    response = client.post(
        "/venues",
        json={**VALID_PAYLOAD, "setupTimeMinutes": 0, "turnaroundTimeMinutes": "0"},
    )

    assert response.status_code == 201
    assert response.json["venue"]["setupTimeMinutes"] == 0
    assert response.json["venue"]["turnaroundTimeMinutes"] == 0


def test_legacy_edit_without_buffers_preserves_existing_values(setup):
    """Compatibility: an older caller cannot silently reset configured buffers."""
    client, cursor = setup
    cursor.fetchone.side_effect = [None, saved_row()]
    legacy_payload = {
        key: value
        for key, value in VALID_PAYLOAD.items()
        if key not in {"setupTimeMinutes", "turnaroundTimeMinutes"}
    }

    response = client.put(f"/venues/{VENUE_ID}", json=legacy_payload)

    assert response.status_code == 200
    query, params = cursor.execute.call_args_list[-1].args
    assert "COALESCE(%s, setup_time_minutes)" in query
    assert params[-3:-1] == [None, None]
