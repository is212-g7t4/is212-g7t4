"""Registration lookups: list every registration row for a given event.

Database calls are mocked; no live database writes.
"""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.models import CapacityReachedError, DuplicateRegistrationError, create_registration

EVENT_ID = "25c9fe40-c44d-4d79-8d5d-de66d40c1678"
ATTENDEE_ID = "56b34ab1-92cd-4b35-83c7-f04e176e2bd0"


def registration_row(**overrides):
    row = {
        "registration_id": "9f725c7a-ac3d-4d4a-937a-84db7906be71",
        "event_id": EVENT_ID,
        "attendee_id": None,
        "registration_date": datetime(2026, 9, 13, 9, 15),
        "status": "Confirmed",
        "attendee_name": "Lena Ho",
        "attendee_email": "lena.ho@example.com",
        "attendee_organization": "Acme Studio",
    }
    row.update(overrides)
    return row


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({
        "TESTING": True,
        "DATABASE_URL": "unused-test-url",
        "FRONTEND_ORIGIN": "http://localhost:5174",
    })
    return app.test_client(), connection, cursor


def test_list_registrations_returns_all_rows_for_event(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = [
        registration_row(),
        registration_row(registration_id="1eec36d7-3c51-4981-8f80-ae62f7f99b7f", status="Withdrawn", attendee_organization=""),
    ]

    response = client.get(f"/registrations?eventId={EVENT_ID}")

    assert response.status_code == 200
    assert len(response.json["registrations"]) == 2
    assert response.json["registrations"][0]["status"] == "Confirmed"
    assert response.json["registrations"][1]["status"] == "Withdrawn"
    query, params = cursor.execute.call_args.args
    assert "WHERE event_id = %s" in query
    assert params == [EVENT_ID]


def test_list_registrations_returns_empty_list_when_none_exist(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = []

    response = client.get(f"/registrations?eventId={EVENT_ID}")

    assert response.status_code == 200
    assert response.json == {"registrations": []}


def test_registration_date_serializes_to_isoformat(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = [registration_row()]

    response = client.get(f"/registrations?eventId={EVENT_ID}")

    assert response.json["registrations"][0]["registration_date"] == "2026-09-13T09:15:00"


def test_null_registration_date_serializes_to_none(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = [registration_row(registration_date=None)]

    response = client.get(f"/registrations?eventId={EVENT_ID}")

    assert response.json["registrations"][0]["registration_date"] is None


@pytest.mark.parametrize("query_string", ["", "?eventId=", "?eventId=not-a-uuid"])
def test_requires_valid_event_id(query_string, setup):
    client, _, cursor = setup
    response = client.get(f"/registrations{query_string}")
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_missing_database_configuration():
    client = create_app({"TESTING": True, "DATABASE_URL": None}).test_client()
    response = client.get(f"/registrations?eventId={EVENT_ID}")
    assert response.status_code == 503


def test_health_and_browser_cors(setup):
    client = setup[0]
    assert client.get("/health").json == {"status": "ok"}
    response = client.options("/registrations", headers={"Origin": "http://localhost:5174"})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert (
        "Access-Control-Allow-Origin"
        not in client.options("/registrations", headers={"Origin": "https://other.example"}).headers
    )


OTHER_EVENT_ID = "11111111-1111-4111-8111-111111111111"


def test_counts_returns_total_and_confirmed_per_event_with_zeros_for_empty(setup):
    """Organiser registration view AC2: total registrations per event."""
    client, _, cursor = setup
    cursor.fetchall.return_value = [{"event_id": EVENT_ID, "total": 5, "confirmed": 3}]

    response = client.get(f"/registrations/counts?eventIds={EVENT_ID},{OTHER_EVENT_ID},{EVENT_ID}")

    assert response.status_code == 200
    assert response.json["counts"] == {
        EVENT_ID: {"total": 5, "confirmed": 3},
        OTHER_EVENT_ID: {"total": 0, "confirmed": 0},
    }
    assert cursor.execute.call_args.args[1] == [[EVENT_ID, OTHER_EVENT_ID]]


@pytest.mark.parametrize("value", ["", "nope", f"{EVENT_ID},nope"])
def test_counts_rejects_missing_or_invalid_event_ids(setup, value):
    client, _, cursor = setup
    assert client.get(f"/registrations/counts?eventIds={value}").status_code == 400
    cursor.execute.assert_not_called()


def test_counts_reports_missing_database_url(setup):
    client, _, _ = setup
    client.application.config["DATABASE_URL"] = None
    assert client.get(f"/registrations/counts?eventIds={EVENT_ID}").status_code == 503


def registration_payload(**overrides):
    payload = {
        "eventId": EVENT_ID,
        "attendeeId": ATTENDEE_ID,
        "capacity": 30,
        "fullName": "Adam Yeo",
        "email": "Adam@Example.com",
        "organization": "External",
    }
    payload.update(overrides)
    return payload


def test_create_registration_endpoint_returns_confirmed_record(setup, monkeypatch):
    client = setup[0]
    saved = registration_row(attendee_id=ATTENDEE_ID, attendee_email="adam@example.com")
    monkeypatch.setattr("app.create_registration", lambda *args: {
        "registration_id": saved["registration_id"],
        "event_id": EVENT_ID,
        "attendee_id": ATTENDEE_ID,
        "status": "Confirmed",
    })

    response = client.post("/registrations", json=registration_payload())

    assert response.status_code == 201
    assert response.json["registration"]["status"] == "Confirmed"


@pytest.mark.parametrize(
    "payload",
    [None, {}, registration_payload(eventId="bad"), registration_payload(capacity=0),
     registration_payload(fullName=""), registration_payload(email="")],
)
def test_create_registration_endpoint_validates_required_values(setup, payload):
    response = setup[0].post("/registrations", json=payload)
    assert response.status_code == 400


@pytest.mark.parametrize(
    ("error", "code"),
    [(DuplicateRegistrationError, "DUPLICATE_REGISTRATION"), (CapacityReachedError, "EVENT_FULL")],
)
def test_create_registration_endpoint_reports_business_conflicts(setup, monkeypatch, error, code):
    def fail(*args):
        raise error

    monkeypatch.setattr("app.create_registration", fail)
    response = setup[0].post("/registrations", json=registration_payload())
    assert response.status_code == 409
    assert response.json["code"] == code


def test_create_registration_endpoint_requires_database(setup):
    client = setup[0]
    client.application.config["DATABASE_URL"] = None
    assert client.post("/registrations", json=registration_payload()).status_code == 503


def test_create_registration_locks_checks_capacity_and_inserts(setup):
    _, _, cursor = setup
    created = registration_row(attendee_id=ATTENDEE_ID, attendee_email="adam@example.com")
    cursor.fetchone.side_effect = [None, {"confirmed": 2}, created]

    result = create_registration(
        "unused-test-url", EVENT_ID, ATTENDEE_ID, 3,
        "Adam Yeo", "adam@example.com", "External",
    )

    assert result["status"] == "Confirmed"
    assert cursor.execute.call_count == 4
    assert "pg_advisory_xact_lock" in cursor.execute.call_args_list[0].args[0]
    assert "INSERT INTO" in cursor.execute.call_args_list[3].args[0]


def test_create_registration_rejects_duplicate_email(setup):
    cursor = setup[2]
    cursor.fetchone.return_value = {"exists": 1}
    with pytest.raises(DuplicateRegistrationError):
        create_registration(
            "unused-test-url", EVENT_ID, ATTENDEE_ID, 3,
            "Adam Yeo", "adam@example.com", "External",
        )
    assert cursor.execute.call_count == 2


def test_create_registration_rejects_full_event(setup):
    cursor = setup[2]
    cursor.fetchone.side_effect = [None, {"confirmed": 3}]
    with pytest.raises(CapacityReachedError):
        create_registration(
            "unused-test-url", EVENT_ID, ATTENDEE_ID, 3,
            "Adam Yeo", "adam@example.com", "External",
        )
    assert cursor.execute.call_count == 3
