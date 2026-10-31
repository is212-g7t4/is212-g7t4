"""
SCRUM-39: Withdraw Registration

User Story
----------
As an Attendee, I want to withdraw my registration for an event, so that I can
free up my place for someone else if I can no longer attend.

Acceptance Criteria
-------------------
AC1: The Attendee can access a "Withdraw" option from their registered event
     details page.
AC2: Given the Attendee confirms withdrawal, the system changes the
     registration status to 'Withdrawn' and displays a confirmation message.
AC3: The withdrawal is recorded with timestamp for auditability.
AC4: Given the Attendee attempts to withdraw after the registration withdrawal
     deadline (if applicable), the system displays a message to contact the
     organisers and the withdrawal does not go through.

Real
----
- PATCH /registrations/<id>/withdraw and app.models.withdraw_registration():
  the ownership, not-found and already-withdrawn checks and the update that
  saves status and withdrawn_at together run for real.
- Assertions are on the status, error code and saved row.

Doubled
-------
- psycopg2.connect: Stub / Mock (tests/unit/conftest.py `setup`) - the cursor
  returns canned Registration rows (or raises); executed SQL and parameters are
  inspected; the model functions are replaced by a Stub where a route test only
  needs their result or error.

Not proven
----------
- The Withdraw button and confirmation message (AC1, AC2 UI half) (-> frontend
  AttendeeRegistrationsPage.test.tsx and e2e view-registration-status.spec.ts).
- AC4 (withdrawal deadline): enforced by Attendee Registration Service before
  it calls here (-> attendee-registration-service
  test_scrum39_withdraw_registration.py).
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


def test_ac2_ac3_withdraw_registration_when_confirmed_saves_withdrawn_with_timestamp(setup):
    """
    Summary: Withdrawing sets the registration to Withdrawn and records when it happened.
    AC2: Given the Attendee confirms withdrawal, the system changes the
        registration status to 'Withdrawn' and displays a confirmation message.
    AC3: The withdrawal is recorded with timestamp for auditability.
    Double: Stub (cursor returns the row before and after; update inspected)
    """
    # Arrange (Given)
    _, _, cursor = setup
    cursor.fetchone.side_effect = [
        registration_row(attendee_id=ATTENDEE_ID),
        registration_row(
            attendee_id=ATTENDEE_ID,
            status="Withdrawn",
            withdrawn_at=datetime(2026, 10, 24, 2, 30, tzinfo=UTC),
        ),
    ]

    # Act (When)
    result = withdraw_registration("unused-test-url", registration_row()["registration_id"], ATTENDEE_ID)

    # Assert (Then)
    assert result["status"] == "Withdrawn"
    assert result["withdrawn_at"] == "2026-10-24T02:30:00+00:00"
    # SCRUM-46 appends an outbox insert after the business UPDATE. Inspect the
    # same withdrawal SQL as before rather than mistaking that final insert for it.
    update_query, update_params = cursor.execute.call_args_list[1].args
    assert "SET status = 'Withdrawn', withdrawn_at = %s" in update_query
    assert update_params[1] == registration_row()["registration_id"]


@pytest.mark.parametrize(
    ("row", "error"),
    [
        (None, RegistrationNotFoundError),
        (registration_row(attendee_id="11111111-1111-4111-8111-111111111111"), RegistrationOwnershipError),
        (registration_row(attendee_id=ATTENDEE_ID, status="Withdrawn"), RegistrationAlreadyWithdrawnError),
    ],
    ids=["not_found", "someone_elses", "already_withdrawn"],
)
def test_ac2_withdraw_registration_when_missing_foreign_or_withdrawn_raises(setup, row, error):
    """
    Summary: Withdrawing an unknown registration, someone else's, or one already withdrawn is refused.
    AC2: Given the Attendee confirms withdrawal, the system changes the
        registration status to 'Withdrawn' and displays a confirmation message.
    Double: Stub (cursor returns no row, another attendee's row or a Withdrawn
        row)
    """
    # Arrange (Given)
    cursor = setup[2]
    cursor.fetchone.return_value = row

    # Act + Assert (When / Then)
    with pytest.raises(error):
        withdraw_registration("unused-test-url", registration_row()["registration_id"], ATTENDEE_ID)


def test_ac2_withdraw_when_allowed_returns_withdrawn_registration(setup, monkeypatch):
    """
    Summary: A successful withdrawal returns the updated registration.
    AC2: Given the Attendee confirms withdrawal, the system changes the
        registration status to 'Withdrawn' and displays a confirmation message.
    Double: Stub (withdraw_registration returns the Withdrawn row)
    """
    # Arrange (Given)
    client = setup[0]
    saved = registration_row(attendee_id=ATTENDEE_ID, status="Withdrawn")
    withdraw = MagicMock(return_value={**saved, "withdrawn_at": "2026-10-24T02:30:00+00:00"})
    monkeypatch.setattr("app.withdraw_registration", withdraw)

    # Act (When)
    response = client.patch(
        f"/registrations/{saved['registration_id']}/withdraw",
        json={},
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["registration"]["status"] == "Withdrawn"
    withdraw.assert_called_once_with("unused-test-url", saved["registration_id"], ATTENDEE_ID)


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (RegistrationNotFoundError(), 404, "REGISTRATION_NOT_FOUND"),
        (RegistrationOwnershipError(), 403, "REGISTRATION_NOT_OWNED"),
        (RegistrationAlreadyWithdrawnError(), 409, "REGISTRATION_ALREADY_WITHDRAWN"),
    ],
    ids=["not_found", "not_owned", "already_withdrawn"],
)
def test_ac2_withdraw_when_refused_returns_status_and_error_code(setup, monkeypatch, error, status, code):
    """
    Summary: Each kind of refused withdrawal gets its own status and code for the UI.
    AC2: Given the Attendee confirms withdrawal, the system changes the
        registration status to 'Withdrawn' and displays a confirmation message.
    Double: Stub (withdraw_registration raises the domain error)
    """
    # Arrange (Given)
    client = setup[0]
    monkeypatch.setattr("app.withdraw_registration", MagicMock(side_effect=error))

    # Act (When)
    response = client.patch(
        f"/registrations/{registration_row()['registration_id']}/withdraw",
        json={},
    )

    # Assert (Then)
    assert response.status_code == status
    assert response.json["code"] == code


def test_ac2_withdraw_with_bad_id_or_missing_database_is_refused(setup):
    """
    Summary: A withdrawal needs a valid registration id and a configured database.
    AC2: Given the Attendee confirms withdrawal, the system changes the
        registration status to 'Withdrawn' and displays a confirmation message.
    Double: None
    """
    # Arrange (Given)
    client = setup[0]
    path = f"/registrations/{registration_row()['registration_id']}/withdraw"

    # Act + Assert (When / Then)
    assert client.patch(path).status_code == 400
    client.application.config["DATABASE_URL"] = None
    assert client.patch(path, json={}).status_code == 503
