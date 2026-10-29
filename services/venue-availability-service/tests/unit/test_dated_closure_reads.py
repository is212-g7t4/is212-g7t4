"""SCRUM-174 calendar closure projection and conservative reads."""

from datetime import datetime, timezone
from unittest.mock import MagicMock
import pytest
from app import create_app
from tests.unit.factories import bearer, signed_in

VENUE = "00000000-0000-0000-0000-000000000001"
CLOSURE = "00000000-0000-0000-0000-000000000002"
START = datetime(2026, 10, 1)
END = datetime(2026, 10, 2)


def row(**changes):
    value = dict(
        closure_id=CLOSURE,
        venue_id=VENUE,
        start_date_time=datetime(2026, 9, 30, 1, 0, 0, 123456, tzinfo=timezone.utc),
        end_date_time=datetime(2026, 10, 3, 2, tzinfo=timezone.utc),
        reason="Repair roof",
    )
    return value | changes


@pytest.mark.parametrize("path", ["/venue-bookings", "/venue-bookings/window"])
def test_ac1_ac2_distinct_original_closures(path, monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [[], [row()]]
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: connection)
    client = signed_in(create_app(
        {"TESTING": True, "DATABASE_URL": "unused"}
    ).test_client())
    response = client.get(
        path,
        query_string=dict(
            venueId=VENUE, dateFrom=START.isoformat(), dateTo=END.isoformat()
        ),
        headers=bearer(VENUE, "Event Coordinator"),
    )
    assert response.status_code == 200
    assert response.json == {
        "bookings": [],
        "closures": [
            {
                "closureId": CLOSURE,
                "venueId": VENUE,
                "startDateTime": "2026-09-30T09:00:00.123456+08:00",
                "endDateTime": "2026-10-03T10:00:00+08:00",
                "reason": "Repair roof",
            }
        ],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"closure_id": None},
        {"closure_id": "bad"},
        {"venue_id": None},
        {"venue_id": "bad"},
        {"start_date_time": None},
        {"end_date_time": None},
        {"start_date_time": "bad"},
        {"end_date_time": datetime(2020, 1, 1)},
        {"reason": None},
        {"reason": " "},
        {"reason": "bad\x00"},
    ],
)
def test_invalid_closure_fails_closed(change, monkeypatch):
    from app.models import list_window_closures, CalendarDataError

    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value.fetchall.return_value = [
        row(**change)
    ]
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: connection)
    with pytest.raises(CalendarDataError):
        list_window_closures("unused", START, END)


def test_duplicate_closure_ids_fail_closed(monkeypatch):
    from app.models import list_window_closures, CalendarDataError

    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value.fetchall.return_value = [
        row(),
        row(),
    ]
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: connection)
    with pytest.raises(CalendarDataError):
        list_window_closures("unused", START, END)


@pytest.mark.parametrize("calendar", [True, False])
@pytest.mark.parametrize("expiry_delta,count", [(-1, 0), (0, 0), (1, 1)])
def test_expired_hold_does_not_block_reads(monkeypatch, calendar, expiry_delta, count):
    from datetime import timedelta
    from app.models import list_bookings, list_window_bookings
    from tests.unit.availability_db import AvailabilityDB, NOW
    from tests.unit.factories import booking_row, VENUE_ID

    hold = booking_row(
        status="On Hold",
        event_id=None,
        requested_start_time=NOW - timedelta(hours=1),
        requested_end_time=NOW + timedelta(hours=1),
    )
    hold["hold_expires_at"] = NOW + timedelta(microseconds=expiry_delta)
    db = AvailabilityDB(bookings=[hold])
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: db)
    try:
        start, end = (
            NOW.replace(tzinfo=None),
            (NOW + timedelta(hours=1)).replace(tzinfo=None),
        )
        result = (
            list_bookings("unused", VENUE_ID, start, end)
            if calendar
            else list_window_bookings("unused", start, end)
        )
        assert len(result) == count
        assert (
            db.db.execute('SELECT status FROM "VenueBooking"').fetchone()[0]
            == "On Hold"
        )
    finally:
        db.db.close()


@pytest.mark.parametrize("calendar", [True, False])
def test_hold_without_expiry_fails_closed(monkeypatch, calendar):
    from app.models import list_bookings, list_window_bookings, CalendarDataError
    from tests.unit.availability_db import AvailabilityDB
    from tests.unit.factories import booking_row, VENUE_ID

    hold = booking_row(status="On Hold", event_id=None)
    db = AvailabilityDB(bookings=[hold])
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: db)
    try:
        with pytest.raises(CalendarDataError):
            if calendar:
                list_bookings("unused", VENUE_ID, START, END)
            else:
                list_window_bookings("unused", START, END)
    finally:
        db.db.close()


def test_active_calendar_hold_explicitly_blocks_selection():
    from app.models import serialize_calendar
    from tests.unit.factories import booking_row

    assert (
        serialize_calendar(booking_row(status="On Hold", event_id=None))[
            "blocksSelection"
        ]
        is True
    )


@pytest.mark.parametrize("calendar", [True, False])
@pytest.mark.parametrize(
    "start,end,count",
    [
        ("2026-10-01T00:00:00+08:00", "2026-10-02T00:00:00+08:00", 1),
        ("2026-10-01T09:00:00+08:00", "2026-10-01T10:00:00+08:00", 1),
        ("2026-09-30T23:00:00+08:00", "2026-10-01T01:00:00+08:00", 1),
        ("2026-10-01T23:00:00+08:00", "2026-10-02T01:00:00+08:00", 1),
        ("2026-09-29T00:00:00+08:00", "2026-10-03T00:00:00+08:00", 1),
        ("2026-09-30T00:00:00+08:00", "2026-10-01T00:00:00+08:00", 0),
        ("2026-10-02T00:00:00+08:00", "2026-10-03T00:00:00+08:00", 0),
        ("2026-10-01T15:59:59.999999Z", "2026-10-02T00:00:00Z", 1),
        ("2026-10-01T16:00:00Z", "2026-10-02T00:00:00Z", 0),
    ],
)
def test_ac1_ac2_actual_sql_half_open_full_interval(
    monkeypatch, calendar, start, end, count
):
    from tests.unit.closure_read_db import ClosureReadDB
    from app.models import list_window_closures

    db = ClosureReadDB(
        [
            row(
                start_date_time=datetime.fromisoformat(start),
                end_date_time=datetime.fromisoformat(end),
            )
        ]
    )
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: db)
    try:
        result = list_window_closures("unused", START, END, VENUE if calendar else None)
        assert len(result) == count
        if result:
            assert datetime.fromisoformat(
                result[0]["startDateTime"]
            ) == datetime.fromisoformat(start)
            assert datetime.fromisoformat(
                result[0]["endDateTime"]
            ) == datetime.fromisoformat(end)
        assert all(sql.lstrip().startswith("SELECT") for sql in db.statements)
    finally:
        db.db.close()


@pytest.mark.parametrize("calendar", [True, False])
@pytest.mark.parametrize(
    "change",
    [
        {"venue_id": None},
        {"closure_id": None},
        {"reason": None},
        {"start_date_time": None},
        {"end_date_time": None},
        {
            "start_date_time": datetime(2020, 1, 2),
            "end_date_time": datetime(2020, 1, 1),
        },
    ],
)
def test_actual_sql_malformed_candidates_fail_closed(monkeypatch, calendar, change):
    from tests.unit.closure_read_db import ClosureReadDB
    from app.models import list_window_closures, CalendarDataError

    db = ClosureReadDB([row(**change)])
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: db)
    try:
        with pytest.raises(CalendarDataError):
            list_window_closures("unused", START, END, VENUE if calendar else None)
    finally:
        db.db.close()


def test_actual_sql_other_venue_is_isolated_and_window_is_unpaginated(monkeypatch):
    from tests.unit.closure_read_db import ClosureReadDB
    from app.models import list_window_closures
    from uuid import UUID

    other = "00000000-0000-0000-0000-000000000003"
    db = ClosureReadDB(
        [row(venue_id=other, closure_id=str(UUID(int=100 + i))) for i in range(105)]
    )
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: db)
    try:
        assert list_window_closures("unused", START, END, VENUE) == []
        assert len(list_window_closures("unused", START, END)) == 105
    finally:
        db.db.close()


@pytest.mark.parametrize(
    "role,code",
    [
        ("Event Coordinator", 200),
        ("Venue Staff", 200),
        ("Technical Support", 200),
        ("Technical Support Staff", 200),
        ("Event Organiser", 403),
        ("Attendee", 403),
        ("Administrator", 403),
    ],
)
def test_calendar_closure_roles_unchanged(monkeypatch, role, code):
    from tests.unit.closure_read_db import ClosureReadDB

    db = ClosureReadDB([row()])
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: db)
    client = signed_in(create_app(
        {"TESTING": True, "DATABASE_URL": "unused"}
    ).test_client())
    try:
        response = client.get(
            "/venue-bookings",
            query_string=dict(
                venueId=VENUE, dateFrom=START.isoformat(), dateTo=END.isoformat()
            ),
            headers=bearer(VENUE, role),
        )
        assert response.status_code == code
        if code == 200:
            assert response.json["closures"][0]["closureId"] == CLOSURE
        else:
            assert db.statements == []
    finally:
        db.db.close()


@pytest.mark.parametrize("path", ["/venue-bookings", "/venue-bookings/window"])
def test_malformed_closure_aborts_entire_http_read(monkeypatch, path):
    from tests.unit.closure_read_db import ClosureReadDB

    db = ClosureReadDB([row(reason=None)])
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: db)
    client = signed_in(create_app(
        {"TESTING": True, "DATABASE_URL": "unused"}
    ).test_client())
    try:
        response = client.get(
            path,
            query_string=dict(
                venueId=VENUE, dateFrom=START.isoformat(), dateTo=END.isoformat()
            ),
            headers=bearer(VENUE, "Event Coordinator"),
        )
        assert response.status_code == 503
        assert "bookings" not in response.json and "closures" not in response.json
    finally:
        db.db.close()


@pytest.mark.parametrize("path", ["/venue-bookings", "/venue-bookings/window"])
def test_closure_collection_preserves_existing_booking_contract(monkeypatch, path):
    from tests.unit.closure_read_db import ClosureReadDB
    from tests.unit.factories import booking_row

    db = ClosureReadDB([row()], [booking_row(venue_id=VENUE, status="Approved")])
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: db)
    client = signed_in(create_app(
        {"TESTING": True, "DATABASE_URL": "unused"}
    ).test_client())
    try:
        response = client.get(
            path,
            query_string=dict(
                venueId=VENUE, dateFrom=START.isoformat(), dateTo=END.isoformat()
            ),
            headers=bearer(VENUE, "Event Coordinator"),
        )
        assert response.status_code == 200
        assert len(response.json["bookings"]) == len(response.json["closures"]) == 1
        assert response.json["bookings"][0]["eventId"] is not None
        assert "eventId" not in response.json["closures"][0]
        assert response.json["bookings"][0]["status"] == "Approved"
        assert all(sql.lstrip().startswith("SELECT") for sql in db.statements)
    finally:
        db.db.close()
