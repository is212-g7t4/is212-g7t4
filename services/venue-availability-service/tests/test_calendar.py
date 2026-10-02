"""SCRUM-25 calendar read: AC1 ranges, AC3 blocking, AC4 dev role simulation."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import psycopg2
import pytest
from test_bookings import USER_ID, VENUE_ID, booking_row

from app import create_app
from app.calendar import parse_boundary
from app.models import CalendarDataError, validate_calendar_row

QUERY = dict(venueId=VENUE_ID, dateFrom="2026-10-01T00:00", dateTo="2026-10-02T00:00")
HEADERS = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Event Coordinator"}


@pytest.fixture
def calendar(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: connection)
    app = create_app(dict(TESTING=True, DATABASE_URL="test", CALENDAR_DEV_MODE=True))
    return app, app.test_client(), cursor


def test_ac4_disabled_by_default(monkeypatch):
    monkeypatch.setattr("app.list_bookings", lambda *a: [])
    monkeypatch.delenv("CALENDAR_DEV_MODE", raising=False)
    client = create_app(dict(TESTING=True, DATABASE_URL="test")).test_client()
    assert (
        client.get("/venue-bookings", query_string=QUERY, headers=HEADERS).status_code
        == 503
    )


@pytest.mark.parametrize(
    "headers,code",
    [
        ({}, 401),
        ({"X-Dev-Role": "Venue Staff"}, 401),
        ({"X-Dev-User-Id": "bad", "X-Dev-Role": "Venue Staff"}, 401),
        ({"X-Dev-User-Id": USER_ID}, 401),
        ({**HEADERS, "X-Dev-Role": "Attendee"}, 403),
        ({**HEADERS, "X-Dev-Role": "Event Organiser"}, 403),
        ({**HEADERS, "X-Dev-Role": "Administrator"}, 403),
    ],
)
def test_ac4_reject_identity(calendar, headers, code):
    _, client, cursor = calendar
    assert (
        client.get("/venue-bookings", query_string=QUERY, headers=headers).status_code
        == code
    )
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    "role",
    [
        "Event Coordinator",
        "Venue Staff",
        "Technical Support",
        "Technical Support Staff",
    ],
)
def test_ac4_internal_roles(calendar, role):
    _, client, _ = calendar
    assert (
        client.get(
            "/venue-bookings",
            query_string=QUERY,
            headers={**HEADERS, "X-Dev-Role": role},
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "change",
    [
        {"venueId": None},
        {"venueId": "bad"},
        {"dateFrom": None},
        {"dateTo": None},
        {"dateFrom": ""},
        {"dateFrom": "invalid"},
        {"dateFrom": "2026-10-01"},
        {"dateFrom": "2026-10-01 00:00"},
        {"dateTo": "2026-10-01T00:00"},
        {"dateTo": "2026-09-30T00:00"},
        {"dateTo": "2026-11-13T00:00"},
    ],
)
def test_ac1_invalid_range(calendar, change):
    _, client, cursor = calendar
    query = {k: v for k, v in (QUERY | change).items() if v is not None}
    assert (
        client.get("/venue-bookings", query_string=query, headers=HEADERS).status_code
        == 400
    )
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-09-30T16:00Z", "2026-10-01T16:00Z"),
        ("2026-10-01T00:00+08:00", "2026-10-02T00:00+08:00"),
        ("2026-09-30T12:00-04:00", "2026-10-01T12:00-04:00"),
    ],
)
def test_ac1_offset_inputs_bind_singapore_naive(calendar, start, end):
    _, client, cursor = calendar
    response = client.get(
        "/venue-bookings",
        query_string=QUERY | dict(dateFrom=start, dateTo=end),
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert cursor.execute.call_args.args[1] == [
        VENUE_ID,
        datetime(2026, 10, 2),
        datetime(2026, 10, 1),
    ]


@pytest.mark.parametrize("days", [1, 7, 31, 42])
def test_ac1_visible_ranges(calendar, days):
    _, client, _ = calendar
    end = (datetime(2026, 10, 1) + timedelta(days=days)).isoformat()
    assert (
        client.get(
            "/venue-bookings", query_string=QUERY | dict(dateTo=end), headers=HEADERS
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "status,blocks", [("Approved", True), ("Pending", False), ("Pending Review", False)]
)
def test_ac3_status_and_explicit_timezone(calendar, status, blocks):
    _, client, cursor = calendar
    cursor.fetchall.return_value = [booking_row(status=status)]
    response = client.get("/venue-bookings", query_string=QUERY, headers=HEADERS)
    assert response.status_code == 200
    booking = response.json["bookings"][0]
    assert booking["blocksSelection"] is blocks
    assert booking["requestedStartTime"] == "2026-10-01T09:00:00+08:00"
    assert booking["requestedEndTime"] == "2026-10-01T12:00:00+08:00"


@pytest.mark.parametrize("status", ["Rejected", "Cancelled"])
def test_ac3_excluded_status(calendar, status):
    _, client, cursor = calendar
    cursor.fetchall.return_value = [booking_row(status=status)]
    assert client.get("/venue-bookings", query_string=QUERY, headers=HEADERS).json == {
        "bookings": []
    }


@pytest.mark.parametrize(
    "start,end,included",
    [
        ("2026-09-30T23:00", "2026-10-01T00:00", False),
        ("2026-10-02T00:00", "2026-10-02T01:00", False),
        ("2026-09-30T23:00", "2026-10-01T00:01", True),
        ("2026-10-01T23:59", "2026-10-02T01:00", True),
        ("2026-09-30T00:00", "2026-10-03T00:00", True),
    ],
)
def test_ac1_half_open_overlap(calendar, start, end, included):
    _, client, cursor = calendar
    cursor.fetchall.return_value = [
        booking_row(
            requested_start_time=datetime.fromisoformat(start),
            requested_end_time=datetime.fromisoformat(end),
        )
    ]
    response = client.get("/venue-bookings", query_string=QUERY, headers=HEADERS)
    assert response.status_code == 200
    assert bool(response.json["bookings"]) is included


@pytest.mark.parametrize(
    "change",
    [
        {"status": None},
        {"status": "Unknown"},
        {"status": "approved"},
        {"requested_start_time": None},
        {"requested_end_time": None},
        {"requested_start_time": "bad"},
        {"requested_end_time": datetime(2026, 10, 1, 9)},
        {"requested_end_time": datetime(2026, 9, 1)},
        {"event_id": None},
        {"booking_id": "bad"},
        {"venue_id": None},
    ],
)
def test_ac3_malformed_rows_fail_closed(calendar, change):
    _, client, cursor = calendar
    cursor.fetchall.return_value = [booking_row(), booking_row(**change)]
    response = client.get("/venue-bookings", query_string=QUERY, headers=HEADERS)
    assert response.status_code == 503
    assert "bookings" not in response.json


def test_query_includes_invalid_rows_not_silently_lost(calendar):
    _, client, cursor = calendar
    client.get("/venue-bookings", query_string=QUERY, headers=HEADERS)
    sql, params = cursor.execute.call_args.args
    normalized = " ".join(sql.split())
    assert "venue_id = %s" in normalized
    assert "requested_start_time < %s AND requested_end_time > %s" in normalized
    for condition in [
        "requested_start_time IS NULL",
        "requested_end_time IS NULL",
        "requested_end_time <= requested_start_time",
        "status IS NULL",
        "venue_id IS NULL",
    ]:
        assert condition in normalized
    assert params == [VENUE_ID, datetime(2026, 10, 2), datetime(2026, 10, 1)]


def test_ac4_cors_preflight(calendar):
    _, client, cursor = calendar
    response = client.options(
        "/venue-bookings",
        headers={
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Dev-User-Id,X-Dev-Role",
        },
    )
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert "GET" in response.headers["Access-Control-Allow-Methods"]
    for header in ["X-Dev-User-Id", "X-Dev-Role"]:
        assert header in response.headers["Access-Control-Allow-Headers"]
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("key", ["venueId", "dateFrom", "dateTo"])
def test_repeated_parameters_rejected(calendar, key):
    _, client, cursor = calendar
    query = list(QUERY.items()) + [(key, QUERY[key])]
    assert (
        client.get("/venue-bookings", query_string=query, headers=HEADERS).status_code
        == 400
    )
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("value", [None, "badTdate", "9999-12-31T23:59:59-12:00"])
def test_invalid_boundary_parser(value):
    assert parse_boundary(value) is None


@pytest.mark.parametrize(
    "change",
    [
        {"requested_start_time": datetime(2026, 10, 1, tzinfo=timezone.utc)},
        {"requested_end_time": datetime.max},
        {"requested_start_time": datetime.min},
    ],
)
def test_non_local_or_infinite_db_time_fails(calendar, change):
    _, client, cursor = calendar
    cursor.fetchall.return_value = [booking_row(**change)]
    assert (
        client.get("/venue-bookings", query_string=QUERY, headers=HEADERS).status_code
        == 503
    )


def test_missing_row_fields_fail():
    with pytest.raises(CalendarDataError):
        validate_calendar_row({})


@pytest.mark.parametrize("origin", ["http://evil.example", "null"])
def test_cors_untrusted_origin(calendar, origin):
    _, client, _ = calendar
    response = client.options("/venue-bookings", headers={"Origin": origin})
    assert "Access-Control-Allow-Origin" not in response.headers


def test_cors_health_no_custom_headers(calendar):
    _, client, _ = calendar
    response = client.get("/health", headers={"Origin": "http://localhost:5174"})
    assert "Access-Control-Allow-Methods" not in response.headers


def test_database_unconfigured(calendar):
    app, client, cursor = calendar
    app.config["DATABASE_URL"] = None
    assert (
        client.get("/venue-bookings", query_string=QUERY, headers=HEADERS).status_code
        == 503
    )
    cursor.execute.assert_not_called()


def test_database_failure_no_details(calendar):
    _, client, cursor = calendar
    cursor.execute.side_effect = psycopg2.OperationalError("secret detail")
    response = client.get("/venue-bookings", query_string=QUERY, headers=HEADERS)
    assert response.status_code == 503
    assert "secret" not in response.get_data(as_text=True)


@pytest.mark.parametrize(
    "value,code", [("true", 200), ("false", 503), ("1", 503), ("TRUE", 503), ("", 503)]
)
def test_dev_mode_exact_environment_opt_in(monkeypatch, calendar, value, code):
    monkeypatch.setenv("CALENDAR_DEV_MODE", value)
    app = create_app(dict(TESTING=True, DATABASE_URL="test"))
    assert (
        app.test_client()
        .get("/venue-bookings", query_string=QUERY, headers=HEADERS)
        .status_code
        == code
    )


@pytest.mark.parametrize(
    "role", ["event coordinator", " Venue Staff", "Venue Staff,Attendee"]
)
def test_roles_are_exact_not_substring_matches(calendar, role):
    _, client, cursor = calendar
    assert (
        client.get(
            "/venue-bookings",
            query_string=QUERY,
            headers=HEADERS | {"X-Dev-Role": role},
        ).status_code
        == 403
    )
    cursor.execute.assert_not_called()


def test_cors_headers_on_denial(calendar):
    _, client, _ = calendar
    response = client.get(
        "/venue-bookings",
        query_string=QUERY,
        headers={"Origin": "http://localhost:5174"},
    )
    assert response.status_code == 401
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert response.headers["Vary"] == "Origin"


def test_empty_date_to_rejected(calendar):
    _, client, _ = calendar
    assert (
        client.get(
            "/venue-bookings", query_string=QUERY | {"dateTo": ""}, headers=HEADERS
        ).status_code
        == 400
    )
