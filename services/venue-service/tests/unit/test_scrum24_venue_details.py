"""
SCRUM-24: View Venue Details

User Story
----------
As an Event Coordinator, I want to view the detailed characteristics of a
specific venue, so that I can evaluate its suitability for an upcoming event.

Acceptance Criteria
-------------------
AC1: Given an Event Coordinator selects a venue from the catalogue, the system
     must display its location, capacity, facilities, accessibility, supported
     room layouts and operating information in a read-only format.
AC2: The system must hide any "Edit Venue" or "Add Venue" buttons from the
     Event Coordinator's view to enforce role-based access control.

SCRUM-114: View Venue Catalogue

User Story
----------
As a Venue Staff, I want to view all existing venue's profile and status, so
that the catalogue always reflects accurate venue statuses

Acceptance Criteria
-------------------
AC1: Given the Venue Staff is on the Venue Catalogue page, he should be able to
     see a list of all venue and their statuses
AC2: Given that there is a change in Venue Status, the Venue staff must be able
     to see the updated status within 30 seconds.

Real
----
- GET /venues/<uuid> and GET /venues: the lookup and the shared serializer
  (facilities normalised to a sorted list, nulls to empty) run for real.
- Assertions are on the returned venue fields and the query parameter.

Doubled
-------
- psycopg2.connect: Stub / Mock (`setup` fixture) - the cursor returns canned
  Venue rows (or raises OperationalError); executed SQL and parameters are
  inspected.

Not proven
----------
- Read-only display and hidden Edit/Add buttons for coordinators (AC1 UI half,
  AC2) (-> frontend venue detail page tests and e2e
  venue-detail-design.spec.ts).
- SCRUM-114 AC2 (updated status visible within 30 seconds): a UI refresh
  concern (NOT COVERED ANYWHERE).
"""
from unittest.mock import MagicMock

import psycopg2
import pytest

from app import create_app
from tests.unit.factories import signed_in

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
        "setup_time_minutes": 30,
        "turnaround_time_minutes": 45,
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
    return signed_in(app.test_client(), role="Venue Staff"), connection, cursor


def test_ac1_get_venue_returns_every_listed_characteristic(setup):
    """
    Summary: One venue's location, capacity, facilities, accessibility, layouts and operating information are all returned.
    AC1: Given an Event Coordinator selects a venue from the catalogue, the
        system must display its location, capacity, facilities, accessibility,
        supported room layouts and operating information in a read-only format.
    Double: Stub (cursor returns one venue row)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = venue_row()

    # Act (When)
    response = client.get(f"/venues/{VENUE_ID}")

    # Assert (Then)
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
        "setupTimeMinutes": 30,
        "turnaroundTimeMinutes": 45,
        "emergencyAccessDetails": None,
        "knownRestrictions": None,
        "safetyInfoUpdatedBy": None,
        "safetyInfoUpdatedAt": None,
    }


def test_ac1_get_venue_queries_only_the_requested_venue(setup):
    """
    Summary: The lookup asks only for the venue that was selected.
    AC1: Given an Event Coordinator selects a venue from the catalogue, the
        system must display its location, capacity, facilities, accessibility,
        supported room layouts and operating information in a read-only format.
    Double: Stub (cursor returns one row; query inspected)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = venue_row()

    client.get(f"/venues/{VENUE_ID}")

    query, params = cursor.execute.call_args.args

    # Act + Assert (When / Then)
    assert 'WHERE venue_id = %s' in query
    assert params == [VENUE_ID]


def test_ac1_get_venue_with_facilities_object_returns_sorted_names_of_true_keys(setup):
    """
    Summary: Facilities stored as flags are shown as a sorted list of the ones the venue has.
    AC1: Given an Event Coordinator selects a venue from the catalogue, the
        system must display its location, capacity, facilities, accessibility,
        supported room layouts and operating information in a read-only format.
    Double: Stub (cursor returns facilities as an object)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = venue_row(
        facilities={"wifi": True, "stage": True, "kitchen": False}
    )

    # Act (When)
    response = client.get(f"/venues/{VENUE_ID}")

    # Assert (Then)
    assert response.json["venue"]["facilities"] == ["stage", "wifi"]


def test_ac1_get_venue_with_facilities_list_returns_it_unchanged(setup):
    """
    Summary: Facilities already stored as a list are shown as they are.
    AC1: Given an Event Coordinator selects a venue from the catalogue, the
        system must display its location, capacity, facilities, accessibility,
        supported room layouts and operating information in a read-only format.
    Double: Stub (cursor returns facilities as a list)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = venue_row(facilities=["Projector", "Whiteboards"])

    # Act (When)
    response = client.get(f"/venues/{VENUE_ID}")

    # Assert (Then)
    assert response.json["venue"]["facilities"] == ["Projector", "Whiteboards"]


def test_ac1_get_venue_with_missing_values_returns_empty_fields(setup):
    """
    Summary: Missing values come back empty so the page can show "Not specified".
    AC1: Given an Event Coordinator selects a venue from the catalogue, the
        system must display its location, capacity, facilities, accessibility,
        supported room layouts and operating information in a read-only format.
    Double: Stub (cursor returns a row of nulls)
    """
    # Arrange (Given)
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

    # Act (When)
    venue = client.get(f"/venues/{VENUE_ID}").json["venue"]

    # Assert (Then)
    assert venue["name"] == ""
    assert venue["location"] == ""
    assert venue["capacity"] is None
    assert venue["facilities"] == []
    assert venue["accessibility"] == ""
    assert venue["supportedLayouts"] == []
    assert venue["status"] == "Unknown"


@pytest.mark.parametrize("status", ["Under Maintenance", "Booked"], ids=["under_maintenance", "booked"])
def test_ac1_get_venue_when_not_available_is_still_returned(status, setup):
    """
    Summary: A venue that is booked or under maintenance can still be viewed.
    AC1: Given an Event Coordinator selects a venue from the catalogue, the
        system must display its location, capacity, facilities, accessibility,
        supported room layouts and operating information in a read-only format.
    Double: Stub (cursor returns the venue with that status)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = venue_row(operational_status=status)

    # Act (When)
    response = client.get(f"/venues/{VENUE_ID}")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["venue"]["status"] == status


def test_ac1_get_venue_when_unknown_returns_404(setup):
    """
    Summary: A venue that does not exist is reported as not found.
    AC1: Given an Event Coordinator selects a venue from the catalogue, the
        system must display its location, capacity, facilities, accessibility,
        supported room layouts and operating information in a read-only format.
    Double: Stub (cursor finds no row)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    # Act (When)
    response = client.get(f"/venues/{MISSING_ID}")

    # Assert (Then)
    assert response.status_code == 404
    assert response.json["message"] == "Venue not found."


def test_ac1_get_venue_with_malformed_id_returns_404_without_query(setup):
    """
    Summary: A malformed venue id is not found, without touching the database.
    AC1: Given an Event Coordinator selects a venue from the catalogue, the
        system must display its location, capacity, facilities, accessibility,
        supported room layouts and operating information in a read-only format.
    Double: Mock (cursor not executed)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = client.get("/venues/not-a-uuid")

    # Assert (Then)
    assert response.status_code == 404
    cursor.execute.assert_not_called()


def test_ac2_venue_detail_with_unsupported_method_returns_405(setup):
    """
    Summary: Only reading and the edit method are accepted on a venue; other writes are refused.
    AC2: the detail view is read-only unless edited through the edit route
    Double: None
    """
    client, _, _ = setup

    assert client.put(f"/venues/{VENUE_ID}").status_code == 400
    for method in (client.patch, client.delete, client.post):
        assert method(f"/venues/{VENUE_ID}").status_code == 405


def test_scrum114_ac1_list_venues_returns_each_venue_in_detail_shape(setup):
    """
    Summary: The catalogue lists every venue with its status in the same clean shape as the detail view.
    SCRUM-114 AC1: Given the Venue Staff is on the Venue Catalogue page, he
        should be able to see a list of all venue and their statuses
    Double: Stub (cursor returns one row)
    """
    # Arrange (Given)
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

    # Act (When)
    response = client.get("/venues")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["venues"][0]["facilities"] == ["av_system", "stage", "wifi"]
    assert response.json["venues"][1]["facilities"] == ["wifi"]
    assert response.json["venues"][1]["status"] == "Under Maintenance"
    query, *_ = cursor.execute.call_args.args
    assert "ORDER BY venue_name ASC" in query


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_support_get_venue_when_database_fails_returns_503_without_internals(setup, monkeypatch):
    """
    Summary: A database outage gives a 503 that leaks no internals.
    Supporting design check: database errors answer 503 with a safe message
    Double: Stub (psycopg2.connect raises OperationalError)
    """
    client, _, _ = setup

    def explode(*args, **kwargs):
        raise psycopg2.OperationalError("connection refused to db.example")

    monkeypatch.setattr("app.models.psycopg2.connect", explode)

    response = client.get(f"/venues/{VENUE_ID}")

    assert response.status_code == 503
    assert response.json["message"] == "Unable to load venue data."


def test_support_get_venue_when_database_url_missing_returns_503():
    """
    Summary: Viewing a venue reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured Venue Service answers 503
    Double: None
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client(), role="Venue Staff")

    assert client.get(f"/venues/{VENUE_ID}").status_code == 503
    assert client.get("/venues").status_code == 503
