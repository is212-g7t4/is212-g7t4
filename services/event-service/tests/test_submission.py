"""Event submission AC1–AC4. Database calls are mocked; no live database writes."""
import json
from datetime import datetime
from unittest.mock import MagicMock
from uuid import UUID

import psycopg2
import pytest

from app import create_app
from app.models import FIELDS, serialize, unpack_description

VALID = {
    "eventName": "Community Workshop", "description": "A workshop", "purpose": "Learning",
    "preferredStartDate": "2026-10-01T09:00", "preferredEndDate": "2026-10-01T17:00",
    "expectedAttendance": "25",
}


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), connection, cursor


def saved_row():
    row = {column: VALID.get(key, "") for key, column in FIELDS.items()}
    row.update(event_id="00000000-0000-0000-0000-000000000001", status="Submitted",
               submission_date=datetime(2026, 9, 15, 1, 30),
               preferred_start_date=datetime(2026, 10, 1, 9),
               preferred_end_date=datetime(2026, 10, 1, 17), expected_attendance=25)
    row["description"] = json.dumps({"_connectsphere": "event-submission-v1",
                                     "description": VALID["description"], "purpose": VALID["purpose"]})
    return row


def test_ac1_ac2_ac3_submit_existing_columns_and_return_confirmation_data(setup):
    client, connection, cursor = setup
    cursor.fetchone.return_value = saved_row()
    response = client.post("/events", json={**VALID, "status": "Approved", "submission_date": "fake"})
    assert response.status_code == 201
    assert response.json["status"] == "Submitted"
    assert response.json["submittedAt"] == "2026-09-15T01:30:00+00:00"
    assert response.json["purpose"] == "Learning"
    assert response.json["description"] == "A workshop"
    query, parameters = cursor.execute.call_args.args
    assert "INSERT INTO public.event_service" in query
    assert "timezone('UTC', CURRENT_TIMESTAMP)" in query
    assert "organiser_id" not in query and "purpose" not in query
    assert "'Submitted'" in query
    assert UUID(parameters[0])
    assert parameters[5] == 25
    assert json.loads(parameters[2])["purpose"] == "Learning"
    assert parameters[6:] == ["", "", "", ""]
    connection.__exit__.assert_called_once()
    connection.close.assert_called_once()


def test_optional_details_roundtrip(setup):
    client, _, cursor = setup
    row = saved_row()
    row["equipment_requirements"] = "Projector"
    cursor.fetchone.return_value = row
    response = client.post("/events", json={**VALID, "equipmentRequirements": "Projector"})
    assert response.json["equipmentRequirements"] == "Projector"
    assert cursor.execute.call_args.args[1][-2] == "Projector"


@pytest.mark.parametrize("field,label", [
    ("eventName", "Event Name"), ("description", "Description"), ("purpose", "Purpose"),
    ("preferredStartDate", "Preferred Start Date & Time"),
    ("preferredEndDate", "Preferred End Date & Time"), ("expectedAttendance", "Expected Attendance"),
])
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
        "Event Name", "Description", "Purpose", "Preferred Start Date & Time",
        "Preferred End Date & Time", "Expected Attendance"]


@pytest.mark.parametrize("value", ["0", "-1", "2.5", "abc", "2147483648", "9" * 5000, "²"])
def test_attendance_boundary_validation(setup, value):
    response = setup[0].post("/events", json={**VALID, "expectedAttendance": value})
    assert response.status_code == 400
    assert response.json["errors"]


@pytest.mark.parametrize("value", ["invalid", "2026-10-01", "2026-10-01T09:00", "2026-09-30T09:00", "2026-10-01T17:00+08:00"])
def test_invalid_period_validation(setup, value):
    assert setup[0].post("/events", json={**VALID, "preferredEndDate": value}).status_code == 400


@pytest.mark.parametrize("body", [None, [], "text"])
def test_invalid_json_body(setup, body):
    assert setup[0].post("/events", json=body).status_code == 400


def test_optional_field_wrong_type(setup):
    assert setup[0].post("/events", json={**VALID, "venueRequirements": []}).status_code == 400


def test_ac2_coordinator_queue_loads_persisted_data(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = [saved_row()]
    response = client.get("/events/submitted")
    assert response.status_code == 200
    assert response.json["events"][0]["eventName"] == "Community Workshop"
    query = cursor.execute.call_args.args[0]
    assert "WHERE status = 'Submitted'" in query
    assert "ORDER BY submission_date ASC NULLS LAST" in query


def test_empty_queue(setup):
    setup[2].fetchall.return_value = []
    assert setup[0].get("/events/submitted").json == {"events": []}


@pytest.mark.parametrize("value,description,purpose", [
    ("Legacy plain text", "Legacy plain text", ""), (None, "", ""),
    ('{"other":"value"}', '{"other":"value"}', ""), ("[]", "[]", ""),
])
def test_legacy_descriptions_are_not_rewritten(value, description, purpose):
    assert unpack_description(value) == (description, purpose)


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
        cursor.execute.side_effect = psycopg2.OperationalError("secret connection information")
    else:
        connection.__exit__.side_effect = psycopg2.OperationalError("commit failed")
    response = client.post("/events", json=VALID)
    assert response.status_code == 503
    assert "secret" not in response.text
    connection.close.assert_called_once()


def test_missing_database_configuration():
    client = create_app({"TESTING": True, "DATABASE_URL": None}).test_client()
    assert client.post("/events", json=VALID).status_code == 503
    assert client.get("/events/submitted").status_code == 503


def test_health_and_browser_cors(setup):
    client = setup[0]
    assert client.get("/health").json == {"status": "ok"}
    response = client.options("/events", headers={"Origin": "http://localhost:5173"})
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "Access-Control-Allow-Origin" not in client.options("/events", headers={"Origin": "https://other.example"}).headers

