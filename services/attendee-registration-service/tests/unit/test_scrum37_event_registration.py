"""
SCRUM-37: Event Registration

User Story
----------
As an Attendee, I want to register for a confirmed event, so that I can secure
my place and receive event details.

Acceptance Criteria
-------------------
AC1: The Attendee can access a registration form from a confirmed event that is
     open for registration.
AC2: The Attendee can provides required registration information including full
     name (required), Email address (required, must be valid format),
     organisation/company (optional)
AC3: The system validates that all required fields are completed before
     submission, and displays an error message if this is not the case.
AC4: Given the Attendee is already registered for the event with the same
     email, the system does not allow for the Attendee to register again.
AC5: Given registration has closed for the event, The system does not allow the
     Attendee to register.
AC6: Given the event has reached capacity, the system displays a message
     stating that the event has reaced max capacity.
AC7: Upon successful registration, a confirmation message on-screen is
     displayed to the Attendee

Real
----
- POST /registrations: form validation (app.validation), the Confirmed,
  not-started and capacity checks on the event, and the mapping of Registration
  Service's duplicate/full conflicts run for real, as do the Event and
  Registration client functions.
- Assertions are on the status, the message shown and what is saved.

Doubled
-------
- app.routes downstream adapters (get_confirmed_event, save_registration,
  get_attendee_registrations, get_user, ...): Stub / Mock via monkeypatch -
  return canned events, registrations and users, or raise; a Mock records what
  is saved.
- httpx.get / httpx.post (client tests): Stub - canned Event, Registration and
  User Service replies; URLs and headers inspected.

Not proven
----------
- The registration form and on-screen confirmation (AC1, AC2, AC7 UI half) (->
  frontend eventRegistration.test.ts and e2e event-registration.spec.ts).
- That Registration Service enforces one registration per attendee and the
  capacity under concurrency (-> registration-service
  test_scrum37_event_registration.py and its integration tests).
- Duplicate detection by email (AC4) - the system checks attendee id (raised as
  a finding).
"""

from datetime import datetime, timedelta
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import httpx
import pytest

from app import clients
from app.clients import RegistrationConflictError
from app.validation import event_has_started, validate_registration, withdrawal_deadline_has_passed
from tests.unit.factories import ATTENDEE_ID, EVENT_ID, USER, confirmed_event, payload, registration, response


def test_register_when_event_open_returns_confirmation(client, monkeypatch):
    """
    Summary: Registering for an open, confirmed event returns a confirmation.
    AC7: Upon successful registration, a confirmation message on-screen is
        displayed to the Attendee
    Double: Stub (confirmed event), Mock (save_registration)
    """
    saved = {"registration_id": "registration-1", "status": "Confirmed"}
    save = Mock(return_value=saved)
    monkeypatch.setattr("app.routes.get_confirmed_event", lambda event_id: confirmed_event())
    monkeypatch.setattr("app.routes.save_registration", save)

    response = client.post("/registrations", json=payload())

    assert response.status_code == 201
    assert response.json["message"] == "Registration confirmed for Community Workshop."
    assert response.json["registration"] == saved
    # SCRUM-46: the route captures name/schedule now; the save adapter (doubled
    # here) separately adds the actual Approved venue before writing the action.
    assert save.call_args.args[0] == {**payload(), "capacity": 30, "notificationContext": dict(
        eventName="Community Workshop", startDateTime=confirmed_event()["preferredStartDate"], endDateTime=confirmed_event()["preferredEndDate"])}


def test_register_with_profile_fields_ignores_them(client, monkeypatch):
    """
    Summary: Name, email and organisation come from the attendee's profile, not the form body.
    AC2: The Attendee can provides required registration information including
        full name (required), Email address (required, must be valid format),
        organisation/company (optional)
    Double: Stub (confirmed event), Mock (save_registration)
    """
    save = Mock(return_value={"registration_id": "registration-1"})
    monkeypatch.setattr("app.routes.get_confirmed_event", lambda event_id: confirmed_event())
    monkeypatch.setattr("app.routes.save_registration", save)

    response = client.post(
        "/registrations",
        json=payload(fullName="Someone Else", email="other@example.com"),
    )

    assert response.status_code == 201
    # SCRUM-46: the route captures name/schedule now; the save adapter (doubled
    # here) separately adds the actual Approved venue before writing the action.
    assert save.call_args.args[0] == {**payload(), "capacity": 30, "notificationContext": dict(
        eventName="Community Workshop", startDateTime=confirmed_event()["preferredStartDate"], endDateTime=confirmed_event()["preferredEndDate"])}


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (None, "Send a JSON object."),
        (payload(eventId=""), "Event"),
    ],
    ids=["no_body", "blank_event"],
)
def test_register_with_missing_event_returns_400_naming_it(client, body, expected):
    """
    Summary: A registration without a body or an event is refused with a message saying what is missing.
    AC3: The system validates that all required fields are completed before
        submission, and displays an error message if this is not the case.
    Double: None
    """
    response = client.post("/registrations", json=body)
    assert response.status_code == 400
    assert expected in str(response.json)


def test_register_with_malformed_event_id_returns_400(client):
    """
    Summary: A registration must name a valid event.
    AC3: The system validates that all required fields are completed before
        submission, and displays an error message if this is not the case.
    Double: None
    """
    response = client.post("/registrations", json=payload(eventId="bad"))
    assert response.status_code == 400
    assert "valid event" in response.json["message"]


def test_register_when_event_not_confirmed_returns_409(client, monkeypatch):
    """
    Summary: Only a confirmed event is open for registration.
    AC1: The Attendee can access a registration form from a confirmed event
        that is open for registration.
    Double: Stub (get_confirmed_event finds nothing)
    """
    monkeypatch.setattr("app.routes.get_confirmed_event", lambda event_id: None)
    response = client.post("/registrations", json=payload())
    assert response.status_code == 409
    assert response.json["code"] == "REGISTRATION_CLOSED"


def test_register_when_event_started_returns_409_closed(client, monkeypatch):
    """
    Summary: Registration closes once the event has started.
    AC5: Given registration has closed for the event, The system does not allow
        the Attendee to register.
    Double: Stub (confirmed event that already started)
    """
    # Arrange (Given)
    monkeypatch.setattr(
        "app.routes.get_confirmed_event",
        lambda event_id: confirmed_event(preferredStartDate="2020-01-01T09:00:00+08:00"),
    )

    # Act (When)
    response = client.post("/registrations", json=payload())

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "REGISTRATION_CLOSED"


@pytest.mark.parametrize("capacity", [None, "invalid", 0], ids=["missing", "not_a_number", "zero"])
def test_register_when_event_has_no_valid_capacity_returns_409(client, monkeypatch, capacity):
    """
    Summary: An event without a usable capacity cannot take registrations.
    AC6: Given the event has reached capacity, the system displays a message
        stating that the event has reaced max capacity.
    Double: Stub (confirmed event with missing, invalid or zero capacity)
    """
    # Arrange (Given)
    monkeypatch.setattr(
        "app.routes.get_confirmed_event",
        lambda event_id: confirmed_event(expectedAttendance=capacity),
    )

    # Act (When)
    response = client.post("/registrations", json=payload())

    # Assert (Then)
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("DUPLICATE_REGISTRATION", "You are already registered for this event."),
        ("EVENT_FULL", "This event has reached maximum capacity."),
    ],
    ids=["already_registered", "event_full"],
)
def test_register_when_duplicate_or_full_shows_the_reason(client, monkeypatch, code, message):
    """
    Summary: Already registered and event-full refusals reach the attendee with a clear message.
    AC4: Given the Attendee is already registered for the event with the same
        email, the system does not allow for the Attendee to register again.
    AC6: Given the event has reached capacity, the system displays a message
        stating that the event has reaced max capacity.
    Double: Stub (save_registration raises RegistrationConflictError)
    """
    # Arrange (Given)
    monkeypatch.setattr("app.routes.get_confirmed_event", lambda event_id: confirmed_event())

    def fail(data):
        raise RegistrationConflictError(code, message)

    monkeypatch.setattr("app.routes.save_registration", fail)

    # Act (When)
    response = client.post("/registrations", json=payload())

    # Assert (Then)
    assert response.status_code == 409
    assert response.json == {"code": code, "message": message}


def test_register_when_downstream_fails_returns_502_without_details(client, monkeypatch):
    """
    Summary: If a downstream service fails, the attendee gets a safe error rather than a false confirmation.
    AC7: Upon successful registration, a confirmation message on-screen is
        displayed to the Attendee
    Double: Stub (downstream adapter raises)
    """
    monkeypatch.setattr("app.routes.get_confirmed_event", Mock(side_effect=RuntimeError("secret")))
    response = client.post("/registrations", json=payload())
    assert response.status_code == 502
    assert "secret" not in response.json["message"]

    monkeypatch.setattr("app.routes.get_confirmed_event", lambda event_id: confirmed_event())
    monkeypatch.setattr("app.routes.save_registration", Mock(side_effect=RuntimeError("secret")))
    response = client.post("/registrations", json=payload())
    assert response.status_code == 502
    assert "secret" not in response.json["message"]


def test_validate_registration_trims_ids_and_drops_profile_fields():
    """
    Summary: Form ids are trimmed and profile fields dropped before use.
    AC2: The Attendee can provides required registration information including
        full name (required), Email address (required, must be valid format),
        organisation/company (optional)
    AC3: The system validates that all required fields are completed before
        submission, and displays an error message if this is not the case.
    Double: None
    """
    cleaned, errors, missing = validate_registration({
        "eventId": " event ",
        "fullName": "Adam Yeo", "email": "adam@example.com",
    })
    assert errors == []
    assert missing == []
    assert cleaned == {"eventId": "event"}


def test_event_has_started_compares_in_singapore_time():
    """
    Summary: Whether an event has started is judged in Singapore time.
    AC5: Given registration has closed for the event, The system does not allow
        the Attendee to register.
    Double: None
    """
    # Arrange (Given)
    now = datetime(2026, 10, 8, 10, 0, tzinfo=ZoneInfo("Asia/Singapore"))

    # Act + Assert (When / Then)
    assert event_has_started({"preferredStartDate": "2026-10-08T09:00:00"}, now)
    assert not event_has_started({"preferredStartDate": "2026-10-08T11:00:00"}, now)
    assert event_has_started(
        {"preferredStartDate": "2026-10-08T09:00:00+08:00"},
        datetime(2026, 10, 8, 10, 0),
    )


def test_event_has_started_without_date_raises():
    """
    Summary: An event without a start date cannot be judged open or closed.
    AC5: Given registration has closed for the event, The system does not allow
        the Attendee to register.
    Double: None
    """
    # Act + Assert (When / Then)
    with pytest.raises(ValueError):
        event_has_started({})


def test_get_confirmed_event_returns_match_or_none(monkeypatch):
    """
    Summary: The event is looked up among Event Service's confirmed events.
    AC1: The Attendee can access a registration form from a confirmed event
        that is open for registration.
    Double: Stub (httpx.get returns two confirmed events)
    """
    get = Mock(return_value=response(200, {"events": [{"id": "event-1"}, {"id": "event-2"}]}))
    monkeypatch.setattr(clients.httpx, "get", get)
    assert clients.get_confirmed_event("event-2") == {"id": "event-2"}
    assert clients.get_confirmed_event("missing") is None


def test_get_confirmed_event_when_event_service_fails_raises(monkeypatch):
    """
    Summary: An Event Service failure while checking the event is raised.
    AC1: The Attendee can access a registration form from a confirmed event
        that is open for registration.
    Double: Stub (httpx.get answers 503)
    """
    monkeypatch.setattr(clients.httpx, "get", Mock(return_value=response(503, {})))
    with pytest.raises(httpx.HTTPStatusError):
        clients.get_confirmed_event("event-1")


def test_save_registration_returns_saved_registration(monkeypatch):
    """
    Summary: The saved registration from Registration Service is returned.
    AC7: Upon successful registration, a confirmation message on-screen is
        displayed to the Attendee
    Double: Stub (httpx.post returns the saved row)
    """
    post = Mock(return_value=response(201, {"registration": {"status": "Confirmed"}}))
    monkeypatch.setattr(clients.httpx, "post", post)
    assert clients.save_registration({"eventId": "event-1"}) == {"status": "Confirmed"}


def test_save_registration_when_refused_raises_conflict_with_code(monkeypatch):
    """
    Summary: A duplicate or full refusal from Registration Service is raised with its code.
    AC4: Given the Attendee is already registered for the event with the same
        email, the system does not allow for the Attendee to register again.
    AC6: Given the event has reached capacity, the system displays a message
        stating that the event has reaced max capacity.
    Double: Stub (httpx.post answers 409 with a code)
    """
    # Arrange (Given)
    monkeypatch.setattr(
        clients.httpx,
        "post",
        Mock(return_value=response(409, {"code": "EVENT_FULL", "message": "Full"})),
    )

    # Act + Assert (When / Then)
    with pytest.raises(clients.RegistrationConflictError) as caught:
        clients.save_registration({"eventId": "event-1"})

    # Assert (Then)
    assert caught.value.code == "EVENT_FULL"


def test_save_registration_when_failing_raises_http_error(monkeypatch):
    """
    Summary: Other Registration Service failures are raised.
    AC7: Upon successful registration, a confirmation message on-screen is
        displayed to the Attendee
    Double: Stub (httpx.post answers 500)
    """
    monkeypatch.setattr(clients.httpx, "post", Mock(return_value=response(503, {})))
    with pytest.raises(httpx.HTTPStatusError):
        clients.save_registration({"eventId": "event-1"})


@pytest.mark.parametrize(
    "capacity, expected_status",
    [("0", 422), ("1", 201), ("2", 201)],
    ids=["below_minimum", "at_minimum", "above_minimum"],
)
def test_register_when_capacity_near_minimum_needs_room_for_one(client, monkeypatch, capacity, expected_status):
    """
    Summary: An event must have room for at least one attendee to take registrations.
    AC6: (boundary: capacity = 0, 1, 2)
    Double: Stub (confirmed event with the given capacity), Stub
        (save_registration)
    """
    # Arrange (Given)
    monkeypatch.setattr("app.routes.get_confirmed_event", lambda event_id: confirmed_event(expectedAttendance=capacity))
    monkeypatch.setattr("app.routes.save_registration", Mock(return_value={"registration_id": "r1", "status": "Confirmed"}))

    # Act (When)
    response = client.post("/registrations", json=payload())

    # Assert (Then)
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "minutes_after_start, started",
    [(-1, False), (0, True), (1, True)],
    ids=["one_minute_before", "at_start", "one_minute_after"],
)
def test_event_has_started_at_start_time_closes_registration(minutes_after_start, started):
    """
    Summary: Registration closes at the event's start time exactly, not a minute later.
    AC5: (boundary: now = start - 1 min, start, start + 1 min)
    Double: None
    """
    # Arrange (Given)
    start = datetime(2026, 10, 8, 9, 0, tzinfo=ZoneInfo("Asia/Singapore"))
    now = start + timedelta(minutes=minutes_after_start)

    # Act + Assert (When / Then)
    assert event_has_started({"preferredStartDate": start.isoformat()}, now) is started
