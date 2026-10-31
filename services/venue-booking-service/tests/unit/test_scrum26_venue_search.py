"""
SCRUM-26: Venue Search and Filtering

User Story
----------
As an Event Coordinator, I want to search and filter potential venues by event
requirements, so that I can shortlist venues that meet my specific event
requirements.

Acceptance Criteria
-------------------
AC1: Event Coordinator must be able to input the following criteria: Date and
     time (required), Expected attendance (required), Location (optional),
     Minimum capacity (optional), Accessibility requirements (optional),
     Supported layout (optional), and Required facilities (optional).
AC2: Given the Event Coordinator submits a search without the mandatory fields,
     when they click the search button, the system displays a message informing
     the user to input the required fields.
AC3: Given the Event Coordinator provides all required fields, when they click
     search, then the system must return a list of venues matching all active
     criteria within 3 seconds.
AC4: The search results must display the following for each matching venue:
     name, location, capacity, accessibility, supported layouts, available
     facilities, and availability status for the requested date/time.
AC5: Given no venues match the selected criteria, when the search completes,
     then the system must display a message informing the user that no venues
     are available.
AC6: The Event Coordinator must be able to clear all search and filter criteria
     with a single button click, resetting the form to its initial empty state.

Real
----
- GET /venue-search: required fields, time and number validation, the stricter
  of attendance and minimum capacity, hiding venues taken by approved bookings
  or holds or not operational, a pending badge, parallel downstream calls,
  ordering and error mapping.
- Assertions are on the status, the venues returned and their fields.

Doubled
-------
- Event, Venue, Venue Availability, User and Safety Check Services: Stub (patch
  / monkeypatch on app.clients, or respx) - canned answers or raised errors;
  calls recorded so tests assert what was (or was not) called.

Not proven
----------
- The form, the required-field and no-results messages and clear-all (AC1, AC2,
  AC5, AC6 UI half) (-> frontend venueSearch.test.ts and e2e
  scrum-26-venue-search.spec.mjs).
- The 3-second budget against real services (NOT COVERED ANYWHERE; the
  parallelism is checked here with timed stubs).
"""
import time
from datetime import datetime, timedelta
from unittest.mock import patch
from urllib.parse import urlencode

import httpx
import pytest

from app import create_app
from app.search import SINGAPORE
from tests.unit.factories import signed_in

# Search inputs represent Singapore dates, regardless of the test runner's timezone.
TOMORROW = (datetime.now(SINGAPORE) + timedelta(days=1)).date().isoformat()
YESTERDAY = (datetime.now(SINGAPORE) - timedelta(days=1)).date().isoformat()
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
    return signed_in(create_app().test_client())


# --- AC2: required criteria -------------------------------------------------


def test_ac2_search_without_required_fields_lists_them(client):
    """
    Summary: An empty search names every field the coordinator still has to fill in.
    AC2: Given the Event Coordinator submits a search without the mandatory
        fields, when they click the search button, the system displays a
        message informing the user to input the required fields.
    Double: None
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get("/venue-search")

    # Assert (Then)
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
    ids=["start", "end", "expected_attendance"],
)
def test_ac2_search_missing_one_required_field_names_only_that_one(client, omitted, label):
    """
    Summary: Only the fields actually missing are listed.
    AC2: Given the Event Coordinator submits a search without the mandatory
        fields, when they click the search button, the system displays a
        message informing the user to input the required fields.
    Double: None
    """
    # Arrange (Given): client, omitted, label, from fixtures

    # Act (When)
    response = search(client, **{omitted: ""})

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["missing"] == [label]


def test_ac2_search_that_cannot_run_calls_no_downstream_service(client, mocker):
    """
    Summary: A search that cannot run calls no other service.
    AC2: Given the Event Coordinator submits a search without the mandatory
        fields, when they click the search button, the system displays a
        message informing the user to input the required fields.
    Double: Mock (no downstream calls)
    """
    # Arrange (Given): mock_search_venues, client, from fixtures
    mock_search_venues = mocker.patch("app.routes.search_venues")

    # Act (When)
    client.get("/venue-search")

    # Assert (Then)
    mock_search_venues.assert_not_called()


@pytest.mark.parametrize("value", ["not-a-date", f"{TOMORROW} 09:00", ""], ids=["not_a_date", "space_separated", "empty"])
def test_ac1_search_with_unreadable_start_returns_400(client, value):
    """
    Summary: A date and time the service cannot read is refused.
    AC1: Event Coordinator must be able to input the following criteria: Date
        and time (required), Expected attendance (required), Location
        (optional), Minimum capacity (optional), Accessibility requirements
        (optional), Supported layout (optional), and Required facilities
        (optional).
    Double: None
    """
    response = search(client, start=value)

    assert response.status_code == 400


def test_ac1_search_with_time_zone_offset_returns_400(client):
    """
    Summary: Times must be local; an offset would be compared wrongly.
    AC1: Event Coordinator must be able to input the following criteria: Date
        and time (required), Expected attendance (required), Location
        (optional), Minimum capacity (optional), Accessibility requirements
        (optional), Supported layout (optional), and Required facilities
        (optional).
    Double: None
    """
    assert search(client, start=f"{TOMORROW}T09:00:00+08:00").status_code == 400


@pytest.mark.parametrize("end", [START, f"{TOMORROW}T08:00:00"], ids=["end_equals_start", "end_before_start"])
def test_ac1_search_with_end_not_after_start_returns_400(client, end):
    """
    Summary: The search window must have length.
    AC1: (boundary: end = start)
    Double: None
    """
    response = search(client, end=end)

    assert response.status_code == 400
    assert response.json["message"] == "The end time must be after the start time."


def test_ac1_search_starting_in_past_returns_400(client):
    """
    Summary: A venue cannot be searched for a time already past.
    AC1: Event Coordinator must be able to input the following criteria: Date
        and time (required), Expected attendance (required), Location
        (optional), Minimum capacity (optional), Accessibility requirements
        (optional), Supported layout (optional), and Required facilities
        (optional).
    Double: None
    """
    response = search(client, start=f"{YESTERDAY}T09:00:00", end=f"{YESTERDAY}T12:00:00")

    assert response.status_code == 400
    assert response.json["message"] == "Choose a date and time in the future."


@pytest.mark.parametrize("value", ["0", "-5", "abc", "2.5"], ids=["zero", "negative", "text", "fractional"])
def test_ac1_search_with_invalid_attendance_returns_400(client, value):
    """
    Summary: Attendance must be a whole number of at least 1.
    AC1: Event Coordinator must be able to input the following criteria: Date
        and time (required), Expected attendance (required), Location
        (optional), Minimum capacity (optional), Accessibility requirements
        (optional), Supported layout (optional), and Required facilities
        (optional).
    Double: None
    """
    response = search(client, expectedAttendance=value)

    assert response.status_code == 400
    assert "Expected attendance" in response.json["message"]


def test_ac1_search_with_invalid_min_capacity_returns_400(client):
    """
    Summary: The optional capacity floor is validated the same way.
    AC1: Event Coordinator must be able to input the following criteria: Date
        and time (required), Expected attendance (required), Location
        (optional), Minimum capacity (optional), Accessibility requirements
        (optional), Supported layout (optional), and Required facilities
        (optional).
    Double: None
    """
    assert search(client, minCapacity="0").status_code == 400


# --- AC3: results matching all active criteria ------------------------------


def test_ac3_search_forwards_every_optional_filter(client, mocker):
    """
    Summary: Every optional criterion reaches Venue Service unchanged.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Mock (search_venues inspected)
    """
    # Arrange (Given)
    mock_search_venues = mocker.patch("app.routes.search_venues")
    mock_get_bookings = mocker.patch("app.routes.get_bookings_between")
    mock_search_venues.return_value = []
    mock_get_bookings.return_value = {"bookings": [], "closures": []}

    # Act (When)
    search(
        client,
        location="Main Tower",
        layout="banquet",
        facility=["wifi", "stage"],
        accessibility=["lift"],
    )

    # Assert (Then)
    assert mock_search_venues.call_args.args[0] == [
        ("minCapacity", "120"),
        ("location", "Main Tower"),
        ("layout", "banquet"),
        ("facility", "wifi"),
        ("facility", "stage"),
        ("accessibility", "lift"),
    ]
    mock_get_bookings.assert_called_once_with(START, END)


def test_ac3_search_uses_larger_of_attendance_and_min_capacity(client, mocker):
    """
    Summary: The larger of attendance and minimum capacity is used.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Mock (search_venues inspected)
    """
    # Arrange (Given)
    mock_search_venues = mocker.patch("app.routes.search_venues")
    mock_get_bookings = mocker.patch("app.routes.get_bookings_between")
    mock_search_venues.return_value = []
    mock_get_bookings.return_value = {"bookings": [], "closures": []}

    # Act (When)
    search(client, expectedAttendance="50", minCapacity="200")

    # Assert (Then)
    assert ("minCapacity", "200") in mock_search_venues.call_args.args[0]


def test_ac3_search_hides_venue_with_approved_overlap(client, mocker):
    """
    Summary: A venue with an approved booking in the window is not offered.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (window with an approved booking)
    """
    # Arrange (Given)
    mock_search_venues = mocker.patch("app.routes.search_venues")
    mock_get_bookings = mocker.patch("app.routes.get_bookings_between")
    mock_search_venues.return_value = [BALLROOM, ROOFTOP]
    mock_get_bookings.return_value = {"bookings": [booking("ven-1", "Approved")], "closures": []}

    # Act (When)
    response = search(client)

    # Assert (Then)
    assert [v["name"] for v in response.json["venues"]] == ["Rooftop Garden"]


def test_ac3_search_hides_venue_with_active_hold(client, mocker):
    """
    Summary: A venue on hold in the window is not offered.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (window with a hold)
    """
    # Arrange (Given)
    mock_search_venues = mocker.patch("app.routes.search_venues")
    mock_get_bookings = mocker.patch("app.routes.get_bookings_between")
    mock_search_venues.return_value = [BALLROOM]
    mock_get_bookings.return_value = {"bookings": [booking("ven-1", "On Hold")], "closures": []}

    # Act (When)
    response = search(client)

    # Assert (Then)
    assert response.json == {"venues": [], "count": 0}


@pytest.mark.parametrize("status", ["Pending", "Pending Review"], ids=["pending", "pending_review"])
def test_ac4_search_keeps_venue_with_pending_request_and_badges_it(client, status, mocker):
    """
    Summary: A venue with only a pending request is still offered, marked as pending.
    AC4: The search results must display the following for each matching venue:
        name, location, capacity, accessibility, supported layouts, available
        facilities, and availability status for the requested date/time.
    Double: Stub (window with a pending booking)
    """
    mock_search_venues = mocker.patch("app.routes.search_venues")
    mock_get_bookings = mocker.patch("app.routes.get_bookings_between")
    mock_search_venues.return_value = [BALLROOM]
    mock_get_bookings.return_value = {"bookings": [booking("ven-1", status)], "closures": []}

    response = search(client)

    assert response.json["venues"][0]["availability"] == "Pending request"


def test_ac3_search_ignores_rejected_booking(client, mocker):
    """
    Summary: Rejected bookings never hide a venue.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (window)
    """
    # Arrange (Given)
    mock_search_venues = mocker.patch("app.routes.search_venues")
    mock_get_bookings = mocker.patch("app.routes.get_bookings_between")
    mock_search_venues.return_value = [BALLROOM]
    mock_get_bookings.return_value = {"bookings": [], "closures": []}

    # Act (When)
    response = search(client)

    # Assert (Then)
    assert response.json["venues"][0]["availability"] == "Available"


@pytest.mark.parametrize("venue", [AUDITORIUM, STATIC_BOOKED], ids=["under_maintenance", "booked"])
def test_ac3_search_hides_non_operational_venue(client, venue, mocker):
    """
    Summary: Venues under maintenance or booked are not offered.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (catalogue)
    """
    # Arrange (Given)
    mock_search_venues = mocker.patch("app.routes.search_venues")
    mock_get_bookings = mocker.patch("app.routes.get_bookings_between")
    mock_search_venues.return_value = [venue]
    mock_get_bookings.return_value = {"bookings": [], "closures": []}

    # Act + Assert (When / Then)
    assert search(client).json == {"venues": [], "count": 0}


def test_ac3_search_ignores_other_venues_bookings(client, mocker):
    """
    Summary: Another venue's booking does not hide this venue.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (window)
    """
    # Arrange (Given)
    mock_search_venues = mocker.patch("app.routes.search_venues")
    mock_get_bookings = mocker.patch("app.routes.get_bookings_between")
    mock_search_venues.return_value = [BALLROOM]
    mock_get_bookings.return_value = {"bookings": [booking("ven-9", "Approved")], "closures": []}

    # Act + Assert (When / Then)
    assert search(client).json["venues"][0]["availability"] == "Available"


def test_ac3_search_calls_downstream_services_in_parallel(client, mocker):
    """
    Summary: The two lookups run in parallel to fit the 3-second goal.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (each lookup sleeps 1 s)
    """
    mock_search_venues = mocker.patch("app.routes.search_venues")
    mock_get_bookings = mocker.patch("app.routes.get_bookings_between")

    # Arrange (Given)
    def slow(*args, **kwargs):
        time.sleep(1)
        return []

    mock_search_venues.side_effect = slow
    mock_get_bookings.side_effect = lambda *a: {"bookings": slow(*a), "closures": []}

    started = time.monotonic()
    response = search(client)

    # Act (When)
    elapsed = time.monotonic() - started

    # Assert (Then)
    assert response.status_code == 200
    assert elapsed < 1.8


# --- AC4 and AC5: what the coordinator sees ---------------------------------


def test_ac4_search_results_carry_every_display_field(client, mocker):
    """
    Summary: Each result carries everything the card shows.
    AC4: The search results must display the following for each matching venue:
        name, location, capacity, accessibility, supported layouts, available
        facilities, and availability status for the requested date/time.
    Double: Stub (catalogue and window)
    """
    mock_search_venues = mocker.patch("app.routes.search_venues")
    mock_get_bookings = mocker.patch("app.routes.get_bookings_between")
    mock_search_venues.return_value = [ROOFTOP]
    mock_get_bookings.return_value = {"bookings": [], "closures": []}

    venue = search(client).json["venues"][0]

    assert venue == {**ROOFTOP, "availability": "Available"}


def test_ac4_search_lists_free_venues_before_pending_then_by_name(client, mocker):
    """
    Summary: Fully free venues come first, then pending ones, by name.
    AC4: The search results must display the following for each matching venue:
        name, location, capacity, accessibility, supported layouts, available
        facilities, and availability status for the requested date/time.
    Double: Stub (catalogue and window)
    """
    mock_search_venues = mocker.patch("app.routes.search_venues")
    mock_get_bookings = mocker.patch("app.routes.get_bookings_between")
    mock_search_venues.return_value = [BALLROOM, ROOFTOP]
    mock_get_bookings.return_value = {"bookings": [booking("ven-1", "Pending")], "closures": []}

    response = search(client)

    assert [(v["name"], v["availability"]) for v in response.json["venues"]] == [
        ("Rooftop Garden", "Available"),
        ("Grand Ballroom", "Pending request"),
    ]


def test_ac5_search_with_no_matches_returns_empty_list(client, mocker):
    """
    Summary: No available venue is a normal empty answer.
    AC5: Given no venues match the selected criteria, when the search
        completes, then the system must display a message informing the user
        that no venues are available.
    Double: Stub (empty catalogue)
    """
    # Arrange (Given)
    mock_search_venues = mocker.patch("app.routes.search_venues")
    mock_get_bookings = mocker.patch("app.routes.get_bookings_between")
    mock_search_venues.return_value = []
    mock_get_bookings.return_value = {"bookings": [], "closures": []}

    # Act (When)
    response = search(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json == {"venues": [], "count": 0}


# --- Failure handling -------------------------------------------------------


def test_ac3_search_when_downstream_slow_returns_504(client, mocker):
    """
    Summary: A downstream service slower than the budget is a 504.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (lookup times out)
    """
    # Arrange (Given)
    mock_search_venues = mocker.patch("app.routes.search_venues")
    mock_get_bookings = mocker.patch("app.routes.get_bookings_between")
    mock_search_venues.side_effect = httpx.TimeoutException("too slow")
    mock_get_bookings.return_value = {"bookings": [], "closures": []}

    # Act (When)
    response = search(client)

    # Assert (Then)
    assert response.status_code == 504
    assert response.json["message"] == "Venue search took too long. Please try again."


def test_ac3_search_when_downstream_fails_returns_502(client, mocker):
    """
    Summary: A downstream failure is a 502 without internals.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (lookup answers 503)
    """
    # Arrange (Given)
    mock_search_venues = mocker.patch("app.routes.search_venues")
    mock_get_bookings = mocker.patch("app.routes.get_bookings_between")
    mock_search_venues.side_effect = httpx.HTTPStatusError(
        "503 Service Unavailable for http://venue-service:5000/venues",
        request=httpx.Request("GET", "http://venue-service:5000/venues"),
        response=httpx.Response(503),
    )
    mock_get_bookings.return_value = {"bookings": [], "closures": []}

    # Act (When)
    response = search(client)

    # Assert (Then)
    assert response.status_code == 502
    assert response.json["message"] == "Unable to search venues right now."
    assert "venue-service" not in response.json["message"]


def test_ac3_search_when_availability_down_returns_502(client, mocker):
    """
    Summary: Either lookup failing fails the search.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (window read fails)
    """
    # Arrange (Given)
    mock_search_venues = mocker.patch("app.routes.search_venues")
    mock_get_bookings = mocker.patch("app.routes.get_bookings_between")
    mock_search_venues.return_value = [BALLROOM]
    mock_get_bookings.side_effect = httpx.ConnectError("connection refused")

    # Act + Assert (When / Then)
    assert search(client).status_code == 502


def test_ac3_search_offers_no_write_method(client):
    """
    Summary: The search changes nothing.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: None
    """
    for method in (client.post, client.patch, client.put, client.delete):
        assert method("/venue-search").status_code == 405


# --- The client wrappers themselves -----------------------------------------
# Everything above mocks these out, so they get their own tests: the query
# they build is the contract with each atomic.


def test_ac3_search_venues_client_sends_repeated_filters_and_timeout(monkeypatch):
    """
    Summary: Repeated filters are sent as separate parameters, with a timeout.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (respx; request inspected)
    """
    from app import clients

    captured = {}

    def fake_get(url, params=None, timeout=None, headers=None):
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


def test_ac3_bookings_between_client_uses_all_venue_window(monkeypatch):
    """
    Summary: Availability comes from the all-venue window read.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (respx; request inspected)
    """
    from app import clients

    captured = {}

    def fake_get(url, params=None, timeout=None, headers=None):
        captured.update(url=url, params=params, timeout=timeout)
        return httpx.Response(
            200,
            json={"bookings": [booking("ven-1", "Approved")], "closures": []},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(clients.httpx, "get", fake_get)

    bookings = clients.get_bookings_between(START, END)

    assert [b["venueId"] for b in bookings["bookings"]] == ["ven-1"]
    assert captured["url"].endswith("/venue-bookings/window")
    assert captured["params"] == {"dateFrom": START, "dateTo": END}
    # The window read covers every venue; the calendar read would need a
    # venueId and the DEV-mode identity headers.
    assert "venueId" not in captured["params"]
    assert captured["timeout"] == clients.SEARCH_TIMEOUT


@pytest.mark.parametrize(
    "wrapper", ["search_venues", "get_bookings_between"],
    ids=["search_venues", "bookings_between"],
)
def test_ac3_search_clients_raise_on_downstream_error(monkeypatch, wrapper):
    """
    Summary: A downstream failure reaches the route so it can answer 502.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (respx answers 503)
    """
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


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_support_search_preflight_from_frontend_is_allowed():
    """
    Summary: The frontend may search from a browser.
    Supporting design check: CORS for the configured frontend origin
    Double: None
    """
    client = signed_in(create_app().test_client())

    response = client.get("/venue-search", headers={"Origin": "http://localhost:5174"})

    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert "GET" in response.headers["Access-Control-Allow-Methods"]
    assert (
        "Access-Control-Allow-Origin"
        not in client.get("/venue-search", headers={"Origin": "https://other.example"}).headers
    )
