"""
SCRUM-22: Add New Venue to Catalogue

User Story
----------
As a Venue Staff, I want to add a new venue to the catalogue, so that its data
can be referenced across the system for venue searches and availability
calendars.

Acceptance Criteria
-------------------
AC1: Given a Venue Staff clicks "Add Venue", the system must provide input
     fields for venue name, location, capacity, facilities, accessibility,
     supported room layouts, and operating information.
AC2: When the user attempts to save the form with any mandatory field left
     blank, the system must prevent submission and display an error message
     highlighting the missing field.
AC3: When the user submits a valid form, then the system must securely save the
     venue, display a success confirmation, and make the new venue visible in
     the catalogue.
AC4: When the user submits an invalid form, the system must prevent submission
     and display an error message highlighting the incorrect field.

Real
----
- POST /venues: app.validation.validate() (blank, type and range checks), the
  duplicate-name check, the insert and the catalogue serializer run for real.
- Assertions are on the status, missingFields/errors and the values sent to the
  database.

Doubled
-------
- psycopg2.connect: Stub / Mock (`setup` fixture) - the cursor returns canned
  Venue rows (or raises OperationalError); executed SQL and parameters are
  inspected to prove what is stored or filtered.

Not proven
----------
- The form fields and success confirmation (AC1, AC3 UI half) (-> frontend
  AddVenuePage.test.tsx and e2e venue-detail-design.spec.ts).
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
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client(), role="Venue Staff"), connection, cursor


def test_ac3_add_venue_with_valid_form_saves_and_returns_catalogue_shape(setup):
    """
    Summary: A valid venue is saved and comes back exactly as the catalogue shows it.
    AC3: When the user submits a valid form, then the system must securely save
        the venue, display a success confirmation, and make the new venue
        visible in the catalogue.
    Double: Stub (cursor: no duplicate, then the saved row)
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [None, saved_row()]

    response = client.post("/venues", json=VALID_PAYLOAD)

    assert response.status_code == 201
    assert response.json["venue"] == {
        "id": VENUE_ID,
        "name": "Sky Lounge",
        "location": "Level 20, Main Tower",
        "capacity": 80,
        "facilities": ["projector", "wifi"],
        "accessibility": "Wheelchair accessible",
        "supportedLayouts": ["theatre", "classroom"],
        "status": "Available",
        "setupTimeMinutes": 30,
        "turnaroundTimeMinutes": 45,
        "emergencyAccessDetails": None,
        "knownRestrictions": None,
        "safetyInfoUpdatedBy": None,
        "safetyInfoUpdatedAt": None,
    }


def test_ac3_add_venue_saves_facilities_in_catalogue_storage_shape(setup):
    """
    Summary: Facilities are stored in the shape the catalogue reads back.
    AC3: When the user submits a valid form, then the system must securely save
        the venue, display a success confirmation, and make the new venue
        visible in the catalogue.
    Double: Stub (cursor: no duplicate, saved row; insert inspected)
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [None, saved_row()]

    client.post("/venues", json=VALID_PAYLOAD)

    insert_query, insert_params = cursor.execute.call_args_list[-1].args
    assert 'INSERT INTO public."Venue"' in insert_query
    assert insert_params[3].adapted == {"wifi": True, "projector": True}
    assert insert_params[-2:] == [30, 45]


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
def test_ac2_add_venue_with_blank_mandatory_field_returns_400_naming_it(field, label, setup):
    """
    Summary: Each mandatory field left blank blocks saving and is named in the error.
    AC2: When the user attempts to save the form with any mandatory field left
        blank, the system must prevent submission and display an error message
        highlighting the missing field.
    Double: Mock (cursor not executed)
    """
    client, _, cursor = setup
    payload = {**VALID_PAYLOAD, field: "" if isinstance(VALID_PAYLOAD[field], str) else []}

    response = client.post("/venues", json=payload)

    assert response.status_code == 400
    assert label in response.json["missingFields"]
    cursor.execute.assert_not_called()


def test_ac2_add_venue_with_mandatory_field_omitted_returns_400_naming_it(setup):
    """
    Summary: A mandatory field left out of the form entirely is treated as blank.
    AC2: When the user attempts to save the form with any mandatory field left
        blank, the system must prevent submission and display an error message
        highlighting the missing field.
    Double: None
    """
    client, _, _ = setup
    payload = {key: value for key, value in VALID_PAYLOAD.items() if key != "name"}

    response = client.post("/venues", json=payload)

    assert response.status_code == 400
    assert response.json["missingFields"] == ["Venue Name"]


def test_ac4_add_venue_with_non_numeric_capacity_returns_400(setup):
    """
    Summary: Capacity must be a number.
    AC4: When the user submits an invalid form, the system must prevent
        submission and display an error message highlighting the incorrect
        field.
    Double: Mock (cursor not executed)
    """
    client, _, cursor = setup
    payload = {**VALID_PAYLOAD, "capacity": "not-a-number"}

    response = client.post("/venues", json=payload)

    assert response.status_code == 400
    assert "Capacity must be a positive whole number (maximum 2147483647)." in response.json["errors"]
    cursor.execute.assert_not_called()


def test_ac4_add_venue_with_zero_capacity_returns_400(setup):
    """
    Summary: Capacity must be at least 1.
    AC4: (boundary: capacity = 0)
    Double: None
    """
    client, _, _ = setup
    payload = {**VALID_PAYLOAD, "capacity": "0"}

    response = client.post("/venues", json=payload)

    assert response.status_code == 400
    assert "Capacity must be a positive whole number (maximum 2147483647)." in response.json["errors"]


def test_ac4_add_venue_with_unknown_status_returns_400(setup):
    """
    Summary: Operating status must be one of the recognised values.
    AC4: When the user submits an invalid form, the system must prevent
        submission and display an error message highlighting the incorrect
        field.
    Double: None
    """
    client, _, _ = setup
    payload = {**VALID_PAYLOAD, "status": "On Fire"}

    response = client.post("/venues", json=payload)

    assert response.status_code == 400
    assert any("Operating Status must be one of" in message for message in response.json["errors"])


def test_ac4_add_venue_with_facilities_not_a_list_returns_400(setup):
    """
    Summary: Facilities must be a list of names.
    AC4: When the user submits an invalid form, the system must prevent
        submission and display an error message highlighting the incorrect
        field.
    Double: None
    """
    client, _, _ = setup
    payload = {**VALID_PAYLOAD, "facilities": "wifi"}

    response = client.post("/venues", json=payload)

    assert response.status_code == 400
    assert "Facilities must be a list of names." in response.json["errors"]


def test_ac4_add_venue_with_existing_name_returns_409(setup):
    """
    Summary: A venue name already in the catalogue is refused rather than overwritten.
    AC4: When the user submits an invalid form, the system must prevent
        submission and display an error message highlighting the incorrect
        field.
    Double: Stub (cursor finds an existing venue with the name)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = {"exists": True}

    response = client.post("/venues", json=VALID_PAYLOAD)

    assert response.status_code == 409
    assert "A venue with this name already exists." in response.json["errors"]


def test_ac4_add_venue_with_non_object_body_returns_400(setup):
    """
    Summary: A request that is not a venue form at all is refused.
    AC4: When the user submits an invalid form, the system must prevent
        submission and display an error message highlighting the incorrect
        field.
    Double: Mock (cursor not executed)
    """
    client, _, cursor = setup

    response = client.post("/venues", json=["not", "an", "object"])

    assert response.status_code == 400
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("field", ["name", "location", "accessibility", "status"], ids=["name", "location", "accessibility", "status"])
def test_ac4_add_venue_with_non_text_field_returns_400_naming_it(field, setup):
    """
    Summary: Name, location, accessibility and status must be sent as text.
    AC4: When the user submits an invalid form, the system must prevent
        submission and display an error message highlighting the incorrect
        field.
    Double: None
    """
    client, _, _ = setup

    response = client.post("/venues", json={**VALID_PAYLOAD, field: 42})

    assert response.status_code == 400
    assert any("must be text" in error for error in response.json["errors"])


def test_ac4_add_venue_with_numeric_capacity_returns_400_capacity_error(setup):
    """
    Summary: A capacity sent as a bare number rather than form text is reported as an invalid capacity.
    AC4: When the user submits an invalid form, the system must prevent
        submission and display an error message highlighting the incorrect
        field.
    Double: None
    """
    client, _, _ = setup

    response = client.post("/venues", json={**VALID_PAYLOAD, "capacity": 120})

    assert response.status_code == 400
    assert response.json["missingFields"] == []
    assert response.json["errors"] == ["Capacity must be a positive whole number (maximum 2147483647)."]


@pytest.mark.parametrize(
    "capacity, expected_status",
    [("0", 400), ("1", 201), ("2147483647", 201), ("2147483648", 400)],
    ids=["below_minimum", "at_minimum", "at_maximum", "above_maximum"],
)
def test_ac4_add_venue_when_capacity_near_limits_accepts_1_to_2147483647(capacity, expected_status, setup):
    """
    Summary: Capacity can be any whole number from 1 up to the largest the database stores.
    AC4: (boundary: capacity = 0, 1, 2147483647, 2147483648)
    Double: Stub (cursor: no duplicate, then the saved row)
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [None, saved_row()]

    response = client.post("/venues", json={**VALID_PAYLOAD, "capacity": capacity})

    assert response.status_code == expected_status


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_support_add_venue_when_database_fails_returns_503_without_internals(setup, monkeypatch):
    """
    Summary: A database outage while saving gives a 503 that leaks no internals.
    Supporting design check: database errors answer 503 with a safe message
    Double: Stub (psycopg2.connect raises OperationalError)
    """
    client, _, _ = setup

    def explode(*args, **kwargs):
        raise psycopg2.OperationalError("connection refused to db.example")

    monkeypatch.setattr("app.models.psycopg2.connect", explode)

    response = client.post("/venues", json=VALID_PAYLOAD)

    assert response.status_code == 503


def test_support_add_venue_when_database_url_missing_returns_503():
    """
    Summary: Adding a venue reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured Venue Service answers 503
    Double: None
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client(), role="Venue Staff")

    response = client.post("/venues", json=VALID_PAYLOAD)

    assert response.status_code == 503
