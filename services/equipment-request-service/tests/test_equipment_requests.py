"""SCRUM-33: review equipment requests. Database calls are mocked; no live reads or writes."""
from unittest.mock import MagicMock

import psycopg2
import pytest

from app import create_app

USER_ID = "ad3d6da3-7220-4f80-9157-2ee4abc0455c"
REQUEST_ID = "2a1bfb57-a3c0-4450-897e-cc5c73690000"
EVENT_ID = "4a569df8-b7e4-44a2-af9f-d60000000000"
TS = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Technical Support"}
COORDINATOR = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Event Coordinator"}
ORIGIN = "http://localhost:5174"


def db_row(**overrides):
    row = {
        "equipment_request_id": REQUEST_ID,
        "event_id": EVENT_ID,
        "equipment_id": "2ebcd2d3-636b-48e7-8784-d00000000000",
        "quantity_requested": 15,
        "technical_requirements": "For vendor booths",
        "status": "Pending",
        "reviewed_by": None,
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


def test_health(setup):
    client, _, _ = setup
    assert client.get("/health").json == {"status": "ok"}


def test_ac1_list_returns_requested_equipment_quantity_and_requirements(setup):
    client, cursor, _ = setup
    cursor.fetchall.return_value = [db_row(), db_row(technical_requirements=None, status="Approved", reviewed_by=USER_ID)]

    response = client.get("/equipment-requests", headers=TS)

    assert response.status_code == 200
    first, second = response.json["requests"]
    assert first == {
        "id": REQUEST_ID,
        "eventId": EVENT_ID,
        "equipmentId": "2ebcd2d3-636b-48e7-8784-d00000000000",
        "quantityRequested": 15,
        "technicalRequirements": "For vendor booths",
        "status": "Pending",
        "reviewedBy": None,
    }
    assert second["technicalRequirements"] == "" and second["reviewedBy"] == USER_ID
    assert "WHERE" not in cursor.execute.call_args[0][0]


def test_list_filters_by_status_and_event(setup):
    client, cursor, _ = setup
    cursor.fetchall.return_value = []

    response = client.get(f"/equipment-requests?status=Pending&eventId={EVENT_ID}", headers=TS)

    assert response.json == {"requests": []}
    sql, params = cursor.execute.call_args[0]
    assert "status = %s AND event_id = %s" in sql and params == ["Pending", EVENT_ID]


def test_list_filters_by_several_event_ids_for_the_reservation_composite(setup):
    client, cursor, _ = setup
    cursor.fetchall.return_value = [db_row(status="Approved")]
    other = "5b569df8-b7e4-44a2-af9f-d60000000000"

    response = client.get(f"/equipment-requests?status=Approved&eventIds={EVENT_ID},{other}", headers=TS)

    assert response.status_code == 200
    sql, params = cursor.execute.call_args[0]
    assert "event_id = ANY(%s::uuid[])" in sql and params == ["Approved", [EVENT_ID, other]]


def test_list_with_empty_event_ids_matches_nothing(setup):
    client, cursor, _ = setup
    cursor.fetchall.return_value = []

    assert client.get("/equipment-requests?eventIds=", headers=TS).json == {"requests": []}
    assert cursor.execute.call_args[0][1] == [[]]


@pytest.mark.parametrize("value", ["not-a-uuid", f"{EVENT_ID},bad"])
def test_list_rejects_bad_event_ids(setup, value):
    client, _, connect = setup
    assert client.get(f"/equipment-requests?eventIds={value}", headers=TS).status_code == 400
    connect.assert_not_called()


def test_list_rejects_too_many_event_ids(setup):
    client, _, _ = setup
    assert client.get("/equipment-requests?eventIds=" + ",".join([EVENT_ID] * 501), headers=TS).status_code == 400


def test_get_one_request(setup):
    client, cursor, _ = setup
    cursor.fetchone.return_value = db_row()

    response = client.get(f"/equipment-requests/{REQUEST_ID}", headers=COORDINATOR)

    assert response.status_code == 200 and response.json["request"]["id"] == REQUEST_ID


def test_get_one_request_errors(setup):
    client, cursor, _ = setup
    cursor.fetchone.return_value = None

    assert client.get(f"/equipment-requests/{REQUEST_ID}", headers=TS).status_code == 404
    assert client.get("/equipment-requests/not-a-uuid", headers=TS).status_code == 400
    assert client.get(f"/equipment-requests/{REQUEST_ID}", headers={}).status_code == 401


def test_ac3_event_coordinator_can_read_but_not_review(setup):
    client, cursor, _ = setup
    cursor.fetchall.return_value = [db_row(status="Approved")]

    assert client.get("/equipment-requests", headers=COORDINATOR).json["requests"][0]["status"] == "Approved"
    assert client.patch(f"/equipment-requests/{REQUEST_ID}", headers=COORDINATOR, json={"status": "Approved"}).status_code == 403


@pytest.mark.parametrize("query", ["?status=Broken", "?eventId=not-a-uuid"])
def test_list_rejects_bad_filters(setup, query):
    client, _, connect = setup
    assert client.get(f"/equipment-requests{query}", headers=TS).status_code == 400
    connect.assert_not_called()


@pytest.mark.parametrize(
    "headers,code",
    [({}, 401), ({"X-Dev-User-Id": "bad", "X-Dev-Role": "Technical Support"}, 401), ({"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Attendee"}, 403)],
)
def test_list_requires_authorised_dev_user(setup, headers, code):
    client, _, connect = setup
    assert client.get("/equipment-requests", headers=headers).status_code == code
    connect.assert_not_called()


def test_missing_database_url_is_503():
    client = create_app({"DATABASE_URL": None}).test_client()
    assert client.get("/equipment-requests", headers=TS).status_code == 503


@pytest.mark.parametrize("decision", ["Approved", "Rejected"])
def test_ac2_pending_request_can_be_approved_or_rejected(setup, decision):
    client, cursor, _ = setup
    cursor.fetchone.return_value = db_row(status=decision, reviewed_by=USER_ID)

    response = client.patch(f"/equipment-requests/{REQUEST_ID}", headers=TS, json={"status": decision})

    assert response.status_code == 200
    assert response.json["request"]["status"] == decision
    assert response.json["request"]["reviewedBy"] == USER_ID
    sql, params = cursor.execute.call_args[0]
    assert "status = 'Pending'" in sql and params == [decision, USER_ID, REQUEST_ID]


def test_review_of_already_decided_request_conflicts(setup):
    client, cursor, _ = setup
    cursor.fetchone.side_effect = [None, (1,)]

    response = client.patch(f"/equipment-requests/{REQUEST_ID}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 409


def test_review_of_unknown_request_is_404(setup):
    client, cursor, _ = setup
    cursor.fetchone.side_effect = [None, None]

    assert client.patch(f"/equipment-requests/{REQUEST_ID}", headers=TS, json={"status": "Approved"}).status_code == 404


@pytest.mark.parametrize("payload", [{"status": "Pending"}, {"status": "Maybe"}, {}, [], None])
def test_review_rejects_invalid_status(setup, payload):
    client, _, connect = setup
    assert client.patch(f"/equipment-requests/{REQUEST_ID}", headers=TS, json=payload).status_code == 400
    connect.assert_not_called()


def test_review_rejects_non_uuid_id(setup):
    client, _, connect = setup
    assert client.patch("/equipment-requests/abc", headers=TS, json={"status": "Approved"}).status_code == 400
    connect.assert_not_called()


def test_database_errors_do_not_leak_details(setup):
    client, cursor, _ = setup
    cursor.execute.side_effect = psycopg2.OperationalError("password=secret")

    response = client.get("/equipment-requests", headers=TS)

    assert response.status_code == 503 and "secret" not in response.get_data(as_text=True)


def test_cors_allows_configured_origin_with_patch(setup):
    client, _, _ = setup
    response = client.options("/equipment-requests", headers={"Origin": ORIGIN})
    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert "PATCH" in response.headers["Access-Control-Allow-Methods"]
    assert "Access-Control-Allow-Origin" not in client.get("/health", headers={"Origin": "http://evil.test"}).headers


@pytest.mark.parametrize("decision", ["Approved", "Rejected"])
def test_bulk_review_updates_all_pending_requests_for_event(setup, decision):
    client, cursor, _ = setup
    cursor.fetchall.return_value = [
        db_row(status=decision, reviewed_by=USER_ID),
        db_row(equipment_request_id="3b1bfb57-a3c0-4450-897e-cc5c73690000", status=decision, reviewed_by=USER_ID),
    ]

    response = client.patch(f"/events/{EVENT_ID}/equipment-requests", headers=TS, json={"status": decision})

    assert response.status_code == 200
    assert [request["status"] for request in response.json["requests"]] == [decision, decision]
    sql, params = cursor.execute.call_args[0]
    assert "event_id = %s AND status = 'Pending'" in sql
    assert params == [decision, USER_ID, EVENT_ID]


def test_bulk_review_returns_conflict_when_event_has_no_pending_requests(setup):
    client, cursor, _ = setup
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = (1,)

    response = client.patch(f"/events/{EVENT_ID}/equipment-requests", headers=TS, json={"status": "Approved"})

    assert response.status_code == 409


def test_bulk_review_returns_not_found_when_event_has_no_requests(setup):
    client, cursor, _ = setup
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = None

    response = client.patch(f"/events/{EVENT_ID}/equipment-requests", headers=TS, json={"status": "Approved"})

    assert response.status_code == 404


def test_bulk_review_validates_role_event_id_and_status(setup):
    client, _, connect = setup
    url = f"/events/{EVENT_ID}/equipment-requests"

    assert client.patch(url, headers=COORDINATOR, json={"status": "Approved"}).status_code == 403
    assert client.patch("/events/not-a-uuid/equipment-requests", headers=TS, json={"status": "Approved"}).status_code == 400
    assert client.patch(url, headers=TS, json={"status": "Pending"}).status_code == 400
    connect.assert_not_called()


