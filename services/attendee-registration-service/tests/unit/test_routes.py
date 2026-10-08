from unittest.mock import Mock

import pytest

from app import create_app
from app.clients import RegistrationConflictError

EVENT_ID = "25c9fe40-c44d-4d79-8d5d-de66d40c1678"
ATTENDEE_ID = "56b34ab1-92cd-4b35-83c7-f04e176e2bd0"


@pytest.fixture
def client():
    return create_app({"TESTING": True, "FRONTEND_ORIGIN": "http://localhost:5174"}).test_client()


def payload(**overrides):
    data = {
        "eventId": EVENT_ID,
        "attendeeId": ATTENDEE_ID,
        "fullName": "Adam Yeo",
        "email": "Adam@Example.com",
        "organization": "External",
    }
    data.update(overrides)
    return data


def confirmed_event(**overrides):
    event = {
        "id": EVENT_ID,
        "eventName": "Community Workshop",
        "status": "Confirmed",
        "preferredStartDate": "2099-11-10T09:00:00+08:00",
        "preferredEndDate": "2099-11-10T12:00:00+08:00",
        "expectedAttendance": "30",
        "venueId": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    }
    event.update(overrides)
    return event


def test_successful_registration_returns_confirmation(client, monkeypatch):
    saved = {"registration_id": "registration-1", "status": "Confirmed"}
    save = Mock(return_value=saved)
    monkeypatch.setattr("app.routes.get_confirmed_event", lambda event_id: confirmed_event())
    monkeypatch.setattr("app.routes.save_registration", save)

    response = client.post("/registrations", json=payload())

    assert response.status_code == 201
    assert response.json["message"] == "Registration confirmed for Community Workshop."
    assert response.json["registration"] == saved
    assert save.call_args.args[0] == {
        **payload(email="adam@example.com"),
        "capacity": 30,
    }


def test_attendee_lists_registration_status_with_event_details(client, monkeypatch):
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda attendee_id: [{
        "registration_id": "registration-1",
        "event_id": EVENT_ID,
        "attendee_id": attendee_id,
        "registration_date": "2026-10-08T10:00:00",
        "status": "Confirmed",
        "attendee_name": "Adam Yeo",
        "attendee_email": "adam@example.com",
        "attendee_organization": "External",
    }])
    monkeypatch.setattr("app.routes.get_confirmed_events", lambda: [confirmed_event()])

    response = client.get(f"/registrations?attendeeId={ATTENDEE_ID}")

    assert response.status_code == 200
    assert response.json["registrations"][0]["registration"]["status"] == "Confirmed"
    assert response.json["registrations"][0]["event"]["eventName"] == "Community Workshop"


def test_attendee_with_no_registrations_receives_empty_list(client, monkeypatch):
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda attendee_id: [])
    monkeypatch.setattr("app.routes.get_confirmed_events", lambda: [])
    response = client.get(f"/registrations?attendeeId={ATTENDEE_ID}")
    assert response.status_code == 200
    assert response.json == {"registrations": []}


def test_attendee_registration_list_validates_id_and_handles_failure(client, monkeypatch):
    assert client.get("/registrations?attendeeId=bad").status_code == 400
    monkeypatch.setattr("app.routes.get_attendee_registrations", Mock(side_effect=RuntimeError("secret")))
    response = client.get(f"/registrations?attendeeId={ATTENDEE_ID}")
    assert response.status_code == 502
    assert "secret" not in response.json["message"]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (None, "Send a JSON object."),
        (payload(fullName=""), "Full name"),
        (payload(email=""), "Email address"),
        (payload(email="not-an-email"), "Enter a valid email address."),
    ],
)
def test_registration_validates_form(client, body, expected):
    response = client.post("/registrations", json=body)
    assert response.status_code == 400
    assert expected in str(response.json)


def test_registration_requires_valid_ids(client):
    response = client.post("/registrations", json=payload(eventId="bad"))
    assert response.status_code == 400
    assert "valid event and attendee" in response.json["message"]


def test_non_confirmed_event_is_not_open(client, monkeypatch):
    monkeypatch.setattr("app.routes.get_confirmed_event", lambda event_id: None)
    response = client.post("/registrations", json=payload())
    assert response.status_code == 409
    assert response.json["code"] == "REGISTRATION_CLOSED"


def test_started_event_is_closed(client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.get_confirmed_event",
        lambda event_id: confirmed_event(preferredStartDate="2020-01-01T09:00:00+08:00"),
    )
    response = client.post("/registrations", json=payload())
    assert response.status_code == 409
    assert response.json["code"] == "REGISTRATION_CLOSED"


@pytest.mark.parametrize("capacity", [None, "invalid", 0])
def test_event_requires_valid_capacity(client, monkeypatch, capacity):
    monkeypatch.setattr(
        "app.routes.get_confirmed_event",
        lambda event_id: confirmed_event(expectedAttendance=capacity),
    )
    response = client.post("/registrations", json=payload())
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("DUPLICATE_REGISTRATION", "This email is already registered for the event."),
        ("EVENT_FULL", "This event has reached maximum capacity."),
    ],
)
def test_registration_preserves_atomic_conflicts(client, monkeypatch, code, message):
    monkeypatch.setattr("app.routes.get_confirmed_event", lambda event_id: confirmed_event())

    def fail(data):
        raise RegistrationConflictError(code, message)

    monkeypatch.setattr("app.routes.save_registration", fail)
    response = client.post("/registrations", json=payload())
    assert response.status_code == 409
    assert response.json == {"code": code, "message": message}


def test_downstream_failures_are_safe(client, monkeypatch):
    monkeypatch.setattr("app.routes.get_confirmed_event", Mock(side_effect=RuntimeError("secret")))
    response = client.post("/registrations", json=payload())
    assert response.status_code == 502
    assert "secret" not in response.json["message"]

    monkeypatch.setattr("app.routes.get_confirmed_event", lambda event_id: confirmed_event())
    monkeypatch.setattr("app.routes.save_registration", Mock(side_effect=RuntimeError("secret")))
    response = client.post("/registrations", json=payload())
    assert response.status_code == 502
    assert "secret" not in response.json["message"]


def test_health_and_cors(client):
    assert client.get("/health").json == {"status": "ok"}
    response = client.options("/registrations", headers={"Origin": "http://localhost:5174"})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert "Access-Control-Allow-Origin" not in client.options(
        "/registrations", headers={"Origin": "https://other.example"}
    ).headers
