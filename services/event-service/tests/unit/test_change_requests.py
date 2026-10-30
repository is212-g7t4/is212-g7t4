"""Event Organiser change-request story: proposal creation and workflow guards."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from app import create_app
from app.models import FIELDS
from tests.unit.factories import signed_in

EVENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ORGANISER_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "22222222-2222-4222-8222-222222222222"
COORDINATOR_ID = "33333333-3333-4333-8333-333333333333"
CHANGE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def event_row(status="Submitted", organiser_id=ORGANISER_ID):
    row = {column: "" for column in FIELDS.values()}
    row.update(
        event_id=EVENT_ID,
        event_name="Community Workshop",
        description=json.dumps({
            "_connectsphere": "event-submission-v1",
            "description": "Original description",
            "purpose": "Learning",
        }),
        preferred_start_date=datetime(2026, 11, 1, 9),
        preferred_end_date=datetime(2026, 11, 1, 12),
        expected_attendance=30,
        status=status,
        submission_date=datetime(2026, 10, 1, tzinfo=UTC),
        coordinator_id=None,
        organiser_id=organiser_id,
        assigned_by=None,
        assigned_at=None,
        previous_coordinator_id=None,
    )
    return row


def change_row():
    return {
        "change_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "event_id": EVENT_ID,
        "requested_changes": {"expectedAttendance": "40"},
        "status": "Pending Review",
        "request_date": datetime(2026, 10, 23, 4, 5, tzinfo=UTC),
        "requested_by": ORGANISER_ID,
        "reason": "More guests accepted the invitation.",
    }


def review_row(change_status="Pending Review", coordinator_id=COORDINATOR_ID):
    return {
        **event_row("Approved"),
        "coordinator_id": coordinator_id,
        "change_id": CHANGE_ID,
        "requested_changes": {"expectedAttendance": "40"},
        "change_request_status": change_status,
        "request_date": datetime(2026, 10, 23, 4, 5, tzinfo=UTC),
        "requested_by": ORGANISER_ID,
        "reason": "More guests accepted the invitation.",
        "rejection_reason": None,
        "review_date": None,
        "reviewed_by": None,
    }


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url", "INTERNAL_SERVICE_TOKEN": "workflow-token"})
    client = signed_in(app.test_client(), role="Event Organiser")
    # The review routes are only for Event Workflow Service, which always sends this header (SCRUM-10: fails closed).
    client.environ_base["HTTP_X_INTERNAL_SERVICE_TOKEN"] = "workflow-token"
    return client, connection, cursor


def post(client, **overrides):
    body = {
        "organiserId": ORGANISER_ID,
        "changes": {"expectedAttendance": "40"},
        "reason": "More guests accepted the invitation.",
        **overrides,
    }
    return client.post(f"/events/{EVENT_ID}/change-requests", json=body)


@pytest.mark.parametrize("status", ["Submitted", "Under Review", "Approved"])
def test_ac1_ac6_eligible_owner_creates_a_pending_audit_record(setup, status):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(status), change_row()]

    response = post(client)

    assert response.status_code == 201
    assert response.json == {
        "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "eventId": EVENT_ID,
        "proposedChanges": {"expectedAttendance": "40"},
        "status": "Pending Review",
        "requestedAt": "2026-10-23T04:05:00+00:00",
        "requestedBy": ORGANISER_ID,
        "reason": "More guests accepted the invitation.",
    }
    insert, parameters = cursor.execute.call_args_list[1].args
    assert 'INSERT INTO public."EventChangeReq"' in insert
    assert "ON CONFLICT (event_id) WHERE status = 'Pending Review'" in insert
    assert json.loads(parameters[1]) == {"expectedAttendance": "40"}
    assert all("UPDATE public.\"Event\"" not in call.args[0] for call in cursor.execute.call_args_list)


@pytest.mark.parametrize("status", [
    "Draft", "Clarification Requested", "Rejected", "Pending Safety Check",
    "Confirmed", "Safety Changes Requested", "Completed", "Cancelled",
])
def test_ac2_every_other_status_is_refused_without_creating_a_request(setup, status):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(status)
    response = post(client)
    assert response.status_code == 409
    assert response.json["code"] == "CHANGE_REQUEST_NOT_ALLOWED"
    assert len(cursor.execute.call_args_list) == 1


def test_ac4_reason_is_required_before_database_access(setup):
    client, _, cursor = setup
    response = post(client, reason="   ")
    assert response.status_code == 400
    assert response.json["message"] == "A reason or justification is required."
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("body", [None, [], "not an object"])
def test_request_body_must_be_a_json_object(setup, body):
    client, _, cursor = setup
    response = client.post(
        f"/events/{EVENT_ID}/change-requests",
        json=body,
    )
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_nonempty_changes_are_required_before_database_access(setup):
    client, _, cursor = setup
    assert post(client, changes={}).status_code == 400
    assert post(client, changes="expected attendance").status_code == 400
    cursor.execute.assert_not_called()


def test_unconfigured_database_returns_service_unavailable():
    app = create_app({"TESTING": True, "DATABASE_URL": None})
    response = post(signed_in(app.test_client()))
    assert response.status_code == 503


def test_reason_must_be_text(setup):
    client, _, cursor = setup
    assert post(client, reason=123).status_code == 400
    cursor.execute.assert_not_called()


def test_ac6_only_the_event_owner_can_submit(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(organiser_id=OTHER_ID)
    response = post(client)
    assert response.status_code == 403
    assert len(cursor.execute.call_args_list) == 1


def test_ac4_at_least_one_value_must_actually_change(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()
    response = post(client, changes={"expectedAttendance": "30"})
    assert response.status_code == 400
    assert "must differ" in response.json["message"]
    assert len(cursor.execute.call_args_list) == 1


def test_ac3_unknown_fields_and_non_text_values_are_refused_before_database_access(setup):
    client, _, cursor = setup
    assert post(client, changes={"status": "Cancelled"}).status_code == 400
    assert post(client, changes={"expectedAttendance": 40}).status_code == 400
    cursor.execute.assert_not_called()


def test_ac3_invalid_combined_details_are_not_recorded(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()
    response = post(client, changes={"preferredEndDate": "2026-11-01T08:00"})
    assert response.status_code == 400
    assert response.json["errors"] == ["Preferred End Date & Time must be after the start."]
    assert len(cursor.execute.call_args_list) == 1


def test_required_event_details_cannot_be_proposed_as_blank(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()
    response = post(client, changes={"eventName": "  "})
    assert response.status_code == 400
    assert response.json["missingFields"] == ["Event Name"]
    assert len(cursor.execute.call_args_list) == 1


def test_one_pending_request_per_event(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), None]
    response = post(client)
    assert response.status_code == 409
    assert response.json["code"] == "CHANGE_REQUEST_ALREADY_PENDING"


def test_missing_event_returns_not_found(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = None
    assert post(client).status_code == 404


def test_review_ac1_ac2_lists_pending_requests_for_events_managed_by_the_coordinator(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = [review_row()]

    response = client.get(f"/change-requests?coordinatorId={COORDINATOR_ID}")

    assert response.status_code == 200
    change = response.json["changeRequests"][0]
    assert change["id"] == CHANGE_ID
    assert change["event"]["eventName"] == "Community Workshop"
    assert change["event"]["expectedAttendance"] == "30"
    assert change["proposedChanges"] == {"expectedAttendance": "40"}
    assert change["reason"] == "More guests accepted the invitation."
    query, params = cursor.execute.call_args.args
    assert "request.status = 'Pending Review'" in query
    assert "event.coordinator_id = %s" in query
    assert params == [COORDINATOR_ID]


def test_review_ac3_approval_updates_event_and_decision_in_one_transaction(setup):
    client, _, cursor = setup
    updated_event = event_row("Approved")
    updated_event.update(coordinator_id=COORDINATOR_ID, expected_attendance=40)
    cursor.fetchone.side_effect = [
        review_row(),
        updated_event,
        {
            "status": "Approved",
            "review_date": datetime(2026, 10, 24, 2, 0, tzinfo=UTC),
            "reviewed_by": COORDINATOR_ID,
            "rejection_reason": None,
        },
    ]

    response = client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
    )

    assert response.status_code == 200
    assert response.json["status"] == "Approved"
    assert response.json["reviewedBy"] == COORDINATOR_ID
    assert response.json["event"]["expectedAttendance"] == "40"
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert 'UPDATE public."Event"' in statements[1]
    assert 'UPDATE public."EventChangeReq"' in statements[2]
    assert cursor.execute.call_args_list[2].args[1][:3] == [
        "Approved", COORDINATOR_ID, None,
    ]


def test_review_ac4_rejection_records_required_reason_without_updating_event(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        review_row(),
        {
            "status": "Rejected",
            "review_date": datetime(2026, 10, 24, 2, 0, tzinfo=UTC),
            "reviewed_by": COORDINATOR_ID,
            "rejection_reason": "The revised capacity cannot be supported.",
        },
    ]

    response = client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={
            "coordinatorId": COORDINATOR_ID,
            "decision": "Rejected",
            "reason": "The revised capacity cannot be supported.",
        },
    )

    assert response.status_code == 200
    assert response.json["rejectionReason"] == "The revised capacity cannot be supported."
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert all('UPDATE public."Event"' not in statement for statement in statements)
    assert 'UPDATE public."EventChangeReq"' in statements[1]


def test_review_rejection_reason_is_required_before_database_access(setup):
    client, _, cursor = setup
    response = client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Rejected", "reason": "  "},
    )
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_review_only_the_assigned_coordinator_can_read_or_decide(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = review_row(coordinator_id=OTHER_ID)

    assert client.get(
        f"/change-requests/{CHANGE_ID}?coordinatorId={COORDINATOR_ID}"
    ).status_code == 403
    assert client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
    ).status_code == 403


def test_review_assigned_coordinator_can_open_request_details(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = review_row()
    response = client.get(
        f"/change-requests/{CHANGE_ID}?coordinatorId={COORDINATOR_ID}"
    )
    assert response.status_code == 200
    assert response.json["id"] == CHANGE_ID
    assert response.json["event"]["expectedAttendance"] == "30"


def test_review_a_decided_request_cannot_be_processed_again(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = review_row(change_status="Approved")
    response = client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
    )
    assert response.status_code == 409
    assert response.json["code"] == "CHANGE_REQUEST_ALREADY_DECIDED"


def test_review_missing_request_returns_not_found_for_read_and_decision(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = None
    assert client.get(
        f"/change-requests/{CHANGE_ID}?coordinatorId={COORDINATOR_ID}"
    ).status_code == 404
    assert client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
    ).status_code == 404


def test_review_approval_is_refused_if_event_stage_has_moved_on(setup):
    client, _, cursor = setup
    row = review_row()
    row["status"] = "Confirmed"
    cursor.fetchone.return_value = row
    response = client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
    )
    assert response.status_code == 409
    assert response.json["code"] == "CHANGE_REQUEST_NOT_APPLICABLE"


def test_review_invalid_stored_proposal_is_refused(setup):
    client, _, cursor = setup
    row = review_row()
    row["requested_changes"] = {"status": "Cancelled"}
    cursor.fetchone.return_value = row
    response = client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
    )
    assert response.status_code == 409
    assert response.json["code"] == "INVALID_STORED_PROPOSAL"


def test_review_stored_proposal_must_still_form_a_valid_event(setup):
    client, _, cursor = setup
    row = review_row()
    row["requested_changes"] = {"preferredEndDate": "2026-11-01T08:00"}
    cursor.fetchone.return_value = row
    response = client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
    )
    assert response.status_code == 409
    assert response.json["code"] == "INVALID_STORED_PROPOSAL"
    assert response.json["errors"] == ["Preferred End Date & Time must be after the start."]


def test_review_already_applied_values_can_still_close_the_request(setup):
    client, _, cursor = setup
    row = review_row()
    row["requested_changes"] = {"expectedAttendance": "30"}
    cursor.fetchone.side_effect = [
        row,
        {
            "status": "Approved",
            "review_date": datetime(2026, 10, 24, 2, 0, tzinfo=UTC),
            "reviewed_by": COORDINATOR_ID,
            "rejection_reason": None,
        },
    ]
    response = client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
    )
    assert response.status_code == 200
    assert all(
        'UPDATE public."Event"' not in call.args[0]
        for call in cursor.execute.call_args_list
    )


@pytest.mark.parametrize(
    "path,method,body",
    [
        (f"/change-requests/{CHANGE_ID}/decision", "patch", None),
        (f"/change-requests/{CHANGE_ID}/decision", "patch", {"coordinatorId": COORDINATOR_ID, "decision": "Maybe"}),
        (f"/change-requests/{CHANGE_ID}/decision", "patch", {"coordinatorId": COORDINATOR_ID, "decision": "Rejected", "reason": "x" * 2001}),
    ],
)
def test_review_malformed_requests_are_rejected_before_database_access(setup, path, method, body):
    client, _, cursor = setup
    signed_in(client, role="Event Coordinator")  # decisions are a coordinator's (SCRUM-10)
    if method == "get":
        response = client.get(path)
    else:
        response = client.patch(path, json=body) if body is not None else client.patch(path, data="x")
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_review_unconfigured_database_returns_service_unavailable():
    client = signed_in(create_app({
        "TESTING": True, "DATABASE_URL": None, "INTERNAL_SERVICE_TOKEN": "workflow-token",
    }).test_client())
    client.environ_base["HTTP_X_INTERNAL_SERVICE_TOKEN"] = "workflow-token"
    assert client.get(f"/change-requests?coordinatorId={COORDINATOR_ID}").status_code == 503
    assert client.get(f"/change-requests/{CHANGE_ID}?coordinatorId={COORDINATOR_ID}").status_code == 503
    assert client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
    ).status_code == 503


def test_review_internal_endpoints_honor_the_configured_service_token(monkeypatch):
    connection = MagicMock()
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    client = signed_in(create_app({
        "TESTING": True,
        "DATABASE_URL": "unused-test-url",
        "INTERNAL_SERVICE_TOKEN": "secret",
    }).test_client())

    responses = [
        client.get(f"/change-requests?coordinatorId={COORDINATOR_ID}"),
        client.get(f"/change-requests/{CHANGE_ID}?coordinatorId={COORDINATOR_ID}"),
        client.patch(
            f"/change-requests/{CHANGE_ID}/decision",
            json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
        ),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403]
    connection.cursor.assert_not_called()


def test_review_routes_fail_closed_when_the_service_token_is_not_configured(monkeypatch):
    """Failure: an unconfigured token used to switch the lock off; now the routes answer 503 and touch nothing."""
    connection = MagicMock()
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    client = signed_in(create_app({
        "TESTING": True, "DATABASE_URL": "unused-test-url", "INTERNAL_SERVICE_TOKEN": None,
    }).test_client())

    responses = [
        client.get(f"/change-requests?coordinatorId={COORDINATOR_ID}"),
        client.get(f"/change-requests/{CHANGE_ID}?coordinatorId={COORDINATOR_ID}"),
        client.patch(
            f"/change-requests/{CHANGE_ID}/decision",
            json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
        ),
    ]

    assert [response.status_code for response in responses] == [503, 503, 503]
    assert {response.json["code"] for response in responses} == {"INTERNAL_AUTH_NOT_CONFIGURED"}
    connection.cursor.assert_not_called()
