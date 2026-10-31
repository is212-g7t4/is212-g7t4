"""
SCRUM-171: Reject Affected Bookings

User Story
----------
As a Venue Staff, I want the system to automatically reject existing venue
requests when I mark a venue as temporarily unavailable, so that I do not have
to manually reject each affected venue request.

Acceptance Criteria
-------------------
AC1: Given a closure is recorded, then requests for the same venue with
     overlapping booking intervals and status Pending, Pending Review, or
     Approved are changed to Rejected.
AC2: Given a request belongs to another venue, does not overlap the closure, or
     is already rejected or cancelled, then that request is not changed by the
     closure.
AC3: Given a request is rejected because of a closure, when its details are
     viewed, then the closure period and operational reason are displayed.
AC4: Given an affected venue request is rejected, the existing event itself or
     other venue requests under that event are not rejected and remain
     unchanged.

Real
----
- The closure preview and confirm routes: enriching every affected request
  through its owning services, refusing an incomplete preview, forwarding the
  confirmation token and keeping refresh conflicts.
- Assertions are on the preview returned and the status.

Doubled
-------
- Event, Venue, Venue Availability, User and Safety Check Services: Stub (patch
  / monkeypatch on app.clients, or respx) - canned answers or raised errors;
  calls recorded so tests assert what was (or was not) called.

Not proven
----------
- That the atomic services behave as stubbed (-> their own unit and integration
  tests, and tests/integration/ here with respx).
- AC2/AC3 persistence and rejection details are owned by Venue Availability;
  this composite covers preview/confirmation and enriched affected-event data.
"""

import httpx
import pytest
from app import create_app
from tests.unit.factories import signed_in, bearer

UID = "00000000-0000-0000-0000-000000000001"
HEADERS = bearer(UID, "Venue Staff")
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
    return signed_in(create_app().test_client()), calls


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
    ids=["venue", "venue_venue_id_wrong_name_hall", "venue_venue_id_uid_name_none", "preview", "preview_dict_closure_body_affectedcount_2_affect", "preview_dict_closure_body_affectedcount_1_affect", "preview_dict_closure_body_affectedcount_2_affect_2", "event_events", "event_events_id_uid_eventname_none"],
)
def test_ac1_preview_closure_with_incomplete_data_is_not_offered(
    setup, monkeypatch, stage, body
):
    """
    Summary: A preview with missing venue, closure or event details is never offered for confirmation.
    AC1: Given a closure is recorded, then requests for the same venue with
        overlapping booking intervals and status Pending, Pending Review, or
        Approved are changed to Rejected.
    Double: Stub (one owner returns incomplete data)
    """
    # Arrange (Given)
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

    # Act (When)
    response = client.post("/venue-closures/preview", json=BODY, headers=HEADERS)

    # Assert (Then)
    assert response.status_code == 502
    assert "confirmationToken" not in response.json


def test_ac1_confirm_closure_forwards_token_and_keeps_refresh_conflict(setup, monkeypatch):
    """
    Summary: Confirming forwards the token, and a changed impact asks to refresh.
    AC1: Given a closure is recorded, then requests for the same venue with
        overlapping booking intervals and status Pending, Pending Review, or
        Approved are changed to Rejected.
    Double: Stub (Venue Availability answers), Mock (request inspected)
    """
    # Arrange (Given)
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

    # Act (When)
    response = client.post("/venue-closures", json=body, headers=HEADERS)

    # Assert (Then)
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
def test_ac1_confirm_or_preview_with_invalid_input_returns_400(setup, path, body):
    """
    Summary: Invalid preview or confirmation input is refused.
    AC1: Given a closure is recorded, then requests for the same venue with
        overlapping booking intervals and status Pending, Pending Review, or
        Approved are changed to Rejected.
    Double: None
    """
    # Arrange (Given)
    client, calls = setup

    # Act + Assert (When / Then)
    assert client.post(path, json=body, headers=HEADERS).status_code == 400
    assert not calls


@pytest.mark.parametrize("body", [{"message": "legacy"}, [], None], ids=["legacy_message", "list_body", "null_body"])
def test_ac1_confirm_closure_with_unknown_conflict_is_not_reported_as_refresh(setup, monkeypatch, body):
    """
    Summary: An unrecognised conflict is not mistaken for "please refresh".
    AC1: Given a closure is recorded, then requests for the same venue with
        overlapping booking intervals and status Pending, Pending Review, or
        Approved are changed to Rejected.
    Double: Stub (Venue Availability answers 409)
    """
    # Arrange (Given)
    client, _ = setup
    monkeypatch.setattr(
        httpx,
        "request",
        lambda method, url, **kw: httpx.Response(
            409, json=body, request=httpx.Request(method, url)
        ),
    )

    # Act (When)
    response = client.post("/venue-closures/preview", json=BODY, headers=HEADERS)

    # Assert (Then)
    assert response.status_code == 503


def test_ac4_preview_closure_reads_all_affected_events_in_batches(setup, monkeypatch):
    """
    Summary: Every affected event is read, in batches, without truncation.
    AC4: Given an affected venue request is rejected, the existing event itself
        or other venue requests under that event are not rejected and remain
        unchanged.
    Double: Stub (Event Service), Mock (batches inspected)
    """
    # Arrange (Given)
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

    # Act (When)
    response = client.post("/venue-closures/preview", json=BODY, headers=HEADERS)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["affectedCount"] == len(rows)
    assert response.json["affectedRequests"] == [
        row | {"eventName": row["eventId"], "venueName": "Hall"} for row in rows
    ]


def test_ac1_ac4_preview_closure_enriches_each_request_from_its_owner(setup):
    """
    Summary: Each affected request is described using its owning services.
    AC1: Given a closure is recorded, then requests for the same venue with
        overlapping booking intervals and status Pending, Pending Review, or
        Approved are changed to Rejected.
    AC4: Given an affected venue request is rejected, the existing event itself
        or other venue requests under that event are not rejected and remain
        unchanged.
    Double: Stub (owners)
    """
    # Arrange (Given)
    client, calls = setup

    # Act (When)
    response = client.post("/venue-closures/preview", json=BODY, headers=HEADERS)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["affectedRequests"] == [
        ROW | {"eventName": "Event", "venueName": "Hall"}
    ]
    assert response.json["venueName"] == "Hall"
    assert response.json["confirmationToken"] == "signed"
    assert all(method == "GET" or url.endswith("/preview") for method, url, _ in calls)
