"""
SCRUM-32: Create Event Equipment Request

User Story
----------
As an Event Coordinator and Event Coordinator Lead, I want to record the equipment required for an event so that the technical team is informed of the resources needed as requested.

Acceptance Criteria
-------------------
AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
AC2: Recorded equipment request accurately reflects the date and time of the corresponding event
AC3: Ensure newly recorded equipment requests default to an initial status such as "Pending"

Real
----
- POST /events/<id>/equipment-requests: item validation, the coordinator role
  check, the insert of every line in one transaction with
  requested_by/requested_at taken from the caller and the database clock, and
  the foreign-key failure mapping run for real.
- Assertions are on the status, the saved lines and the SQL and values sent to
  the database.

Doubled
-------
- psycopg2.connect: Stub / Mock (tests/unit/conftest.py `setup`) - the cursor
  returns the inserted rows (or raises ForeignKeyViolation); the executed SQL
  and parameters are inspected; connect is asserted not called when a request
  is refused before the database.
- Equipment Reservation Service: Fake (CompositeClient in conftest) - adds the
  internal token and an empty notification context as the composite would.

Not proven
----------
- AC2 (the request reflects the event's date and time): this service stores
  only the event id; the event's dates are joined in by Equipment Reservation
  Service (-> equipment-reservation-service unit tests).
- That PostgreSQL really rejects unknown event/equipment ids and rolls the
  whole request back (-> tests/integration/, fixture-owned pinned PostgreSQL (observed 17.11)).

- Scope: supporting validation boundary; the precise numeric API limit is not specified by this AC. Applies to: `test_create_request_when_item_count_near_limit_accepts_up_to_50_lines`, `test_create_request_when_quantity_near_minimum_accepts_one_or_more`, `test_create_request_when_requirements_near_limit_accepts_up_to_1000_characters`.
"""

import psycopg2
import pytest

from tests.unit.factories import EVENT_ID, MIC, REQUEST_ID, TABLE, USER_ID, bearer, db_row, item

TS = bearer(USER_ID, "Technical Support")
COORDINATOR = bearer(USER_ID, "Event Coordinator")
SAFETY_OFFICER = bearer(USER_ID, "Safety Officer")


def test_create_request_with_several_lines_saves_each_as_pending_for_the_event(setup):
    """Summary: Every equipment line a coordinator records is saved against the event as Pending.
    AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
    AC3: Ensure newly recorded equipment requests default to an initial status such as "Pending"
    Double: Stub (canned database results/errors); Mock (database interactions inspected); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    """
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


def test_create_request_with_forged_audit_fields_records_caller_and_database_time(setup):
    """Summary: Who recorded a request and when come from the token and the database clock, never from the body.
    AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
    Double: Stub (canned database results/errors); Mock (database interactions inspected); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    cursor.fetchone.return_value = db_row()
    forged = {"requestedBy": EVENT_ID, "requestedAt": "2000-01-01T00:00:00Z"}

    # Act (When)
    response = client.post(
        f"/events/{EVENT_ID}/equipment-requests",
        headers=COORDINATOR,
        json={"items": [{**item(), **forged}], **forged},
    )

    # Assert (Then)
    assert response.status_code == 201
    sql, params = cursor.execute.call_args[0]
    assert "CURRENT_TIMESTAMP" in sql
    assert params == [EVENT_ID, MIC, 2, "Two handheld", USER_ID]


def test_create_request_when_event_or_equipment_unknown_returns_404(setup):
    """Summary: A simulated second-line foreign-key failure returns a safe refusal; real rollback is checked separately.
    AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
    Double: Stub (canned database results/errors); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    """
    client, cursor, _ = setup
    cursor.execute.side_effect = [None, psycopg2.errors.ForeignKeyViolation()]
    cursor.fetchone.return_value = db_row()

    response = client.post(f"/events/{EVENT_ID}/equipment-requests", headers=COORDINATOR, json={"items": [item(), item(TABLE)]})

    assert response.status_code == 404
    assert "no longer exists" in response.json["message"]


def test_create_request_when_caller_is_lead_saves_request(setup):
    """Summary: The Event Coordinator Lead can record equipment needs like a coordinator.
    AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
    Double: Stub (canned database results/errors); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    """
    client, cursor, _ = setup
    cursor.fetchone.return_value = db_row()

    headers = bearer(USER_ID, "Event Coordinator Lead")
    response = client.post(f"/events/{EVENT_ID}/equipment-requests", headers=headers, json={"items": [item()]})

    assert response.status_code == 201




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
    ids=["no_body", "list_body", "empty_object", "empty_items", "items_as_text", "item_as_text", "bad_equipment_id", "zero_quantity", "negative_quantity", "fractional_quantity", "quantity_as_text", "quantity_as_bool", "requirements_not_text", "requirements_too_long", "duplicate_equipment", "too_many_items"],
)
def test_create_request_with_invalid_items_returns_400_before_database(setup, payload):
    """Summary: A submission with no items, a bad equipment id, quantity or requirement text is refused before saving.
    AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
    Double: Stub (canned database results/errors); Mock (database interactions inspected); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    """
    # Create request AC1 (validation): reject malformed equipment, quantity and technical requirements.
    client, _, connect = setup
    assert client.post(f"/events/{EVENT_ID}/equipment-requests", headers=COORDINATOR, json=payload).status_code == 400
    connect.assert_not_called()


def test_create_request_with_malformed_event_id_returns_400_before_database(setup):
    """Summary: A request must name a valid event.
    AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
    Double: Stub (canned database results/errors); Mock (database interactions inspected); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    """
    client, _, connect = setup
    assert client.post("/events/abc/equipment-requests", headers=COORDINATOR, json={"items": [item()]}).status_code == 400
    connect.assert_not_called()


def distinct_items(count):
    return [item(f"{i:08d}-636b-48e7-8784-d00000000000") for i in range(count)]


@pytest.mark.parametrize(
    "count, expected_status",
    [(49, 201), (50, 201), (51, 400)],
    ids=["below_limit", "at_limit", "above_limit"],
)
def test_create_request_when_item_count_near_limit_accepts_up_to_50_lines(setup, count, expected_status):
    """Summary: One request can record up to 50 equipment lines.
    AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
    Double: Stub (canned database results/errors); Mock (database interactions inspected); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    """
    client, cursor, connect = setup
    items = distinct_items(count)
    cursor.fetchone.side_effect = [db_row(equipment_id=line["equipmentId"], quantity_requested=line["quantityRequested"], technical_requirements=line["technicalRequirements"].strip()) for line in items]
    context = {"eventId": EVENT_ID, "eventName": "Fixture event", "recipientIds": [], "coordinatorId": None,
               "equipmentNames": {line["equipmentId"]: "Microphone" for line in items}}

    response = client.post(
        f"/events/{EVENT_ID}/equipment-requests", headers=COORDINATOR, json={"items": items, "notificationContext": context}
    )

    assert response.status_code == expected_status
    if expected_status == 201:
        saved = response.json["requests"]
        assert len(saved) == count
        assert [(row["equipmentId"], row["quantityRequested"], row["technicalRequirements"], row["status"], row["eventId"]) for row in saved] == [
            (line["equipmentId"], line["quantityRequested"], line["technicalRequirements"].strip(), "Pending", EVENT_ID) for line in items]
        assert [call.args[1] for call in cursor.execute.call_args_list] == [
            [EVENT_ID, line["equipmentId"], line["quantityRequested"], line["technicalRequirements"].strip(), USER_ID] for line in items]
    else:
        connect.assert_not_called()


@pytest.mark.parametrize(
    "quantity, expected_status",
    [(0, 400), (1, 201), (2, 201)],
    ids=["below_minimum", "at_minimum", "above_minimum"],
)
def test_create_request_when_quantity_near_minimum_accepts_one_or_more(setup, quantity, expected_status):
    """Summary: Each line must ask for at least one unit.
    AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
    Double: Stub (canned database results/errors); Mock (database interactions inspected); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    """
    client, cursor, connect = setup
    cursor.fetchone.return_value = db_row(quantity_requested=quantity)

    response = client.post(f"/events/{EVENT_ID}/equipment-requests", headers=COORDINATOR, json={"items": [item(quantity=quantity)]})

    assert response.status_code == expected_status
    if expected_status == 201:
        assert response.json["requests"][0]["quantityRequested"] == quantity
        assert cursor.execute.call_args.args[1] == [EVENT_ID, MIC, quantity, "Two handheld", USER_ID]
    else:
        connect.assert_not_called()


@pytest.mark.parametrize(
    "length, expected_status",
    [(999, 201), (1000, 201), (1001, 400)],
    ids=["below_limit", "at_limit", "above_limit"],
)
def test_create_request_when_requirements_near_limit_accepts_up_to_1000_characters(setup, length, expected_status):
    """Summary: Technical requirements can be up to 1000 characters.
    AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
    Double: Stub (canned database results/errors); Mock (database interactions inspected); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    """
    client, cursor, connect = setup
    cursor.fetchone.return_value = db_row(quantity_requested=2, technical_requirements="x" * length)

    response = client.post(
        f"/events/{EVENT_ID}/equipment-requests", headers=COORDINATOR, json={"items": [item(requirements="x" * length)]}
    )

    assert response.status_code == expected_status
    if expected_status == 201:
        assert response.json["requests"][0]["technicalRequirements"] == "x" * length
        assert cursor.execute.call_args.args[1] == [EVENT_ID, MIC, 2, "x" * length, USER_ID]
    else:
        connect.assert_not_called()
