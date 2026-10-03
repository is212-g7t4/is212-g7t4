"""SCRUM-24 View Venue Details — GET /venues/<id> on Venue Service.

AC1: a venue's characteristics (location, capacity, facilities, accessibility,
supported layouts and operating status) are returned for a single venue.
AC2 (no edit controls for Event Coordinators) is a frontend concern and is
covered by docs/test-scripts/scrum-24-view-venue-details.md; the backend side
of it is that this endpoint is read-only.

Database calls are mocked; no live database reads or writes.
"""
from unittest.mock import MagicMock

import psycopg2
import pytest

from app import create_app

VENUE_ID = "8381b11e-aaae-4d58-bdba-2607e9e2bde2"
MISSING_ID = "00000000-0000-0000-0000-000000000000"


def venue_row(**overrides):
    row = {
        "venue_id": VENUE_ID,
        "venue_name": "Grand Ballroom",
        "location": "Level 3, Main Tower",
        "max_capacity": 500,
        "facilities": {"wifi": True, "stage": True, "av_system": True},
        "accessibility": "Wheelchair accessible, elevator access",
        "supported_layouts": ["theatre", "banquet", "classroom"],
        "operational_status": "Available",
    }
    row.update(overrides)
    return row


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({
        "TESTING": True,
        "DATABASE_URL": "unused-test-url",
        "FRONTEND_ORIGIN": "http://localhost:5174",
    })
    return app.test_client(), connection, cursor


def test_ac1_returns_all_venue_characteristics(setup):
    """AC1: every characteristic the story lists comes back for one venue."""
    client, _, cursor = setup
    cursor.fetchone.return_value = venue_row()

    response = client.get(f"/venues/{VENUE_ID}")

    assert response.status_code == 200
    assert response.json["venue"] == {
        "id": VENUE_ID,
        "name": "Grand Ballroom",
        "location": "Level 3, Main Tower",
        "capacity": 500,
        "facilities": ["av_system", "stage", "wifi"],
        "accessibility": "Wheelchair accessible, elevator access",
        "supportedLayouts": ["theatre", "banquet", "classroom"],
        "status": "Available",
    }


def test_ac1_query_filters_by_venue_id(setup):
    """AC1: the lookup is scoped to the requested venue, passed as a parameter."""
    client, _, cursor = setup
    cursor.fetchone.return_value = venue_row()

    client.get(f"/venues/{VENUE_ID}")

    query, params = cursor.execute.call_args.args
    assert 'WHERE venue_id = %s' in query
    assert params == [VENUE_ID]


def test_ac1_facilities_object_becomes_sorted_list(setup):
    """AC1 boundary: the live jsonb object shape drops false keys and sorts."""
    client, _, cursor = setup
    cursor.fetchone.return_value = venue_row(
        facilities={"wifi": True, "stage": True, "kitchen": False}
    )

    response = client.get(f"/venues/{VENUE_ID}")

    assert response.json["venue"]["facilities"] == ["stage", "wifi"]


def test_ac1_facilities_array_passes_through(setup):
    """AC1 boundary: the seed script's array shape still works."""
    client, _, cursor = setup
    cursor.fetchone.return_value = venue_row(facilities=["Projector", "Whiteboards"])

    response = client.get(f"/venues/{VENUE_ID}")

    assert response.json["venue"]["facilities"] == ["Projector", "Whiteboards"]


def test_ac1_null_fields_serialise_to_empty(setup):
    """AC1 boundary: missing values are empty/null so the UI shows 'Not specified'."""
    client, _, cursor = setup
    cursor.fetchone.return_value = venue_row(
        location=None,
        max_capacity=None,
        facilities=None,
        accessibility=None,
        supported_layouts=None,
        operational_status=None,
        venue_name=None,
    )

    venue = client.get(f"/venues/{VENUE_ID}").json["venue"]

    assert venue["name"] == ""
    assert venue["location"] == ""
    assert venue["capacity"] is None
    assert venue["facilities"] == []
    assert venue["accessibility"] == ""
    assert venue["supportedLayouts"] == []
    assert venue["status"] == "Unknown"


@pytest.mark.parametrize("status", ["Under Maintenance", "Booked"])
def test_ac1_non_available_venue_still_viewable(status, setup):
    """AC1 conflict: a venue that can't be booked is still readable."""
    client, _, cursor = setup
    cursor.fetchone.return_value = venue_row(operational_status=status)

    response = client.get(f"/venues/{VENUE_ID}")

    assert response.status_code == 200
    assert response.json["venue"]["status"] == status


def test_unknown_venue_returns_404(setup):
    """Failure: a well-formed id with no matching row is not found."""
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = client.get(f"/venues/{MISSING_ID}")

    assert response.status_code == 404
    assert response.json["message"] == "Venue not found."


def test_malformed_id_returns_404(setup):
    """Failure: the uuid converter rejects a malformed id before any query."""
    client, _, cursor = setup

    response = client.get("/venues/not-a-uuid")

    assert response.status_code == 404
    cursor.execute.assert_not_called()


def test_database_error_returns_503(setup, monkeypatch):
    """Failure: a database outage is a 503 that leaks no internals."""
    client, _, _ = setup

    def explode(*args, **kwargs):
        raise psycopg2.OperationalError("connection refused to db.example")

    monkeypatch.setattr("app.models.psycopg2.connect", explode)

    response = client.get(f"/venues/{VENUE_ID}")

    assert response.status_code == 503
    assert response.json["message"] == "Unable to load venue data."


def test_missing_database_url_returns_503():
    """Failure: an unconfigured service says so rather than crashing."""
    client = create_app({"TESTING": True, "DATABASE_URL": None}).test_client()

    assert client.get(f"/venues/{VENUE_ID}").status_code == 503
    assert client.get("/venues").status_code == 503


def test_detail_endpoint_only_allows_the_intended_update_method(setup):
    """Only PUT is accepted for edits; unrelated write methods stay disallowed."""
    client, _, _ = setup

    assert client.put(f"/venues/{VENUE_ID}").status_code == 400
    for method in (client.patch, client.delete, client.post):
        assert method(f"/venues/{VENUE_ID}").status_code == 405


def test_list_venues_uses_shared_serializer(setup):
    """Regression (SCRUM-114): the catalogue gets the same clean facilities list."""
    client, _, cursor = setup
    cursor.fetchall.return_value = [
        venue_row(),
        venue_row(
            venue_id=MISSING_ID,
            venue_name="Auditorium",
            facilities={"wifi": True, "kitchen": False},
            operational_status="Under Maintenance",
        ),
    ]

    response = client.get("/venues")

    assert response.status_code == 200
    assert response.json["venues"][0]["facilities"] == ["av_system", "stage", "wifi"]
    assert response.json["venues"][1]["facilities"] == ["wifi"]
    assert response.json["venues"][1]["status"] == "Under Maintenance"
    query, *_ = cursor.execute.call_args.args
    assert "ORDER BY venue_name ASC" in query


def test_health_and_browser_cors(setup):
    """The service is reachable from the SPA's origin and nowhere else."""
    client = setup[0]

    assert client.get("/health").json == {"status": "ok"}
    response = client.options(f"/venues/{VENUE_ID}", headers={"Origin": "http://127.0.0.1:5174"})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5174"
    assert response.headers["Access-Control-Allow-Methods"] == "GET, POST, PUT, OPTIONS"
    assert (
        "Access-Control-Allow-Origin"
        not in client.get("/venues", headers={"Origin": "https://other.example"}).headers
    )
