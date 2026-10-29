"""SCRUM-174 closure-aware search using the complete atomic window contract."""

import httpx
import pytest
from app import create_app
from tests.unit.factories import signed_in
from app import clients

VENUE = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000003"
CLOSURE = "00000000-0000-0000-0000-000000000002"
START = "2090-10-01T09:00:00"
END = "2090-10-01T12:00:00"
CATALOGUE = [dict(id=VENUE, name="Hall", status="Available", capacity=100)]


def closure(**changes):
    return (
        dict(
            closureId=CLOSURE,
            venueId=VENUE,
            startDateTime="2090-10-01T10:00:00+08:00",
            endDateTime="2090-10-01T11:00:00+08:00",
            reason="Roof repair",
        )
        | changes
    )


def search(monkeypatch, payload, **query):
    def get(url, **kwargs):
        # Only the caller's own token travels downstream; no impersonated identity (SCRUM-8).
        assert set(kwargs["headers"]) == {"Authorization"}
        assert not url.endswith("/venue-closures")
        body = {"venues": CATALOGUE} if url.endswith("/venues") else payload
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(clients.httpx, "get", get)
    return (
        signed_in(create_app().test_client())
        .get(
            "/venue-search",
            query_string={"start": START, "end": END, "expectedAttendance": "10"}
            | query,
        )
    )


def test_ac3_partial_closure_excludes_venue(monkeypatch):
    response = search(monkeypatch, {"bookings": [], "closures": [closure()]})
    assert response.status_code == 200
    assert response.json == {"venues": [], "count": 0}
    assert CATALOGUE[0]["status"] == "Available"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"bookings": []},
        {"bookings": [], "closures": None},
        {"bookings": None, "closures": []},
        {"bookings": [], "closures": {}},
        *[
            {"bookings": [], "closures": [bad]}
            for bad in [
                None,
                {},
                closure(closureId="bad"),
                closure(venueId=None),
                closure(startDateTime="bad"),
                closure(endDateTime=None),
                closure(startDateTime="2090-10-01T10:00:00"),
                closure(endDateTime="2090-10-01T09:00:00+08:00"),
                closure(reason=""),
                closure(reason=None),
                closure(reason="bad\x00"),
            ]
        ],
        {"bookings": [], "closures": [closure(), closure()]},
    ],
)
def test_missing_or_malformed_closure_contract_fails_closed(monkeypatch, payload):
    response = search(monkeypatch, payload)
    assert response.status_code == 502
    assert response.json == {"message": "Unable to search venues right now."}


@pytest.mark.parametrize(
    "start,end,excluded",
    [
        ("2090-10-01T09:00:00+08:00", "2090-10-01T12:00:00+08:00", True),
        ("2090-09-30T10:00:00+08:00", "2090-10-02T11:00:00+08:00", True),
        ("2090-10-01T08:00:00+08:00", "2090-10-01T10:00:00+08:00", True),
        ("2090-10-01T11:00:00+08:00", "2090-10-01T13:00:00+08:00", True),
        ("2090-10-01T08:00:00+08:00", "2090-10-01T09:00:00+08:00", False),
        ("2090-10-01T12:00:00+08:00", "2090-10-01T13:00:00+08:00", False),
        ("2090-10-01T03:59:59.999999Z", "2090-10-01T05:00:00Z", True),
        ("2090-10-01T04:00:00Z", "2090-10-01T05:00:00Z", False),
    ],
)
def test_ac3_ac4_half_open_overlap(monkeypatch, start, end, excluded):
    response = search(
        monkeypatch,
        {"bookings": [], "closures": [closure(startDateTime=start, endDateTime=end)]},
    )
    assert response.status_code == 200
    assert response.json["count"] == (0 if excluded else 1)


def test_search_rejects_more_than_atomic_42_day_limit(monkeypatch):
    response = search(
        monkeypatch, {"bookings": [], "closures": []}, end="2090-11-12T09:00:00.000001"
    )
    assert response.status_code == 400
    assert "42 days" in response.json["message"]


def test_search_uses_singapore_now_not_host_local(monkeypatch):
    from datetime import datetime, timezone
    from werkzeug.datastructures import MultiDict
    from app.search import validate_search, SearchError

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2090, 10, 1, 2, tzinfo=timezone.utc)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr("app.search.datetime", Clock)
    with pytest.raises(SearchError, match="future"):
        validate_search(MultiDict(dict(start=START, end=END, expectedAttendance="10")))


@pytest.mark.parametrize(
    "status,count,label",
    [
        ("Approved", 0, None),
        ("On Hold", 0, None),
        ("Pending", 1, "Pending request"),
        ("Pending Review", 1, "Pending request"),
    ],
)
def test_ac4_outside_closure_retains_booking_rules(monkeypatch, status, count, label):
    response = search(
        monkeypatch,
        {
            "bookings": [{"venueId": VENUE, "status": status}],
            "closures": [
                closure(
                    startDateTime="2090-10-01T12:00:00+08:00",
                    endDateTime="2090-10-01T13:00:00+08:00",
                )
            ],
        },
    )
    assert response.status_code == 200
    assert response.json["count"] == count
    if count:
        assert response.json["venues"][0]["availability"] == label


def test_other_venue_closure_does_not_hide_candidate(monkeypatch):
    response = search(
        monkeypatch, {"bookings": [], "closures": [closure(venueId=OTHER)]}
    )
    assert response.status_code == 200
    assert response.json["count"] == 1


def test_exact_42_day_search_allowed(monkeypatch):
    response = search(
        monkeypatch, {"bookings": [], "closures": []}, end="2090-11-12T09:00:00"
    )
    assert response.status_code == 200


def test_full_closure_window_is_not_first_history_page(monkeypatch):
    from uuid import UUID

    closures = [
        closure(closureId=str(UUID(int=100 + i)), venueId=OTHER) for i in range(105)
    ] + [closure()]
    assert (
        search(monkeypatch, {"bookings": [], "closures": closures}).json["count"] == 0
    )


@pytest.mark.parametrize("status", ["Under Maintenance", "Booked"])
def test_ac4_outside_closure_retains_catalogue_status(monkeypatch, status):
    original = CATALOGUE[0]["status"]
    try:
        CATALOGUE[0]["status"] = status
        response = search(
            monkeypatch,
            {
                "bookings": [],
                "closures": [
                    closure(
                        startDateTime="2090-10-01T12:00:00+08:00",
                        endDateTime="2090-10-01T13:00:00+08:00",
                    )
                ],
            },
        )
        assert response.status_code == 200
        assert response.json["count"] == 0
        assert CATALOGUE[0]["status"] == status
    finally:
        CATALOGUE[0]["status"] = original


def test_even_nonoverlapping_malformed_closure_fails_closed(monkeypatch):
    response = search(
        monkeypatch,
        {
            "bookings": [],
            "closures": [
                closure(
                    startDateTime="2090-10-02T10:00:00+08:00",
                    endDateTime="2090-10-02T11:00:00+08:00",
                    reason=None,
                )
            ],
        },
    )
    assert response.status_code == 502
