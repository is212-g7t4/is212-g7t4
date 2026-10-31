"""
SCRUM-174: View Dated Closures in Venue Search & Calendar

User Story
----------
As an Event Coordinator, I want venue search and the availability calendar to
reflect dated closures, so that I can identify usable venues and understand
when a closed venue becomes eligible again and do not attempt to book
unavailable venues for my event duration.

Acceptance Criteria
-------------------
AC1: Given an internal user views the availability calendar, any periods marked
     as closed must be visually indicated and clearly distinguished from
     regular event bookings or open slots.
AC2: Given a user views the details of a closed period on the calendar, the
     system must display the specific start/end dates, times, and the
     operational reason for the closure.
AC3: Given an Event Coordinator searches for available venues, if their
     specified date and time overlap (even partially) with a venue's recorded
     closure, that venue must be automatically excluded from the search
     results.
AC4: Given an Event Coordinator searches for venues outside of a recorded
     closure period, the venue must be shown with its standard operating
     conditions, capacity, and existing bookings.

Real
----
- GET /venue-search with closures: partial overlap excludes a venue, malformed
  closure data fails closed, the 42-day limit, Singapore now, and
  outside-closure venues keep their booking and catalogue rules.
- Assertions are on the venues returned and the status.

Doubled
-------
- Event, Venue, Venue Availability, User and Safety Check Services: Stub (patch
  / monkeypatch on app.clients, or respx) - canned answers or raised errors;
  calls recorded so tests assert what was (or was not) called.

Not proven
----------
- That the atomic services behave as stubbed (-> their own unit and integration
  tests, and tests/integration/ here with respx).
- AC1/AC2 calendar display and closure detail presentation are owned by Venue
  Availability and the frontend; this composite owns AC3/AC4 search exclusion.
"""

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


def test_ac3_search_with_partially_overlapping_closure_excludes_venue(monkeypatch):
    """
    Summary: A venue closed for any part of the requested time is left out.
    AC3: Given an Event Coordinator searches for available venues, if their
        specified date and time overlap (even partially) with a venue's
        recorded closure, that venue must be automatically excluded from the
        search results.
    Double: Stub (window with a closure)
    """
    # Arrange (Given): monkeypatch, from fixtures

    # Act (When)
    response = search(monkeypatch, {"bookings": [], "closures": [closure()]})

    # Assert (Then)
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
def test_ac3_search_with_malformed_closure_data_fails_closed(monkeypatch, payload):
    """
    Summary: Missing or malformed closure data fails the search rather than showing venues as free.
    AC3: Given an Event Coordinator searches for available venues, if their
        specified date and time overlap (even partially) with a venue's
        recorded closure, that venue must be automatically excluded from the
        search results.
    Double: Stub (window answers malformed data)
    """
    # Arrange (Given): monkeypatch, payload, from fixtures

    # Act (When)
    response = search(monkeypatch, payload)

    # Assert (Then)
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
    ids=["2090_10_01t09_00_00_08_00_2090_10_01t12_00_00_08", "2090_09_30t10_00_00_08_00_2090_10_02t11_00_00_08", "2090_10_01t08_00_00_08_00_2090_10_01t10_00_00_08", "2090_10_01t11_00_00_08_00_2090_10_01t13_00_00_08", "2090_10_01t08_00_00_08_00_2090_10_01t09_00_00_08", "2090_10_01t12_00_00_08_00_2090_10_01t13_00_00_08", "2090_10_01t03_59_59_999999z_2090_10_01t05_00_00z", "2090_10_01t04_00_00z_2090_10_01t05_00_00z_false"],
)
def test_ac3_ac4_search_excludes_venue_only_when_closure_really_overlaps(monkeypatch, start, end, excluded):
    """
    Summary: A closure only touching the requested time does not hide the venue.
    AC3: Given an Event Coordinator searches for available venues, if their
        specified date and time overlap (even partially) with a venue's
        recorded closure, that venue must be automatically excluded from the
        search results.
    AC4: Given an Event Coordinator searches for venues outside of a recorded
        closure period, the venue must be shown with its standard operating
        conditions, capacity, and existing bookings.
    Double: Stub (window with a closure)
    """
    # Arrange (Given): monkeypatch, start, end, excluded, from fixtures

    # Act (When)
    response = search(
        monkeypatch,
        {"bookings": [], "closures": [closure(startDateTime=start, endDateTime=end)]},
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["count"] == (0 if excluded else 1)


def test_ac3_search_longer_than_42_days_returns_400(monkeypatch):
    """
    Summary: A search longer than 42 days is refused.
    AC3: Given an Event Coordinator searches for available venues, if their
        specified date and time overlap (even partially) with a venue's
        recorded closure, that venue must be automatically excluded from the
        search results.
    Double: Stub (the search helper replaces both downstream HTTP reads).
    """
    # Arrange (Given): monkeypatch, from fixtures

    # Act (When)
    response = search(
        monkeypatch, {"bookings": [], "closures": []}, end="2090-11-12T09:00:00.000001"
    )

    # Assert (Then)
    assert response.status_code == 400
    assert "42 days" in response.json["message"]


def test_ac3_search_judges_past_in_singapore_time(monkeypatch):
    """
    Summary: "In the past" is judged in Singapore time, whatever the server's zone.
    AC3: Given an Event Coordinator searches for available venues, if their
        specified date and time overlap (even partially) with a venue's
        recorded closure, that venue must be automatically excluded from the
        search results.
    Double: Stub (clock)
    """
    # Arrange (Given)
    from datetime import datetime, timezone
    from werkzeug.datastructures import MultiDict
    from app.search import validate_search, SearchError

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2090, 10, 1, 2, tzinfo=timezone.utc)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr("app.search.datetime", Clock)

    # Act + Assert (When / Then)
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
    ids=["approved_0_none", "on_hold_0_none", "pending_1_pending_request", "pending_review_1_pending_request"],
)
def test_ac4_search_outside_closure_keeps_booking_rules(monkeypatch, status, count, label):
    """
    Summary: Outside a closure, bookings still decide availability as before.
    AC4: Given an Event Coordinator searches for venues outside of a recorded
        closure period, the venue must be shown with its standard operating
        conditions, capacity, and existing bookings.
    Double: Stub (window with a booking)
    """
    # Arrange (Given): monkeypatch, status, count, label, from fixtures

    # Act (When)
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

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["count"] == count
    if count:
        assert response.json["venues"][0]["availability"] == label


def test_ac4_search_with_other_venues_closure_keeps_venue(monkeypatch):
    """
    Summary: Another venue's closure does not hide this venue.
    AC4: Given an Event Coordinator searches for venues outside of a recorded
        closure period, the venue must be shown with its standard operating
        conditions, capacity, and existing bookings.
    Double: Stub (window with another venue's closure)
    """
    # Arrange (Given): monkeypatch, from fixtures

    # Act (When)
    response = search(
        monkeypatch, {"bookings": [], "closures": [closure(venueId=OTHER)]}
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["count"] == 1


def test_ac3_search_of_exactly_42_days_is_allowed(monkeypatch):
    """
    Summary: A search of exactly 42 days is allowed.
    AC3: (boundary: 42 days)
    Double: Stub (window)
    """
    # Arrange (Given): monkeypatch, from fixtures

    # Act (When)
    response = search(
        monkeypatch, {"bookings": [], "closures": []}, end="2090-11-12T09:00:00"
    )

    # Assert (Then)
    assert response.status_code == 200


def test_ac3_search_reads_every_closure_in_window(monkeypatch):
    """
    Summary: Every closure in the window is used, not just the first page.
    AC3: Given an Event Coordinator searches for available venues, if their
        specified date and time overlap (even partially) with a venue's
        recorded closure, that venue must be automatically excluded from the
        search results.
    Double: Stub (window), Mock (read inspected)
    """
    # Arrange (Given)
    from uuid import UUID

    # Act (When)
    closures = [
        closure(closureId=str(UUID(int=100 + i)), venueId=OTHER) for i in range(105)
    ] + [closure()]

    # Assert (Then)
    assert (
        search(monkeypatch, {"bookings": [], "closures": closures}).json["count"] == 0
    )


@pytest.mark.parametrize("status", ["Under Maintenance", "Booked"], ids=["under_maintenance", "booked"])
def test_ac4_search_outside_closure_keeps_catalogue_status_rules(monkeypatch, status):
    """
    Summary: Outside a closure, venues under maintenance or booked are still hidden.
    AC4: Given an Event Coordinator searches for venues outside of a recorded
        closure period, the venue must be shown with its standard operating
        conditions, capacity, and existing bookings.
    Double: Stub (catalogue status)
    """
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


def test_ac3_search_with_malformed_unrelated_closure_fails_closed(monkeypatch):
    """
    Summary: A malformed closure fails the search even if it would not overlap.
    AC3: Given an Event Coordinator searches for available venues, if their
        specified date and time overlap (even partially) with a venue's
        recorded closure, that venue must be automatically excluded from the
        search results.
    Double: Stub (window answers malformed data)
    """
    # Arrange (Given): monkeypatch, from fixtures

    # Act (When)
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

    # Assert (Then)
    assert response.status_code == 502
