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
- POST /registrations and app.models.create_registration(): payload validation,
  the per-event advisory lock, the duplicate and capacity checks, reuse of a
  withdrawn row and the unique-violation fallback run for real.
- Assertions are on the status and error code, the saved row and the SQL sent.

Doubled
-------
- psycopg2.connect: Stub / Mock (tests/unit/conftest.py `setup`) - the cursor
  returns canned Registration rows (or raises); executed SQL and parameters are
  inspected; the model functions are replaced by a Stub where a route test only
  needs their result or error.

Not proven
----------
- That the event is Confirmed and open for registration (AC1, AC5): Attendee
  Registration Service checks that before calling here (->
  attendee-registration-service unit tests for SCRUM-37).
- Name, email and organisation validation (AC2, AC3): they live on User, not
  here (-> attendee-registration-service unit tests and frontend
  eventRegistration.test.ts).
- That the advisory lock really serialises two concurrent registrations for the
  last place (-> tests/integration/, throwaway postgres:17.6).
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import psycopg2.errors
import pytest

from app import create_app
from app.models import (
    CapacityReachedError,
    DuplicateRegistrationError,
    RegistrationAlreadyWithdrawnError,
    RegistrationNotFoundError,
    RegistrationOwnershipError,
    create_registration,
    withdraw_registration,
)
from tests.unit.factories import ATTENDEE_ID, EVENT_ID, registration_payload, registration_row, signed_in

OTHER_EVENT_ID = "11111111-1111-4111-8111-111111111111"


def test_ac7_register_when_place_available_returns_confirmed_registration(setup, monkeypatch):
    """
    Summary: A successful registration returns the confirmed registration.
    AC7: Upon successful registration, a confirmation message on-screen is
        displayed to the Attendee
    Double: Stub (create_registration returns the saved row)
    """
    client = setup[0]
    saved = registration_row(attendee_id=ATTENDEE_ID)
    received = []

    def fake_create(*args):
        received.append(args)
        return {
            "registration_id": saved["registration_id"],
            "event_id": EVENT_ID,
            "attendee_id": ATTENDEE_ID,
            "status": "Confirmed",
        }

    monkeypatch.setattr("app.create_registration", fake_create)
    response = client.post(
        "/registrations",
        # Profile fields are ignored: they are no longer stored on Registration.
        json=registration_payload(fullName="Ignored", email="ignored@example.com"),
    )

    assert response.status_code == 201
    assert received == [("unused-test-url", EVENT_ID, ATTENDEE_ID, 30)]


def test_ac2_register_without_profile_fields_still_registers(setup, monkeypatch):
    """
    Summary: Registration needs only the event and capacity; profile details come from User Service.
    AC2: name, email and organisation are held on the attendee's User profile
    Double: Stub (create_registration returns a row)
    """
    client = setup[0]
    monkeypatch.setattr("app.create_registration", lambda *args: {
        "registration_id": registration_row()["registration_id"],
        "event_id": EVENT_ID,
        "attendee_id": ATTENDEE_ID,
        "status": "Confirmed",
    })

    response = client.post("/registrations", json=registration_payload())

    assert response.status_code == 201
    assert response.json["registration"]["status"] == "Confirmed"


@pytest.mark.parametrize(
    "payload",
    [None, {}, registration_payload(eventId="bad"),
     registration_payload(capacity=0), registration_payload(capacity="many")],
     ids=["no_body", "empty_object", "bad_event_id", "zero_capacity", "capacity_as_text"],
)
def test_ac3_register_with_missing_or_invalid_values_returns_400(setup, payload):
    """
    Summary: A registration without a valid event or a positive whole capacity is refused.
    AC3: The system validates that all required fields are completed before
        submission, and displays an error message if this is not the case.
    Double: None
    """
    response = setup[0].post("/registrations", json=payload)
    assert response.status_code == 400


@pytest.mark.parametrize(
    ("error", "code"),
    [(DuplicateRegistrationError, "DUPLICATE_REGISTRATION"), (CapacityReachedError, "EVENT_FULL")],
    ids=["already_registered", "event_full"],
)
def test_ac4_ac6_register_when_duplicate_or_full_returns_409_with_reason(setup, monkeypatch, error, code):
    """
    Summary: A second registration or one for a full event is refused with a reason the UI can show.
    AC4: Given the Attendee is already registered for the event with the same
        email, the system does not allow for the Attendee to register again.
    AC6: Given the event has reached capacity, the system displays a message
        stating that the event has reaced max capacity.
    Double: Stub (create_registration raises the business error)
    """
    # Arrange (Given)
    def fail(*args):
        raise error

    monkeypatch.setattr("app.create_registration", fail)

    # Act (When)
    response = setup[0].post("/registrations", json=registration_payload())

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == code


def test_ac6_ac7_create_registration_when_place_available_locks_counts_and_inserts(setup):
    """
    Summary: A registration locks the event, counts confirmed places and then saves a Confirmed row.
    AC6: Given the event has reached capacity, the system displays a message
        stating that the event has reaced max capacity.
    AC7: Upon successful registration, a confirmation message on-screen is
        displayed to the Attendee
    Double: Stub (cursor returns no existing row, a count, then the saved row;
        SQL inspected)
    """
    # Arrange (Given)
    _, _, cursor = setup
    created = registration_row(attendee_id=ATTENDEE_ID)
    cursor.fetchone.side_effect = [None, {"confirmed": 2}, created]

    # Act (When)
    result = create_registration("unused-test-url", EVENT_ID, ATTENDEE_ID, 3)

    # Assert (Then)
    assert result["status"] == "Confirmed"
    # One additional statement records the notification intent on this cursor;
    # the existing capacity/identity assertions below still check registration SQL.
    assert cursor.execute.call_count == 5
    assert "pg_advisory_xact_lock" in cursor.execute.call_args_list[0].args[0]
    lookup, params = cursor.execute.call_args_list[1].args
    assert "event_id = %s AND attendee_id = %s" in lookup
    assert params == [EVENT_ID, ATTENDEE_ID]
    insert, values = cursor.execute.call_args_list[3].args
    assert "INSERT INTO" in insert
    assert values[1:3] == [EVENT_ID, ATTENDEE_ID]


def test_ac4_create_registration_when_already_registered_raises_duplicate(setup):
    """
    Summary: An attendee who is already registered cannot register again.
    AC4: Given the Attendee is already registered for the event with the same
        email, the system does not allow for the Attendee to register again.
    Double: Stub (cursor finds a Confirmed registration)
    """
    # Arrange (Given)
    cursor = setup[2]
    cursor.fetchone.return_value = {"registration_id": "existing", "status": "Confirmed"}

    # Act + Assert (When / Then)
    with pytest.raises(DuplicateRegistrationError):
        create_registration("unused-test-url", EVENT_ID, ATTENDEE_ID, 3)

    # Assert (Then)
    assert cursor.execute.call_count == 2


def test_ac4_ac7_create_registration_after_withdrawal_reconfirms_the_same_row(setup):
    """
    Summary: Registering again after withdrawing reconfirms the same registration.
    AC4: Given the Attendee is already registered for the event with the same
        email, the system does not allow for the Attendee to register again.
    AC7: Upon successful registration, a confirmation message on-screen is
        displayed to the Attendee
    Double: Stub (cursor finds a Withdrawn row; update inspected)
    """
    # Arrange (Given)
    cursor = setup[2]
    reconfirmed = registration_row(attendee_id=ATTENDEE_ID)
    cursor.fetchone.side_effect = [
        {"registration_id": "withdrawn-row", "status": "Withdrawn"},
        {"confirmed": 1},
        reconfirmed,
    ]

    # Act (When)
    result = create_registration("unused-test-url", EVENT_ID, ATTENDEE_ID, 3)

    # Assert (Then)
    assert result["status"] == "Confirmed"
    update, values = cursor.execute.call_args_list[3].args
    assert 'UPDATE public."Registration"' in update
    assert "status = 'Confirmed'" in update
    assert values[1] == "withdrawn-row"


def test_ac6_create_registration_after_withdrawal_when_full_raises_capacity_reached(setup):
    """
    Summary: Re-registering after withdrawal still needs a free place.
    AC6: Given the event has reached capacity, the system displays a message
        stating that the event has reaced max capacity.
    Double: Stub (cursor finds a Withdrawn row and a full count)
    """
    # Arrange (Given)
    cursor = setup[2]
    cursor.fetchone.side_effect = [
        {"registration_id": "withdrawn-row", "status": "Withdrawn"},
        {"confirmed": 3},
    ]

    # Act + Assert (When / Then)
    with pytest.raises(CapacityReachedError):
        create_registration("unused-test-url", EVENT_ID, ATTENDEE_ID, 3)


def test_ac4_create_registration_when_database_reports_duplicate_raises_duplicate(setup):
    """
    Summary: If the database's own uniqueness rule fires, it is still reported as already registered.
    AC4: Given the Attendee is already registered for the event with the same
        email, the system does not allow for the Attendee to register again.
    Double: Stub (insert raises UniqueViolation)
    """
    # Arrange (Given)
    cursor = setup[2]
    cursor.fetchone.side_effect = [None, {"confirmed": 0}]
    cursor.execute.side_effect = [None, None, None, psycopg2.errors.UniqueViolation()]

    # Act + Assert (When / Then)
    with pytest.raises(DuplicateRegistrationError):
        create_registration("unused-test-url", EVENT_ID, ATTENDEE_ID, 3)


def test_ac6_create_registration_when_event_full_raises_capacity_reached(setup):
    """
    Summary: A full event takes no more registrations.
    AC6: Given the event has reached capacity, the system displays a message
        stating that the event has reaced max capacity.
    Double: Stub (cursor returns confirmed = capacity)
    """
    # Arrange (Given)
    cursor = setup[2]
    cursor.fetchone.side_effect = [None, {"confirmed": 3}]

    # Act + Assert (When / Then)
    with pytest.raises(CapacityReachedError):
        create_registration("unused-test-url", EVENT_ID, ATTENDEE_ID, 3)

    # Assert (Then)
    assert cursor.execute.call_count == 3


@pytest.mark.parametrize(
    "capacity, expected_status",
    [(0, 400), (1, 201), (2, 201)],
    ids=["below_minimum", "at_minimum", "above_minimum"],
)
def test_ac6_register_when_capacity_near_minimum_accepts_one_or_more(setup, monkeypatch, capacity, expected_status):
    """
    Summary: An event must have room for at least one attendee to take registrations.
    AC6: (boundary: capacity = 0, 1, 2)
    Double: Stub (create_registration returns the saved row)
    """
    # Arrange (Given)
    monkeypatch.setattr("app.create_registration", lambda *args: registration_row(attendee_id=ATTENDEE_ID))

    # Act (When)
    response = setup[0].post("/registrations", json=registration_payload(capacity=capacity))

    # Assert (Then)
    assert response.status_code == expected_status
