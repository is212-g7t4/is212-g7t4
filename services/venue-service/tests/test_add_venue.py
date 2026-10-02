"""SCRUM-22 Add Venue — POST /venues on Venue Service.

AC1: input fields exist for name, location, capacity, facilities,
accessibility, supported layouts and operating status (frontend concern;
this file covers the fields the backend accepts and persists).
AC2: a blank mandatory field is rejected with 400 and missingFields naming it.
AC3: a valid submission is saved and returned in the same shape the catalogue
reads (`app.models.serialize`), so it is immediately visible there.
AC4: an invalid (but non-blank) field is rejected with 400 and errors naming it.

Database calls are mocked; no live database reads or writes.
"""
from unittest.mock import MagicMock

import psycopg2
import pytest

from app import create_app

VENUE_ID = "8381b11e-aaae-4d58-bdba-2607e9e2bde2"

VALID_PAYLOAD = {
    "name": "Sky Lounge",
    "location": "Level 20, Main Tower",
    "capacity": "80",
    "facilities": ["wifi", "projector"],
    "accessibility": "Wheelchair accessible",
    "supportedLayouts": ["theatre", "classroom"],
    "status": "Available",
}


def saved_row(**overrides):
    row = {
        "venue_id": VENUE_ID,
        "venue_name": "Sky Lounge",
        "location": "Level 20, Main Tower",
        "max_capacity": 80,
        "facilities": {"wifi": True, "projector": True},
        "accessibility": "Wheelchair accessible",
        "supported_layouts": ["theatre", "classroom"],
        "operational_status": "Available",
    }
    row.update(overrides)
    return row


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), connection, cursor


def test_ac3_valid_submission_is_saved_and_visible_in_catalogue(setup):
    """AC3: a valid form is saved and comes back in the catalogue's shape."""
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
    }


def test_ac3_facilities_are_saved_as_a_jsonb_object(setup):
    """AC3: facilities are persisted in the shape the catalogue's serializer expects."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [None, saved_row()]

    client.post("/venues", json=VALID_PAYLOAD)

    insert_query, insert_params = cursor.execute.call_args_list[-1].args
    assert 'INSERT INTO public."Venue"' in insert_query
    assert insert_params[3].adapted == {"wifi": True, "projector": True}


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
)
def test_ac2_blank_mandatory_field_is_rejected(field, label, setup):
    """AC2: each mandatory field, left blank, blocks submission and is named."""
    client, _, cursor = setup
    payload = {**VALID_PAYLOAD, field: "" if isinstance(VALID_PAYLOAD[field], str) else []}

    response = client.post("/venues", json=payload)

    assert response.status_code == 400
    assert label in response.json["missingFields"]
    cursor.execute.assert_not_called()


def test_ac2_missing_field_entirely_is_rejected(setup):
    """AC2 boundary: a field omitted from the payload is treated as missing."""
    client, _, _ = setup
    payload = {key: value for key, value in VALID_PAYLOAD.items() if key != "name"}

    response = client.post("/venues", json=payload)

    assert response.status_code == 400
    assert response.json["missingFields"] == ["Venue Name"]


def test_ac4_non_numeric_capacity_is_rejected(setup):
    """AC4: capacity must be a positive whole number, not arbitrary text."""
    client, _, cursor = setup
    payload = {**VALID_PAYLOAD, "capacity": "not-a-number"}

    response = client.post("/venues", json=payload)

    assert response.status_code == 400
    assert "Capacity must be a positive whole number (maximum 2147483647)." in response.json["errors"]
    cursor.execute.assert_not_called()


def test_ac4_zero_capacity_is_rejected(setup):
    """AC4 boundary: capacity must be at least 1."""
    client, _, _ = setup
    payload = {**VALID_PAYLOAD, "capacity": "0"}

    response = client.post("/venues", json=payload)

    assert response.status_code == 400
    assert "Capacity must be a positive whole number (maximum 2147483647)." in response.json["errors"]


def test_ac4_unknown_status_is_rejected(setup):
    """AC4: operating status must be one of the recognised values."""
    client, _, _ = setup
    payload = {**VALID_PAYLOAD, "status": "On Fire"}

    response = client.post("/venues", json=payload)

    assert response.status_code == 400
    assert any("Operating Status must be one of" in message for message in response.json["errors"])


def test_ac4_non_list_facilities_is_rejected(setup):
    """AC4: facilities must be a list of names, not a single string."""
    client, _, _ = setup
    payload = {**VALID_PAYLOAD, "facilities": "wifi"}

    response = client.post("/venues", json=payload)

    assert response.status_code == 400
    assert "Facilities must be a list of names." in response.json["errors"]


def test_conflict_duplicate_venue_name_returns_409(setup):
    """Conflict: a venue name already in the catalogue is rejected, not silently overwritten."""
    client, _, cursor = setup
    cursor.fetchone.return_value = {"exists": True}

    response = client.post("/venues", json=VALID_PAYLOAD)

    assert response.status_code == 409
    assert "A venue with this name already exists." in response.json["errors"]


def test_non_object_json_body_is_rejected(setup):
    """Failure: valid JSON with the wrong top-level shape is rejected."""
    client, _, cursor = setup

    response = client.post("/venues", json=["not", "an", "object"])

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_database_error_returns_503(setup, monkeypatch):
    """Failure: a database outage while saving is a 503 that leaks no internals."""
    client, _, _ = setup

    def explode(*args, **kwargs):
        raise psycopg2.OperationalError("connection refused to db.example")

    monkeypatch.setattr("app.models.psycopg2.connect", explode)

    response = client.post("/venues", json=VALID_PAYLOAD)

    assert response.status_code == 503


def test_missing_database_url_returns_503():
    """Failure: an unconfigured service says so rather than crashing."""
    client = create_app({"TESTING": True, "DATABASE_URL": None}).test_client()

    response = client.post("/venues", json=VALID_PAYLOAD)

    assert response.status_code == 503
