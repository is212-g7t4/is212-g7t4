"""# Test scope and acceptance mapping — SCRUM-171 integration

- **SCRUM-170 closure regressions:** staff/configuration/CORS guards, validation, ongoing and offset dates, parameterized reason, pagination, nullable legacy data and controlled database errors. These retain SCRUM-170 scope.
- **SCRUM-171 AC4 backend support:** a signed zero-impact confirmation preserves the existing closure contract; no full-list UI claim.
- **Supporting AC5 failure handling:** mocked connection rollback/close checks do not prove real all-row atomicity; that is tested in the PostgreSQL harness.

## Case/group traceability

The named test functions/cases below implement the groups above; their existing
names and assertions specify the scenario. No group is credited with all five ACs.

## Existing test contract and detailed cases

SCRUM-170 closure contract (independent of booking timestamp contracts)."""

from unittest.mock import MagicMock
from datetime import datetime, timezone
import psycopg2
import pytest
from app import create_app
from app.closure_store import sign_preview
from app.closure_contract import create_input
from tests.unit.factories import bearer


UID = "00000000-0000-0000-0000-000000000001"
HEADERS = bearer(UID, "Venue Staff")


@pytest.fixture
def client():
    return create_app({"CLOSURE_CONFIRMATION_KEY": KEY}).test_client()


@pytest.mark.parametrize(
    "headers,code",
    [
        ({}, 401),
        ({"X-Dev-User-Id": UID, "X-Dev-Role": "Venue Staff"}, 401),
        ({"Authorization": "Bearer not-a-jwt"}, 401),
        (bearer(UID, "Event Coordinator"), 403),
    ],
)
@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/venue-closures"),
        ("get", "/venue-closures"),
        ("get", "/venue-closures/" + UID),
    ],
)
def test_staff_guard(client, headers, code, method, path):
    assert getattr(client, method)(path, headers=headers).status_code == code


@pytest.mark.parametrize("path", ["/venue-closures", "/venue-closures/" + UID])
def test_preflight(client, path):
    r = client.options(
        path,
        headers={
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    assert r.status_code == 200
    assert r.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert "Authorization" in r.headers["Access-Control-Allow-Headers"]


@pytest.mark.parametrize(
    "path",
    [
        "/venue-closures/bad",
        "/venue-closures",
        "/venue-closures?venueId=bad",
        "/venue-closures?venueId=" + UID + "&limit=0",
        "/venue-closures?venueId=" + UID + "&limit=101",
        "/venue-closures?venueId=" + UID + "&limit=no",
        "/venue-closures?venueId=" + UID + "&limit=1&limit=2",
        "/venue-closures?venueId=" + UID + "&cursor=bad",
        "/venue-closures?venueId=" + UID + "&unknown=1",
    ],
)
def test_invalid_read(client, path):
    assert client.get(path, headers=HEADERS).status_code == 400


KEY = "test-only-signing-key-not-a-production-default"

BODY = {
    "venueId": UID,
    "startDateTime": "2099-01-01T10:00:00+08:00",
    "endDateTime": "2099-01-01T11:00:00+08:00",
    "reason": "  Maintenance  ",
}


def confirmed(body):
    clean = {
        k: v for k, v in body.items() if k not in {"confirmed", "confirmationToken"}
    }
    return clean | {
        "confirmed": True,
        "confirmationToken": sign_preview(create_input(clean), UID, [], KEY),
    }


BODY = confirmed(BODY)


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        "text",
        {},
        {**BODY, "venueId": 12},
        {**BODY, "venueId": "bad"},
        {**BODY, "reason": None},
        {**BODY, "reason": "  "},
        {**BODY, "startDateTime": 12},
        {**BODY, "startDateTime": "2099-01-01T10:00:00"},
        {**BODY, "startDateTime": "bad"},
        {**BODY, "endDateTime": BODY["startDateTime"]},
        {**BODY, "endDateTime": "2000-01-01T00:00:00Z"},
        {**BODY, "createdBy": UID},
        {**BODY, "createdAt": "2099-01-01"},
    ],
)
def test_invalid_create(client, body):
    assert client.post("/venue-closures", json=body, headers=HEADERS).status_code == 400


@pytest.mark.parametrize(
    "start,end",
    [
        ("0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-12:00"),
        ("2099-01-01T10:00:00+08:00", "2099-01-01T02:00:00Z"),
    ],
)
def test_unsafe_or_equal_instants(client, start, end):
    assert (
        client.post(
            "/venue-closures",
            json={**BODY, "startDateTime": start, "endDateTime": end},
            headers=HEADERS,
        ).status_code
        == 400
    )


def test_reject_invalid_unicode_reason(client):
    assert (
        client.post(
            "/venue-closures", json={**BODY, "reason": "\ud800"}, headers=HEADERS
        ).status_code
        == 400
    )


def test_reject_nul_reason(client):
    assert (
        client.post(
            "/venue-closures",
            json={**BODY, "reason": "unsafe\x00text"},
            headers=HEADERS,
        ).status_code
        == 400
    )


@pytest.mark.parametrize("cursor", ["", "a" * 1025])
def test_empty_or_excessive_cursor(client, cursor):
    assert (
        client.get(
            "/venue-closures",
            query_string={"venueId": UID, "cursor": cursor},
            headers=HEADERS,
        ).status_code
        == 400
    )


def test_end_equal_server_now(client, monkeypatch):
    from datetime import datetime, timezone
    import app.closure_contract as contract

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2099, 1, 1, 3, tzinfo=timezone.utc)

    monkeypatch.setattr(contract, "datetime", Clock)
    assert client.post("/venue-closures", json=BODY, headers=HEADERS).status_code == 400


def test_untrusted_origin_gets_no_cors_grant(client):
    r = client.options(
        "/venue-closures", headers={"Origin": "https://untrusted.example"}
    )
    assert "Access-Control-Allow-Origin" not in r.headers


def test_malformed_json(client):
    assert (
        client.post(
            "/venue-closures",
            data="{",
            content_type="application/json",
            headers=HEADERS,
        ).status_code
        == 400
    )


@pytest.fixture(autouse=True)
def database(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    row = dict(
        closure_id=UID,
        venue_id=UID,
        start_date_time=datetime(2099, 1, 1, 2, tzinfo=timezone.utc),
        end_date_time=datetime(2099, 1, 1, 3, tzinfo=timezone.utc),
        reason="Maintenance",
        created_by=UID,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    cursor.fetchone.return_value = row
    cursor.fetchall.return_value = []
    cursor.rowcount = 0
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr(psycopg2, "connect", connect)
    return connect, connection, cursor, row


def test_confirmed_zero_impact_preserves_closure_contract(client, database):
    connect, conn, cur, row = database
    client.application.config["DATABASE_URL"] = "fake-dsn"
    response = client.post("/venue-closures", json=BODY, headers=HEADERS)
    assert response.status_code == 201
    result = response.json["closure"]
    assert result == dict(
        closureId=UID,
        venueId=UID,
        startDateTime="2099-01-01T10:00:00+08:00",
        endDateTime="2099-01-01T11:00:00+08:00",
        reason="Maintenance",
        createdBy=UID,
        createdAt="2026-01-01T08:00:00+08:00",
    )
    assert response.json["rejectedCount"] == 0
    sql, params = cur.execute.call_args_list[-2].args
    assert 'INSERT INTO public."VenueClosure"' in sql
    assert "VenueBooking" not in sql and "VenueHold" not in sql
    assert params[:5] == (
        UID,
        BODY["startDateTime"],
        BODY["endDateTime"],
        "Maintenance",
        UID,
    )
    assert params[5].tzinfo is not None
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
    conn.close.assert_called_once()
    conn.cursor.return_value.__exit__.assert_called_once()


def test_ongoing_and_offset_create(client, database):
    client.application.config["DATABASE_URL"] = "fake-dsn"
    r = client.post(
        "/venue-closures",
        json=confirmed(
            {
                **BODY,
                "startDateTime": "2000-01-01T00:00:00Z",
                "endDateTime": "2099-01-01T03:00:00Z",
            }
        ),
        headers=HEADERS,
    )
    assert r.status_code == 201


@pytest.mark.parametrize("stage", ["connect", "execute", "commit"])
def test_create_db_failure_rolls_back_and_closes(client, database, stage):
    connect, conn, cur, _ = database
    client.application.config["DATABASE_URL"] = "fake-dsn"
    target = {"connect": connect, "execute": cur.execute, "commit": conn.commit}[stage]
    target.side_effect = psycopg2.OperationalError("private database details")
    r = client.post("/venue-closures", json=BODY, headers=HEADERS)
    assert r.status_code == 503 and "private" not in r.text
    if stage != "connect":
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()
        conn.cursor.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize(
    "constraint,code",
    [("VenueClosure_venue_id_fkey", 404), ("VenueClosure_created_by_fkey", 400)],
)
def test_fk_failure(client, database, constraint, code):
    class FK(psycopg2.IntegrityError):
        pgcode = "23503"
        diag = type("Diag", (), {"constraint_name": constraint})()

    client.application.config["DATABASE_URL"] = "fake-dsn"
    database[2].execute.side_effect = FK()
    assert (
        client.post("/venue-closures", json=BODY, headers=HEADERS).status_code == code
    )
    database[1].rollback.assert_called_once()
    database[1].close.assert_called_once()


def test_overlapping_creates_are_not_rejected(client, database):
    client.application.config["DATABASE_URL"] = "fake-dsn"
    for _ in range(2):
        assert (
            client.post("/venue-closures", json=BODY, headers=HEADERS).status_code
            == 201
        )
    assert (
        sum(
            'INSERT INTO public."VenueClosure"' in call.args[0]
            for call in database[2].execute.call_args_list
        )
        == 2
    )


def test_reason_is_parameterized(client, database):
    client.application.config["DATABASE_URL"] = "fake-dsn"
    reason = '\'); DROP TABLE public."VenueClosure"; --'
    assert (
        client.post(
            "/venue-closures",
            json=confirmed({**BODY, "reason": reason}),
            headers=HEADERS,
        ).status_code
        == 201
    )
    sql, params = database[2].execute.call_args_list[-2].args
    assert reason not in sql and params[3] == reason


def test_no_database_config(client, database):
    client.application.config["DATABASE_URL"] = None
    assert client.post("/venue-closures", json=BODY, headers=HEADERS).status_code == 503
    database[0].assert_not_called()


def test_get_closure_and_missing(client, database):
    client.application.config["DATABASE_URL"] = "fake-dsn"
    r = client.get("/venue-closures/" + UID, headers=HEADERS)
    assert r.status_code == 200 and r.json["closure"]["closureId"] == UID
    assert database[2].execute.call_args.args[1] == (UID,)
    database[2].fetchone.return_value = None
    assert client.get("/venue-closures/" + UID, headers=HEADERS).status_code == 404
    assert database[1].close.call_count == 2


def test_list_paginates_with_lookahead_and_foreign_cursor(client, database):
    client.application.config["DATABASE_URL"] = "fake-dsn"
    _, conn, cur, row = database
    cur.fetchall.return_value = [
        row,
        {**row, "closure_id": "00000000-0000-0000-0000-000000000002"},
    ]
    r = client.get(
        "/venue-closures", query_string={"venueId": UID, "limit": 1}, headers=HEADERS
    )
    assert r.status_code == 200 and len(r.json["closures"]) == 1
    cursor = r.json["nextCursor"]
    assert cursor
    sql, params = cur.execute.call_args.args
    assert "ORDER BY start_date_time, closure_id" in sql
    assert params == (UID, 2)
    cur.fetchall.return_value = []
    r = client.get(
        "/venue-closures",
        query_string={"venueId": UID, "limit": 1, "cursor": cursor},
        headers=HEADERS,
    )
    assert r.json == {"closures": [], "nextCursor": None}
    sql, params = cur.execute.call_args.args
    assert "(start_date_time, closure_id) > (%s, %s)" in sql
    assert params[0] == UID and params[-1] == 2 and params[-2] == UID
    r = client.get(
        "/venue-closures",
        query_string={
            "venueId": "00000000-0000-0000-0000-000000000003",
            "cursor": cursor,
        },
        headers=HEADERS,
    )
    assert r.status_code == 400
    conn.commit.assert_not_called()
    assert conn.close.call_count == 2


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        [UID, "bad", UID],
        [UID, "2099-01-01T00:00:00Z", "bad"],
        [UID, "2099-01-01T00:00:00Z", UID, 1],
    ],
)
def test_malformed_cursor_payload(client, payload):
    import base64
    import json

    cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    assert (
        client.get(
            "/venue-closures",
            query_string={"venueId": UID, "cursor": cursor},
            headers=HEADERS,
        ).status_code
        == 400
    )


@pytest.mark.parametrize(
    "path", ["/venue-closures/" + UID, "/venue-closures?venueId=" + UID]
)
def test_read_failure_cleanup(client, database, path):
    client.application.config["DATABASE_URL"] = "fake-dsn"
    database[2].execute.side_effect = psycopg2.OperationalError()
    assert client.get(path, headers=HEADERS).status_code == 503
    database[1].rollback.assert_called_once()
    database[1].close.assert_called_once()


def test_legacy_nullable_metadata(client, database):
    client.application.config["DATABASE_URL"] = "fake-dsn"
    database[2].fetchone.return_value = {
        **database[3],
        "created_at": None,
        "created_by": None,
    }
    r = client.get("/venue-closures/" + UID, headers=HEADERS)
    assert r.status_code == 200
    assert (
        r.json["closure"]["createdAt"] is None
        and r.json["closure"]["createdBy"] is None
    )


def test_legacy_null_venue_is_not_string_none(client, database):
    client.application.config["DATABASE_URL"] = "fake-dsn"
    database[2].fetchone.return_value = {**database[3], "venue_id": None}
    response = client.get("/venue-closures/" + UID, headers=HEADERS)
    assert response.status_code == 200
    assert response.json["closure"]["venueId"] is None


def test_other_integrity_error_is_controlled(client, database):
    client.application.config["DATABASE_URL"] = "fake-dsn"
    database[2].execute.side_effect = psycopg2.IntegrityError()
    assert client.post("/venue-closures", json=BODY, headers=HEADERS).status_code == 503
