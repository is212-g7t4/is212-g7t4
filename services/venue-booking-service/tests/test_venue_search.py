"""SCRUM-26 Venue Search and Filtering — GET /venue-search on the composite.

AC1 the criteria, AC2 the required-field message, AC3 results matching all
active criteria within 3 seconds, AC4 availability shown per venue, AC5 the
empty result. AC6 (Clear all) is a frontend concern, covered by
docs/test-scripts/scrum-26-venue-search-and-filtering.md.

Both downstream calls are mocked; no live service or database is reached.
"""
import time
from datetime import datetime, timedelta
from unittest.mock import patch
from urllib.parse import urlencode

import httpx
import pytest

from app import create_app

TOMORROW = (datetime.now() + timedelta(days=1)).date().isoformat()
YESTERDAY = (datetime.now() - timedelta(days=1)).date().isoformat()
START = f"{TOMORROW}T09:00:00"
END = f"{TOMORROW}T12:00:00"

BALLROOM = {
    "id": "ven-1",
    "name": "Grand Ballroom",
    "location": "Level 3, Main Tower",
    "capacity": 500,
    "facilities": ["stage", "wifi"],
    "accessibility": "Wheelchair accessible, elevator access",
    "supportedLayouts": ["theatre", "banquet"],
    "status": "Available",
}
ROOFTOP = {
    "id": "ven-2",
    "name": "Rooftop Garden",
    "location": "Level 12, Main Tower",
    "capacity": 150,
    "facilities": ["outdoor", "wifi"],
    "accessibility": "Elevator access, no stairs",
    "supportedLayouts": ["standing", "banquet"],
    "status": "Available",
}
AUDITORIUM = {**BALLROOM, "id": "ven-3", "name": "Auditorium", "status": "Under Maintenance"}
STATIC_BOOKED = {**BALLROOM, "id": "ven-4", "name": "Conference Room A", "status": "Booked"}


def booking(venue_id, status):
    return {
        "id": f"booking-{venue_id}-{status}",
        "eventId": "evt-1",
        "venueId": venue_id,
        "requestedStartTime": START,
        "requestedEndTime": END,
        "status": status,
        "requestedBy": "coord-1",
        "reviewedBy": None,
    }


def search(client, **overrides):
    params = {"start": START, "end": END, "expectedAttendance": "120"}
    params.update(overrides)
    query = urlencode(
        [(k, v) for k, values in params.items() for v in (values if isinstance(values, list) else [values])]
    )
    return client.get(f"/venue-search?{query}")


@pytest.fixture
def client():
    return create_app().test_client()


# --- AC2: required criteria -------------------------------------------------


def test_ac2_missing_required_fields_returns_400_listing_them(client):
    """AC2: an empty search names every field the coordinator still has to fill."""
    response = client.get("/venue-search")

    assert response.status_code == 400
    assert response.json["missing"] == [
        "Date and start time",
        "End time",
        "Expected attendance",
    ]
    assert response.json["message"].startswith("Please fill in the required fields:")


@pytest.mark.parametrize(
    ("omitted", "label"),
    [
        ("start", "Date and start time"),
        ("end", "End time"),
        ("expectedAttendance", "Expected attendance"),
    ],
)
def test_ac2_each_required_field_checked(client, omitted, label):
    """AC2: only the fields actually missing are listed back."""
    response = search(client, **{omitted: ""})

    assert response.status_code == 400
    assert response.json["missing"] == [label]


@patch("app.routes.search_venues")
def test_ac2_invalid_search_calls_no_downstream_service(mock_search_venues, client):
    """AC2: a search that can't run costs nothing downstream."""
    client.get("/venue-search")

    mock_search_venues.assert_not_called()


@pytest.mark.parametrize("value", ["not-a-date", f"{TOMORROW} 09:00", ""])
def test_malformed_start_returns_400(client, value):
    """Failure: a date and time the service can't read is refused."""
    response = search(client, start=value)

    assert response.status_code == 400


def test_timezone_aware_start_returns_400(client):
    """Failure: VenueBooking is naive, so an offset would be compared wrongly."""
    assert search(client, start=f"{TOMORROW}T09:00:00+08:00").status_code == 400


@pytest.mark.parametrize("end", [START, f"{TOMORROW}T08:00:00"])
def test_end_before_start_returns_400(client, end):
    """Failure boundary: a window must have length; equal times are refused."""
    response = search(client, end=end)

    assert response.status_code == 400
    assert response.json["message"] == "The end time must be after the start time."


def test_start_in_past_returns_400(client):
    """Failure: a venue cannot be booked for a time that has already passed."""
    response = search(client, start=f"{YESTERDAY}T09:00:00", end=f"{YESTERDAY}T12:00:00")

    assert response.status_code == 400
    assert response.json["message"] == "Choose a date and time in the future."


@pytest.mark.parametrize("value", ["0", "-5", "abc", "2.5"])
def test_invalid_attendance_returns_400(client, value):
    """Failure boundary: attendance must be a whole number of at least 1."""
    response = search(client, expectedAttendance=value)

    assert response.status_code == 400
    assert "Expected attendance" in response.json["message"]


def test_invalid_min_capacity_returns_400(client):
    """Failure: the optional capacity floor is validated the same way."""
    assert search(client, minCapacity="0").status_code == 400


# --- AC3: results matching all active criteria ------------------------------


@patch("app.routes.get_bookings_between")
@patch("app.routes.search_venues")
def test_ac3_forwards_optional_filters_to_venue_service(
    mock_search_venues, mock_get_bookings, client
):
    """AC3: every optional criterion reaches Venue Service unchanged."""
    mock_search_venues.return_value = []
    mock_get_bookings.return_value = []

    search(
        client,
        location="Main Tower",
        layout="banquet",
        facility=["wifi", "stage"],
        accessibility=["lift"],
    )

    assert mock_search_venues.call_args.args[0] == [
        ("minCapacity", "120"),
        ("location", "Main Tower"),
        ("layout", "banquet"),
        ("facility", "wifi"),
        ("facility", "stage"),
        ("accessibility", "lift"),
    ]
    mock_get_bookings.assert_called_once_with(START, END)


@patch("app.routes.get_bookings_between")
@patch("app.routes.search_venues")
def test_ac3_stricter_min_capacity_wins(mock_search_venues, mock_get_bookings, client):
    """AC3: attendance and minCapacity are both floors, so the larger applies."""
    mock_search_venues.return_value = []
    mock_get_bookings.return_value = []

    search(client, expectedAttendance="50", minCapacity="200")

    assert ("minCapacity", "200") in mock_search_venues.call_args.args[0]


@patch("app.routes.get_bookings_between")
@patch("app.routes.search_venues")
def test_ac3_approved_overlap_hides_venue(mock_search_venues, mock_get_bookings, client):
    """AC3 conflict: an approved booking means the venue is not free."""
    mock_search_venues.return_value = [BALLROOM, ROOFTOP]
    mock_get_bookings.return_value = [booking("ven-1", "Approved")]

    response = search(client)

    assert [v["name"] for v in response.json["venues"]] == ["Rooftop Garden"]


@pytest.mark.parametrize("status", ["Pending", "Pending Review"])
@patch("app.routes.get_bookings_between")
@patch("app.routes.search_venues")
def test_ac4_pending_overlap_kept_with_pending_badge(
    mock_search_venues, mock_get_bookings, client, status
):
    """AC4 conflict: the venue is still free, but a request is waiting on it.

    The live data says "Pending" and the service writes "Pending Review";
    both must behave the same.
    """
    mock_search_venues.return_value = [BALLROOM]
    mock_get_bookings.return_value = [booking("ven-1", status)]

    response = search(client)

    assert response.json["venues"][0]["availability"] == "Pending request"


@patch("app.routes.get_bookings_between")
@patch("app.routes.search_venues")
def test_ac3_rejected_booking_ignored(mock_search_venues, mock_get_bookings, client):
    """AC3: Venue Availability already drops Rejected bookings, so none arrive."""
    mock_search_venues.return_value = [BALLROOM]
    mock_get_bookings.return_value = []

    response = search(client)

    assert response.json["venues"][0]["availability"] == "Available"


@pytest.mark.parametrize("venue", [AUDITORIUM, STATIC_BOOKED])
@patch("app.routes.get_bookings_between")
@patch("app.routes.search_venues")
def test_ac3_non_operational_venue_hidden(
    mock_search_venues, mock_get_bookings, client, venue
):
    """AC3: Under Maintenance and the static Booked status both drop out."""
    mock_search_venues.return_value = [venue]
    mock_get_bookings.return_value = []

    assert search(client).json == {"venues": [], "count": 0}


@patch("app.routes.get_bookings_between")
@patch("app.routes.search_venues")
def test_ac3_bookings_for_other_venues_do_not_block(
    mock_search_venues, mock_get_bookings, client
):
    """AC3: the window query covers every venue, so rows are matched by id."""
    mock_search_venues.return_value = [BALLROOM]
    mock_get_bookings.return_value = [booking("ven-9", "Approved")]

    assert search(client).json["venues"][0]["availability"] == "Available"


@patch("app.routes.get_bookings_between")
@patch("app.routes.search_venues")
def test_ac3_downstream_calls_run_in_parallel(
    mock_search_venues, mock_get_bookings, client
):
    """AC3: two 1-second calls must cost about 1 second, not 2, to fit 3 s."""

    def slow(*args, **kwargs):
        time.sleep(1)
        return []

    mock_search_venues.side_effect = slow
    mock_get_bookings.side_effect = slow

    started = time.monotonic()
    response = search(client)
    elapsed = time.monotonic() - started

    assert response.status_code == 200
    assert elapsed < 1.8


# --- AC4 and AC5: what the coordinator sees ---------------------------------


@patch("app.routes.get_bookings_between")
@patch("app.routes.search_venues")
def test_ac4_result_has_all_display_fields(mock_search_venues, mock_get_bookings, client):
    """AC4: each result carries everything the card shows."""
    mock_search_venues.return_value = [ROOFTOP]
    mock_get_bookings.return_value = []

    venue = search(client).json["venues"][0]

    assert venue == {**ROOFTOP, "availability": "Available"}


@patch("app.routes.get_bookings_between")
@patch("app.routes.search_venues")
def test_ac4_available_sorted_before_pending(mock_search_venues, mock_get_bookings, client):
    """AC4: fully free venues come first, then by name."""
    mock_search_venues.return_value = [BALLROOM, ROOFTOP]
    mock_get_bookings.return_value = [booking("ven-1", "Pending")]

    response = search(client)

    assert [(v["name"], v["availability"]) for v in response.json["venues"]] == [
        ("Rooftop Garden", "Available"),
        ("Grand Ballroom", "Pending request"),
    ]


@patch("app.routes.get_bookings_between")
@patch("app.routes.search_venues")
def test_ac5_no_matches_returns_empty_list(mock_search_venues, mock_get_bookings, client):
    """AC5: no venues available is a normal answer, not an error."""
    mock_search_venues.return_value = []
    mock_get_bookings.return_value = []

    response = search(client)

    assert response.status_code == 200
    assert response.json == {"venues": [], "count": 0}


# --- Failure handling -------------------------------------------------------


@patch("app.routes.get_bookings_between")
@patch("app.routes.search_venues")
def test_downstream_timeout_returns_504(mock_search_venues, mock_get_bookings, client):
    """Failure: a downstream service slower than the budget is a 504, not a hang."""
    mock_search_venues.side_effect = httpx.TimeoutException("too slow")
    mock_get_bookings.return_value = []

    response = search(client)

    assert response.status_code == 504
    assert response.json["message"] == "Venue search took too long. Please try again."


@patch("app.routes.get_bookings_between")
@patch("app.routes.search_venues")
def test_downstream_error_returns_502(mock_search_venues, mock_get_bookings, client):
    """Failure: a downstream 503 surfaces as 502 with no internals leaked."""
    mock_search_venues.side_effect = httpx.HTTPStatusError(
        "503 Service Unavailable for http://venue-service:5000/venues",
        request=httpx.Request("GET", "http://venue-service:5000/venues"),
        response=httpx.Response(503),
    )
    mock_get_bookings.return_value = []

    response = search(client)

    assert response.status_code == 502
    assert response.json["message"] == "Unable to search venues right now."
    assert "venue-service" not in response.json["message"]


@patch("app.routes.get_bookings_between")
@patch("app.routes.search_venues")
def test_availability_outage_also_returns_502(
    mock_search_venues, mock_get_bookings, client
):
    """Failure: either downstream failing is enough to fail the search."""
    mock_search_venues.return_value = [BALLROOM]
    mock_get_bookings.side_effect = httpx.ConnectError("connection refused")

    assert search(client).status_code == 502


def test_search_is_read_only(client):
    """The search creates nothing, so it answers GET and nothing else."""
    for method in (client.post, client.patch, client.put, client.delete):
        assert method("/venue-search").status_code == 405


def test_cors_allows_the_ui_origin_by_default():
    """The UI calls this service directly, so its dev origin must be allowed."""
    client = create_app().test_client()

    response = client.get("/venue-search", headers={"Origin": "http://localhost:5174"})

    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert "GET" in response.headers["Access-Control-Allow-Methods"]
    assert (
        "Access-Control-Allow-Origin"
        not in client.get("/venue-search", headers={"Origin": "https://other.example"}).headers
    )


# --- The client wrappers themselves -----------------------------------------
# Everything above mocks these out, so they get their own tests: the query
# they build is the contract with each atomic.


def test_search_venues_sends_repeatable_filters_and_a_timeout(monkeypatch):
    """Repeated facility/accessibility pairs must survive as separate parameters."""
    from app import clients

    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured.update(url=url, params=params, timeout=timeout)
        return httpx.Response(
            200, json={"venues": [BALLROOM]}, request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(clients.httpx, "get", fake_get)

    venues = clients.search_venues([("minCapacity", "120"), ("facility", "wifi"), ("facility", "stage")])

    assert venues == [BALLROOM]
    assert captured["url"].endswith("/venues")
    assert captured["params"] == [("minCapacity", "120"), ("facility", "wifi"), ("facility", "stage")]
    assert captured["timeout"] == clients.SEARCH_TIMEOUT


def test_get_bookings_between_uses_the_all_venue_window_read(monkeypatch):
    """SCRUM-25 made GET /venue-bookings single-venue and DEV-gated, so the
    search uses the window read instead — all venues, one call, no headers."""
    from app import clients

    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured.update(url=url, params=params, timeout=timeout)
        return httpx.Response(
            200,
            json={"bookings": [booking("ven-1", "Approved")]},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(clients.httpx, "get", fake_get)

    bookings = clients.get_bookings_between(START, END)

    assert [b["venueId"] for b in bookings] == ["ven-1"]
    assert captured["url"].endswith("/venue-bookings/window")
    assert captured["params"] == {"dateFrom": START, "dateTo": END}
    # The window read covers every venue; the calendar read would need a
    # venueId and the DEV-mode identity headers.
    assert "venueId" not in captured["params"]
    assert captured["timeout"] == clients.SEARCH_TIMEOUT


@pytest.mark.parametrize(
    "wrapper", ["search_venues", "get_bookings_between"]
)
def test_search_wrappers_raise_on_a_downstream_error(monkeypatch, wrapper):
    """A downstream failure must reach the route so it can answer 502."""
    from app import clients

    monkeypatch.setattr(
        clients.httpx,
        "get",
        lambda url, **kwargs: httpx.Response(
            503, request=httpx.Request("GET", url)
        ),
    )

    with pytest.raises(httpx.HTTPStatusError):
        getattr(clients, wrapper)([]) if wrapper == "search_venues" else clients.get_bookings_between(START, END)
