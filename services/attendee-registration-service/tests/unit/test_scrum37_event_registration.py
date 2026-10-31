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
- Registering for an event: only confirmed events that have not started, the
  attendee taken from their sign-in rather than the form, and Registration
  Service's "already registered" and "full" refusals passed on.
- We check the confirmation or refusal the attendee sees, and what is sent to
  be saved.

Doubled
-------
- Event Service: says whether the event is confirmed, with its start time and
  capacity [Stub].
- Registration Service: saves the registration, refuses it, or fails [Stub]; we
  check what it was asked to save [Mock].
- Sign-in: a test key signs the caller's token (tests/unit/conftest.py) [Stub].

Not proven
----------
- The registration form and on-screen confirmation (AC1, AC2, AC7) (-> frontend
  eventRegistration.test.ts and E2E journey J7).
- That Registration Service really refuses duplicates and full events,
  including under simultaneous registrations (-> registration-service
  test_scrum37_event_registration.py and its integration tests).
- Duplicates are detected by the attendee's account, not by email as AC4 says
  (raised as a finding).
"""

from datetime import datetime, timedelta
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import httpx
import pytest

from app import clients
from app.clients import RegistrationConflictError
from app.validation import event_has_started, validate_registration
from tests.unit.factories import EVENT_ID, confirmed_event, payload, response


def test_register_when_event_open_returns_confirmation(client, monkeypatch):
    """
    Summary: Registering for an open, confirmed event saves the registration and returns a confirmation naming the event.
    AC7: Upon successful registration, a confirmation message on-screen is
        displayed to the Attendee
    Double: The event is confirmed and open [Stub]; Registration Service saves
        the registration, and we check what it was asked to save [Mock].
    """
    saved = {"registration_id": "registration-1", "status": "Confirmed"}
    save = Mock(return_value=saved)
    monkeypatch.setattr("app.routes.get_confirmed_event", lambda event_id: confirmed_event())
    monkeypatch.setattr("app.routes.save_registration", save)

    response = client.post("/registrations", json=payload())

    assert response.status_code == 201
    assert response.json["message"] == "Registration confirmed for Community Workshop."
    assert response.json["registration"] == saved
    assert response.json["event"]["eventName"] == "Community Workshop"
    sent = save.call_args.args[0]
    assert sent["eventId"] == EVENT_ID
    assert sent["capacity"] == 30


def test_register_with_profile_fields_ignores_them(client, monkeypatch):
    """
    Summary: The attendee's name, email and organisation come from their profile, so values typed into the request are ignored.
    AC2: The Attendee can provides required registration information including
        full name (required), Email address (required, must be valid format),
        organisation/company (optional)
    Double: The event is confirmed and open [Stub]; we check what Registration
        Service was asked to save [Mock].
    """
    save = Mock(return_value={"registration_id": "registration-1"})
    monkeypatch.setattr("app.routes.get_confirmed_event", lambda event_id: confirmed_event())
    monkeypatch.setattr("app.routes.save_registration", save)

    response = client.post("/registrations", json=payload(fullName="Someone Else", email="other@example.com"))

    assert response.status_code == 201
    sent = save.call_args.args[0]
    assert "fullName" not in sent
    assert "email" not in sent


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
    Summary: A registration that does not say which event it is for is refused, naming what is missing.
    AC3: The system validates that all required fields are completed before
        submission, and displays an error message if this is not the case.
    Double: None
    """
    response = client.post("/registrations", json=body)

    assert response.status_code == 400
    assert response.json["message"] == "Complete the required registration fields."
    assert expected in str(response.json)


def test_register_with_malformed_event_id_returns_400(client):
    """
    Summary: A registration must name a real event, not a malformed id.
    AC3: The system validates that all required fields are completed before
        submission, and displays an error message if this is not the case.
    Double: None
    """
    response = client.post("/registrations", json=payload(eventId="bad"))

    assert response.status_code == 400
    assert response.json == {"message": "A valid event is required."}


def test_register_when_event_not_confirmed_returns_409(client, monkeypatch):
    """
    Summary: An event that is not confirmed is not open for registration.
    AC1: The Attendee can access a registration form from a confirmed event
        that is open for registration.
    Double: The event is not among the confirmed events [Stub].
    """
    save = Mock()
    monkeypatch.setattr("app.routes.get_confirmed_event", lambda event_id: None)
    monkeypatch.setattr("app.routes.save_registration", save)

    response = client.post("/registrations", json=payload())

    assert response.status_code == 409
    assert response.json["code"] == "REGISTRATION_CLOSED"
    save.assert_not_called()


def test_register_when_event_started_returns_409_closed(client, monkeypatch):
    """
    Summary: Registration closes once the event has started, and nothing is saved.
    AC5: Given registration has closed for the event, The system does not allow
        the Attendee to register.
    Double: The event started in the past [Stub]; we check nothing is saved
        [Mock].
    """
    save = Mock()
    monkeypatch.setattr(
        "app.routes.get_confirmed_event",
        lambda event_id: confirmed_event(preferredStartDate="2020-01-01T09:00:00+08:00"),
    )
    monkeypatch.setattr("app.routes.save_registration", save)

    response = client.post("/registrations", json=payload())

    assert response.status_code == 409
    assert response.json == {
        "code": "REGISTRATION_CLOSED",
        "message": "Registration has closed because this event has started.",
    }
    save.assert_not_called()


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
    Summary: An attendee who is already registered, or an event that is full, is refused with a clear message.
    AC4: Given the Attendee is already registered for the event with the same
        email, the system does not allow for the Attendee to register again.
    AC6: Given the event has reached capacity, the system displays a message
        stating that the event has reaced max capacity.
    Double: The event is confirmed and open, and Registration Service refuses
        the registration as a duplicate or as full [Stub].
    """
    monkeypatch.setattr("app.routes.get_confirmed_event", lambda event_id: confirmed_event())

    def refuse(data):
        raise RegistrationConflictError(code, message)

    monkeypatch.setattr("app.routes.save_registration", refuse)

    response = client.post("/registrations", json=payload())

    assert response.status_code == 409
    assert response.json == {"code": code, "message": message}


@pytest.mark.parametrize("failing", ["event_lookup", "save"], ids=["event_lookup_fails", "save_fails"])
def test_register_when_downstream_fails_returns_502_without_details(client, monkeypatch, failing):
    """
    Summary: If the event cannot be checked or the registration cannot be saved, the attendee gets an error, never a false confirmation.
    AC7: Upon successful registration, a confirmation message on-screen is
        displayed to the Attendee
    Double: Event Service or Registration Service fails [Stub].
    """
    broken = Mock(side_effect=RuntimeError("secret"))
    monkeypatch.setattr("app.routes.get_confirmed_event", broken if failing == "event_lookup" else (lambda event_id: confirmed_event()))
    monkeypatch.setattr("app.routes.save_registration", broken if failing == "save" else Mock())

    response = client.post("/registrations", json=payload())

    assert response.status_code == 502
    assert "secret" not in response.json["message"]
    assert "registration" not in response.json


def test_validate_registration_trims_ids_and_drops_profile_fields():
    """
    Summary: The event id is trimmed and any typed-in profile details are dropped before the registration is checked.
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
    Summary: Whether registration has closed is judged in Singapore time, however the start time is written.
    AC5: Given registration has closed for the event, The system does not allow
        the Attendee to register.
    Double: None
    """
    now = datetime(2026, 10, 8, 10, 0, tzinfo=ZoneInfo("Asia/Singapore"))

    assert event_has_started({"preferredStartDate": "2026-10-08T09:00:00"}, now)
    assert not event_has_started({"preferredStartDate": "2026-10-08T11:00:00"}, now)
    assert event_has_started(
        {"preferredStartDate": "2026-10-08T09:00:00+08:00"},
        datetime(2026, 10, 8, 10, 0),
    )


def test_get_confirmed_event_returns_match_or_none(monkeypatch):
    """
    Summary: The event is looked up among Event Service's confirmed events, so an unconfirmed event is not found.
    AC1: The Attendee can access a registration form from a confirmed event
        that is open for registration.
    Double: Event Service lists two confirmed events [Stub].
    """
    monkeypatch.setattr(clients.httpx, "get", Mock(return_value=response(200, {"events": [{"id": "event-1"}, {"id": "event-2"}]})))

    assert clients.get_confirmed_event("event-2") == {"id": "event-2"}
    assert clients.get_confirmed_event("missing") is None


def test_get_confirmed_event_when_event_service_fails_raises(monkeypatch):
    """
    Summary: If Event Service fails while checking the event, the failure is passed up rather than treated as "not confirmed".
    AC1: The Attendee can access a registration form from a confirmed event
        that is open for registration.
    Double: Event Service answers with an error [Stub].
    """
    monkeypatch.setattr(clients.httpx, "get", Mock(return_value=response(503, {})))

    with pytest.raises(httpx.HTTPStatusError):
        clients.get_confirmed_event("event-1")


def test_save_registration_returns_saved_registration(monkeypatch):
    """
    Summary: The registration Registration Service saved is what the attendee's confirmation shows.
    AC7: Upon successful registration, a confirmation message on-screen is
        displayed to the Attendee
    Double: Registration Service saves the registration [Stub].
    """
    monkeypatch.setattr(clients.httpx, "post", Mock(return_value=response(201, {"registration": {"status": "Confirmed"}})))

    assert clients.save_registration({"eventId": "event-1"}) == {"status": "Confirmed"}


def test_save_registration_when_refused_raises_conflict_with_code(monkeypatch):
    """
    Summary: When Registration Service refuses a duplicate or a full event, its reason is passed on so the attendee can be told.
    AC4: Given the Attendee is already registered for the event with the same
        email, the system does not allow for the Attendee to register again.
    AC6: Given the event has reached capacity, the system displays a message
        stating that the event has reaced max capacity.
    Double: Registration Service refuses the registration because the event
        is full [Stub].
    """
    monkeypatch.setattr(
        clients.httpx,
        "post",
        Mock(return_value=response(409, {"code": "EVENT_FULL", "message": "Full"})),
    )

    with pytest.raises(clients.RegistrationConflictError) as caught:
        clients.save_registration({"eventId": "event-1"})

    assert caught.value.code == "EVENT_FULL"
    assert caught.value.message == "Full"


def test_save_registration_when_failing_raises_http_error(monkeypatch):
    """
    Summary: Any other Registration Service failure is passed up, so no confirmation is shown.
    AC7: Upon successful registration, a confirmation message on-screen is
        displayed to the Attendee
    Double: Registration Service answers with an error [Stub].
    """
    monkeypatch.setattr(clients.httpx, "post", Mock(return_value=response(503, {})))

    with pytest.raises(httpx.HTTPStatusError):
        clients.save_registration({"eventId": "event-1"})


@pytest.mark.parametrize(
    "minutes_after_start, started",
    [(-1, False), (0, True), (1, True)],
    ids=["one_minute_before", "at_start", "one_minute_after"],
)
def test_event_has_started_at_start_time_closes_registration(minutes_after_start, started):
    """
    Summary: Registration closes at the event's start time exactly, not a minute later.
    AC5: Given registration has closed for the event, The system does not allow
        the Attendee to register.
    Double: None
    """
    start = datetime(2026, 10, 8, 9, 0, tzinfo=ZoneInfo("Asia/Singapore"))
    now = start + timedelta(minutes=minutes_after_start)

    assert event_has_started({"preferredStartDate": start.isoformat()}, now) is started


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


@pytest.mark.parametrize(
    "capacity, expected_status",
    [(None, 422), ("invalid", 422), ("0", 422), ("1", 201)],
    ids=["missing", "not_a_number", "zero", "one"],
)
def test_register_when_event_capacity_unusable_returns_422(client, monkeypatch, capacity, expected_status):
    """
    Summary: An event whose capacity is missing, not a number or zero cannot take registrations; a capacity of one can.
    Supporting design check: an event must have a usable capacity before
        registrations are accepted (whether it is full is decided by
        Registration Service)
    Double: The event is confirmed with the given capacity, and Registration
        Service saves the registration [Stub].
    """
    monkeypatch.setattr("app.routes.get_confirmed_event", lambda event_id: confirmed_event(expectedAttendance=capacity))
    monkeypatch.setattr("app.routes.save_registration", Mock(return_value={"registration_id": "r1", "status": "Confirmed"}))

    response = client.post("/registrations", json=payload())

    assert response.status_code == expected_status


def test_event_has_started_without_date_raises():
    """
    Summary: An event without a start time cannot be judged open or closed, so it is not treated as open.
    Supporting design check: missing event data fails safely
    Double: None
    """
    with pytest.raises(ValueError):
        event_has_started({})
