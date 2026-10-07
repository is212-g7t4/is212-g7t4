"""List and add equipment. Database calls are mocked; no live reads or writes."""
from unittest.mock import MagicMock

import psycopg2
import pytest

from app import create_app

USER_ID = "ad3d6da3-7220-4f80-9157-2ee4abc0455c"
TS_HEADERS = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Technical Support"}
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
    return app.test_client(), cursor, connect


def body(**overrides):
    payload = {
        "equipmentType": "Projector",
        "description": " 4K laser projector ",
        "totalQuantity": 5,
        "location": " Tech Store ",
    }
    payload.update(overrides)
    return payload


def test_health(setup):
    client, _, _ = setup
    assert client.get("/health").json == {"status": "ok"}


def test_list_returns_serialized_equipment_with_polymorphic_requirements(setup):
    client, cursor, _ = setup
    cursor.fetchall.return_value = [db_row(), db_row(equipment_type="Chair", description="Chair")]

    response = client.get("/equipment")

    assert response.status_code == 200
    items = response.json["equipment"]
    assert [i["type"] for i in items] == ["Projector", "Chair"]
    assert items[0]["setupRequirements"] != items[1]["setupRequirements"]
    assert "WHERE" not in cursor.execute.call_args[0][0]


def test_list_filters_by_status(setup):
    client, cursor, _ = setup
    cursor.fetchall.return_value = []

    response = client.get("/equipment?status=Available")

    assert response.json == {"equipment": []}
    sql, params = cursor.execute.call_args[0]
    assert "operational_status = %s" in sql and params == ["Available"]


def test_list_rejects_unknown_status(setup):
    client, _, connect = setup
    assert client.get("/equipment?status=Broken").status_code == 400
    connect.assert_not_called()


def test_list_without_database_url_is_503():
    client = create_app({"DATABASE_URL": None}).test_client()
    assert client.get("/equipment").status_code == 503


def test_database_error_is_503_and_generic(setup):
    client, _, connect = setup
    connect.side_effect = psycopg2.OperationalError("secret host")
    response = client.get("/equipment")
    assert response.status_code == 503
    assert "secret" not in response.json["message"]


def test_create_returns_201_and_trims_values(setup):
    client, cursor, _ = setup
    cursor.fetchone.return_value = db_row()

    response = client.post("/equipment", json=body(), headers=TS_HEADERS)

    assert response.status_code == 201
    assert response.json["equipment"]["type"] == "Projector"
    assert cursor.execute.call_args[0][1] == [
        "Projector", "4K laser projector", 5, "Tech Store", "Available"
    ]


def test_create_accepts_a_custom_type_and_trims_it(setup):
    client, cursor, _ = setup
    cursor.fetchone.return_value = db_row(equipment_type="Drone")
    response = client.post("/equipment", json=body(equipmentType="  Drone "), headers=TS_HEADERS)
    assert response.status_code == 201
    assert cursor.execute.call_args[0][1][0] == "Drone"
    assert response.json["equipment"]["setupRequirements"]  # base-class fallback


def test_create_canonicalises_known_type_casing(setup):
    client, cursor, _ = setup
    cursor.fetchone.return_value = db_row(equipment_type="LightingKit")
    client.post("/equipment", json=body(equipmentType="lightingkit"), headers=TS_HEADERS)
    assert cursor.execute.call_args[0][1][0] == "LightingKit"


def test_create_accepts_explicit_status(setup):
    client, cursor, _ = setup
    cursor.fetchone.return_value = db_row(operational_status="Unavailable")
    response = client.post("/equipment", json=body(status="Unavailable"), headers=TS_HEADERS)
    assert response.status_code == 201
    assert cursor.execute.call_args[0][1][-1] == "Unavailable"


def test_create_requires_dev_headers(setup):
    client, _, connect = setup
    assert client.post("/equipment", json=body()).status_code == 401
    assert client.post(
        "/equipment", json=body(), headers={"X-Dev-User-Id": "nope", "X-Dev-Role": "Technical Support"}
    ).status_code == 401
    connect.assert_not_called()


def test_create_forbidden_for_other_roles(setup):
    client, _, connect = setup
    headers = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Event Coordinator"}
    assert client.post("/equipment", json=body(), headers=headers).status_code == 403
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
)
def test_create_validation_errors_are_400(setup, payload):
    client, _, connect = setup
    response = client.post("/equipment", json=payload, headers=TS_HEADERS)
    assert response.status_code == 400
    connect.assert_not_called()


def test_create_with_invalid_json_is_400(setup):
    client, _, _ = setup
    response = client.post(
        "/equipment", data="{bad", content_type="application/json", headers=TS_HEADERS
    )
    assert response.status_code == 400


def test_create_without_database_url_is_503():
    client = create_app({"DATABASE_URL": None}).test_client()
    assert client.post("/equipment", json=body(), headers=TS_HEADERS).status_code == 503


def test_cors_allows_post_and_dev_headers_for_frontend_origin(setup):
    client, _, _ = setup
    response = client.options("/equipment", headers={"Origin": ORIGIN})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert "POST" in response.headers["Access-Control-Allow-Methods"]
    assert "X-Dev-Role" in response.headers["Access-Control-Allow-Headers"]
