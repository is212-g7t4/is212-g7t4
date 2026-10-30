"""Event submission AC1–AC4. Database calls are mocked; no live database writes."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

import psycopg2
import pytest
from app import create_app
from app.models import FIELDS, SINGAPORE, RejectionReasonError, reject_event, serialize, unpack_description
from tests.unit.factories import signed_in

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
    app = create_app({
        "TESTING": True,
        "DATABASE_URL": "unused-test-url",
        "FRONTEND_ORIGIN": "http://localhost:5174",
    })
    return signed_in(app.test_client(), role="Event Organiser"), connection, cursor


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
    # No deadline; the organiser is the signed-in caller (SCRUM-8), not a body field.
    assert parameters[6:] == ["", "", "", "", None, "00000000-0000-4000-8000-000000000001"]
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
    assert cursor.execute.call_args.args[1][8] == "Projector"


def test_optional_withdrawal_deadline_roundtrips_as_singapore_local_time(setup):
    client, _, cursor = setup
    row = saved_row()
    row["withdrawal_deadline"] = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)
    cursor.fetchone.return_value = row

    response = client.post(
        "/events", json={**VALID, "withdrawalDeadline": "2026-10-01T02:00"}
    )

    assert response.status_code == 201
    assert response.json["withdrawalDeadline"] == "2026-10-01T02:00:00"
    assert cursor.execute.call_args.args[1][10] == datetime(
        2026, 10, 1, 2, tzinfo=SINGAPORE
    )


@pytest.mark.parametrize(
    "deadline",
    ["invalid", "2026-10-01T09:01"],
)
def test_withdrawal_deadline_must_be_valid_and_no_later_than_start(setup, deadline):
    response = setup[0].post(
        "/events", json={**VALID, "withdrawalDeadline": deadline}
    )
    assert response.status_code == 400
    assert "Withdrawal Deadline" in response.json["errors"][0]
    setup[2].execute.assert_not_called()


def test_withdrawal_deadline_must_be_text(setup):
    response = setup[0].post(
        "/events", json={**VALID, "withdrawalDeadline": 123}
    )
    assert response.status_code == 400
    assert "withdrawalDeadline must be text" in response.json["errors"][0]


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


def test_submitted_queue_requires_a_signed_in_coordinator(setup):
    """No caller-less "show me everything" — the old unfiltered fallback is gone (SCRUM-8: no token, no queue)."""
    _, _, cursor = setup
    client = setup[0].application.test_client()
    response = client.get("/events/submitted")
    assert response.status_code == 401
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


def test_empty_queue(setup):
    setup[2].fetchall.return_value = []
    response = setup[0].get(f"/events/submitted?coordinatorId={OTHER_COORDINATOR_ID}")
    assert response.json == {"events": []}


LEAD_ID = "33333333-3333-4333-8333-333333333333"


def test_assign_coordinator_updates_event(setup):
    """Assignment records the coordinator, who assigned them and when, and
    moves the event out of the unassigned queue ('Submitted' -> 'Under Review')."""
    client, _, cursor = setup
    assigned = saved_row()
    assigned["coordinator_id"] = COORDINATOR_ID
    assigned["status"] = "Under Review"
    assigned["assigned_by"] = LEAD_ID
    assigned["assigned_at"] = datetime(2026, 10, 16, 2, 15, tzinfo=UTC)
    cursor.fetchone.side_effect = [{"coordinator_id": None, "status": "Submitted"}, assigned]

    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001",
        json={"assignedCoordinatorId": COORDINATOR_ID, "assignedBy": LEAD_ID},
    )

    assert response.status_code == 200
    assert response.json["coordinatorId"] == COORDINATOR_ID
    assert response.json["status"] == "Under Review"
    assert response.json["assignedBy"] == LEAD_ID
    assert response.json["assignedAt"] == "2026-10-16T02:15:00+00:00"
    assert response.json["previousCoordinatorId"] is None
    lock_query, lock_parameters = cursor.execute.call_args_list[0].args
    assert "FOR UPDATE" in lock_query
    assert lock_parameters == ["00000000-0000-0000-0000-000000000001"]
    query, parameters = cursor.execute.call_args_list[1].args
    assert "previous_coordinator_id = coordinator_id" in query
    assert "coordinator_id = %s" in query
    assert "assigned_by = %s" in query
    assert "assigned_at = now()" in query
    assert "status = CASE WHEN status = 'Submitted' THEN 'Under Review'" in query
    assert "RETURNING" in query and "assigned_by, assigned_at, previous_coordinator_id" in query
    assert parameters == [COORDINATOR_ID, LEAD_ID, "00000000-0000-0000-0000-000000000001"]


@pytest.mark.parametrize("status", [
    "Under Review", "Approved", "Pending Safety Check", "Confirmed", "Safety Changes Requested",
])
def test_reassign_replaces_the_coordinator_and_records_the_previous_one(setup, status):
    """Reassignment: any open event can move to a different coordinator; the
    Lead, previous coordinator, new coordinator and time are all returned."""
    client, _, cursor = setup
    reassigned = saved_row()
    reassigned.update(
        status=status, coordinator_id=OTHER_COORDINATOR_ID, previous_coordinator_id=COORDINATOR_ID,
        assigned_by=LEAD_ID, assigned_at=datetime(2026, 10, 16, 13, 5, tzinfo=UTC),
    )
    cursor.fetchone.side_effect = [{"coordinator_id": COORDINATOR_ID, "status": status}, reassigned]

    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001",
        json={"assignedCoordinatorId": OTHER_COORDINATOR_ID, "assignedBy": LEAD_ID},
    )

    assert response.status_code == 200
    assert response.json["coordinatorId"] == OTHER_COORDINATOR_ID
    assert response.json["previousCoordinatorId"] == COORDINATOR_ID
    assert response.json["assignedBy"] == LEAD_ID
    assert response.json["assignedAt"] == "2026-10-16T13:05:00+00:00"
    assert response.json["status"] == status
    writes = [call for call in cursor.execute.call_args_list if 'UPDATE public."Event"' in call.args[0]]
    assert len(writes) == 1
    assert writes[0].args[1] == [OTHER_COORDINATOR_ID, LEAD_ID, "00000000-0000-0000-0000-000000000001"]


@pytest.mark.parametrize("status", ["Rejected", "Cancelled", "Clarification Requested"])
def test_reassign_is_blocked_for_closed_events(setup, status):
    """Closed events and an open clarification keep their coordinator."""
    client, _, cursor = setup
    cursor.fetchone.return_value = {"coordinator_id": COORDINATOR_ID, "status": status}

    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001",
        json={"assignedCoordinatorId": OTHER_COORDINATOR_ID, "assignedBy": LEAD_ID},
    )

    assert response.status_code == 409
    assert response.json["message"] == f"A {status} event can't be reassigned."
    assert cursor.execute.call_count == 1  # the lock only; nothing updated


def test_reassign_to_the_current_coordinator_is_rejected_as_no_change(setup):
    """Reassignment: choosing the coordinator who already has the event is refused."""
    client, _, cursor = setup
    cursor.fetchone.return_value = {"coordinator_id": COORDINATOR_ID, "status": "Under Review"}

    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001",
        json={"assignedCoordinatorId": COORDINATOR_ID, "assignedBy": LEAD_ID},
    )

    assert response.status_code == 409
    assert "No change" in response.json["message"]
    assert cursor.execute.call_count == 1


def test_assign_coordinator_requires_a_signed_in_assigner(setup):
    """Without a signed-in assigner (SCRUM-8) there's nothing to show on the detail page."""
    _, _, cursor = setup
    client = setup[0].application.test_client()

    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001",
        json={"assignedCoordinatorId": COORDINATOR_ID},
    )

    assert response.status_code == 401
    cursor.execute.assert_not_called()


def test_assign_coordinator_returns_not_found(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = client.patch(
        "/events/00000000-0000-0000-0000-000000000001",
        json={"assignedCoordinatorId": COORDINATOR_ID, "assignedBy": LEAD_ID},
    )

    assert response.status_code == 404


def test_unassigned_event_serializes_without_assignment_record():
    """Events never assigned (or legacy rows) have no assigner or time."""
    body = serialize(saved_row())
    assert body["assignedBy"] is None
    assert body["assignedAt"] is None
    assert body["previousCoordinatorId"] is None


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
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client(), role="Event Organiser")
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


def test_approval_requires_a_signed_in_coordinator(setup):
    response = setup[0].application.test_client().patch(
        "/events/00000000-0000-0000-0000-000000000001/approve",
        json={"coordinatorId": COORDINATOR_ID},
    )
    assert response.status_code == 401
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
    # Notification INSERTs follow the mutation; inspect the UPDATE itself, not the last SQL call.
    update_query, parameters = next(call.args for call in cursor.execute.call_args_list
                                    if 'UPDATE public."Event"' in call.args[0])
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
    event_insert = next(call for call in cursor.execute.call_args_list if 'INSERT INTO public."Event"' in call.args[0])
    assert event_insert.args[1][-1] == ORGANISER_ID


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
    signed_in(client, role="Event Coordinator Lead")
    cursor.fetchall.return_value = [saved_row()]
    response = client.get("/events/unassigned")
    assert response.status_code == 200
    assert response.json["events"][0]["coordinatorId"] is None
    query = cursor.execute.call_args.args[0]
    assert "WHERE status = 'Submitted' AND coordinator_id IS NULL" in query
    assert "'Under Review'" not in query
    assert "ORDER BY submission_date ASC NULLS LAST" in query


def test_unassigned_queue_needs_database(monkeypatch):
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": ""}).test_client(), role="Event Coordinator Lead")
    assert client.get("/events/unassigned").status_code == 503


def test_active_events_include_unassigned_and_exclude_confirmed_rejected_cancelled(setup):
    """The Lead's workload view lists active events, assigned or
    not; Confirmed, Rejected and Cancelled events are left out."""
    client, _, cursor = setup
    signed_in(client, role="Event Coordinator Lead")
    assigned = {**saved_row(), "status": "Under Review", "coordinator_id": COORDINATOR_ID}
    cursor.fetchall.return_value = [saved_row(), assigned]
    response = client.get("/events/active")
    assert response.status_code == 200
    assert [event["coordinatorId"] for event in response.json["events"]] == [None, COORDINATOR_ID]
    query, params = cursor.execute.call_args.args
    assert "WHERE status NOT IN %s" in query
    assert "coordinator_id" not in query.split("WHERE")[1]
    assert params == [("Confirmed", "Rejected", "Cancelled")]
    assert "ORDER BY preferred_start_date ASC NULLS LAST" in query


def test_active_events_need_database(monkeypatch):
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": ""}).test_client(), role="Event Coordinator Lead")
    assert client.get("/events/active").status_code == 503


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


# Supporting decision/configuration guards: inherited submission behavior,
# deliberately not attributed to SCRUM-49 notification acceptance criteria.
@pytest.mark.parametrize("route,body", [
    ("approve", {"coordinatorId": COORDINATOR_ID}),
    ("reject", {"coordinatorId": COORDINATOR_ID, "reason": "Unsafe exits."}),
], ids=["approve-without-database-503", "reject-without-database-503"])
def test_decision_without_database_configuration_never_connects(setup, route, body):
    """Failure: approval and rejection cannot report success without Event storage."""
    client, connection, cursor = setup
    client.application.config["DATABASE_URL"] = None

    response = client.patch(f"/events/00000000-0000-0000-0000-000000000001/{route}", json=body)

    assert response.status_code == 503
    assert response.json == {"message": "DATABASE_URL is not configured for Event Service."}
    connection.cursor.assert_not_called()
    cursor.execute.assert_not_called()


def test_reject_unknown_event_does_not_write_a_decision(setup):
    """Failure: rejecting an unknown event returns not-found without a write."""
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = client.patch("/events/00000000-0000-0000-0000-000000000001/reject",
                            json={"coordinatorId": COORDINATOR_ID, "reason": "Unsafe exits."})

    assert response.status_code == 404
    assert response.json == {"message": "Event request not found."}
    assert cursor.execute.call_count == 1
    assert cursor.execute.call_args.args[0].lstrip().startswith("SELECT")


def test_public_rejection_model_refuses_whitespace_reason_before_writing(setup):
    """Failure: a non-HTTP caller cannot record a rejection with only whitespace."""
    _, connection, cursor = setup
    cursor.fetchone.return_value = {**saved_row(), "coordinator_id": COORDINATOR_ID}

    with pytest.raises(RejectionReasonError):
        reject_event("unused-test-url", "00000000-0000-0000-0000-000000000001", COORDINATOR_ID, " \t\n")

    assert cursor.execute.call_count == 1
    assert cursor.execute.call_args.args[0].lstrip().startswith("SELECT")
    assert connection.__exit__.call_args.args[0] is RejectionReasonError
    connection.close.assert_called_once()


def test_unconfigured_frontend_origin_does_not_authorise_browser_access():
    """Boundary: no configured frontend origin leaves a foreign browser origin disallowed."""
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None, "FRONTEND_ORIGIN": ""}).test_client())

    response = client.get("/health", headers={"Origin": "http://localhost:5174"})

    assert response.status_code == 200
    assert response.json == {"status": "ok"}
    assert "Access-Control-Allow-Origin" not in response.headers
