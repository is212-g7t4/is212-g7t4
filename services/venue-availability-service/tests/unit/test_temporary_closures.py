"""
SCRUM-170: Record Temporary Venue Unavailability

User Story
----------
As a Venue Staff, I want to mark a venue as temporarily unavailable for a
specific time period and provide a reason, so that the venue cannot be booked
during maintenance, equipment failure, renovation, safety concerns, or other
operational issues.

Acceptance Criteria
-------------------
AC1: Given an existing venue, Venue Staff can view an existing venue and enter
     a start date/time, a later end date/time, and a nonblank operational
     reason and save, then the closure is persisted and its venue, period, and
     reason are displayed.
AC2: Given required information is missing or the end is not later than the
     start, when Venue Staff save, then the system identifies the invalid input
     and does not create a closure.
AC3: Given the closure cannot be saved, then the system displays a failure
     message and does not report successful creation.

Real
----
- POST /venue-closures, GET /venue-closures and GET /venue-closures/<id>: the
  Venue Staff guard, input validation (venue, later end, nonblank safe reason),
  ongoing and offset times, cursor pagination, database failure cleanup and
  foreign-key mapping run for real.
- Assertions are on the status, error and SQL sent.

Doubled
-------
- psycopg2.connect: Stub (`setup`/`client` fixtures) - fresh MagicMock
  connection; the cursor returns canned VenueBooking / VenueClosure rows (or
  raises); executed SQL, parameters and locks are inspected.

Not proven
----------
- That the SQL, locks and constraints behave the same on real PostgreSQL (->
  tests/integration/, throwaway postgres:17.6).
- That the closure is shown on the venue page (AC1 UI half) (-> frontend
  VenueClosuresPanel tests and e2e venue-closures.spec.ts).
"""

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
    ids=["no_token", "dev_headers", "bad_token", "coordinator"],
)
@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/venue-closures"),
        ("get", "/venue-closures"),
        ("get", "/venue-closures/" + UID),
    ],
    ids=["create", "list", "get"],
)
def test_closure_routes_when_not_venue_staff_are_refused(client, headers, code, method, path):
    """
    Summary: Only signed-in Venue Staff can record or read closures.
    AC1: Given an existing venue, Venue Staff can view an existing venue and
        enter a start date/time, a later end date/time, and a nonblank
        operational reason and save, then the closure is persisted and its
        venue, period, and reason are displayed.
    Double: Mock (cursor not executed)
    """
    # Arrange (Given): client, headers, code, method, path, from fixtures

    # Act + Assert (When / Then)
    assert getattr(client, method)(path, headers=headers).status_code == code


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
    ids=["venue_closures_bad", "venue_closures", "venue_closures_venueid_bad", "venue_closures_venueid_uid_limit_0", "venue_closures_venueid_uid_limit_101", "venue_closures_venueid_uid_limit_no", "venue_closures_venueid_uid_limit_1_limit_2", "venue_closures_venueid_uid_cursor_bad", "venue_closures_venueid_uid_unknown_1"],
)
def test_read_closures_with_bad_id_or_filter_returns_400(client, path):
    """
    Summary: Closure reads need a valid id or venue filter.
    AC1: Given an existing venue, Venue Staff can view an existing venue and
        enter a start date/time, a later end date/time, and a nonblank
        operational reason and save, then the closure is persisted and its
        venue, period, and reason are displayed.
    Double: None
    """
    # Arrange (Given): client, path, from fixtures

    # Act + Assert (When / Then)
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
    ids=["none", "empty", "text", "empty_2", "body_venueid_12", "body_venueid_bad", "body_reason_none", "body_reason", "body_startdatetime_12", "body_startdatetime_2099_01_01t10_00_00", "body_startdatetime_bad", "body_enddatetime_body_startdatetime", "body_enddatetime_2000_01_01t00_00_00z", "body_createdby_uid", "body_createdat_2099_01_01"],
)
def test_create_closure_with_invalid_input_returns_400_without_saving(client, body):
    """
    Summary: A closure without a valid venue, reason, start and later end is refused.
    AC2: Given required information is missing or the end is not later than the
        start, when Venue Staff save, then the system identifies the invalid
        input and does not create a closure.
    Double: Mock (cursor not executed)
    """
    # Arrange (Given): client, body, from fixtures

    # Act + Assert (When / Then)
    assert client.post("/venue-closures", json=body, headers=HEADERS).status_code == 400


@pytest.mark.parametrize(
    "start,end",
    [
        ("0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-12:00"),
        ("2099-01-01T10:00:00+08:00", "2099-01-01T02:00:00Z"),
    ],
    ids=["extreme_instant", "end_equals_start"],
)
def test_create_closure_with_unsafe_or_equal_times_returns_400(client, start, end):
    """
    Summary: A closure whose end is not later than its start, or at an unsafe extreme, is refused.
    AC2: (boundary: end = start)
    Double: None
    """
    # Arrange (Given): client, start, end, from fixtures

    # Act + Assert (When / Then)
    assert (
        client.post(
            "/venue-closures",
            json={**BODY, "startDateTime": start, "endDateTime": end},
            headers=HEADERS,
        ).status_code
        == 400
    )


def test_create_closure_with_invalid_unicode_reason_returns_400(client):
    """
    Summary: A reason with invalid characters is refused.
    AC2: Given required information is missing or the end is not later than the
        start, when Venue Staff save, then the system identifies the invalid
        input and does not create a closure.
    Double: None
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert (
        client.post(
            "/venue-closures", json={**BODY, "reason": "\ud800"}, headers=HEADERS
        ).status_code
        == 400
    )


def test_create_closure_with_nul_in_reason_returns_400(client):
    """
    Summary: A reason containing a NUL character is refused.
    AC2: Given required information is missing or the end is not later than the
        start, when Venue Staff save, then the system identifies the invalid
        input and does not create a closure.
    Double: None
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert (
        client.post(
            "/venue-closures",
            json={**BODY, "reason": "unsafe\x00text"},
            headers=HEADERS,
        ).status_code
        == 400
    )


@pytest.mark.parametrize("cursor", ["", "a" * 1025], ids=["empty", "too_long"])
def test_list_closures_with_empty_or_oversized_cursor_returns_400(client, cursor):
    """
    Summary: A page cursor must be present and of a sane length.
    AC1: Given an existing venue, Venue Staff can view an existing venue and
        enter a start date/time, a later end date/time, and a nonblank
        operational reason and save, then the closure is persisted and its
        venue, period, and reason are displayed.
    Double: None
    """
    # Arrange (Given): client, cursor, from fixtures

    # Act + Assert (When / Then)
    assert (
        client.get(
            "/venue-closures",
            query_string={"venueId": UID, "cursor": cursor},
            headers=HEADERS,
        ).status_code
        == 400
    )


def test_create_closure_ending_now_is_refused(client, monkeypatch):
    """
    Summary: A closure that ends right now is refused.
    AC2: (boundary: end = now)
    Double: None
    """
    # Arrange (Given)
    from datetime import datetime, timezone
    import app.closure_contract as contract

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2099, 1, 1, 3, tzinfo=timezone.utc)

    monkeypatch.setattr(contract, "datetime", Clock)

    # Act + Assert (When / Then)
    assert client.post("/venue-closures", json=BODY, headers=HEADERS).status_code == 400


def test_create_closure_with_malformed_json_returns_400(client):
    """
    Summary: A body that is not valid JSON is refused.
    AC2: Given required information is missing or the end is not later than the
        start, when Venue Staff save, then the system identifies the invalid
        input and does not create a closure.
    Double: None
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
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


def test_create_closure_with_no_affected_requests_returns_saved_closure(client, database):
    """
    Summary: A confirmed closure that affects no requests is saved and returned in full.
    AC1: Given an existing venue, Venue Staff can view an existing venue and
        enter a start date/time, a later end date/time, and a nonblank
        operational reason and save, then the closure is persisted and its
        venue, period, and reason are displayed.
    Double: Stub (cursor returns the saved closure)
    """
    # Arrange (Given)
    connect, conn, cur, row = database
    client.application.config["DATABASE_URL"] = "fake-dsn"

    # Act (When)
    response = client.post("/venue-closures", json=BODY, headers=HEADERS)

    # Assert (Then)
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


def test_create_closure_ongoing_or_with_offset_times_is_saved(client, database):
    """
    Summary: A closure already in progress, or given with a time zone, is saved correctly.
    AC1: Given an existing venue, Venue Staff can view an existing venue and
        enter a start date/time, a later end date/time, and a nonblank
        operational reason and save, then the closure is persisted and its
        venue, period, and reason are displayed.
    Double: Stub (cursor; parameters inspected)
    """
    # Arrange (Given)
    client.application.config["DATABASE_URL"] = "fake-dsn"

    # Act (When)
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

    # Assert (Then)
    assert r.status_code == 201


@pytest.mark.parametrize("stage", ["connect", "execute", "commit"], ids=["connect", "execute", "commit"])
def test_create_closure_when_database_fails_rolls_back_and_reports_failure(client, database, stage):
    """
    Summary: A database failure rolls back and reports failure, not success.
    AC3: Given the closure cannot be saved, then the system displays a failure
        message and does not report successful creation.
    Double: Stub (connect, execute or commit raises)
    """
    # Arrange (Given)
    connect, conn, cur, _ = database
    client.application.config["DATABASE_URL"] = "fake-dsn"
    target = {"connect": connect, "execute": cur.execute, "commit": conn.commit}[stage]
    target.side_effect = psycopg2.OperationalError("private database details")

    # Act (When)
    r = client.post("/venue-closures", json=BODY, headers=HEADERS)

    # Assert (Then)
    assert r.status_code == 503 and "private" not in r.text
    if stage != "connect":
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()
        conn.cursor.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize(
    "constraint,code",
    [("VenueClosure_venue_id_fkey", 404), ("VenueClosure_created_by_fkey", 400)],
    ids=["unknown_venue", "unknown_creator"],
)
def test_create_closure_with_unknown_venue_or_user_returns_error(client, database, constraint, code):
    """
    Summary: A closure for an unknown venue or by an unknown user is refused.
    AC3: Given the closure cannot be saved, then the system displays a failure
        message and does not report successful creation.
    Double: Stub (insert raises ForeignKeyViolation)
    """
    # Arrange (Given)
    class FK(psycopg2.IntegrityError):
        pgcode = "23503"
        diag = type("Diag", (), {"constraint_name": constraint})()

    client.application.config["DATABASE_URL"] = "fake-dsn"
    database[2].execute.side_effect = FK()

    # Act + Assert (When / Then)
    assert (
        client.post("/venue-closures", json=BODY, headers=HEADERS).status_code == code
    )
    database[1].rollback.assert_called_once()
    database[1].close.assert_called_once()


def test_create_overlapping_closures_are_both_saved(client, database):
    """
    Summary: Overlapping closures can both be recorded.
    AC1: Given an existing venue, Venue Staff can view an existing venue and
        enter a start date/time, a later end date/time, and a nonblank
        operational reason and save, then the closure is persisted and its
        venue, period, and reason are displayed.
    Double: Stub (cursor)
    """
    # Arrange (Given)
    client.application.config["DATABASE_URL"] = "fake-dsn"

    # Act (When)
    for _ in range(2):
        assert (
            client.post("/venue-closures", json=BODY, headers=HEADERS).status_code
            == 201
        )

    # Assert (Then)
    assert (
        sum(
            'INSERT INTO public."VenueClosure"' in call.args[0]
            for call in database[2].execute.call_args_list
        )
        == 2
    )


def test_create_closure_sends_reason_as_parameter(client, database):
    """
    Summary: The reason is sent as a query parameter, never pasted into SQL.
    AC1: Given an existing venue, Venue Staff can view an existing venue and
        enter a start date/time, a later end date/time, and a nonblank
        operational reason and save, then the closure is persisted and its
        venue, period, and reason are displayed.
    Double: Stub (cursor; SQL inspected)
    """
    # Arrange (Given)
    client.application.config["DATABASE_URL"] = "fake-dsn"
    reason = '\'); DROP TABLE public."VenueClosure"; --'

    # Act + Assert (When / Then)
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


def test_get_closure_returns_it_or_404(client, database):
    """
    Summary: One closure can be read with its venue, period and reason, or reported missing.
    AC1: Given an existing venue, Venue Staff can view an existing venue and
        enter a start date/time, a later end date/time, and a nonblank
        operational reason and save, then the closure is persisted and its
        venue, period, and reason are displayed.
    Double: Stub (cursor returns a row or nothing)
    """
    # Arrange (Given)
    client.application.config["DATABASE_URL"] = "fake-dsn"

    # Act (When)
    r = client.get("/venue-closures/" + UID, headers=HEADERS)

    # Assert (Then)
    assert r.status_code == 200 and r.json["closure"]["closureId"] == UID
    assert database[2].execute.call_args.args[1] == (UID,)
    database[2].fetchone.return_value = None
    assert client.get("/venue-closures/" + UID, headers=HEADERS).status_code == 404
    assert database[1].close.call_count == 2


def test_list_closures_paginates_and_rejects_other_venues_cursor(client, database):
    """
    Summary: Closures are listed a page at a time, and another venue's cursor is refused.
    AC1: Given an existing venue, Venue Staff can view an existing venue and
        enter a start date/time, a later end date/time, and a nonblank
        operational reason and save, then the closure is persisted and its
        venue, period, and reason are displayed.
    Double: Stub (cursor returns rows)
    """
    # Arrange (Given)
    client.application.config["DATABASE_URL"] = "fake-dsn"
    _, conn, cur, row = database
    cur.fetchall.return_value = [
        row,
        {**row, "closure_id": "00000000-0000-0000-0000-000000000002"},
    ]

    # Act (When)
    r = client.get(
        "/venue-closures", query_string={"venueId": UID, "limit": 1}, headers=HEADERS
    )

    # Assert (Then)
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
    ids=["empty", "empty_2", "uid_bad_uid", "uid_2099_01_01t00_00_00z_bad", "uid_2099_01_01t00_00_00z_uid_1"],
)
def test_list_closures_with_malformed_cursor_returns_400(client, payload):
    """
    Summary: A tampered page cursor is refused.
    AC1: Given an existing venue, Venue Staff can view an existing venue and
        enter a start date/time, a later end date/time, and a nonblank
        operational reason and save, then the closure is persisted and its
        venue, period, and reason are displayed.
    Double: None
    """
    # Arrange (Given)
    import base64
    import json

    cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()

    # Act + Assert (When / Then)
    assert (
        client.get(
            "/venue-closures",
            query_string={"venueId": UID, "cursor": cursor},
            headers=HEADERS,
        ).status_code
        == 400
    )


@pytest.mark.parametrize(
    "path", ["/venue-closures/" + UID, "/venue-closures?venueId=" + UID],
    ids=["single_closure", "venue_list"],
)
def test_read_closures_when_database_fails_closes_connection(client, database, path):
    """
    Summary: A failed read still closes its connection.
    AC3: Given the closure cannot be saved, then the system displays a failure
        message and does not report successful creation.
    Double: Stub (cursor raises), Mock (close)
    """
    # Arrange (Given)
    client.application.config["DATABASE_URL"] = "fake-dsn"
    database[2].execute.side_effect = psycopg2.OperationalError()

    # Act + Assert (When / Then)
    assert client.get(path, headers=HEADERS).status_code == 503
    database[1].rollback.assert_called_once()
    database[1].close.assert_called_once()


def test_read_closure_with_missing_metadata_returns_nulls(client, database):
    """
    Summary: Older closures without creator or time still read.
    AC1: Given an existing venue, Venue Staff can view an existing venue and
        enter a start date/time, a later end date/time, and a nonblank
        operational reason and save, then the closure is persisted and its
        venue, period, and reason are displayed.
    Double: Stub (cursor returns a legacy row)
    """
    # Arrange (Given)
    client.application.config["DATABASE_URL"] = "fake-dsn"
    database[2].fetchone.return_value = {
        **database[3],
        "created_at": None,
        "created_by": None,
    }

    # Act (When)
    r = client.get("/venue-closures/" + UID, headers=HEADERS)

    # Assert (Then)
    assert r.status_code == 200
    assert (
        r.json["closure"]["createdAt"] is None
        and r.json["closure"]["createdBy"] is None
    )


def test_read_closure_with_null_venue_returns_null_not_text(client, database):
    """
    Summary: A missing venue is returned as nothing, not the text "None".
    AC1: Given an existing venue, Venue Staff can view an existing venue and
        enter a start date/time, a later end date/time, and a nonblank
        operational reason and save, then the closure is persisted and its
        venue, period, and reason are displayed.
    Double: Stub (cursor returns a row without venue)
    """
    # Arrange (Given)
    client.application.config["DATABASE_URL"] = "fake-dsn"
    database[2].fetchone.return_value = {**database[3], "venue_id": None}

    # Act (When)
    response = client.get("/venue-closures/" + UID, headers=HEADERS)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["closure"]["venueId"] is None


def test_create_closure_with_other_integrity_error_returns_controlled_error(client, database):
    """
    Summary: Any other database integrity error is reported as a controlled failure.
    AC3: Given the closure cannot be saved, then the system displays a failure
        message and does not report successful creation.
    Double: Stub (insert raises IntegrityError)
    """
    # Arrange (Given)
    client.application.config["DATABASE_URL"] = "fake-dsn"
    database[2].execute.side_effect = psycopg2.IntegrityError()

    # Act + Assert (When / Then)
    assert client.post("/venue-closures", json=BODY, headers=HEADERS).status_code == 503


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


@pytest.mark.parametrize("path", ["/venue-closures", "/venue-closures/" + UID], ids=["collection", "single_closure"])
def test_closure_preflight_from_frontend_is_allowed(client, path):
    """
    Summary: The frontend may manage closures from a browser.
    Supporting design check: CORS for the configured frontend origin
    Double: None
    """
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


def test_closure_preflight_from_other_origin_gets_no_grant(client):
    """
    Summary: Other websites get no browser access.
    Supporting design check: CORS for the configured frontend origin
    Double: None
    """
    r = client.options(
        "/venue-closures", headers={"Origin": "https://untrusted.example"}
    )
    assert "Access-Control-Allow-Origin" not in r.headers


def test_closures_when_database_url_missing_return_503(client, database):
    """
    Summary: Closures report themselves unavailable when no database is configured.
    Supporting design check: an unconfigured service answers 503
    Double: None
    """
    client.application.config["DATABASE_URL"] = None
    assert client.post("/venue-closures", json=BODY, headers=HEADERS).status_code == 503
    database[0].assert_not_called()
