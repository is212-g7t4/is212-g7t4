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
- GET /venues with minCapacity, location, layout, facility and accessibility
  filters: parameter validation and app.venues matching (capacity fit,
  case-insensitive location, required layouts and every facility, accessibility
  synonyms) run for real over a fixed catalogue.
- Assertions are on the names of the venues returned and the status.

Doubled
-------
- list_venues: Stub (`client` fixture) - returns a fixed in-memory catalogue
  instead of reading the database.

Not proven
----------
- Required date/time and attendance fields, the "fill required fields" and "no
  venues" messages, clear-all and the 3-second limit (AC1, AC2, AC5, AC6, AC3
  timing) (-> frontend venueSearch.test.ts and e2e
  scrum-26-venue-search.spec.mjs).
- Availability for the requested date/time (AC4) (-> venue-booking-service
  search tests, which join Venue Availability).
- Hiding Booked / Under Maintenance venues: these filters do not look at status
  (-> venue-booking-service search tests).
"""
from unittest.mock import MagicMock

import pytest

from app import create_app
from tests.unit.factories import signed_in

CATALOGUE = [
    {
        "venue_id": "11111111-1111-1111-1111-111111111111",
        "venue_name": "Grand Ballroom",
        "location": "Level 3, Main Tower",
        "max_capacity": 500,
        "facilities": {"wifi": True, "stage": True, "kitchen": False},
        "accessibility": "Wheelchair accessible, elevator access",
        "supported_layouts": ["theatre", "banquet"],
        "operational_status": "Available",
    },
    {
        "venue_id": "22222222-2222-2222-2222-222222222222",
        "venue_name": "Seminar Room C",
        "location": "Level 2, East Wing",
        "max_capacity": 60,
        "facilities": {"wifi": True, "whiteboard": True},
        "accessibility": "Lift access; accessible washroom nearby",
        "supported_layouts": ["classroom"],
        "operational_status": "Available",
    },
    {
        "venue_id": "33333333-3333-3333-3333-333333333333",
        "venue_name": "Community Hall",
        "location": "Level 1, Main Tower",
        "max_capacity": None,
        "facilities": ["wifi"],
        "accessibility": "Hearing loop installed; level entrance",
        "supported_layouts": ["banquet"],
        "operational_status": "Available",
    },
]


@pytest.fixture
def client(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = CATALOGUE
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *a, **k: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client())


def names(response):
    return [venue["name"] for venue in response.json["venues"]]


def test_search_venues_without_filters_returns_whole_catalogue(client):
    """
    Summary: With no filters set, the whole catalogue is returned.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (fixed catalogue)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get("/venues")

    # Assert (Then)
    assert response.status_code == 200
    assert names(response) == ["Grand Ballroom", "Seminar Room C", "Community Hall"]


def test_search_venues_when_attendance_equals_capacity_includes_venue(client):
    """
    Summary: A venue whose capacity exactly equals the attendance still fits.
    AC3: (boundary: minCapacity = capacity)
    Double: Stub (fixed catalogue)
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert names(client.get("/venues?minCapacity=60")) == ["Grand Ballroom", "Seminar Room C"]


def test_search_venues_when_attendance_one_over_capacity_excludes_venue(client):
    """
    Summary: A venue one place too small is left out.
    AC3: (boundary: minCapacity = capacity + 1)
    Double: Stub (fixed catalogue)
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert names(client.get("/venues?minCapacity=61")) == ["Grand Ballroom"]


def test_search_venues_with_min_capacity_uses_the_stricter_number(client):
    """
    Summary: The stricter of attendance and minimum capacity decides which venues fit.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (fixed catalogue)
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert names(client.get("/venues?minCapacity=200")) == ["Grand Ballroom"]


def test_search_venues_when_venue_has_no_capacity_excludes_it(client):
    """
    Summary: A venue with no stated capacity is not offered for an attendance filter.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (fixed catalogue)
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert "Community Hall" not in names(client.get("/venues?minCapacity=1"))


def test_search_venues_by_location_matches_part_of_name_any_case(client):
    """
    Summary: Location matches part of the venue's location, in any letter case.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (fixed catalogue)
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert names(client.get("/venues?location=main+tower")) == [
        "Grand Ballroom",
        "Community Hall",
    ]


def test_search_venues_by_layout_returns_only_venues_supporting_it(client):
    """
    Summary: Only venues that support the chosen layout are returned.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (fixed catalogue)
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert names(client.get("/venues?layout=banquet")) == ["Grand Ballroom", "Community Hall"]


def test_search_venues_by_facilities_requires_every_one(client):
    """
    Summary: A venue must have every selected facility, not just one.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (fixed catalogue)
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert names(client.get("/venues?facility=wifi&facility=stage")) == ["Grand Ballroom"]


def test_search_venues_by_facility_ignores_facility_marked_false(client):
    """
    Summary: A facility recorded as absent does not count.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (fixed catalogue)
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert names(client.get("/venues?facility=kitchen")) == []


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("lift", ["Grand Ballroom", "Seminar Room C"]),
        ("wheelchair", ["Grand Ballroom"]),
        ("hearing_loop", ["Community Hall"]),
        ("accessible_washroom", ["Seminar Room C"]),
        ("step_free", ["Community Hall"]),
    ],
    ids=["lift", "wheelchair", "hearing_loop", "accessible_washroom", "step_free"],
)
def test_search_venues_by_accessibility_matches_common_wordings(client, key, expected):
    """
    Summary: Accessibility needs match the different ways venues describe them.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (fixed catalogue)
    """
    # Arrange (Given): client, key, expected, from fixtures

    # Act + Assert (When / Then)
    assert names(client.get(f"/venues?accessibility={key}")) == expected


def test_search_venues_with_every_criterion_returns_only_full_match(client):
    """
    Summary: Every criterion applied together narrows the results to the venues matching all of them.
    AC3: Given the Event Coordinator provides all required fields, when they
        click search, then the system must return a list of venues matching all
        active criteria within 3 seconds.
    Double: Stub (fixed catalogue)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get(
        "/venues?minCapacity=100&location=Main+Tower&layout=theatre"
        "&facility=wifi&facility=stage&accessibility=wheelchair&accessibility=lift"
    )

    # Assert (Then)
    assert names(response) == ["Grand Ballroom"]


def test_search_venues_with_blank_filters_treats_them_as_unset(client):
    """
    Summary: A filter left blank is ignored rather than matching nothing.
    AC6: a cleared form searches with no criteria
    Double: Stub (fixed catalogue)
    """
    response = client.get("/venues?minCapacity=&location=+&layout=&facility=&accessibility=")

    assert names(response) == ["Grand Ballroom", "Seminar Room C", "Community Hall"]


@pytest.mark.parametrize("value", ["0", "-5", "abc", "2.5"], ids=["zero", "negative", "text", "fractional"])
def test_search_venues_with_invalid_min_capacity_returns_400(client, value):
    """
    Summary: Minimum capacity must be a whole number of at least 1.
    AC1: Event Coordinator must be able to input the following criteria: Date
        and time (required), Expected attendance (required), Location
        (optional), Minimum capacity (optional), Accessibility requirements
        (optional), Supported layout (optional), and Required facilities
        (optional).
    Double: Stub (fixed catalogue)
    """
    response = client.get(f"/venues?minCapacity={value}")

    assert response.status_code == 400
    assert "minCapacity" in response.json["message"]


def test_search_venues_with_unknown_accessibility_need_returns_400(client):
    """
    Summary: An accessibility need the service cannot match is refused.
    AC1: Event Coordinator must be able to input the following criteria: Date
        and time (required), Expected attendance (required), Location
        (optional), Minimum capacity (optional), Accessibility requirements
        (optional), Supported layout (optional), and Required facilities
        (optional).
    Double: Stub (fixed catalogue)
    """
    response = client.get("/venues?accessibility=teleporter")

    assert response.status_code == 400
    assert "accessibility" in response.json["message"]


def test_search_venues_with_invalid_filter_returns_400_even_unconfigured(monkeypatch):
    """
    Summary: A bad filter is refused before the database is needed.
    AC1: Event Coordinator must be able to input the following criteria: Date
        and time (required), Expected attendance (required), Location
        (optional), Minimum capacity (optional), Accessibility requirements
        (optional), Supported layout (optional), and Required facilities
        (optional).
    Double: None
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client())

    assert client.get("/venues?minCapacity=0").status_code == 400
