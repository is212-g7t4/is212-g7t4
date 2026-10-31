"""SCRUM-31: Equipment Catalogue

User Story
----------
As a Technical Support Staff member, I want to add equipment records in the catalogue so that the system reflects our current physical inventory.

Acceptance Criteria
-------------------
AC1: Can input and add new equipment records
AC2: Must display the list of available equipments

Real
----
- GET /equipment and POST /equipment: the status filter, payload validation and
  trimming, type canonicalisation, the Technical Support role check and
  serialisation (including each type's setup requirements) run for real.
- Assertions are on the status, the returned items and the values sent to the
  database.

Doubled
-------
- psycopg2.connect: Stub / Mock - the cursor returns canned Equipment rows;
  execute() arguments are inspected to prove what is stored or filtered, and
  connect is asserted not called when a request is refused early.

Not proven
----------
- AC1: Local validation, canonicalisation, caller-role gate, INSERT values and serialised replies are checked, not committed rows.
- AC2: Local list/status-filter SQL construction and response values are checked here. Real query filtering and committed creation are checked in tests/integration/test_scrum31_equipment_catalogue_api.py using fixture-owned PostgreSQL.
- Browser form/list presentation is outside this owner and not executed here.
- Technical field/type/status/size restrictions are supporting design rules; SCRUM-31 does not specify their exact limits. Related write-role obligation is SCRUM-10; no event relationship is involved in catalogue creation.
"""
from unittest.mock import MagicMock

import psycopg2
import pytest

from app import create_app
from tests.unit.factories import bearer

USER_ID = "ad3d6da3-7220-4f80-9157-2ee4abc0455c"
TS_HEADERS = bearer(USER_ID, "Technical Support")
ORIGIN = "http://localhost:5173"


def db_row(**overrides):
    row = {
        "equipment_id": "22222222-2222-2222-2222-222222222222",
        "equipment_type": "Projector",
        "description": "4K laser projector",
        "total_quantity": 5,
        "location": "Tech Store",
        "operational_status": "Available",
    }
    row.update(overrides)
    return row


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr("app.models.psycopg2.connect", connect)
    app = create_app({"DATABASE_URL": "postgresql://x", "FRONTEND_ORIGIN": ORIGIN})
    client = app.test_client()
    client.environ_base["HTTP_AUTHORIZATION"] = bearer(USER_ID, "Event Coordinator")["Authorization"]
    return client, cursor, connect


def body(**overrides):
    payload = {
        "equipmentType": "Projector",
        "description": " 4K laser projector ",
        "totalQuantity": 5,
        "location": " Tech Store ",
    }
    payload.update(overrides)
    return payload


def test_list_equipment_returns_items_with_type_specific_setup_requirements(setup):
    """Summary: The catalogue lists every item with the setup requirements for its type.
AC2: Must display the list of available equipments
Double: Stub (database cursor rows and local Supabase signing key), Mock (database write/filter parameters or refusal without connecting).
"""
    client, cursor, _ = setup
    cursor.fetchall.return_value = [db_row(), db_row(equipment_type="Chair", description="Chair")]

    response = client.get("/equipment")

    assert response.status_code == 200
    items = response.json["equipment"]
    assert [i["type"] for i in items] == ["Projector", "Chair"]
    assert items[0]["setupRequirements"] != items[1]["setupRequirements"]
    assert [(i["description"], i["totalQuantity"], i["location"], i["status"]) for i in items] == [
        ("4K laser projector", 5, "Tech Store", "Available"),
        ("Chair", 5, "Tech Store", "Available"),
    ]
    assert "WHERE" not in cursor.execute.call_args[0][0]


def test_list_equipment_with_status_filter_queries_only_that_status(setup):
    """Summary: The list can be narrowed to equipment with one operational status, such as Available.
AC2: Must display the list of available equipments
Double: Stub (database cursor rows and local Supabase signing key), Mock (database write/filter parameters or refusal without connecting).
"""
    client, cursor, _ = setup
    cursor.fetchall.return_value = []

    response = client.get("/equipment?status=Available")

    assert response.json == {"equipment": []}
    sql, params = cursor.execute.call_args[0]
    assert "operational_status = %s" in sql and params == ["Available"]


def test_list_equipment_with_unknown_status_returns_400_without_query(setup):
    """Summary: Asking for a status that does not exist is refused without touching the database.
AC2: Must display the list of available equipments
Double: Stub (database cursor rows and local Supabase signing key), Mock (database write/filter parameters or refusal without connecting).
"""
    client, _, connect = setup
    assert client.get("/equipment?status=Broken").status_code == 400
    connect.assert_not_called()


def test_create_equipment_with_valid_record_returns_201_and_stores_trimmed_values(setup):
    """Summary: Technical Support can add an equipment record, stored without stray spaces and Available by default.
AC1: Can input and add new equipment records
Double: Stub (database cursor rows and local Supabase signing key), Mock (database write/filter parameters or refusal without connecting).
"""
    client, cursor, _ = setup
    cursor.fetchone.return_value = db_row()

    response = client.post("/equipment", json=body(), headers=TS_HEADERS)

    assert response.status_code == 201
    assert response.json["equipment"] == {
        "id": "22222222-2222-2222-2222-222222222222", "type": "Projector",
        "description": "4K laser projector", "totalQuantity": 5,
        "location": "Tech Store", "status": "Available",
        "setupRequirements": "Mount or place on a stable surface, connect HDMI and a power outlet, then align the image.",
    }
    assert cursor.execute.call_args[0][1] == [
        "Projector", "4K laser projector", 5, "Tech Store", "Available"
    ]


def test_create_equipment_with_custom_type_stores_it_with_generic_requirements(setup):
    """Summary: A type outside the known list can still be added and gets generic setup requirements.
AC1: Can input and add new equipment records
Double: Stub (database cursor rows and local Supabase signing key), Mock (database write/filter parameters or refusal without connecting).
"""
    client, cursor, _ = setup
    cursor.fetchone.return_value = db_row(equipment_type="Drone")
    response = client.post("/equipment", json=body(equipmentType="  Drone "), headers=TS_HEADERS)
    assert response.status_code == 201
    assert cursor.execute.call_args[0][1][0] == "Drone"
    assert response.json["equipment"]["setupRequirements"] == "Check the item is present and working before the event."


def test_create_equipment_with_known_type_in_other_casing_stores_canonical_name(setup):
    """Summary: A known type typed in different casing is stored under its standard name.
AC1: Can input and add new equipment records
Double: Stub (database cursor rows and local Supabase signing key), Mock (database write/filter parameters or refusal without connecting).
"""
    client, cursor, _ = setup
    cursor.fetchone.return_value = db_row(equipment_type="LightingKit")
    response = client.post("/equipment", json=body(equipmentType="lightingkit"), headers=TS_HEADERS)
    assert response.status_code == 201
    assert response.json["equipment"]["type"] == "LightingKit"
    assert cursor.execute.call_args[0][1][0] == "LightingKit"


def test_create_equipment_with_explicit_status_stores_that_status(setup):
    """Summary: An item can be added with an operational status other than Available.
AC1: Can input and add new equipment records
Double: Stub (database cursor rows and local Supabase signing key), Mock (database write/filter parameters or refusal without connecting).
"""
    client, cursor, _ = setup
    cursor.fetchone.return_value = db_row(operational_status="Unavailable")
    response = client.post("/equipment", json=body(status="Unavailable"), headers=TS_HEADERS)
    assert response.status_code == 201
    assert cursor.execute.call_args[0][1][-1] == "Unavailable"


def test_create_equipment_with_dev_role_header_returns_403_without_saving(setup):
    """Summary: A retired developer role header does not grant the right to add equipment.
AC1: Can input and add new equipment records
Double: Stub (database cursor rows and local Supabase signing key), Mock (database write/filter parameters or refusal without connecting).
"""
    # Arrange (Given)
    client, _, connect = setup
    headers = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Technical Support"}

    # Act + Assert (When / Then)
    assert client.post("/equipment", json=body(), headers=headers).status_code == 403
    connect.assert_not_called()


def test_create_equipment_when_role_not_technical_support_returns_403(setup):
    """Summary: Only Technical Support can add equipment records.
AC1: Can input and add new equipment records
Double: Stub (database cursor rows and local Supabase signing key), Mock (database write/filter parameters or refusal without connecting).
"""
    # Arrange (Given)
    client, _, connect = setup

    # Act + Assert (When / Then)
    assert client.post("/equipment", json=body(), headers=bearer(USER_ID, "Event Coordinator")).status_code == 403
    connect.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        body(equipmentType="   "),
        body(equipmentType=None),
        body(equipmentType="x" * 101),
        body(description="  "),
        body(description=5),
        body(totalQuantity=-1),
        body(totalQuantity="5"),
        body(totalQuantity=True),
        body(totalQuantity=1.5),
        body(location=""),
        body(status="Broken"),
        ["not", "an", "object"],
    ],
    ids=["blank_type", "missing_type", "type_too_long", "blank_description", "non_text_description", "negative_quantity", "quantity_as_text", "quantity_as_bool", "fractional_quantity", "blank_location", "unknown_status", "non_object_body"],
)
def test_create_equipment_with_invalid_field_returns_400_without_saving(setup, payload):
    """Summary: A record with a missing or malformed field is refused before anything is stored.
AC1: Can input and add new equipment records
Double: Stub (database cursor rows and local Supabase signing key), Mock (database write/filter parameters or refusal without connecting).
"""
    client, _, connect = setup
    response = client.post("/equipment", json=payload, headers=TS_HEADERS)
    assert response.status_code == 400
    connect.assert_not_called()


def test_create_equipment_with_malformed_json_returns_400(setup):
    """Summary: A request body that is not valid JSON is refused.
AC1: Can input and add new equipment records
Double: Stub (database cursor rows and local Supabase signing key), Mock (database write/filter parameters or refusal without connecting).
"""
    client, _, _ = setup
    response = client.post(
        "/equipment", data="{bad", content_type="application/json", headers=TS_HEADERS
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "quantity, expected_status",
    [(-1, 400), (0, 201), (1, 201)],
    ids=["below_zero", "at_zero", "above_zero"],
)
def test_create_equipment_when_quantity_near_zero_accepts_zero_and_above(setup, quantity, expected_status):
    """Summary: An item can be recorded with none in stock, but never a negative quantity.
AC1: Can input and add new equipment records
Double: Stub (database cursor rows and local Supabase signing key), Mock (database write/filter parameters or refusal without connecting).
"""
    client, cursor, _ = setup
    cursor.fetchone.return_value = db_row(total_quantity=quantity)

    response = client.post("/equipment", json=body(totalQuantity=quantity), headers=TS_HEADERS)

    assert response.status_code == expected_status
    if expected_status == 201:
        assert response.json["equipment"]["type"] == cursor.fetchone.return_value["equipment_type"]
        assert response.json["equipment"]["totalQuantity"] == cursor.fetchone.return_value["total_quantity"]
        assert cursor.execute.call_count == 1
    else:
        assert cursor.execute.call_count == 0


@pytest.mark.parametrize(
    "length, expected_status",
    [(99, 201), (100, 201), (101, 400)],
    ids=["below_limit", "at_limit", "above_limit"],
)
def test_create_equipment_when_type_name_near_limit_accepts_up_to_100_characters(setup, length, expected_status):
    """Summary: An equipment type name can be up to 100 characters long.
AC1: Can input and add new equipment records
Double: Stub (database cursor rows and local Supabase signing key), Mock (database write/filter parameters or refusal without connecting).
"""
    client, cursor, _ = setup
    cursor.fetchone.return_value = db_row(equipment_type="x" * length)

    response = client.post("/equipment", json=body(equipmentType="x" * length), headers=TS_HEADERS)

    assert response.status_code == expected_status
    if expected_status == 201:
        assert response.json["equipment"]["type"] == cursor.fetchone.return_value["equipment_type"]
        assert response.json["equipment"]["totalQuantity"] == cursor.fetchone.return_value["total_quantity"]
        assert cursor.execute.call_count == 1
    else:
        assert cursor.execute.call_count == 0
