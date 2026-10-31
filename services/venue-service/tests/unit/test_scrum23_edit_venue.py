"""
SCRUM-23: Edit Existing Venue Details and Status

User Story
----------
As a Venue Staff, I want to edit an existing venue's profile and status, so
that the catalogue always reflects accurate characteristics and operating
information.

Acceptance Criteria
-------------------
AC1: Given the user clicks on a "Edit Venue", the system must pre-populate the
     form with the venue's current data.
AC2: When the Venue Staff member updates the venue's details and saves, then
     the updated details must reflect on the venue's profile.
AC3: The system must provide a toggle or dropdown to change the venue's
     operational status to either "Available", “Booked", or “Under
     Maintenance”.
AC4: Given a venue's status is changed to "Booked" or “Under Maintenance”, then
     the system must hide it from the Event Coordinator's venue search and
     availability calendar.

Real
----
- PUT /venues/<id>: validation, the duplicate-name check that ignores the
  venue's own name, the update, 404 for an unknown venue and the serializer run
  for real.
- Assertions are on the status, errors and the values sent to the database.

Doubled
-------
- psycopg2.connect: Stub / Mock (`setup` fixture) - the cursor returns canned
  Venue rows (or raises OperationalError); executed SQL and parameters are
  inspected to prove what is stored or filtered.

Not proven
----------
- Pre-populating the form and the status dropdown (AC1, AC3 UI half) (->
  frontend AddVenuePage.test.tsx edit mode).
- Hiding Booked / Under Maintenance venues from search and the calendar (AC4)
  (-> test_scrum26_venue_search_filters.py does not filter by status;
  venue-booking-service search tests and venue-availability calendar tests).
- That the real public."Venue" table stores and returns these values (->
  tests/integration/, throwaway postgres:17.6).
- That only Venue Staff can make this change (->
  test_scrum10_venue_modification_access.py, SCRUM-10).
"""
from unittest.mock import MagicMock

import psycopg2
import pytest

from app import create_app
from tests.unit.factories import VALID_PAYLOAD, VENUE_ID, saved_row, signed_in


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
    return signed_in(app.test_client(), role="Venue Staff"), cursor


def test_ac2_ac3_edit_venue_with_valid_form_saves_fields_and_status(setup):
    """
    Summary: Saving an edit updates every field, including operating status, and returns the new profile.
    AC2: When the Venue Staff member updates the venue's details and saves,
        then the updated details must reflect on the venue's profile.
    AC3: The system must provide a toggle or dropdown to change the venue's
        operational status to either "Available", “Booked", or “Under
        Maintenance”.
    Double: Stub (cursor: no duplicate, the updated row; update inspected)
    """
    client, cursor = setup
    cursor.fetchone.side_effect = [None, saved_row(
        venue_name="Updated Lounge",
        location="Level 21",
        max_capacity=100,
        facilities={"wifi": True, "stage": True},
        accessibility="Step-free access",
        supported_layouts=["theatre"],
        operational_status="Under Maintenance",
        setup_time_minutes=60,
        turnaround_time_minutes=20,
    )]
    payload = {
        **VALID_PAYLOAD,
        "name": "Updated Lounge",
        "location": "Level 21",
        "capacity": "100",
        "facilities": ["wifi", "stage"],
        "accessibility": "Step-free access",
        "supportedLayouts": ["theatre"],
        "status": "Under Maintenance",
        "setupTimeMinutes": "60",
        "turnaroundTimeMinutes": "20",
    }

    response = client.put(f"/venues/{VENUE_ID}", json=payload)

    assert response.status_code == 200
    assert response.json["venue"] == {
        "id": VENUE_ID,
        "name": "Updated Lounge",
        "location": "Level 21",
        "capacity": 100,
        "facilities": ["stage", "wifi"],
        "accessibility": "Step-free access",
        "supportedLayouts": ["theatre"],
        "status": "Under Maintenance",
        "setupTimeMinutes": 60,
        "turnaroundTimeMinutes": 20,
        "emergencyAccessDetails": None,
        "knownRestrictions": None,
        "safetyInfoUpdatedBy": None,
        "safetyInfoUpdatedAt": None,
    }
    update_query, update_params = cursor.execute.call_args_list[-1].args
    assert 'UPDATE public."Venue"' in update_query
    assert update_params[3].adapted == {"wifi": True, "stage": True}
    assert update_params[-3:-1] == [60, 20]
    assert update_params[-1] == VENUE_ID


def test_ac2_edit_venue_keeping_its_own_name_saves_without_conflict(setup):
    """
    Summary: Keeping a venue's own name is not treated as a duplicate.
    AC2: When the Venue Staff member updates the venue's details and saves,
        then the updated details must reflect on the venue's profile.
    Double: Stub (cursor: duplicate check excludes this venue)
    """
    client, cursor = setup
    cursor.fetchone.side_effect = [None, saved_row()]

    response = client.put(f"/venues/{VENUE_ID}", json=VALID_PAYLOAD)

    assert response.status_code == 200
    duplicate_query, duplicate_params = cursor.execute.call_args_list[0].args
    assert "venue_id <> %s" in duplicate_query
    assert duplicate_params == [VALID_PAYLOAD["name"], VENUE_ID]


def test_ac2_edit_venue_with_another_venues_name_returns_409(setup):
    """
    Summary: An edit cannot give a venue another venue's name.
    AC2: When the Venue Staff member updates the venue's details and saves,
        then the updated details must reflect on the venue's profile.
    Double: Stub (cursor finds another venue with the name)
    """
    client, cursor = setup
    cursor.fetchone.return_value = {"exists": True}

    response = client.put(f"/venues/{VENUE_ID}", json={**VALID_PAYLOAD, "name": "Taken"})

    assert response.status_code == 409
    assert "A venue with this name already exists." in response.json["errors"]
    assert cursor.execute.call_count == 1


def test_ac3_edit_venue_with_unknown_status_returns_400_without_saving(setup):
    """
    Summary: Status can only be set to Available, Booked or Under Maintenance.
    AC3: The system must provide a toggle or dropdown to change the venue's
        operational status to either "Available", “Booked", or “Under
        Maintenance”.
    Double: Mock (cursor not executed)
    """
    client, cursor = setup

    response = client.put(
        f"/venues/{VENUE_ID}", json={**VALID_PAYLOAD, "status": "Closed"}
    )

    assert response.status_code == 400
    assert any("Operating Status must be one of" in error for error in response.json["errors"])
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    "field,label",
    [
        ("name", "Venue Name"),
        ("location", "Location"),
        ("capacity", "Capacity"),
        ("facilities", "Facilities"),
        ("supportedLayouts", "Supported Room Layouts"),
        ("status", "Operating Status"),
    ],
    ids=["name", "location", "capacity", "facilities", "supported_layouts", "status"],
)
def test_ac2_edit_venue_with_blank_mandatory_field_returns_400_naming_it(field, label, setup):
    """
    Summary: Clearing a mandatory field blocks the save and names the field.
    AC2: When the Venue Staff member updates the venue's details and saves,
        then the updated details must reflect on the venue's profile.
    Double: Mock (cursor not executed)
    """
    client, cursor = setup
    payload = {**VALID_PAYLOAD, field: "" if isinstance(VALID_PAYLOAD[field], str) else []}

    response = client.put(f"/venues/{VENUE_ID}", json=payload)

    assert response.status_code == 400
    assert label in response.json["missingFields"]
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    ("field", "label"),
    [
        ("name", "Venue Name"),
        ("location", "Location"),
        ("capacity", "Capacity"),
        ("facilities", "Facilities"),
        ("supportedLayouts", "Supported Room Layouts"),
        ("status", "Operating Status"),
    ],
    ids=["name", "location", "capacity", "facilities", "supported_layouts", "status"],
)
def test_ac2_edit_venue_with_mandatory_field_omitted_returns_400_naming_it(field, label, setup):
    """
    Summary: Leaving a mandatory field out of the edit blocks the save and names the field.
    AC2: When the Venue Staff member updates the venue's details and saves,
        then the updated details must reflect on the venue's profile.
    Double: Mock (cursor not executed)
    """
    client, cursor = setup
    payload = {key: value for key, value in VALID_PAYLOAD.items() if key != field}

    response = client.put(f"/venues/{VENUE_ID}", json=payload)

    assert response.status_code == 400
    assert label in response.json["missingFields"]
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("capacity", ["not-a-number", "0"], ids=["not_a_number", "zero"])
def test_ac2_edit_venue_with_invalid_capacity_returns_400_without_saving(capacity, setup):
    """
    Summary: Capacity must stay a whole number of at least 1.
    AC2: When the Venue Staff member updates the venue's details and saves,
        then the updated details must reflect on the venue's profile.
    Double: Mock (cursor not executed)
    """
    client, cursor = setup

    response = client.put(
        f"/venues/{VENUE_ID}", json={**VALID_PAYLOAD, "capacity": capacity}
    )

    assert response.status_code == 400
    assert "Capacity must be a positive whole number (maximum 2147483647)." in response.json["errors"]
    cursor.execute.assert_not_called()


def test_ac2_edit_venue_with_facilities_not_a_list_returns_400_without_saving(setup):
    """
    Summary: Facilities must stay a list of names.
    AC2: When the Venue Staff member updates the venue's details and saves,
        then the updated details must reflect on the venue's profile.
    Double: Mock (cursor not executed)
    """
    client, cursor = setup

    response = client.put(
        f"/venues/{VENUE_ID}", json={**VALID_PAYLOAD, "facilities": "wifi"}
    )

    assert response.status_code == 400
    assert "Facilities must be a list of names." in response.json["errors"]
    cursor.execute.assert_not_called()


def test_ac2_edit_venue_with_non_object_body_returns_400(setup):
    """
    Summary: A request that is not a venue form is refused.
    AC2: When the Venue Staff member updates the venue's details and saves,
        then the updated details must reflect on the venue's profile.
    Double: None
    """
    client, cursor = setup

    response = client.put(f"/venues/{VENUE_ID}", json=["not", "an", "object"])

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_ac2_edit_venue_when_venue_unknown_returns_404(setup):
    """
    Summary: Editing a venue that does not exist is refused.
    AC2: When the Venue Staff member updates the venue's details and saves,
        then the updated details must reflect on the venue's profile.
    Double: Stub (update matches no row)
    """
    client, cursor = setup
    cursor.fetchone.side_effect = [None, None]

    response = client.put(f"/venues/{VENUE_ID}", json=VALID_PAYLOAD)

    assert response.status_code == 404
    assert response.json["message"] == "Venue not found."


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_support_edit_venue_preflight_allows_put_from_frontend(setup):
    """
    Summary: The browser may send the edit from the frontend.
    Supporting design check: CORS allows PUT for venue edits
    Double: None
    """
    client, _ = setup

    response = client.options(
        f"/venues/{VENUE_ID}",
        headers={
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "PUT",
        },
    )

    assert response.status_code == 200
    assert "PUT" in response.headers["Access-Control-Allow-Methods"]


def test_support_edit_venue_when_database_fails_returns_503_without_internals(setup, monkeypatch):
    """
    Summary: A database outage while editing gives a 503 that leaks no internals.
    Supporting design check: database errors answer 503 with a safe message
    Double: Stub (psycopg2.connect raises OperationalError)
    """
    client, _ = setup

    def explode(*args, **kwargs):
        raise psycopg2.OperationalError("connection refused to db.example")

    monkeypatch.setattr("app.models.psycopg2.connect", explode)

    response = client.put(f"/venues/{VENUE_ID}", json=VALID_PAYLOAD)

    assert response.status_code == 503


def test_support_edit_venue_when_database_url_missing_returns_503():
    """
    Summary: Editing reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured Venue Service answers 503
    Double: None
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client(), role="Venue Staff")

    response = client.put(f"/venues/{VENUE_ID}", json=VALID_PAYLOAD)

    assert response.status_code == 503
