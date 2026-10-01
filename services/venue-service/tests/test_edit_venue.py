"""SCRUM-23 Edit Venue — PUT /venues/<id> on Venue Service."""
from unittest.mock import MagicMock

import pytest

from app import create_app
from test_add_venue import saved_row, VALID_PAYLOAD, VENUE_ID


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
    assert update_params[-1] == VENUE_ID


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