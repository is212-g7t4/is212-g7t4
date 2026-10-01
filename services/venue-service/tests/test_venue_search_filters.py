"""SCRUM-26 Venue Search and Filtering — the filters on GET /venues.

Venue Service owns the suitability check: given an event's requirements, which
venues in the catalogue meet them? Venue Booking Service (composite) calls this
with the coordinator's search criteria, then merges the result with bookings
from Venue Availability Service.

AC3 is "venues matching all active criteria", so each criterion gets a test and
the combination gets one of its own. Database calls are mocked.
"""
from unittest.mock import MagicMock

import pytest

from app import create_app

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
    return app.test_client()


def names(response):
    return [venue["name"] for venue in response.json["venues"]]


def test_ac3_no_filters_returns_full_catalogue(client):
    """Regression (SCRUM-114, SCRUM-24): the catalogue page is unaffected."""
    response = client.get("/venues")

    assert response.status_code == 200
    assert names(response) == ["Grand Ballroom", "Seminar Room C", "Community Hall"]


def test_ac3_capacity_at_limit_matches(client):
    """AC3 boundary: attendance exactly equal to max_capacity still fits."""
    assert names(client.get("/venues?minCapacity=60")) == ["Grand Ballroom", "Seminar Room C"]


def test_ac3_capacity_one_over_limit_excluded(client):
    """AC3 boundary: one person over max_capacity does not fit."""
    assert names(client.get("/venues?minCapacity=61")) == ["Grand Ballroom"]


def test_ac3_min_capacity_stricter_than_attendance(client):
    """AC3: the composite sends max(attendance, minCapacity) as one number."""
    assert names(client.get("/venues?minCapacity=200")) == ["Grand Ballroom"]


def test_ac3_null_capacity_excluded(client):
    """AC3 boundary: a venue with no stated capacity can't be confirmed to fit."""
    assert "Community Hall" not in names(client.get("/venues?minCapacity=1"))


def test_ac3_location_contains_case_insensitive(client):
    """AC3: 'main tower' matches 'Level 3, Main Tower'."""
    assert names(client.get("/venues?location=main+tower")) == [
        "Grand Ballroom",
        "Community Hall",
    ]


def test_ac3_layout_must_be_supported(client):
    """AC3: only venues whose supported_layouts contain the choice."""
    assert names(client.get("/venues?layout=banquet")) == ["Grand Ballroom", "Community Hall"]


def test_ac3_all_required_facilities_needed(client):
    """AC3: every selected facility is required, not just one of them."""
    assert names(client.get("/venues?facility=wifi&facility=stage")) == ["Grand Ballroom"]


def test_ac3_false_facility_does_not_match(client):
    """AC3 boundary: a facilities key stored as false is not a facility."""
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
)
def test_ac3_accessibility_synonyms(client, key, expected):
    """AC3: 'lift' matches both 'Elevator access' and 'Lift access'."""
    assert names(client.get(f"/venues?accessibility={key}")) == expected


def test_ac3_all_active_criteria_combined(client):
    """AC3: every optional criterion at once narrows to one venue."""
    response = client.get(
        "/venues?minCapacity=100&location=Main+Tower&layout=theatre"
        "&facility=wifi&facility=stage&accessibility=wheelchair&accessibility=lift"
    )

    assert names(response) == ["Grand Ballroom"]


def test_blank_filters_are_treated_as_unset(client):
    """An untouched form field is the same as an absent parameter."""
    response = client.get("/venues?minCapacity=&location=+&layout=&facility=&accessibility=")

    assert names(response) == ["Grand Ballroom", "Seminar Room C", "Community Hall"]


@pytest.mark.parametrize("value", ["0", "-5", "abc", "2.5"])
def test_invalid_min_capacity_returns_400(client, value):
    """Failure: minCapacity must be a whole number of at least 1."""
    response = client.get(f"/venues?minCapacity={value}")

    assert response.status_code == 400
    assert "minCapacity" in response.json["message"]


def test_unknown_accessibility_key_returns_400(client):
    """Failure: an accessibility key the service can't match is rejected."""
    response = client.get("/venues?accessibility=teleporter")

    assert response.status_code == 400
    assert "accessibility" in response.json["message"]


def test_invalid_filter_is_rejected_before_the_database(monkeypatch):
    """Failure: a bad parameter is a 400 even when the service is unconfigured."""
    client = create_app({"TESTING": True, "DATABASE_URL": None}).test_client()

    assert client.get("/venues?minCapacity=0").status_code == 400
