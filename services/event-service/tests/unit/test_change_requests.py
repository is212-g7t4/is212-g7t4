"""Event Organiser change-request story: proposal creation and workflow guards."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from app import create_app
from app.models import FIELDS

EVENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ORGANISER_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "22222222-2222-4222-8222-222222222222"


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


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), connection, cursor


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


def test_organiser_id_and_nonempty_changes_are_required_before_database_access(setup):
    client, _, cursor = setup
    assert post(client, organiserId="not-a-uuid").status_code == 400
    assert post(client, changes={}).status_code == 400
    assert post(client, changes="expected attendance").status_code == 400
    cursor.execute.assert_not_called()


def test_unconfigured_database_returns_service_unavailable():
    app = create_app({"TESTING": True, "DATABASE_URL": None})
    response = post(app.test_client())
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
