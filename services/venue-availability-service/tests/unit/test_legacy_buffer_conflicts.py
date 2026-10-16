"""# Test scope and acceptance mapping — SCRUM-171 integration

- **SCRUM-155 regression; no direct SCRUM-171 AC:** buffer-only conflict detection, half-open effective windows, original booking information, owned-marker cleanup, buffer validation, lookup and route contracts. Existing AC labels below belong to SCRUM-155.
- **SCRUM-171 integration compatibility:** stale-marker cleanup still makes exactly two booking queries, excluding the newly required advisory gate. The marker predicate and venue parameter assertions remain unchanged. This is not AC2 closure-time preservation.

## Existing test contract

SCRUM-155: identify legacy conflicts without altering bookings."""

from datetime import datetime
from unittest.mock import MagicMock

import app as app_module
from app import _parse_buffer_minutes, create_app
from app.models import (
    BookingNotFoundError,
    _conflict_types,
    _legacy_conflict_pairs,
    _shift,
    get_booking,
    list_bookings,
    reconcile_legacy_conflicts,
)
from tests.unit.factories import EVENT_ID, USER_ID, VENUE_ID, booking_row


SECOND_BOOKING_ID = "00000000-0000-0000-0000-00000000000c"
SECOND_EVENT_ID = "00000000-0000-0000-0000-0000000000e2"


def approved(**overrides):
    return booking_row(status="Approved", conflict_reason=None, **overrides)


def test_padding_identifies_non_overlapping_existing_bookings():
    """AC1-2: raw windows are safe, but effective occupancy overlaps."""
    first = approved(
        requested_start_time=datetime(2026, 10, 1, 10),
        requested_end_time=datetime(2026, 10, 1, 12),
    )
    second = approved(
        booking_id=SECOND_BOOKING_ID,
        event_id=SECOND_EVENT_ID,
        requested_start_time=datetime(2026, 10, 1, 12, 30),
        requested_end_time=datetime(2026, 10, 1, 14),
    )

    pairs = _legacy_conflict_pairs([first, second], 30, 45)

    assert len(pairs) == 1
    assert pairs[0][1] == (datetime(2026, 10, 1, 9, 30), datetime(2026, 10, 1, 12, 45))
    assert pairs[0][3] == (datetime(2026, 10, 1, 12), datetime(2026, 10, 1, 14, 45))


def test_half_open_touching_boundaries_are_not_conflicts():
    first = approved(requested_end_time=datetime(2026, 10, 1, 12))
    second = approved(
        booking_id=SECOND_BOOKING_ID,
        event_id=SECOND_EVENT_ID,
        requested_start_time=datetime(2026, 10, 1, 12, 30),
        requested_end_time=datetime(2026, 10, 1, 14),
    )

    assert _legacy_conflict_pairs([first, second], 0, 30) == []


def test_raw_overlap_is_not_mislabelled_as_new_legacy_conflict():
    first = approved(requested_end_time=datetime(2026, 10, 1, 12))
    second = approved(
        booking_id=SECOND_BOOKING_ID,
        event_id=SECOND_EVENT_ID,
        requested_start_time=datetime(2026, 10, 1, 11, 30),
        requested_end_time=datetime(2026, 10, 1, 14),
    )

    assert _legacy_conflict_pairs([first, second], 30, 45) == []


def test_reconciliation_flags_both_and_preserves_original_information(monkeypatch):
    """AC2-3: markers change; event, time, and status fields remain untouched."""
    first = approved(
        requested_start_time=datetime(2026, 10, 1, 10),
        requested_end_time=datetime(2026, 10, 1, 12),
        hold_expires_at=None,
    )
    second = approved(
        booking_id=SECOND_BOOKING_ID,
        event_id=SECOND_EVENT_ID,
        requested_start_time=datetime(2026, 10, 1, 12, 30),
        requested_end_time=datetime(2026, 10, 1, 14),
        hold_expires_at=None,
    )
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [first, second]
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)

    result = reconcile_legacy_conflicts("test", VENUE_ID, 30, 45)

    assert result["conflictCount"] == 1
    members = result["conflicts"][0]
    assert members["firstBooking"]["eventId"] == EVENT_ID
    assert members["firstBooking"]["status"] == "Approved"
    assert members["firstBooking"]["requestedStartTime"] == "2026-10-01T10:00:00"
    assert members["secondBooking"]["eventId"] == SECOND_EVENT_ID
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert any("SET conflict_reason = 'BUFFER_OVERLAP'" in sql for sql in statements)
    assert all("SET status" not in sql and "event_id =" not in sql for sql in statements)


def test_reconciliation_clears_only_its_own_stale_marker(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)

    result = reconcile_legacy_conflicts("test", VENUE_ID, 0, 0)

    assert result["conflicts"] == []
    booking_queries = [call for call in cursor.execute.call_args_list if "pg_advisory_xact_lock" not in call.args[0]]
    clear_sql, clear_params = booking_queries[1].args
    assert "conflict_reason = 'BUFFER_OVERLAP'" in clear_sql
    assert clear_params == [VENUE_ID]
    assert len(booking_queries) == 2


def test_buffer_parser_rejects_every_invalid_shape():
    class BadText:
        def __str__(self):
            raise TypeError

    assert _parse_buffer_minutes(None, 9) == 9
    assert _parse_buffer_minutes(True) is None
    assert _parse_buffer_minutes("1.5") is None
    assert _parse_buffer_minutes("2147483648") is None
    assert _parse_buffer_minutes(BadText()) is None


def test_datetime_shift_clamps_both_python_boundaries():
    assert _shift(datetime.max, 1) == datetime.max
    assert _shift(datetime.min, -1) == datetime.min


def test_buffered_calendar_read_returns_original_and_effective_times(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [approved(hold_expires_at=None)]
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)

    rows = list_bookings(
        "test", VENUE_ID, datetime(2026, 10, 1), datetime(2026, 10, 2), 30, 45
    )

    assert rows[0]["requestedStartTime"].startswith("2026-10-01T09:00")
    assert rows[0]["effectiveStartTime"].startswith("2026-10-01T08:30")
    assert rows[0]["effectiveEndTime"].startswith("2026-10-01T12:45")
    assert len(cursor.execute.call_args.args[1]) == 5


def test_buffered_conflict_query_expands_events_but_not_hold_interval():
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {"conflict_type": "TENTATIVE_HOLD"},
        {"conflict_type": "APPROVED_BOOKING"},
    ]

    result = _conflict_types(
        cursor,
        VENUE_ID,
        datetime(2026, 10, 1, 10),
        datetime(2026, 10, 1, 12),
        exclude_booking_id="booking-1",
        setup_time_minutes=30,
        turnaround_time_minutes=45,
    )

    assert result == ["APPROVED_BOOKING", "TENTATIVE_HOLD"]
    sql, params = cursor.execute.call_args.args
    assert "status IN ('Approved', 'On Hold')" in sql
    assert "booking_id <> %s" in sql
    assert "booking-1" in params

    cursor.reset_mock()
    cursor.fetchall.return_value = []
    assert _conflict_types(
        cursor,
        VENUE_ID,
        datetime(2026, 10, 1, 10),
        datetime(2026, 10, 1, 12),
        setup_time_minutes=30,
        turnaround_time_minutes=45,
    ) == []
    assert "booking_id <> %s" not in cursor.execute.call_args.args[0]


def test_single_booking_lookup_found_and_missing(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    cursor.fetchone.return_value = approved()
    assert get_booking("test", "booking-1")["eventId"] == EVENT_ID
    cursor.fetchone.return_value = None
    try:
        get_booking("test", "missing")
        assert False, "expected BookingNotFoundError"
    except BookingNotFoundError:
        pass


def _booking_payload(**overrides):
    payload = {
        "eventId": EVENT_ID,
        "venueId": VENUE_ID,
        "requestedBy": USER_ID,
        "requestedStartTime": "2026-10-01T10:00",
        "requestedEndTime": "2026-10-01T12:00",
        "requiredCapacity": 20,
        "venueRequirements": "Stage",
        "setupTimeMinutes": 30,
        "turnaroundTimeMinutes": 45,
    }
    payload.update(overrides)
    return payload


def test_buffer_route_validation_and_internal_lookup_contract(monkeypatch):
    client = create_app(
        {"TESTING": True, "DATABASE_URL": "test", "CALENDAR_DEV_MODE": True}
    ).test_client()
    booking_id = "00000000-0000-0000-0000-00000000000b"

    assert client.post("/venue-bookings", json=_booking_payload(setupTimeMinutes=-1)).status_code == 400
    update = _booking_payload(setupTimeMinutes="bad")
    update.pop("requestedBy")
    assert client.patch(f"/venue-bookings/{booking_id}", json=update).status_code == 400
    assert client.patch(
        f"/venue-bookings/{booking_id}/approve",
        json={"reviewedBy": USER_ID, "setupTimeMinutes": True},
    ).status_code == 400

    monkeypatch.setattr(app_module, "get_booking", lambda *args: {"id": booking_id})
    assert client.get(f"/venue-bookings/{booking_id}").json == {"id": booking_id}
    monkeypatch.setattr(
        app_module,
        "get_booking",
        lambda *args: (_ for _ in ()).throw(BookingNotFoundError()),
    )
    assert client.get(f"/venue-bookings/{booking_id}").status_code == 404

    no_database = create_app({"TESTING": True, "DATABASE_URL": None}).test_client()
    assert no_database.get(f"/venue-bookings/{booking_id}").status_code == 503


def test_reconcile_route_validates_configuration_and_returns_result(monkeypatch):
    path = f"/venues/{VENUE_ID}/legacy-conflicts/reconcile"
    client = create_app({"TESTING": True, "DATABASE_URL": "test"}).test_client()
    assert client.post(path, json=[]).status_code == 400
    assert client.post(path, json={"setupTimeMinutes": -1}).status_code == 400

    expected = {"venueId": VENUE_ID, "conflictCount": 0, "conflicts": []}
    monkeypatch.setattr(app_module, "reconcile_legacy_conflicts", lambda *args: expected)
    assert client.post(
        path, json={"setupTimeMinutes": 30, "turnaroundTimeMinutes": 45}
    ).json == expected

    no_database = create_app({"TESTING": True, "DATABASE_URL": None}).test_client()
    assert no_database.post(
        path, json={"setupTimeMinutes": 30, "turnaroundTimeMinutes": 45}
    ).status_code == 503


def test_empty_frontend_origin_skips_cors_alias_expansion():
    response = create_app({"TESTING": True, "FRONTEND_ORIGIN": ""}).test_client().get(
        "/health", headers={"Origin": "http://localhost:5174"}
    )
    assert "Access-Control-Allow-Origin" not in response.headers
