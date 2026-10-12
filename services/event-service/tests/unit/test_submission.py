"""Event submission AC1–AC4. Database calls are mocked; no live database writes."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

import psycopg2
import pytest
from app import create_app
from app.models import FIELDS, SINGAPORE, serialize, unpack_description

VALID = {
    "eventName": "Community Workshop",
    "description": "A workshop",
    "purpose": "Learning",
    "preferredStartDate": "2026-10-01T09:00",
    "preferredEndDate": "2026-10-01T17:00",
    "expectedAttendance": "25",
}


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), connection, cursor


def saved_row():
    row = {column: VALID.get(key, "") for key, column in FIELDS.items()}
    row.update(
        event_id="00000000-0000-0000-0000-000000000001",
        status="Submitted",
        submission_date=datetime(2026, 9, 15, 1, 30, tzinfo=UTC),
        preferred_start_date=datetime(2026, 10, 1, 9),
        preferred_end_date=datetime(2026, 10, 1, 17),
        expected_attendance=25,
        coordinator_id=None,
    )
    row["description"] = json.dumps(
        {
            "_connectsphere": "event-submission-v1",
            "description": VALID["description"],
            "purpose": VALID["purpose"],
        }
    )
    return row


def test_ac1_ac2_ac3_submit_existing_columns_and_return_confirmation_data(setup):
    client, connection, cursor = setup
    cursor.fetchone.return_value = saved_row()
    response = client.post(
        "/events", json={**VALID, "status": "Approved", "submission_date": "fake"}
    )
    assert response.status_code == 201
    assert response.json["status"] == "Submitted"
    assert response.json["submittedAt"] == "2026-09-15T01:30:00+00:00"
    assert response.json["purpose"] == "Learning"
    assert response.json["description"] == "A workshop"
    query, parameters = cursor.execute.call_args.args
    assert 'INSERT INTO public."Event"' in query
    assert "'Submitted', now()" in query
    assert "purpose" not in query
    assert "'Submitted'" in query
    assert UUID(parameters[0])
    # Naive local input is bound as an aware Singapore time for TIMESTAMPTZ.
    assert parameters[3] == datetime(2026, 10, 1, 9, tzinfo=SINGAPORE)
    assert parameters[4] == datetime(2026, 10, 1, 17, tzinfo=SINGAPORE)
    assert parameters[5] == 25
    assert json.loads(parameters[2])["purpose"] == "Learning"
    assert parameters[6:] == ["", "", "", "", None]  # last: organiser_id (not supplied)
    connection.__exit__.assert_called_once()
    connection.close.assert_called_once()


def test_optional_details_roundtrip(setup):
    client, _, cursor = setup
    row = saved_row()
    row["equipment_requirements"] = "Projector"
    cursor.fetchone.return_value = row
    response = client.post(
        "/events", json={**VALID, "equipmentRequirements": "Projector"}
    )
    assert response.json["equipmentRequirements"] == "Projector"
    assert cursor.execute.call_args.args[1][-3] == "Projector"


@pytest.mark.parametrize(
    "field,label",
    [
        ("eventName", "Event Name"),
        ("description", "Description"),
        ("purpose", "Purpose"),
        ("preferredStartDate", "Preferred Start Date & Time"),
        ("preferredEndDate", "Preferred End Date & Time"),
        ("expectedAttendance", "Expected Attendance"),
    ],
)
@pytest.mark.parametrize("value", [None, "", "  "])
def test_ac4_exact_missing_fields_prevent_database_call(setup, field, label, value):
    client, _, cursor = setup
    response = client.post("/events", json={**VALID, field: value})
    assert response.status_code == 400
    assert response.json["missingFields"] == [label]
    cursor.execute.assert_not_called()


def test_ac4_all_required_missing(setup):
    response = setup[0].post("/events", json={})
    assert response.json["missingFields"] == [
        "Event Name",
        "Description",
        "Purpose",
        "Preferred Start Date & Time",
        "Preferred End Date & Time",
        "Expected Attendance",
    ]


@pytest.mark.parametrize(
    "value", ["0", "-1", "2.5", "abc", "2147483648", "9" * 5000, "²"]
)
def test_attendance_boundary_validation(setup, value):
    response = setup[0].post("/events", json={**VALID, "expectedAttendance": value})
    assert response.status_code == 400
    assert response.json["errors"]


@pytest.mark.parametrize(
    "value",
    [
        "invalid",
        "2026-10-01",
        "2026-10-01T09:00",
        "2026-09-30T09:00",
        "2026-10-01T17:00+08:00",
    ],
)
def test_invalid_period_validation(setup, value):
    assert (
        setup[0].post("/events", json={**VALID, "preferredEndDate": value}).status_code
        == 400
    )


@pytest.mark.parametrize("body", [None, [], "text"])
def test_invalid_json_body(setup, body):
    assert setup[0].post("/events", json=body).status_code == 400


def test_optional_field_wrong_type(setup):
    assert (
        setup[0].post("/events", json={**VALID, "venueRequirements": []}).status_code
        == 400
    )


def test_submitted_queue_requires_a_coordinator_id(setup):
    """No caller-less "show me everything" — the old unfiltered fallback is gone."""
    client, _, cursor = setup
    response = client.get("/events/submitted")
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_submitted_queue_filters_to_the_coordinator(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = []
    response = client.get(f"/events/submitted?coordinatorId={OTHER_COORDINATOR_ID}")
    assert response.status_code == 200
    assert response.json == {"events": []}
    query, params = cursor.execute.call_args.args
    assert "coordinator_id = %s" in query
    assert params == [OTHER_COORDINATOR_ID]


def test_submitted_queue_manager_sees_all_even_with_coordinator_id(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = [saved_row()]
    response = client.get(
        f"/events/submitted?coordinatorId={OTHER_COORDINATOR_ID}&viewerRole=Event+Coordinator+Lead"
    )
    assert response.status_code == 200
    assert len(response.json["events"]) == 1
    query, params = cursor.execute.call_args.args
    assert "coordinator_id = %s" not in query
    assert params == []


@pytest.mark.parametrize("query_string", ["?coordinatorId=not-a-uuid"])
def test_submitted_queue_rejects_invalid_optional_coordinator_id(query_string, setup):
    client, _, cursor = setup
    response = client.get(f"/events/submitted{query_string}")
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_empty_queue(setup):
    setup[2].fetchall.return_value = []
    response = setup[0].get(f"/events/submitted?coordinatorId={OTHER_COORDINATOR_ID}")
    assert response.json == {"events": []}


def test_assign_coordinator_updates_event(setup):
    client, _, cursor = setup
    assigned = saved_row()
    assigned["coordinator_id"] = COORDINATOR_ID
    assigned["status"] = "Under Review"
    cursor.fetchone.return_value = assigned

    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001",
        json={"assignedCoordinatorId": COORDINATOR_ID},
    )

    assert response.status_code == 200
    assert response.json["coordinatorId"] == COORDINATOR_ID
    assert response.json["status"] == "Under Review"
    query, parameters = cursor.execute.call_args.args
    assert "SET coordinator_id = %s" in query
    assert "status = CASE WHEN status = 'Submitted' THEN 'Under Review'" in query
    assert parameters == [COORDINATOR_ID, "00000000-0000-0000-0000-000000000001"]


def test_assign_coordinator_returns_not_found(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001",
        json={"assignedCoordinatorId": COORDINATOR_ID},
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "value,description,purpose",
    [
        ("Legacy plain text", "Legacy plain text", ""),
        (None, "", ""),
        ('{"other":"value"}', '{"other":"value"}', ""),
        ("[]", "[]", ""),
    ],
)
def test_legacy_descriptions_are_not_rewritten(value, description, purpose):
    assert unpack_description(value) == (description, purpose, None)


def test_nullable_legacy_fields_serialize():
    row = saved_row()
    for column in FIELDS.values():
        row[column] = None
    row["submission_date"] = None
    serialized = serialize(row)
    assert serialized["preferredStartDate"] == ""
    assert serialized["submittedAt"] is None
    assert serialized["purpose"] == ""


@pytest.mark.parametrize("operation", ["execute", "commit"])
def test_database_failure_never_reports_success(setup, operation):
    client, connection, cursor = setup
    cursor.fetchone.return_value = saved_row()
    if operation == "execute":
        cursor.execute.side_effect = psycopg2.OperationalError(
            "secret connection information"
        )
    else:
        connection.__exit__.side_effect = psycopg2.OperationalError("commit failed")
    response = client.post("/events", json=VALID)
    assert response.status_code == 503
    assert "secret" not in response.text
    connection.close.assert_called_once()


def test_missing_database_configuration():
    client = create_app({"TESTING": True, "DATABASE_URL": None}).test_client()
    assert client.post("/events", json=VALID).status_code == 503
    assert (
        client.get(f"/events/submitted?coordinatorId={COORDINATOR_ID}").status_code
        == 503
    )


def test_health_and_browser_cors(setup):
    client = setup[0]
    assert client.get("/health").json == {"status": "ok"}
    response = client.options("/events", headers={"Origin": "http://localhost:5174"})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert (
        "Access-Control-Allow-Origin"
        not in client.options(
            "/events", headers={"Origin": "https://other.example"}
        ).headers
    )


def test_reject_preflight_is_allowed(setup):
    client = setup[0]
    response = client.options(
        "/events/00000000-0000-0000-0000-000000000001/reject",
        headers={
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert "PATCH" in response.headers["Access-Control-Allow-Methods"]


COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OTHER_COORDINATOR_ID = "22222222-2222-4222-8222-222222222222"


def approved_row():
    row = saved_row()
    row["status"] = "Approved"
    row["coordinator_id"] = COORDINATOR_ID
    row["description"] = json.dumps(
        {
            "_connectsphere": "event-submission-v1",
            "description": VALID["description"],
            "purpose": VALID["purpose"],
            "approval": {
                "coordinatorId": COORDINATOR_ID,
                "approvedAt": "2026-09-15T02:30:00.000000+00:00",
            },
        }
    )
    return row


def test_approval_changes_status_and_records_audit_metadata(setup):
    client, connection, cursor = setup
    assigned = saved_row()
    assigned["coordinator_id"] = COORDINATOR_ID
    cursor.fetchone.side_effect = [assigned, approved_row()]

    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001/approve",
        json={"coordinatorId": COORDINATOR_ID},
    )

    assert response.status_code == 200
    assert response.json["status"] == "Approved"
    assert response.json["decision"]["status"] == "Approved"
    assert response.json["decision"]["coordinatorId"] == COORDINATOR_ID
    assert response.json["decision"]["reason"] is None
    assert response.json["decisionHistory"] == [response.json["decision"]]
    assert cursor.execute.call_count == 2
    update_query, parameters = cursor.execute.call_args.args
    assert "SET status = %s" in update_query
    assert parameters[0:3] == ["Approved", VALID["description"], VALID["purpose"]]
    assert parameters[3:5] == ["Approved", COORDINATOR_ID]
    assert parameters[-1] == "00000000-0000-0000-0000-000000000001"
    connection.__exit__.assert_called_once()


def test_approval_is_rejected_for_another_coordinators_assignment(setup):
    client, _, cursor = setup
    assigned = saved_row()
    assigned["coordinator_id"] = OTHER_COORDINATOR_ID
    cursor.fetchone.return_value = assigned

    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001/approve",
        json={"coordinatorId": COORDINATOR_ID},
    )

    assert response.status_code == 403
    assert cursor.execute.call_count == 1


def test_approval_is_rejected_when_event_is_not_submitted(setup):
    client, _, cursor = setup
    assigned = saved_row()
    assigned.update(coordinator_id=COORDINATOR_ID, status="Approved")
    cursor.fetchone.return_value = assigned

    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001/approve",
        json={"coordinatorId": COORDINATOR_ID},
    )

    assert response.status_code == 409
    assert cursor.execute.call_count == 1


def test_approval_returns_not_found_for_unknown_event(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = None
    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001/approve",
        json={"coordinatorId": COORDINATOR_ID},
    )
    assert response.status_code == 404


@pytest.mark.parametrize("body", [{}, None, {"coordinatorId": "not-a-uuid"}])
def test_approval_requires_valid_current_coordinator(body, setup):
    response = setup[0].patch(
        "/events/00000000-0000-0000-0000-000000000001/approve",
        json=body,
    )
    assert response.status_code == 400
    setup[2].execute.assert_not_called()


def rejected_row():
    row = saved_row()
    row["status"] = "Rejected"
    row["coordinator_id"] = COORDINATOR_ID
    row["description"] = json.dumps(
        {
            "_connectsphere": "event-submission-v1",
            "description": VALID["description"],
            "purpose": VALID["purpose"],
            "decision": {
                "status": "Rejected",
                "coordinatorId": COORDINATOR_ID,
                "decidedAt": "2026-09-15T02:30:00.000000+00:00",
                "reason": "The selected venue is unavailable.",
            },
            "decisionHistory": [
                {
                    "status": "Rejected",
                    "coordinatorId": COORDINATOR_ID,
                    "decidedAt": "2026-09-15T02:30:00.000000+00:00",
                    "reason": "The selected venue is unavailable.",
                }
            ],
        }
    )
    return row


def test_rejection_changes_status_and_records_reason_and_audit_metadata(setup):
    client, _, cursor = setup
    assigned = saved_row()
    assigned["coordinator_id"] = COORDINATOR_ID
    cursor.fetchone.side_effect = [assigned, rejected_row()]

    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001/reject",
        json={
            "coordinatorId": COORDINATOR_ID,
            "reason": "The selected venue is unavailable.",
        },
    )

    assert response.status_code == 200
    assert response.json["status"] == "Rejected"
    assert response.json["decision"]["status"] == "Rejected"
    assert response.json["decision"]["coordinatorId"] == COORDINATOR_ID
    assert response.json["decision"]["reason"] == "The selected venue is unavailable."
    assert response.json["decision"]["decidedAt"]
    update_query, parameters = cursor.execute.call_args.args
    assert "SET status = %s" in update_query
    assert parameters[0] == "Rejected"
    assert parameters[6] == "The selected venue is unavailable."


def test_rejection_is_unavailable_for_another_coordinators_assignment(setup):
    client, _, cursor = setup
    assigned = saved_row()
    assigned["coordinator_id"] = OTHER_COORDINATOR_ID
    cursor.fetchone.return_value = assigned

    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001/reject",
        json={"coordinatorId": COORDINATOR_ID, "reason": "Not suitable."},
    )

    assert response.status_code == 403
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("reason", [None, "", "  "])
def test_rejection_requires_a_reason(reason, setup):
    response = setup[0].patch(
        "/events/00000000-0000-0000-0000-000000000001/reject",
        json={"coordinatorId": COORDINATOR_ID, "reason": reason},
    )
    assert response.status_code == 400
    setup[2].execute.assert_not_called()


def test_rejection_is_rejected_when_event_is_not_submitted(setup):
    client, _, cursor = setup
    assigned = saved_row()
    assigned.update(coordinator_id=COORDINATOR_ID, status="Approved")
    cursor.fetchone.return_value = assigned

    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001/reject",
        json={"coordinatorId": COORDINATOR_ID, "reason": "Not suitable."},
    )

    assert response.status_code == 409
    assert cursor.execute.call_count == 1


ORGANISER_ID = "33333333-3333-4333-8333-333333333333"


def test_submit_persists_organiser_id(setup):
    """Organiser registration view: the creator is recorded so ownership can be checked."""
    client, _, cursor = setup
    row = saved_row()
    row["organiser_id"] = ORGANISER_ID
    cursor.fetchone.return_value = row
    response = client.post("/events", json={**VALID, "organiserId": ORGANISER_ID})
    assert response.status_code == 201
    assert response.json["organiserId"] == ORGANISER_ID
    assert cursor.execute.call_args.args[1][-1] == ORGANISER_ID


def test_submit_rejects_invalid_organiser_id(setup):
    client, _, cursor = setup
    response = client.post("/events", json={**VALID, "organiserId": "not-a-uuid"})
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_timestamptz_values_serialize_as_singapore_local():
    """TIMESTAMPTZ columns come back aware in the session zone (UTC on Supabase);
    the API keeps returning the naive Singapore-local strings it always has."""
    row = saved_row()
    row["preferred_start_date"] = datetime(2026, 10, 1, 1, tzinfo=UTC)
    row["preferred_end_date"] = datetime(2026, 10, 1, 9, tzinfo=UTC)

    serialized = serialize(row)

    assert serialized["preferredStartDate"] == "2026-10-01T09:00:00"
    assert serialized["preferredEndDate"] == "2026-10-01T17:00:00"


def test_unassigned_queue_only_submitted_events_with_no_coordinator(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = [saved_row()]
    response = client.get("/events/unassigned")
    assert response.status_code == 200
    assert response.json["events"][0]["coordinatorId"] is None
    query = cursor.execute.call_args.args[0]
    assert "WHERE status = 'Submitted' AND coordinator_id IS NULL" in query
    assert "'Under Review'" not in query
    assert "ORDER BY submission_date ASC NULLS LAST" in query


def test_unassigned_queue_needs_database(monkeypatch):
    client = create_app({"TESTING": True, "DATABASE_URL": ""}).test_client()
    assert client.get("/events/unassigned").status_code == 503


def test_submitted_queue_ignores_the_retired_is_manager_flag(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = []
    response = client.get(
        f"/events/submitted?coordinatorId={OTHER_COORDINATOR_ID}&isManager=true"
    )
    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert "coordinator_id = %s" in query
    assert params == [OTHER_COORDINATOR_ID]


@pytest.mark.parametrize("role", ["Venue Staff", "Event Coordinator", "Attendee"])
def test_only_the_lead_can_view_every_submitted_request(role, setup):
    client, _, cursor = setup
    response = client.get(
        "/events/submitted",
        query_string={"coordinatorId": OTHER_COORDINATOR_ID, "viewerRole": role},
    )
    assert response.status_code == 403
    cursor.execute.assert_not_called()
