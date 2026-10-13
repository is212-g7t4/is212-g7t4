"""SCRUM-170 closure contract (independent of booking timestamp contracts)."""

from unittest.mock import MagicMock
import httpx
import pytest
from app import create_app


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/venue-closures"),
        ("get", "/venue-closures"),
        ("get", "/venue-closures/00000000-0000-0000-0000-000000000001"),
    ],
)
def test_closure_disabled_by_default(monkeypatch, method, path):
    monkeypatch.delenv("VENUE_CLOSURE_DEV_MODE", raising=False)
    client = create_app().test_client()
    assert getattr(client, method)(path).status_code == 503


UID = "00000000-0000-0000-0000-000000000001"
HEADERS = {"X-Dev-User-Id": UID, "X-Dev-Role": "Venue Staff"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("VENUE_CLOSURE_DEV_MODE", "true")
    return create_app().test_client()


@pytest.mark.parametrize(
    "headers,code",
    [
        ({}, 401),
        ({"X-Dev-User-Id": "bad", "X-Dev-Role": "Venue Staff"}, 401),
        ({"X-Dev-User-Id": UID}, 401),
        ({**HEADERS, "X-Dev-Role": "Event Coordinator"}, 403),
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
            "Access-Control-Request-Headers": "X-Dev-User-Id, X-Dev-Role, Content-Type",
        },
    )
    assert r.status_code == 200
    assert r.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert "X-Dev-Role" in r.headers["Access-Control-Allow-Headers"]


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


BODY = {
    "venueId": UID,
    "startDateTime": "2099-01-01T10:00:00+08:00",
    "endDateTime": "2099-01-01T11:00:00+08:00",
    "reason": "  Maintenance  ",
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


def test_composite_create_checks_existing_venue_any_status(client, downstream):
    r = client.post("/venue-closures", json=BODY, headers=HEADERS)
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
)
def test_downstream_errors(client, downstream, stage, code, expected):
    good = httpx.Response(
        200, json={"venue": {"id": UID}}, request=httpx.Request("GET", "http://test")
    )
    bad = httpx.Response(
        code,
        json={"message": "private upstream details"},
        request=httpx.Request("GET", "http://test"),
    )
    downstream.side_effect = [bad] if stage == 0 else [good, bad]
    r = client.post("/venue-closures", json=BODY, headers=HEADERS)
    assert r.status_code == expected and "private" not in r.text
    assert downstream.call_count == stage + 1


@pytest.mark.parametrize(
    "error", [httpx.ConnectError("private"), httpx.ReadTimeout("private")]
)
def test_downstream_transport_failure(client, downstream, error):
    downstream.side_effect = error
    assert client.post("/venue-closures", json=BODY, headers=HEADERS).status_code == 503


@pytest.mark.parametrize(
    "payload", [None, [], {}, {"venue": None}, {"venue": {"id": "wrong"}}]
)
def test_invalid_venue_response(client, downstream, payload):
    downstream.return_value = httpx.Response(
        200, json=payload, request=httpx.Request("GET", "http://test")
    )
    downstream.side_effect = None
    assert client.post("/venue-closures", json=BODY, headers=HEADERS).status_code == 502
    downstream.assert_called_once()


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/venue-closures/" + UID, {"closure": {"closureId": UID}}),
        ("/venue-closures?venueId=" + UID, {"closures": [], "nextCursor": None}),
    ],
)
def test_composite_reads_forward_staff_identity(client, downstream, path, payload):
    downstream.side_effect = None
    downstream.return_value = httpx.Response(
        200, json=payload, request=httpx.Request("GET", "http://test")
    )
    r = client.get(path, headers=HEADERS)
    assert r.status_code == 200 and r.json == payload
    assert downstream.call_count == 1
    assert downstream.call_args.kwargs["headers"] == HEADERS


@pytest.mark.parametrize(
    "path", ["/venue-closures/" + UID, "/venue-closures?venueId=" + UID]
)
@pytest.mark.parametrize(
    "payload",
    [None, [], {}, {"closure": None}, {"closures": "bad", "nextCursor": None}],
)
def test_reject_invalid_closure_response(client, downstream, path, payload):
    downstream.side_effect = None
    downstream.return_value = httpx.Response(
        200, json=payload, request=httpx.Request("GET", "http://test")
    )
    assert client.get(path, headers=HEADERS).status_code == 502


def test_reject_invalid_create_response(client, downstream):
    downstream.side_effect = [
        httpx.Response(
            200,
            json={"venue": {"id": UID}},
            request=httpx.Request("GET", "http://test"),
        ),
        httpx.Response(201, json={}, request=httpx.Request("POST", "http://test")),
    ]
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
)
def test_malformed_or_foreign_cursor(client, payload, downstream):
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
    downstream.assert_not_called()


def test_cursor_forwarded_without_truncation(client, downstream):
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
    assert (
        client.get("/venue-closures", query_string=params, headers=HEADERS).status_code
        == 200
    )
    assert downstream.call_args.kwargs["params"] == params


def test_ongoing_closure_forwarded(client, downstream):
    r = client.post(
        "/venue-closures",
        json={**BODY, "startDateTime": "2000-01-01T00:00:00Z"},
        headers=HEADERS,
    )
    assert r.status_code == 201
    assert (
        downstream.call_args.kwargs["json"]["startDateTime"]
        == "2000-01-01T00:00:00+00:00"
    )


def test_malformed_downstream_json(client, downstream):
    downstream.side_effect = None
    downstream.return_value = httpx.Response(
        200, text="not JSON", request=httpx.Request("GET", "http://test")
    )
    assert client.get("/venue-closures/" + UID, headers=HEADERS).status_code == 502
