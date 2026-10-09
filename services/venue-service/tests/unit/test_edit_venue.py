"""SCRUM-23 Edit Venue — PUT /venues/<id> on Venue Service."""
from unittest.mock import MagicMock

import psycopg2
import pytest

from app import create_app
from tests.unit.factories import VALID_PAYLOAD, VENUE_ID, saved_row


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), cursor


def test_ac2_edit_saves_current_venue_fields_and_status(setup):
    """AC1-3: PUT updates all fields and returns the saved profile, including status."""
    client, cursor = setup
    cursor.fetchone.side_effect = [None, saved_row(
        venue_name="Updated Lounge",
        location="Level 21",
        max_capacity=100,
        facilities={"wifi": True, "stage": True},
        accessibility="Step-free access",
        supported_layouts=["theatre"],
        operational_status="Under Maintenance",
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
    }
    update_query, update_params = cursor.execute.call_args_list[-1].args
    assert 'UPDATE public."Venue"' in update_query
    assert update_params[3].adapted == {"wifi": True, "stage": True}
    assert update_params[-1] == VENUE_ID


def test_edit_keeps_existing_name_without_duplicate_conflict(setup):
    """Keeping this venue's own name must not conflict with itself."""
    client, cursor = setup
    cursor.fetchone.side_effect = [None, saved_row()]

    response = client.put(f"/venues/{VENUE_ID}", json=VALID_PAYLOAD)

    assert response.status_code == 200
    duplicate_query, duplicate_params = cursor.execute.call_args_list[0].args
    assert "venue_id <> %s" in duplicate_query
    assert duplicate_params == [VALID_PAYLOAD["name"], VENUE_ID]


def test_duplicate_name_from_another_venue_returns_409(setup):
    client, cursor = setup
    cursor.fetchone.return_value = {"exists": True}

    response = client.put(f"/venues/{VENUE_ID}", json={**VALID_PAYLOAD, "name": "Taken"})

    assert response.status_code == 409
    assert "A venue with this name already exists." in response.json["errors"]
    assert cursor.execute.call_count == 1


def test_edit_rejects_invalid_status_without_database_write(setup):
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
)
def test_edit_rejects_blank_required_field(field, label, setup):
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
)
def test_edit_rejects_omitted_required_field(field, label, setup):
    client, cursor = setup
    payload = {key: value for key, value in VALID_PAYLOAD.items() if key != field}

    response = client.put(f"/venues/{VENUE_ID}", json=payload)

    assert response.status_code == 400
    assert label in response.json["missingFields"]
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("capacity", ["not-a-number", "0"])
def test_edit_rejects_invalid_capacity_without_database_write(capacity, setup):
    client, cursor = setup

    response = client.put(
        f"/venues/{VENUE_ID}", json={**VALID_PAYLOAD, "capacity": capacity}
    )

    assert response.status_code == 400
    assert "Capacity must be a positive whole number (maximum 2147483647)." in response.json["errors"]
    cursor.execute.assert_not_called()


def test_edit_rejects_non_list_facilities_without_database_write(setup):
    client, cursor = setup

    response = client.put(
        f"/venues/{VENUE_ID}", json={**VALID_PAYLOAD, "facilities": "wifi"}
    )

    assert response.status_code == 400
    assert "Facilities must be a list of names." in response.json["errors"]
    cursor.execute.assert_not_called()


def test_edit_rejects_non_object_json_body(setup):
    client, cursor = setup

    response = client.put(f"/venues/{VENUE_ID}", json=["not", "an", "object"])

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_edit_unknown_venue_returns_404(setup):
    client, cursor = setup
    cursor.fetchone.side_effect = [None, None]

    response = client.put(f"/venues/{VENUE_ID}", json=VALID_PAYLOAD)

    assert response.status_code == 404
    assert response.json["message"] == "Venue not found."


def test_edit_preflight_allows_put(setup):
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


def test_edit_database_error_returns_503(setup, monkeypatch):
    client, _ = setup

    def explode(*args, **kwargs):
        raise psycopg2.OperationalError("connection refused to db.example")

    monkeypatch.setattr("app.models.psycopg2.connect", explode)

    response = client.put(f"/venues/{VENUE_ID}", json=VALID_PAYLOAD)

    assert response.status_code == 503


def test_edit_missing_database_url_returns_503():
    client = create_app({"TESTING": True, "DATABASE_URL": None}).test_client()

    response = client.put(f"/venues/{VENUE_ID}", json=VALID_PAYLOAD)

    assert response.status_code == 503