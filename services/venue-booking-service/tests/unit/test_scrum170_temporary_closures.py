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
- The composite closure routes: the Venue Staff guard, validation, checking the
  venue exists in any status, forwarding staff identity and cursors, and
  mapping downstream errors and malformed responses.
- Assertions are on the status and what is forwarded.

Doubled
-------
- Event, Venue, Venue Availability, User and Safety Check Services: Stub (patch
  / monkeypatch on app.clients, or respx) - canned answers or raised errors;
  calls recorded so tests assert what was (or was not) called.

Not proven
----------
- That the atomic services behave as stubbed (-> their own unit and integration
  tests, and tests/integration/ here with respx).
"""

from unittest.mock import MagicMock
import httpx
import pytest
from app import create_app
from tests.unit.factories import bearer


UID = "00000000-0000-0000-0000-000000000001"
HEADERS = bearer(UID, "Venue Staff")


@pytest.fixture
def client():
    return create_app().test_client()


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
def test_ac1_closure_routes_when_not_venue_staff_are_refused(client, headers, code, method, path):
    """
    Summary: Only signed-in Venue Staff can record or read closures.
    AC1: Given an existing venue, Venue Staff can view an existing venue and
        enter a start date/time, a later end date/time, and a nonblank
        operational reason and save, then the closure is persisted and its
        venue, period, and reason are displayed.
    Double: None
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
def test_ac1_read_closures_with_bad_id_or_filter_returns_400(client, path):
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


BODY = {
    "venueId": UID,
    "startDateTime": "2099-01-01T10:00:00+08:00",
    "endDateTime": "2099-01-01T11:00:00+08:00",
    "reason": "  Maintenance  ",
    "confirmed": True,
    "confirmationToken": "test-token",
}


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
def test_ac2_create_closure_with_invalid_input_returns_400(client, body):
    """
    Summary: A closure without a valid venue, reason, start and later end is refused.
    AC2: Given required information is missing or the end is not later than the
        start, when Venue Staff save, then the system identifies the invalid
        input and does not create a closure.
    Double: None
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
def test_ac2_create_closure_with_unsafe_or_equal_times_returns_400(client, start, end):
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


def test_ac2_create_closure_with_invalid_unicode_reason_returns_400(client):
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


def test_ac2_create_closure_with_nul_in_reason_returns_400(client):
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
def test_ac1_list_closures_with_empty_or_oversized_cursor_returns_400(client, cursor):
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


def test_ac2_create_closure_ending_now_is_refused(client, monkeypatch):
    """
    Summary: A closure that ends right now is refused.
    AC2: (boundary: end = now)
    Double: Fake clock fixed at the exact closure boundary.
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


def test_ac2_create_closure_with_malformed_json_returns_400(client):
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
def downstream(monkeypatch):
    def response(method, url, **kwargs):
        payload = (
            {"venue": {"id": UID, "status": "Unavailable"}}
            if "/venues/" in url
            else {"closure": {"closureId": UID}}
        )
        return httpx.Response(
            200 if method == "GET" else 201,
            json=payload,
            request=httpx.Request(method, url),
        )

    mock = MagicMock(side_effect=response)
    monkeypatch.setattr(httpx, "request", mock)
    return mock


def test_ac1_create_closure_checks_venue_exists_in_any_status(client, downstream):
    """
    Summary: A closure can be recorded for any existing venue, whatever its status.
    AC1: Given an existing venue, Venue Staff can view an existing venue and
        enter a start date/time, a later end date/time, and a nonblank
        operational reason and save, then the closure is persisted and its
        venue, period, and reason are displayed.
    Double: Stub (Venue Service returns the venue)
    """
    # Arrange (Given): client, downstream, from fixtures

    # Act (When)
    r = client.post("/venue-closures", json=BODY, headers=HEADERS)

    # Assert (Then)
    assert r.status_code == 201 and r.json == {"closure": {"closureId": UID}}
    assert downstream.call_count == 2
    first, second = downstream.call_args_list
    assert first.args[0] == "GET" and first.args[1].endswith("/venues/" + UID)
    assert second.args[0] == "POST" and second.args[1].endswith("/venue-closures")
    assert second.kwargs["json"] == {**BODY, "reason": "Maintenance"}
    assert second.kwargs["headers"] == HEADERS
    assert second.kwargs["timeout"] == 5.0


@pytest.mark.parametrize(
    "stage,code,expected",
    [
        (0, 404, 404),
        (0, 500, 503),
        (1, 400, 400),
        (1, 401, 401),
        (1, 403, 403),
        (1, 404, 404),
        (1, 503, 503),
        (1, 500, 503),
    ],
    ids=["0_404_404", "0_500_503", "1_400_400", "1_401_401", "1_403_403", "1_404_404", "1_503_503", "1_500_503"],
)
def test_ac3_closure_routes_map_downstream_errors(client, downstream, stage, code, expected):
    """
    Summary: Downstream refusals and failures are mapped to clear statuses.
    AC3: Given the closure cannot be saved, then the system displays a failure
        message and does not report successful creation.
    Double: Stub (downstream answers the status)
    """
    # Arrange (Given)
    good = httpx.Response(
        200, json={"venue": {"id": UID}}, request=httpx.Request("GET", "http://test")
    )
    bad = httpx.Response(
        code,
        json={"message": "private upstream details"},
        request=httpx.Request("GET", "http://test"),
    )
    downstream.side_effect = [bad] if stage == 0 else [good, bad]

    # Act (When)
    r = client.post("/venue-closures", json=BODY, headers=HEADERS)

    # Assert (Then)
    assert r.status_code == expected and "private" not in r.text
    assert downstream.call_count == stage + 1


@pytest.mark.parametrize(
    "error", [httpx.ConnectError("private"), httpx.ReadTimeout("private")],
    ids=["connect_error", "timeout"],
)
def test_ac3_closure_routes_when_unreachable_return_503(client, downstream, error):
    """
    Summary: An unreachable downstream service is reported without leaking details.
    AC3: Given the closure cannot be saved, then the system displays a failure
        message and does not report successful creation.
    Double: Stub (httpx raises)
    """
    # Arrange (Given)
    downstream.side_effect = error

    # Act + Assert (When / Then)
    assert client.post("/venue-closures", json=BODY, headers=HEADERS).status_code == 503


@pytest.mark.parametrize(
    "payload", [None, [], {}, {"venue": None}, {"venue": {"id": "wrong"}}],
    ids=["none", "empty", "empty_2", "venue_none", "venue_id_wrong"],
)
def test_ac3_create_closure_with_bad_venue_answer_returns_502(client, downstream, payload):
    """
    Summary: A malformed venue answer is a dependency failure.
    AC3: Given the closure cannot be saved, then the system displays a failure
        message and does not report successful creation.
    Double: Stub (Venue Service answers malformed data)
    """
    # Arrange (Given)
    downstream.return_value = httpx.Response(
        200, json=payload, request=httpx.Request("GET", "http://test")
    )
    downstream.side_effect = None

    # Act + Assert (When / Then)
    assert client.post("/venue-closures", json=BODY, headers=HEADERS).status_code == 502
    downstream.assert_called_once()


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/venue-closures/" + UID, {"closure": {"closureId": UID}}),
        ("/venue-closures?venueId=" + UID, {"closures": [], "nextCursor": None}),
    ],
    ids=["single_closure", "venue_list"],
)
def test_ac1_closure_reads_forward_staff_identity(client, downstream, path, payload):
    """
    Summary: Closure reads are made as the signed-in staff member.
    AC1: Given an existing venue, Venue Staff can view an existing venue and
        enter a start date/time, a later end date/time, and a nonblank
        operational reason and save, then the closure is persisted and its
        venue, period, and reason are displayed.
    Double: Stub (respx; headers inspected)
    """
    # Arrange (Given)
    downstream.side_effect = None
    downstream.return_value = httpx.Response(
        200, json=payload, request=httpx.Request("GET", "http://test")
    )

    # Act (When)
    r = client.get(path, headers=HEADERS)

    # Assert (Then)
    assert r.status_code == 200 and r.json == payload
    assert downstream.call_count == 1
    assert downstream.call_args.kwargs["headers"] == HEADERS


@pytest.mark.parametrize(
    "path", ["/venue-closures/" + UID, "/venue-closures?venueId=" + UID],
    ids=["single_closure", "venue_list"],
)
@pytest.mark.parametrize(
    "payload",
    [None, [], {}, {"closure": None}, {"closures": "bad", "nextCursor": None}],
    ids=["none", "empty", "empty_2", "closure_none", "closures_bad_nextcursor_none"],
)
def test_ac3_closure_reads_with_malformed_answer_return_502(client, downstream, path, payload):
    """
    Summary: A malformed closure answer is a dependency failure.
    AC3: Given the closure cannot be saved, then the system displays a failure
        message and does not report successful creation.
    Double: Stub (Venue Availability answers malformed data)
    """
    # Arrange (Given)
    downstream.side_effect = None
    downstream.return_value = httpx.Response(
        200, json=payload, request=httpx.Request("GET", "http://test")
    )

    # Act + Assert (When / Then)
    assert client.get(path, headers=HEADERS).status_code == 502


def test_ac3_create_closure_with_malformed_answer_returns_502(client, downstream):
    """
    Summary: A malformed answer to creating a closure is a dependency failure.
    AC3: Given the closure cannot be saved, then the system displays a failure
        message and does not report successful creation.
    Double: Stub (Venue Availability answers malformed data)
    """
    # Arrange (Given)
    downstream.side_effect = [
        httpx.Response(
            200,
            json={"venue": {"id": UID}},
            request=httpx.Request("GET", "http://test"),
        ),
        httpx.Response(201, json={}, request=httpx.Request("POST", "http://test")),
    ]

    # Act + Assert (When / Then)
    assert client.post("/venue-closures", json=BODY, headers=HEADERS).status_code == 502


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        [UID, "bad", UID],
        [UID, "2099-01-01T00:00:00Z", "bad"],
        ["00000000-0000-0000-0000-000000000002", "2099-01-01T00:00:00Z", UID],
    ],
    ids=["empty", "empty_2", "uid_bad_uid", "uid_2099_01_01t00_00_00z_bad", "00000000_0000_0000_0000_000000000002_2099_01_01t"],
)
def test_ac1_list_closures_with_tampered_cursor_returns_400(client, payload, downstream):
    """
    Summary: A tampered or foreign page cursor is refused.
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
    downstream.assert_not_called()


def test_ac1_list_closures_forwards_cursor_unchanged(client, downstream):
    """
    Summary: The page cursor is forwarded unchanged.
    AC1: Given an existing venue, Venue Staff can view an existing venue and
        enter a start date/time, a later end date/time, and a nonblank
        operational reason and save, then the closure is persisted and its
        venue, period, and reason are displayed.
    Double: Stub (respx; request inspected)
    """
    # Arrange (Given)
    import base64
    import json

    cursor = base64.urlsafe_b64encode(
        json.dumps([UID, "2099-01-01T00:00:00Z", UID]).encode()
    ).decode()
    downstream.side_effect = None
    downstream.return_value = httpx.Response(
        200,
        json={"closures": [], "nextCursor": None},
        request=httpx.Request("GET", "http://test"),
    )
    params = {"venueId": UID, "cursor": cursor, "limit": "100"}

    # Act + Assert (When / Then)
    assert (
        client.get("/venue-closures", query_string=params, headers=HEADERS).status_code
        == 200
    )
    assert downstream.call_args.kwargs["params"] == params


def test_ac1_create_ongoing_closure_is_forwarded(client, downstream):
    """
    Summary: A closure already in progress is forwarded.
    AC1: Given an existing venue, Venue Staff can view an existing venue and
        enter a start date/time, a later end date/time, and a nonblank
        operational reason and save, then the closure is persisted and its
        venue, period, and reason are displayed.
    Double: Stub (respx; request inspected)
    """
    # Arrange (Given): client, downstream, from fixtures

    # Act (When)
    r = client.post(
        "/venue-closures",
        json={**BODY, "startDateTime": "2000-01-01T00:00:00Z"},
        headers=HEADERS,
    )

    # Assert (Then)
    assert r.status_code == 201
    assert (
        downstream.call_args.kwargs["json"]["startDateTime"]
        == "2000-01-01T00:00:00+00:00"
    )


def test_ac3_closure_routes_with_unreadable_answer_return_502(client, downstream):
    """
    Summary: An unreadable downstream answer is a dependency failure.
    AC3: Given the closure cannot be saved, then the system displays a failure
        message and does not report successful creation.
    Double: Stub (respx answers invalid JSON)
    """
    # Arrange (Given)
    downstream.side_effect = None
    downstream.return_value = httpx.Response(
        200, text="not JSON", request=httpx.Request("GET", "http://test")
    )

    # Act + Assert (When / Then)
    assert client.get("/venue-closures/" + UID, headers=HEADERS).status_code == 502


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


@pytest.mark.parametrize("path", ["/venue-closures", "/venue-closures/" + UID], ids=["collection", "single_closure"])
def test_support_closure_preflight_from_frontend_is_allowed(client, path):
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


def test_support_closure_preflight_from_other_origin_gets_no_grant(client):
    """
    Summary: Other websites get no browser access.
    Supporting design check: CORS for the configured frontend origin
    Double: None
    """
    r = client.options(
        "/venue-closures", headers={"Origin": "https://untrusted.example"}
    )
    assert "Access-Control-Allow-Origin" not in r.headers
