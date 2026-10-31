"""
SCRUM-154: Configure Venue Buffer Times

User Story
----------
As a Venue Staff member, I want to configure specific setup and turnaround
times for each venue so that the system accurately reflects the total
operational time required around an event

Acceptance Criteria
-------------------
AC1: The system must allow Venue Staff to input and save a configurable setup
     time and turnaround time (e.g., in minutes) when creating or editing a
     venue profile.
AC2: These buffer durations must be configurable on a per-venue basis, allowing
     different spaces to have unique time requirements.
AC3: The saved setup and turnaround times must be persistently associated with
     the specific venue in the catalogue.

Real
----
- POST /venues and PUT /venues/<id> with setupTimeMinutes and
  turnaroundTimeMinutes: validation (whole minutes, 0 to 2147483647), save and
  read-back per venue, and keeping existing values when an older caller omits
  them run for real.
- Assertions are on the status, errors and the values sent and returned.

Doubled
-------
- psycopg2.connect: Stub / Mock (`setup` fixture) - the cursor returns canned
  Venue rows (or raises OperationalError); executed SQL and parameters are
  inspected.

Not proven
----------
- That bookings use these buffers when checking conflicts (-> venue-
  availability-service unit tests for SCRUM-154).
- That the database CHECK constraint matches these rules (-> database/tests and
  tests/integration/).
"""

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


def test_ac1_ac2_ac3_venues_with_buffer_times_each_return_their_own(setup):
    """
    Summary: Each venue keeps and returns its own setup and turnaround times.
    AC1: The system must allow Venue Staff to input and save a configurable
        setup time and turnaround time (e.g., in minutes) when creating or
        editing a venue profile.
    AC2: These buffer durations must be configurable on a per-venue basis,
        allowing different spaces to have unique time requirements.
    AC3: The saved setup and turnaround times must be persistently associated
        with the specific venue in the catalogue.
    Double: Stub (cursor returns two venues with different buffers)
    """
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
    ids=["negative", "fractional", "boolean", "above_maximum", "huge_number"],
)
def test_ac1_save_venue_with_invalid_buffer_minutes_returns_400_naming_it(field, value, label, setup):
    """
    Summary: Buffer times must be whole, non-negative minutes within range.
    AC1: The system must allow Venue Staff to input and save a configurable
        setup time and turnaround time (e.g., in minutes) when creating or
        editing a venue profile.
    Double: Mock (cursor not executed)
    """
    client, cursor = setup

    response = client.post("/venues", json={**VALID_PAYLOAD, field: value})

    assert response.status_code == 400
    assert any(message.startswith(label) for message in response.json["errors"])
    cursor.execute.assert_not_called()


def test_ac1_save_venue_with_zero_minute_buffers_saves_them(setup):
    """
    Summary: A venue can have no setup or turnaround time.
    AC1: (boundary: buffer = 0 minutes)
    Double: Stub (cursor returns the saved row)
    """
    client, cursor = setup
    cursor.fetchone.side_effect = [None, saved_row(setup_time_minutes=0, turnaround_time_minutes=0)]

    response = client.post(
        "/venues",
        json={**VALID_PAYLOAD, "setupTimeMinutes": 0, "turnaroundTimeMinutes": "0"},
    )

    assert response.status_code == 201
    assert response.json["venue"]["setupTimeMinutes"] == 0
    assert response.json["venue"]["turnaroundTimeMinutes"] == 0


def test_ac3_edit_venue_without_buffer_fields_keeps_saved_buffers(setup):
    """
    Summary: An edit that does not mention buffer times leaves the saved ones in place.
    AC3: The saved setup and turnaround times must be persistently associated
        with the specific venue in the catalogue.
    Double: Stub (cursor returns the venue; update inspected)
    """
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


@pytest.mark.parametrize(
    "minutes, expected_status",
    [
        (2147483647, 201),
        (2147483648, 400),
        ("2147483647", 201),
        ("2147483648", 400),
        ("0000000001", 201),
        ("00000000001", 400),
    ],
    ids=["number_at_max", "number_above_max", "text_at_max", "text_above_max", "text_10_digits", "text_11_digits"],
)
def test_ac1_save_venue_when_buffer_minutes_near_maximum_accepts_up_to_2147483647(setup, minutes, expected_status):
    """
    Summary: Buffer times up to 2147483647 minutes are accepted, sent as a number or as text of at most 10 digits.
    AC1: (boundary: minutes = 2147483647, 2147483648; text of 10 and 11 digits)
    Double: Stub (cursor: no duplicate, then the saved row)
    """
    client, cursor = setup
    cursor.fetchone.side_effect = [None, saved_row()]

    response = client.post("/venues", json={**VALID_PAYLOAD, "setupTimeMinutes": minutes})

    assert response.status_code == expected_status
