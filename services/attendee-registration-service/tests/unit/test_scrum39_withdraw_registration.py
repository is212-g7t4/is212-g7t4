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
- PATCH /registrations/<id>/withdraw: the ownership and already-withdrawn
  checks, the deadline rule (explicit cutoff first, event start as the
  fallback) and the Registration Service call run for real, as do the deadline
  helpers in app.validation.
- Assertions are on the status, message and what is saved.

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
- The Withdraw button and "contact the organisers" message (AC1, AC4 UI half)
  (-> frontend AttendeeRegistrationsPage.test.tsx).
- That Registration Service stores the timestamp (AC3) (-> registration-
  service test_scrum39_withdraw_registration.py).
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


def test_withdraw_before_deadline_saves_withdrawal_with_timestamp(client, monkeypatch):
    """
    Summary: An attendee can withdraw their own confirmed registration before the deadline, and it is timestamped.
    AC2: Given the Attendee confirms withdrawal, the system changes the
        registration status to 'Withdrawn' and displays a confirmation message.
    AC3: The withdrawal is recorded with timestamp for auditability.
    Double: Stub (registration, event), Mock (withdraw_saved_registration)
    """
    # Arrange (Given)
    saved = registration(status="Withdrawn", withdrawn_at="2026-10-24T02:30:00+00:00")
    withdraw = Mock(return_value=saved)
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda: [registration()])
    monkeypatch.setattr(
        "app.routes.get_confirmed_event",
        lambda event_id: confirmed_event(withdrawalDeadline="2099-11-01T09:00:00+08:00"),
    )
    monkeypatch.setattr("app.routes.withdraw_saved_registration", withdraw)

    # Act (When)
    response = client.patch(
        "/registrations/11111111-1111-4111-8111-111111111111/withdraw",
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["message"] == "Registration withdrawn for Community Workshop."
    assert response.json["registration"]["withdrawn_at"] == "2026-10-24T02:30:00+00:00"
    # SCRUM-46: withdrawal carries the event name to the doubled owner adapter,
    # keeping the notification snapshot independent of later Event edits.
    withdraw.assert_called_once_with("11111111-1111-4111-8111-111111111111", "Community Workshop")


def test_withdraw_after_organiser_deadline_returns_409_contact_organisers(client, monkeypatch):
    """
    Summary: Once the organiser's withdrawal deadline has passed, withdrawal is refused even before the event starts.
    AC4: Given the Attendee attempts to withdraw after the registration
        withdrawal deadline (if applicable), the system displays a message to
        contact the organisers and the withdrawal does not go through.
    Double: Stub (event with an elapsed cutoff), Mock (nothing saved)
    """
    # Arrange (Given)
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda: [registration()])
    monkeypatch.setattr(
        "app.routes.get_confirmed_event",
        lambda event_id: confirmed_event(withdrawalDeadline="2020-01-01T09:00:00+08:00"),
    )
    withdraw = Mock()
    monkeypatch.setattr("app.routes.withdraw_saved_registration", withdraw)

    # Act (When)
    response = client.patch(
        "/registrations/11111111-1111-4111-8111-111111111111/withdraw",
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "WITHDRAWAL_DEADLINE_PASSED"
    assert "contact the event organisers" in response.json["message"]
    withdraw.assert_not_called()


def test_withdraw_after_event_start_without_cutoff_returns_409(client, monkeypatch):
    """
    Summary: Without a set deadline, withdrawal closes when the event starts.
    AC4: Given the Attendee attempts to withdraw after the registration
        withdrawal deadline (if applicable), the system displays a message to
        contact the organisers and the withdrawal does not go through.
    Double: Stub (started event without cutoff), Mock (nothing saved)
    """
    # Arrange (Given)
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda: [registration()])
    monkeypatch.setattr(
        "app.routes.get_confirmed_event",
        lambda event_id: confirmed_event(preferredStartDate="2020-01-01T09:00:00+08:00"),
    )
    monkeypatch.setattr("app.routes.withdraw_saved_registration", Mock())

    # Act (When)
    response = client.patch(
        "/registrations/11111111-1111-4111-8111-111111111111/withdraw",
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "WITHDRAWAL_DEADLINE_PASSED"


def test_withdraw_someone_elses_registration_returns_403(client, monkeypatch):
    """
    Summary: An attendee can only withdraw their own registration.
    AC2: Given the Attendee confirms withdrawal, the system changes the
        registration status to 'Withdrawn' and displays a confirmation message.
    Double: Stub (registration of another attendee)
    """
    # Arrange (Given)
    path = "/registrations/11111111-1111-4111-8111-111111111111/withdraw"
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda: [])

    # Act (When)
    response = client.patch(path)

    # Assert (Then)
    assert response.status_code == 404
    assert response.json["code"] == "REGISTRATION_NOT_FOUND"


def test_withdraw_already_withdrawn_registration_returns_409_without_saving(client, monkeypatch):
    """
    Summary: A registration already withdrawn is not withdrawn again.
    AC2: Given the Attendee confirms withdrawal, the system changes the
        registration status to 'Withdrawn' and displays a confirmation message.
    Double: Stub (Withdrawn registration), Mock (nothing saved)
    """
    # Arrange (Given)
    monkeypatch.setattr(
        "app.routes.get_attendee_registrations",
        lambda: [registration(status="Withdrawn")],
    )

    # Act (When)
    response = client.patch(
        "/registrations/11111111-1111-4111-8111-111111111111/withdraw",
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "REGISTRATION_ALREADY_WITHDRAWN"


def test_withdraw_when_event_or_deadline_unknown_is_refused(client, monkeypatch):
    """
    Summary: If the event or its deadline cannot be determined, withdrawal is refused safely.
    AC4: Given the Attendee attempts to withdraw after the registration
        withdrawal deadline (if applicable), the system displays a message to
        contact the organisers and the withdrawal does not go through.
    Double: Stub (event lookup returns nothing or lacks dates)
    """
    # Arrange (Given)
    path = "/registrations/11111111-1111-4111-8111-111111111111/withdraw"
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda: [registration()])
    monkeypatch.setattr("app.routes.get_confirmed_event", lambda event_id: None)

    # Act (When)
    response = client.patch(path)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "WITHDRAWAL_UNAVAILABLE"
    monkeypatch.setattr(
        "app.routes.get_confirmed_event",
        lambda event_id: confirmed_event(preferredStartDate="", withdrawalDeadline="bad"),
    )
    assert client.patch(path).status_code == 502


def test_withdraw_when_downstream_fails_returns_502(client, monkeypatch):
    """
    Summary: If a downstream service fails, the attendee gets a safe error.
    AC2: Given the Attendee confirms withdrawal, the system changes the
        registration status to 'Withdrawn' and displays a confirmation message.
    Double: Stub (downstream adapter raises)
    """
    # Arrange (Given)
    path = "/registrations/11111111-1111-4111-8111-111111111111/withdraw"
    monkeypatch.setattr("app.routes.get_attendee_registrations", Mock(side_effect=RuntimeError("secret")))

    # Act + Assert (When / Then)
    assert client.patch(path).status_code == 502
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda: [registration()])
    monkeypatch.setattr("app.routes.get_confirmed_event", Mock(side_effect=RuntimeError("secret")))
    assert client.patch(path).status_code == 502
    monkeypatch.setattr("app.routes.get_confirmed_event", lambda event_id: confirmed_event())
    monkeypatch.setattr(
        "app.routes.withdraw_saved_registration",
        Mock(side_effect=RegistrationConflictError("REGISTRATION_NOT_OWNED", "Not yours")),
    )
    response = client.patch(path)
    assert response.status_code == 409
    assert response.json["code"] == "REGISTRATION_NOT_OWNED"
    monkeypatch.setattr("app.routes.withdraw_saved_registration", Mock(side_effect=RuntimeError("secret")))
    response = client.patch(path)
    assert response.status_code == 502
    assert "secret" not in response.json["message"]


def test_withdrawal_deadline_uses_cutoff_else_event_start():
    """
    Summary: The withdrawal deadline is the organiser's cutoff when set, otherwise the event start.
    AC4: Given the Attendee attempts to withdraw after the registration
        withdrawal deadline (if applicable), the system displays a message to
        contact the organisers and the withdrawal does not go through.
    Double: None
    """
    # Arrange (Given)
    now = datetime(2026, 10, 24, 10, 0, tzinfo=ZoneInfo("Asia/Singapore"))

    # Act + Assert (When / Then)
    assert withdrawal_deadline_has_passed({
        "withdrawalDeadline": "2026-10-24T09:00:00+08:00",
        "preferredStartDate": "2026-11-10T09:00:00+08:00",
    }, now)
    assert not withdrawal_deadline_has_passed({
        "withdrawalDeadline": "",
        "preferredStartDate": "2026-11-10T09:00:00",
    }, now)
    assert withdrawal_deadline_has_passed(
        {"preferredStartDate": "2026-10-24T09:00:00+08:00"},
        datetime(2026, 10, 24, 10, 0),
    )


def test_withdrawal_deadline_without_any_date_raises():
    """
    Summary: A deadline cannot be judged without a cutoff or start date.
    AC4: Given the Attendee attempts to withdraw after the registration
        withdrawal deadline (if applicable), the system displays a message to
        contact the organisers and the withdrawal does not go through.
    Double: None
    """
    # Act + Assert (When / Then)
    with pytest.raises(ValueError):
        withdrawal_deadline_has_passed({})


def test_withdraw_saved_registration_returns_updated_row(monkeypatch):
    """
    Summary: The withdrawn registration from Registration Service is returned.
    AC2: Given the Attendee confirms withdrawal, the system changes the
        registration status to 'Withdrawn' and displays a confirmation message.
    Double: Stub (httpx.patch returns the withdrawn row)
    """
    # Arrange (Given)
    patch = Mock(return_value=response(200, {"registration": {"status": "Withdrawn"}}))

    monkeypatch.setattr(clients.httpx, "patch", patch)

    # Act + Assert (When / Then)
    assert clients.withdraw_saved_registration("registration-1") == {"status": "Withdrawn"}
    assert patch.call_args.kwargs["json"] == {}


def test_withdraw_saved_registration_when_refused_raises_conflict(monkeypatch):
    """
    Summary: A refusal from Registration Service is raised with its code.
    AC2: Given the Attendee confirms withdrawal, the system changes the
        registration status to 'Withdrawn' and displays a confirmation message.
    Double: Stub (httpx.patch answers 409)
    """
    # Arrange (Given)
    monkeypatch.setattr(
        clients.httpx,
        "patch",
        Mock(return_value=response(403, {"code": "REGISTRATION_NOT_OWNED", "message": "Not yours"})),
    )

    # Act + Assert (When / Then)
    with pytest.raises(clients.RegistrationConflictError) as caught:
        clients.withdraw_saved_registration("registration-1")

    # Assert (Then)
    assert caught.value.code == "REGISTRATION_NOT_OWNED"


def test_withdraw_saved_registration_when_failing_raises_http_error(monkeypatch):
    """
    Summary: Other Registration Service failures are raised.
    AC2: Given the Attendee confirms withdrawal, the system changes the
        registration status to 'Withdrawn' and displays a confirmation message.
    Double: Stub (httpx.patch answers 500)
    """
    # Arrange (Given)
    monkeypatch.setattr(clients.httpx, "patch", Mock(return_value=response(503, {})))

    # Act + Assert (When / Then)
    with pytest.raises(httpx.HTTPStatusError):
        clients.withdraw_saved_registration("registration-1")


@pytest.mark.parametrize(
    "minutes_after_deadline, passed",
    [(-1, False), (0, True), (1, True)],
    ids=["one_minute_before", "at_deadline", "one_minute_after"],
)
def test_withdrawal_deadline_at_cutoff_time_closes_withdrawal(minutes_after_deadline, passed):
    """
    Summary: Withdrawal closes at the deadline exactly, not a minute later.
    AC4: (boundary: now = deadline - 1 min, deadline, deadline + 1 min)
    Double: None
    """
    # Arrange (Given)
    deadline = datetime(2026, 10, 24, 9, 0, tzinfo=ZoneInfo("Asia/Singapore"))
    now = deadline + timedelta(minutes=minutes_after_deadline)

    # Act (When)
    event = {"withdrawalDeadline": deadline.isoformat(), "preferredStartDate": "2026-11-10T09:00:00+08:00"}

    # Assert (Then)
    assert withdrawal_deadline_has_passed(event, now) is passed
