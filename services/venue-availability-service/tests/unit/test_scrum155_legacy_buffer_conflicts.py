"""
SCRUM-155: Identify Legacy Scheduling Conflicts

User Story
----------
As a Venue Staff member, I want the system to identify existing venue bookings
that now have scheduling conflicts due to the new setup and turnaround rules so
that I can resolve them manually without losing the original bookings.

Acceptance Criteria
-------------------
AC1: The system must evaluate existing bookings against the newly applied setup
     and turnaround time rules to identify any overlapping schedules.
AC2: Existing bookings that become problematic under the new time padding rules
     must be explicitly flagged or identified by the system.
AC3: The system must preserve the original event information and must not
     silently remove or automatically cancel these conflicting existing
     bookings.
AC4: If the calculated total occupied time overlaps with any existing booking's
     total occupied time, the system must detect the conflict and flag the
     venue as unavailable

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
- app.buffers and the reconcile route: setup/turnaround padding of existing
  bookings, half-open comparison, flagging both sides of a new conflict while
  keeping their original data, clearing only its own stale markers, the buffer
  parser, and the buffered calendar and conflict reads.
- Assertions are on the conflicts found, markers written and SQL sent.

Doubled
-------
- psycopg2.connect: Stub (`setup`/`client` fixtures) - fresh MagicMock
  connection; the cursor returns canned VenueBooking / VenueClosure rows (or
  raises); executed SQL, parameters and locks are inspected.

Not proven
----------
- That the SQL, locks and constraints behave the same on real PostgreSQL (->
  tests/integration/, throwaway postgres:17.6).
"""

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
from tests.unit.factories import bearer, EVENT_ID, USER_ID, VENUE_ID, booking_row, signed_in


SECOND_BOOKING_ID = "00000000-0000-0000-0000-00000000000c"
SECOND_EVENT_ID = "00000000-0000-0000-0000-0000000000e2"


def approved(**overrides):
    return booking_row(status="Approved", conflict_reason=None, **overrides)


def test_ac1_ac2_padding_flags_bookings_that_overlap_only_with_buffers():
    """
    Summary: Bookings that do not overlap on their own but do once buffers are added are found.
    AC1: The system must evaluate existing bookings against the newly applied
        setup and turnaround time rules to identify any overlapping schedules.
    AC2: Existing bookings that become problematic under the new time padding
        rules must be explicitly flagged or identified by the system.
    Double: None
    """
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


def test_ac4_padding_with_touching_buffered_windows_is_not_conflict():
    """
    Summary: Buffered windows that only touch are not a conflict.
    AC4: (boundary: touching windows)
    Double: None
    """
    first = approved(requested_end_time=datetime(2026, 10, 1, 12))
    second = approved(
        booking_id=SECOND_BOOKING_ID,
        event_id=SECOND_EVENT_ID,
        requested_start_time=datetime(2026, 10, 1, 12, 30),
        requested_end_time=datetime(2026, 10, 1, 14),
    )

    assert _legacy_conflict_pairs([first, second], 0, 30) == []


def test_ac2_padding_does_not_label_real_overlap_as_new_conflict():
    """
    Summary: A real overlap is not mislabelled as one caused by the new buffers.
    AC2: Existing bookings that become problematic under the new time padding
        rules must be explicitly flagged or identified by the system.
    Double: None
    """
    first = approved(requested_end_time=datetime(2026, 10, 1, 12))
    second = approved(
        booking_id=SECOND_BOOKING_ID,
        event_id=SECOND_EVENT_ID,
        requested_start_time=datetime(2026, 10, 1, 11, 30),
        requested_end_time=datetime(2026, 10, 1, 14),
    )

    assert _legacy_conflict_pairs([first, second], 30, 45) == []


def test_ac2_ac3_reconcile_flags_both_bookings_and_keeps_their_details(monkeypatch):
    """
    Summary: Both bookings in a new conflict are flagged and their details left untouched.
    AC2: Existing bookings that become problematic under the new time padding
        rules must be explicitly flagged or identified by the system.
    AC3: The system must preserve the original event information and must not
        silently remove or automatically cancel these conflicting existing
        bookings.
    Double: Stub (cursor; updates inspected)
    """
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


def test_ac3_reconcile_clears_only_its_own_stale_markers(monkeypatch):
    """
    Summary: Reconciliation clears only the conflict markers it set before.
    AC3: The system must preserve the original event information and must not
        silently remove or automatically cancel these conflicting existing
        bookings.
    Double: Stub (cursor; SQL inspected)
    """
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


def test_scrum154_ac1_buffer_parser_rejects_invalid_values():
    """
    Summary: Invalid buffer values are refused.
    SCRUM-154 AC1: The system must allow Venue Staff to input and save a
        configurable setup time and turnaround time (e.g., in minutes) when
        creating or editing a venue profile.
    Double: None
    """
    class BadText:
        def __str__(self):
            raise TypeError

    assert _parse_buffer_minutes(None, 9) == 9
    assert _parse_buffer_minutes(True) is None
    assert _parse_buffer_minutes("1.5") is None
    assert _parse_buffer_minutes("2147483648") is None
    assert _parse_buffer_minutes(BadText()) is None


def test_ac1_buffer_shift_clamps_at_earliest_and_latest_datetime():
    """
    Summary: Padding near the earliest or latest possible time is clamped, not crashed.
    AC1: The system must evaluate existing bookings against the newly applied
        setup and turnaround time rules to identify any overlapping schedules.
    Double: None
    """
    assert _shift(datetime.max, 1) == datetime.max
    assert _shift(datetime.min, -1) == datetime.min


def test_ac4_buffered_calendar_returns_original_and_padded_times(monkeypatch):
    """
    Summary: The calendar shows both a booking's own time and its padded occupied time.
    AC4: If the calculated total occupied time overlaps with any existing
        booking's total occupied time, the system must detect the conflict and
        flag the venue as unavailable
    Double: Stub (cursor returns bookings with buffers)
    """
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


def test_ac4_buffered_conflict_query_pads_bookings_but_not_holds():
    """
    Summary: Conflict checks pad bookings by their venue's buffers but not holds.
    AC4: If the calculated total occupied time overlaps with any existing
        booking's total occupied time, the system must detect the conflict and
        flag the venue as unavailable
    Double: Stub (cursor; SQL inspected)
    """
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


def test_ac1_single_booking_lookup_returns_row_or_none(monkeypatch):
    """
    Summary: A single booking lookup returns the booking, or none.
    AC1: The system must evaluate existing bookings against the newly applied
        setup and turnaround time rules to identify any overlapping schedules.
    Double: Stub (cursor returns a row or nothing)
    """
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


def test_scrum154_ac3_buffer_route_validates_input_and_internal_lookup(monkeypatch):
    """
    Summary: The buffer routes validate their input and serve the internal lookup.
    SCRUM-154 AC3: The saved setup and turnaround times must be persistently
        associated with the specific venue in the catalogue.
    Double: Stub (cursor)
    """
    client = signed_in(create_app(
        {"TESTING": True, "DATABASE_URL": "test"}
    ).test_client())
    booking_id = "00000000-0000-0000-0000-00000000000b"

    assert client.post("/venue-bookings", json=_booking_payload(setupTimeMinutes=-1)).status_code == 400
    update = _booking_payload(setupTimeMinutes="bad")
    update.pop("requestedBy")
    assert client.patch(f"/venue-bookings/{booking_id}", json=update).status_code == 400
    assert client.patch(
        f"/venue-bookings/{booking_id}/approve",
        json={"reviewedBy": USER_ID, "setupTimeMinutes": True},
        headers=bearer(USER_ID, "Venue Staff"),
    ).status_code == 400

    monkeypatch.setattr(app_module, "get_booking", lambda *args: {"id": booking_id})
    assert client.get(f"/venue-bookings/{booking_id}").json == {"id": booking_id}
    monkeypatch.setattr(
        app_module,
        "get_booking",
        lambda *args: (_ for _ in ()).throw(BookingNotFoundError()),
    )
    assert client.get(f"/venue-bookings/{booking_id}").status_code == 404

    no_database = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client())
    assert no_database.get(f"/venue-bookings/{booking_id}").status_code == 503


def test_ac2_reconcile_route_validates_configuration_and_returns_result(monkeypatch):
    """
    Summary: The reconcile route checks its configuration and returns what it flagged.
    AC2: Existing bookings that become problematic under the new time padding
        rules must be explicitly flagged or identified by the system.
    Double: Stub (cursor)
    """
    path = f"/venues/{VENUE_ID}/legacy-conflicts/reconcile"
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": "test"}).test_client())
    assert client.post(path, json=[]).status_code == 400
    assert client.post(path, json={"setupTimeMinutes": -1}).status_code == 400

    expected = {"venueId": VENUE_ID, "conflictCount": 0, "conflicts": []}
    monkeypatch.setattr(app_module, "reconcile_legacy_conflicts", lambda *args: expected)
    assert client.post(
        path, json={"setupTimeMinutes": 30, "turnaroundTimeMinutes": 45}
    ).json == expected

    no_database = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client())
    assert no_database.post(
        path, json={"setupTimeMinutes": 30, "turnaroundTimeMinutes": 45}
    ).status_code == 503


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_support_blank_frontend_origin_allows_no_browser_origin():
    """
    Summary: Blanking the frontend origin turns browser access off.
    Supporting design check: CORS for the configured frontend origin
    Double: None
    """
    response = signed_in(create_app({"TESTING": True, "FRONTEND_ORIGIN": ""}).test_client()).get(
        "/health", headers={"Origin": "http://localhost:5174"}
    )
    assert "Access-Control-Allow-Origin" not in response.headers
