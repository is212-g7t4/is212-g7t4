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


# Supporting service health check; no story AC is directly verified.
def test_health(setup):
    client, _, _ = setup
    assert client.get("/health").json == {"status": "ok"}


# Review AC1: return equipment IDs, quantities and technical requirements; catalogue types are composed separately.
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


# Review AC1/AC2 / Reservation AC2: filter request records by their event ID and decision status.
def test_list_filters_by_status_and_event(setup):
    client, cursor, _ = setup
    cursor.fetchall.return_value = []

    response = client.get(f"/equipment-requests?status=Pending&eventId={EVENT_ID}", headers=TS)

    assert response.json == {"requests": []}
    sql, params = cursor.execute.call_args[0]
    assert "status = %s AND event_id = %s" in sql and params == ["Pending", EVENT_ID]


# Reservation AC1/AC2: retrieve Approved records for the specified overlapping event IDs.
def test_list_filters_by_several_event_ids_for_the_reservation_composite(setup):
    client, cursor, _ = setup
    cursor.fetchall.return_value = [db_row(status="Approved")]
    other = "5b569df8-b7e4-44a2-af9f-d60000000000"

    response = client.get(f"/equipment-requests?status=Approved&eventIds={EVENT_ID},{other}", headers=TS)

    assert response.status_code == 200
    sql, params = cursor.execute.call_args[0]
    assert "event_id = ANY(%s::uuid[])" in sql and params == ["Approved", [EVENT_ID, other]]


# Review AC3 (access boundary): an empty assigned-event scope must not expose every request.
def test_list_with_empty_event_ids_matches_nothing(setup):
    client, cursor, _ = setup
    cursor.fetchall.return_value = []

    assert client.get("/equipment-requests?eventIds=", headers=TS).json == {"requests": []}
    assert cursor.execute.call_args[0][1] == [[]]


@pytest.mark.parametrize("value", ["not-a-uuid", f"{EVENT_ID},bad"])
def test_list_rejects_bad_event_ids(setup, value):
    # Review AC1 / Reservation AC2 (validation): require valid event references for scoped reads.
    client, _, connect = setup
    assert client.get(f"/equipment-requests?eventIds={value}", headers=TS).status_code == 400
    connect.assert_not_called()


# Review AC1 (supporting validation): bound the event-scoped lookup size.
def test_list_rejects_too_many_event_ids(setup):
    client, _, _ = setup
    assert client.get("/equipment-requests?eventIds=" + ",".join([EVENT_ID] * 501), headers=TS).status_code == 400


# Review AC1/AC3: return an individual request to an authorized coordinator reader.
def test_get_one_request(setup):
    client, cursor, _ = setup
    cursor.fetchone.return_value = db_row()

    response = client.get(f"/equipment-requests/{REQUEST_ID}", headers=COORDINATOR)

    assert response.status_code == 200 and response.json["request"]["id"] == REQUEST_ID


# Review AC1 (failure/access): reject invalid, missing and anonymous request lookups.
def test_get_one_request_errors(setup):
    client, cursor, _ = setup
    cursor.fetchone.return_value = None

    assert client.get(f"/equipment-requests/{REQUEST_ID}", headers=TS).status_code == 404
    assert client.get("/equipment-requests/not-a-uuid", headers=TS).status_code == 400
    assert client.get(f"/equipment-requests/{REQUEST_ID}", headers={}).status_code == 401


# Review AC2/AC3: coordinators may read a saved Approved status but cannot perform staff decisions.
def test_ac3_event_coordinator_can_read_but_not_review(setup):
    client, cursor, _ = setup
    cursor.fetchall.return_value = [db_row(status="Approved")]

    assert client.get("/equipment-requests", headers=COORDINATOR).json["requests"][0]["status"] == "Approved"
    assert client.patch(f"/equipment-requests/{REQUEST_ID}", headers=COORDINATOR, json={"status": "Approved"}).status_code == 403


@pytest.mark.parametrize("query", ["?status=Broken", "?eventId=not-a-uuid"])
def test_list_rejects_bad_filters(setup, query):
    # Review AC1/AC2 (validation): reject invalid event and status filters.
    client, _, connect = setup
    assert client.get(f"/equipment-requests{query}", headers=TS).status_code == 400
    connect.assert_not_called()


@pytest.mark.parametrize(
    "headers,code",
    [({}, 401), ({"X-Dev-User-Id": "bad", "X-Dev-Role": "Technical Support"}, 401), ({"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Attendee"}, 403)],
)
def test_list_requires_authorised_dev_user(setup, headers, code):
    # Review AC1/AC3 (access): require an identified user with a permitted reader role.
    client, _, connect = setup
    assert client.get("/equipment-requests", headers=headers).status_code == code
    connect.assert_not_called()


# Review AC1 (infrastructure failure): report an unconfigured database without claiming successful reads.
def test_missing_database_url_is_503():
    client = create_app({"DATABASE_URL": None}).test_client()
    assert client.get("/equipment-requests", headers=TS).status_code == 503


@pytest.mark.parametrize("decision", ["Approved", "Rejected"])
def test_ac2_pending_request_can_be_approved_or_rejected(setup, decision):
    # Review AC2 / Reservation AC2: save the decision and reviewer on the existing event-linked request.
    client, cursor, _ = setup
    cursor.fetchone.return_value = db_row(status=decision, reviewed_by=USER_ID)

    response = client.patch(f"/equipment-requests/{REQUEST_ID}", headers=TS, json={"status": decision})

    assert response.status_code == 200
    assert response.json["request"]["status"] == decision
    assert response.json["request"]["reviewedBy"] == USER_ID
    sql, params = cursor.execute.call_args[0]
    assert "status = 'Pending'" in sql and params == [decision, USER_ID, REQUEST_ID]


# Review AC2 (conflict): an already-decided request cannot be reviewed a second time.
def test_review_of_already_decided_request_conflicts(setup):
    client, cursor, _ = setup
    cursor.fetchone.side_effect = [None, (1,)]

    response = client.patch(f"/equipment-requests/{REQUEST_ID}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 409


# Review AC2 (failure): do not update a nonexistent equipment request.
def test_review_of_unknown_request_is_404(setup):
    client, cursor, _ = setup
    cursor.fetchone.side_effect = [None, None]

    assert client.patch(f"/equipment-requests/{REQUEST_ID}", headers=TS, json={"status": "Approved"}).status_code == 404


@pytest.mark.parametrize("payload", [{"status": "Pending"}, {"status": "Maybe"}, {}, [], None])
def test_review_rejects_invalid_status(setup, payload):
    # Review AC2 (validation): reject unsupported or missing decision values.
    client, _, connect = setup
    assert client.patch(f"/equipment-requests/{REQUEST_ID}", headers=TS, json=payload).status_code == 400
    connect.assert_not_called()


# Review AC2 (validation): decisions require a valid equipment-request ID.
def test_review_rejects_non_uuid_id(setup):
    client, _, connect = setup
    assert client.patch("/equipment-requests/abc", headers=TS, json={"status": "Approved"}).status_code == 400
    connect.assert_not_called()


# Review AC1 (failure): report unavailable storage without exposing database credentials.
def test_database_errors_do_not_leak_details(setup):
    client, cursor, _ = setup
    cursor.execute.side_effect = psycopg2.OperationalError("password=secret")

    response = client.get("/equipment-requests", headers=TS)

    assert response.status_code == 503 and "secret" not in response.get_data(as_text=True)


# Review AC1/AC2 (supporting transport): permit frontend reads and status-update requests.
def test_cors_allows_configured_origin_with_patch(setup):
    client, _, _ = setup
    response = client.options("/equipment-requests", headers={"Origin": ORIGIN})
    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert "PATCH" in response.headers["Access-Control-Allow-Methods"]
    assert "Access-Control-Allow-Origin" not in client.get("/health", headers={"Origin": "http://evil.test"}).headers


@pytest.mark.parametrize("decision", ["Approved", "Rejected"])
def test_bulk_review_updates_all_pending_requests_for_event(setup, decision):
    # Review AC2 / Reservation AC2: update only Pending records belonging to the supplied event ID.
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


# Review AC2 (conflict): an event without Pending lines cannot receive another bulk decision.
def test_bulk_review_returns_conflict_when_event_has_no_pending_requests(setup):
    client, cursor, _ = setup
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = (1,)

    response = client.patch(f"/events/{EVENT_ID}/equipment-requests", headers=TS, json={"status": "Approved"})

    assert response.status_code == 409


# Review AC2 / Reservation AC2 (failure): reject bulk decisions for an event without request records.
def test_bulk_review_returns_not_found_when_event_has_no_requests(setup):
    client, cursor, _ = setup
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = None

    response = client.patch(f"/events/{EVENT_ID}/equipment-requests", headers=TS, json={"status": "Approved"})

    assert response.status_code == 404


# Review AC2 / Reservation AC2 (validation): bulk updates require staff identity, a valid event and a decision.
def test_bulk_review_validates_role_event_id_and_status(setup):
    client, _, connect = setup
    url = f"/events/{EVENT_ID}/equipment-requests"

    assert client.patch(url, headers=COORDINATOR, json={"status": "Approved"}).status_code == 403
    assert client.patch("/events/not-a-uuid/equipment-requests", headers=TS, json={"status": "Approved"}).status_code == 400
    assert client.patch(url, headers=TS, json={"status": "Pending"}).status_code == 400
    connect.assert_not_called()


# --- create (Event Coordinator submits equipment request lines) -------------

MIC = "2ebcd2d3-636b-48e7-8784-d00000000000"
TABLE = "3ebcd2d3-636b-48e7-8784-d00000000000"


def item(equipment_id=MIC, quantity=2, requirements="  Two handheld  "):
    return {"equipmentId": equipment_id, "quantityRequested": quantity, "technicalRequirements": requirements}


# Create request AC1/AC2/AC3: persist equipment needs against the event with an initial Pending status.
def test_create_saves_every_line_as_pending_for_the_event(setup):
    client, cursor, connect = setup
    cursor.fetchone.side_effect = [
        db_row(equipment_id=MIC, quantity_requested=2, technical_requirements="Two handheld"),
        db_row(equipment_request_id="3b1bfb57-a3c0-4450-897e-cc5c73690000", equipment_id=TABLE,
               quantity_requested=5, technical_requirements=None),
    ]

    response = client.post(
        f"/events/{EVENT_ID}/equipment-requests",
        headers=COORDINATOR,
        json={"items": [item(), item(TABLE, 5, "")]},
    )

    assert response.status_code == 201
    assert [(r["equipmentId"], r["quantityRequested"], r["status"]) for r in response.json["requests"]] == [
        (MIC, 2, "Pending"), (TABLE, 5, "Pending"),
    ]
    assert connect.call_count == 1
    inserts = [call.args for call in cursor.execute.call_args_list]
    assert all("INSERT INTO public.\"EquipmentRequest\"" in sql and "'Pending'" in sql for sql, _ in inserts)
    assert all("requested_by, requested_at" in sql and "CURRENT_TIMESTAMP" in sql for sql, _ in inserts)
    assert [params for _, params in inserts] == [
        [EVENT_ID, MIC, 2, "Two handheld", USER_ID],
        [EVENT_ID, TABLE, 5, None, USER_ID],
    ]


# Create request AC1 (supporting audit): record the caller; submission time is not the event schedule in AC2.
def test_create_uses_caller_and_database_time_instead_of_body_audit_fields(setup):
    client, cursor, _ = setup
    cursor.fetchone.return_value = db_row()
    forged = {"requestedBy": EVENT_ID, "requestedAt": "2000-01-01T00:00:00Z"}

    response = client.post(
        f"/events/{EVENT_ID}/equipment-requests",
        headers=COORDINATOR,
        json={"items": [{**item(), **forged}], **forged},
    )

    assert response.status_code == 201
    sql, params = cursor.execute.call_args[0]
    assert "CURRENT_TIMESTAMP" in sql
    assert params == [EVENT_ID, MIC, 2, "Two handheld", USER_ID]


# Create request AC1/AC2 (integrity): invalid equipment/event references cannot leave a partial request.
def test_create_saves_nothing_when_an_event_or_equipment_does_not_exist(setup):
    client, cursor, _ = setup
    cursor.execute.side_effect = [None, psycopg2.errors.ForeignKeyViolation()]
    cursor.fetchone.return_value = db_row()

    response = client.post(f"/events/{EVENT_ID}/equipment-requests", headers=COORDINATOR, json={"items": [item(), item(TABLE)]})

    assert response.status_code == 404
    assert "no longer exists" in response.json["message"]


# Create request AC1 (access): only an identified Event Coordinator may record equipment needs.
@pytest.mark.parametrize("headers,code", [({}, 401), (TS, 403), ({"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Attendee"}, 403)])
def test_only_event_coordinators_can_create(setup, headers, code):
    client, _, connect = setup
    assert client.post(f"/events/{EVENT_ID}/equipment-requests", headers=headers, json={"items": [item()]}).status_code == code
    connect.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"items": []},
        {"items": "mic"},
        {"items": ["mic"]},
        {"items": [item(equipment_id="not-a-uuid")]},
        {"items": [item(quantity=0)]},
        {"items": [item(quantity=-1)]},
        {"items": [item(quantity=1.5)]},
        {"items": [item(quantity="2")]},
        {"items": [item(quantity=True)]},
        {"items": [item(requirements=5)]},
        {"items": [item(requirements="x" * 1001)]},
        {"items": [item(), item()]},
        {"items": [item(f"{i:08d}-636b-48e7-8784-d00000000000") for i in range(51)]},
    ],
)
def test_create_rejects_invalid_items(setup, payload):
    # Create request AC1 (validation): reject malformed equipment, quantity and technical requirements.
    client, _, connect = setup
    assert client.post(f"/events/{EVENT_ID}/equipment-requests", headers=COORDINATOR, json=payload).status_code == 400
    connect.assert_not_called()


# Create request AC2 (integrity): require a valid corresponding event reference.
def test_create_rejects_non_uuid_event_id(setup):
    client, _, connect = setup
    assert client.post("/events/abc/equipment-requests", headers=COORDINATOR, json={"items": [item()]}).status_code == 400
    connect.assert_not_called()


# Create request AC1 (supporting transport): permit browser submission of equipment needs.
def test_cors_allows_post_for_request_creation(setup):
    client, _, _ = setup
    response = client.options(f"/events/{EVENT_ID}/equipment-requests", headers={"Origin": ORIGIN})
    assert "POST" in response.headers["Access-Control-Allow-Methods"]


