"""# Test scope and acceptance mapping — SCRUM-171 integration

- **SCRUM-171 AC4 backend support:** read-only complete enriched names/list/count, including 101 requests without truncation; confirmation token forwarded and changed-impact conflict preserved.
- **Supporting validation/contracts:** incomplete names/counts/IDs fail closed; malformed inputs make no downstream calls; unknown conflicts are not fabricated as refreshed impact. These mocks do not prove browser reconfirmation or persistence.

## Case/group traceability

- `test_incomplete_preview_never_offered_for_confirmation`: Supporting AC4 complete-preview safeguard — incomplete names/IDs/counts fail closed with no token; no standalone positive list proof.
- `test_confirm_forwards_token_and_preserves_refresh_conflict`: AC4 backend support — token forwarded and changed-impact conflict preserved; redaction supplementary.
- `test_invalid_confirmation_and_preview_inputs`: Supporting AC4 input validation: four independently isolated malformed create/preview inputs, no downstream calls; identical empty preview exercised once.
- `test_unknown_conflict_is_not_fabricated_as_refresh`: Supporting error-contract regression — unknown conflict not fabricated as refreshed impact; no direct AC.
- `test_preview_batches_all_events_without_truncating`: AC4 backend complete-list clause: exact affectedCount and all 101 complete enriched request rows; batching strategy intentionally not asserted.
- `test_preview_enriches_all_requests_through_owning_services`: AC4 backend list clause — event/venue names enriched, venue detail and token returned with read-only calls.

## Existing test contract and detailed cases

SCRUM-171 AC4: complete enriched preview, no writes.

Malformed upstream-response checks support preview integrity/robustness; they
are not standalone proof of the complete user-facing confirmation criterion.
"""

import httpx
import pytest
from app import create_app

UID = "00000000-0000-0000-0000-000000000001"
HEADERS = {"X-Dev-User-Id": UID, "X-Dev-Role": "Venue Staff"}
BODY = dict(
    venueId=UID,
    startDateTime="2099-01-01T10:00:00+08:00",
    endDateTime="2099-01-01T11:00:00+08:00",
    reason="Maintenance",
)
ROW = dict(
    id=UID,
    eventId=UID,
    venueId=UID,
    requestedStartTime=BODY["startDateTime"],
    requestedEndTime=BODY["endDateTime"],
    status="Approved",
)


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("VENUE_CLOSURE_DEV_MODE", "true")
    calls = []

    def reply(method, url, **kw):
        calls.append((method, url, kw))
        if "/venues/" in url:
            body = {"venue": {"id": UID, "name": "Hall"}}
        elif "/events/summaries" in url:
            body = {"events": [{"id": UID, "eventName": "Event"}]}
        else:
            body = dict(
                closure=BODY,
                affectedCount=1,
                affectedRequests=[ROW],
                confirmationToken="signed",
            )
        return httpx.Response(200, json=body, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", reply)
    return create_app().test_client(), calls


@pytest.mark.parametrize(
    "stage,body",
    [
        ("venue", {}),
        ("venue", {"venue": {"id": "wrong", "name": "Hall"}}),
        ("venue", {"venue": {"id": UID, "name": None}}),
        ("preview", {}),
        (
            "preview",
            dict(
                closure=BODY,
                affectedCount=2,
                affectedRequests=[ROW],
                confirmationToken="signed",
            ),
        ),
        (
            "preview",
            dict(
                closure=BODY,
                affectedCount=1,
                affectedRequests=[ROW | {"eventId": None}],
                confirmationToken="signed",
            ),
        ),
        (
            "preview",
            dict(
                closure=BODY,
                affectedCount=2,
                affectedRequests=[ROW, ROW],
                confirmationToken="signed",
            ),
        ),
        ("event", {"events": []}),
        ("event", {"events": [{"id": UID, "eventName": None}]}),
    ],
)
def test_incomplete_preview_never_offered_for_confirmation(
    setup, monkeypatch, stage, body
):
    client, _ = setup
    original = httpx.request

    def reply(method, url, **kw):
        selected = (
            "/venues/" in url
            if stage == "venue"
            else "/preview" in url if stage == "preview" else "/events/summaries" in url
        )
        return (
            httpx.Response(200, json=body, request=httpx.Request(method, url))
            if selected
            else original(method, url, **kw)
        )

    monkeypatch.setattr(httpx, "request", reply)
    response = client.post("/venue-closures/preview", json=BODY, headers=HEADERS)
    assert response.status_code == 502
    assert "confirmationToken" not in response.json


def test_confirm_forwards_token_and_preserves_refresh_conflict(setup, monkeypatch):
    client, calls = setup
    original = httpx.request

    def reply(method, url, **kw):
        if method == "POST":
            calls.append((method, url, kw))
            return httpx.Response(
                409,
                json={"code": "CLOSURE_PREVIEW_CHANGED", "message": "private"},
                request=httpx.Request(method, url),
            )
        return original(method, url, **kw)

    monkeypatch.setattr(httpx, "request", reply)
    body = BODY | dict(confirmed=True, confirmationToken="signed")
    response = client.post("/venue-closures", json=body, headers=HEADERS)
    assert response.status_code == 409
    assert response.json["code"] == "CLOSURE_PREVIEW_CHANGED"
    assert "private" not in response.text
    assert calls[-1][2]["json"] == body


@pytest.mark.parametrize(
    "path,body",
    [
        ("/venue-closures", BODY),
        ("/venue-closures", BODY | {"confirmed": True}),
        ("/venue-closures", BODY | {"confirmed": True, "confirmationToken": 123}),
        ("/venue-closures/preview", {}),
    ],
    ids=["unconfirmed", "missing-token", "invalid-token-type", "invalid-preview"],
)
def test_invalid_confirmation_and_preview_inputs(setup, path, body):
    client, calls = setup
    assert client.post(path, json=body, headers=HEADERS).status_code == 400
    assert not calls


@pytest.mark.parametrize("body", [{"message": "legacy"}, [], None])
def test_unknown_conflict_is_not_fabricated_as_refresh(setup, monkeypatch, body):
    client, _ = setup
    monkeypatch.setattr(
        httpx,
        "request",
        lambda method, url, **kw: httpx.Response(
            409, json=body, request=httpx.Request(method, url)
        ),
    )
    response = client.post("/venue-closures/preview", json=BODY, headers=HEADERS)
    assert response.status_code == 503


def test_preview_batches_all_events_without_truncating(setup, monkeypatch):
    from uuid import UUID

    client, _ = setup
    ids = [str(UUID(int=i + 1)) for i in range(101)]
    rows = [ROW | {"id": id, "eventId": id} for id in ids]
    def reply(method, url, **kw):
        if "/venues/" in url:
            body = {"venue": {"id": UID, "name": "Hall"}}
        elif "/summaries" in url:
            batch = kw["params"]["ids"].split(",")
            body = {"events": [{"id": id, "eventName": id} for id in batch]}
        else:
            body = dict(
                closure=BODY,
                affectedCount=len(rows),
                affectedRequests=rows,
                confirmationToken="signed",
            )
        return httpx.Response(200, json=body, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", reply)
    response = client.post("/venue-closures/preview", json=BODY, headers=HEADERS)
    assert response.status_code == 200
    assert response.json["affectedCount"] == len(rows)
    assert response.json["affectedRequests"] == [
        row | {"eventName": row["eventId"], "venueName": "Hall"} for row in rows
    ]


def test_preview_enriches_all_requests_through_owning_services(setup):
    client, calls = setup
    response = client.post("/venue-closures/preview", json=BODY, headers=HEADERS)
    assert response.status_code == 200
    assert response.json["affectedRequests"] == [
        ROW | {"eventName": "Event", "venueName": "Hall"}
    ]
    assert response.json["venueName"] == "Hall"
    assert response.json["confirmationToken"] == "signed"
    assert all(method == "GET" or url.endswith("/preview") for method, url, _ in calls)
