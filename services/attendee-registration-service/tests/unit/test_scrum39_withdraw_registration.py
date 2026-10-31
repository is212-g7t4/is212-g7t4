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
- Withdrawing a registration: only the attendee's own, not twice, and not after
  the withdrawal deadline (the organiser's cutoff, or the event start when
  there is none), judged in Singapore time.
- We check the confirmation or refusal the attendee sees, and whether the
  withdrawal was sent to be saved.

Doubled
-------
- Registration Service: holds the attendee's registrations and records the
  withdrawal, refuses it, or fails [Stub]; we check whether a withdrawal was
  requested [Mock].
- Event Service: returns the event with its deadline and start time [Stub].
- Sign-in: a test key signs the caller's token (tests/unit/conftest.py) [Stub].

Not proven
----------
- The Withdraw button and the "contact the organisers" message (AC1, AC4) (->
  frontend AttendeeRegistrationsPage.test.tsx and E2E journey J7).
- That Registration Service stores the withdrawal time (AC3) (->
  registration-service test_scrum39_withdraw_registration.py).
"""

from datetime import datetime, timedelta
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import httpx
import pytest

from app import clients
from app.clients import RegistrationConflictError
from app.validation import withdrawal_deadline_has_passed
from tests.unit.factories import confirmed_event, registration, response


def test_withdraw_before_deadline_saves_withdrawal_with_timestamp(client, monkeypatch):
    """
    Summary: An attendee withdraws their own registration before the deadline; it becomes Withdrawn, is timestamped, and a confirmation is shown.
    AC2: Given the Attendee confirms withdrawal, the system changes the
        registration status to 'Withdrawn' and displays a confirmation message.
    AC3: The withdrawal is recorded with timestamp for auditability.
    Double: The attendee has one confirmed registration and the event's
        deadline is in the future [Stub]; Registration Service records the
        withdrawal, and we check which registration it was asked to withdraw
        [Mock].
    """
    saved = registration(status="Withdrawn", withdrawn_at="2026-10-24T02:30:00+00:00")
    withdraw = Mock(return_value=saved)
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda: [registration()])
    monkeypatch.setattr(
        "app.routes.get_confirmed_event",
        lambda event_id: confirmed_event(withdrawalDeadline="2099-11-01T09:00:00+08:00"),
    )
    monkeypatch.setattr("app.routes.withdraw_saved_registration", withdraw)

    response = client.patch("/registrations/11111111-1111-4111-8111-111111111111/withdraw")

    assert response.status_code == 200
    assert response.json["message"] == "Registration withdrawn for Community Workshop."
    assert response.json["registration"]["status"] == "Withdrawn"
    assert response.json["registration"]["withdrawn_at"] == "2026-10-24T02:30:00+00:00"
    assert withdraw.call_args.args[0] == "11111111-1111-4111-8111-111111111111"


def test_withdraw_after_organiser_deadline_returns_409_contact_organisers(client, monkeypatch):
    """
    Summary: After the organiser's withdrawal deadline, withdrawal is refused with a message to contact the organisers, even before the event starts.
    AC4: Given the Attendee attempts to withdraw after the registration
        withdrawal deadline (if applicable), the system displays a message to
        contact the organisers and the withdrawal does not go through.
    Double: The event's withdrawal deadline has passed [Stub]; we check nothing
        is withdrawn [Mock].
    """
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda: [registration()])
    monkeypatch.setattr(
        "app.routes.get_confirmed_event",
        lambda event_id: confirmed_event(withdrawalDeadline="2020-01-01T09:00:00+08:00"),
    )
    withdraw = Mock()
    monkeypatch.setattr("app.routes.withdraw_saved_registration", withdraw)

    response = client.patch("/registrations/11111111-1111-4111-8111-111111111111/withdraw")

    assert response.status_code == 409
    assert response.json["code"] == "WITHDRAWAL_DEADLINE_PASSED"
    assert "contact the event organisers" in response.json["message"]
    withdraw.assert_not_called()


def test_withdraw_after_event_start_without_cutoff_returns_409(client, monkeypatch):
    """
    Summary: When the organiser set no deadline, withdrawal closes once the event starts.
    AC4: Given the Attendee attempts to withdraw after the registration
        withdrawal deadline (if applicable), the system displays a message to
        contact the organisers and the withdrawal does not go through.
    Double: The event has no withdrawal deadline and has already started
        [Stub]; we check nothing is withdrawn [Mock].
    """
    withdraw = Mock()
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda: [registration()])
    monkeypatch.setattr(
        "app.routes.get_confirmed_event",
        lambda event_id: confirmed_event(preferredStartDate="2020-01-01T09:00:00+08:00"),
    )
    monkeypatch.setattr("app.routes.withdraw_saved_registration", withdraw)

    response = client.patch("/registrations/11111111-1111-4111-8111-111111111111/withdraw")

    assert response.status_code == 409
    assert response.json["code"] == "WITHDRAWAL_DEADLINE_PASSED"
    withdraw.assert_not_called()


def test_withdraw_already_withdrawn_registration_returns_409_without_saving(client, monkeypatch):
    """
    Summary: A registration that is already withdrawn cannot be withdrawn again.
    AC2: Given the Attendee confirms withdrawal, the system changes the
        registration status to 'Withdrawn' and displays a confirmation message.
    Double: The attendee's registration is already Withdrawn [Stub]; we check
        nothing is withdrawn [Mock].
    """
    withdraw = Mock()
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda: [registration(status="Withdrawn")])
    monkeypatch.setattr("app.routes.withdraw_saved_registration", withdraw)

    response = client.patch("/registrations/11111111-1111-4111-8111-111111111111/withdraw")

    assert response.status_code == 409
    assert response.json["code"] == "REGISTRATION_ALREADY_WITHDRAWN"
    withdraw.assert_not_called()


def test_withdraw_when_event_no_longer_open_is_refused_with_contact_message(client, monkeypatch):
    """
    Summary: If the event is no longer open (for example cancelled), withdrawal is not done online and the attendee is told to contact the organisers.
    AC4: Given the Attendee attempts to withdraw after the registration
        withdrawal deadline (if applicable), the system displays a message to
        contact the organisers and the withdrawal does not go through.
    Double: The event is not among the confirmed events [Stub]; we check
        nothing is withdrawn [Mock].
    """
    withdraw = Mock()
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda: [registration()])
    monkeypatch.setattr("app.routes.get_confirmed_event", lambda event_id: None)
    monkeypatch.setattr("app.routes.withdraw_saved_registration", withdraw)

    response = client.patch("/registrations/11111111-1111-4111-8111-111111111111/withdraw")

    assert response.status_code == 409
    assert response.json["code"] == "WITHDRAWAL_UNAVAILABLE"
    assert "contact the event organisers" in response.json["message"]
    withdraw.assert_not_called()


@pytest.mark.parametrize("failing", ["registration_lookup", "event_lookup", "withdraw"])
def test_withdraw_when_downstream_fails_returns_502(client, monkeypatch, failing):
    """
    Summary: If the registration, the event or the withdrawal itself cannot be processed, the attendee gets an error, never a false confirmation.
    AC2: Given the Attendee confirms withdrawal, the system changes the
        registration status to 'Withdrawn' and displays a confirmation message.
    Double: Registration Service or Event Service fails at the given step
        [Stub].
    """
    broken = Mock(side_effect=RuntimeError("secret"))
    monkeypatch.setattr("app.routes.get_attendee_registrations", broken if failing == "registration_lookup" else (lambda: [registration()]))
    monkeypatch.setattr("app.routes.get_confirmed_event", broken if failing == "event_lookup" else (lambda event_id: confirmed_event()))
    monkeypatch.setattr("app.routes.withdraw_saved_registration", broken if failing == "withdraw" else Mock())

    response = client.patch("/registrations/11111111-1111-4111-8111-111111111111/withdraw")

    assert response.status_code == 502
    assert "secret" not in response.json["message"]


def test_withdrawal_deadline_uses_cutoff_else_event_start():
    """
    Summary: The withdrawal deadline is the organiser's cutoff when one is set, otherwise the event's start, judged in Singapore time.
    AC4: Given the Attendee attempts to withdraw after the registration
        withdrawal deadline (if applicable), the system displays a message to
        contact the organisers and the withdrawal does not go through.
    Double: None
    """
    now = datetime(2026, 10, 24, 10, 0, tzinfo=ZoneInfo("Asia/Singapore"))

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


def test_withdraw_saved_registration_returns_updated_row(monkeypatch):
    """
    Summary: The withdrawn registration Registration Service saved is what the attendee's confirmation shows.
    AC2: Given the Attendee confirms withdrawal, the system changes the
        registration status to 'Withdrawn' and displays a confirmation message.
    Double: Registration Service records the withdrawal [Stub]; we check the
        request carries no attendee details, since the attendee comes from
        their sign-in [Mock].
    """
    patch = Mock(return_value=response(200, {"registration": {"status": "Withdrawn"}}))
    monkeypatch.setattr(clients.httpx, "patch", patch)

    assert clients.withdraw_saved_registration("registration-1") == {"status": "Withdrawn"}
    assert patch.call_args.kwargs["json"] == {}


def test_withdraw_saved_registration_when_refused_raises_conflict(monkeypatch):
    """
    Summary: When Registration Service refuses the withdrawal (for example, not this attendee's registration), its reason is passed on.
    AC2: Given the Attendee confirms withdrawal, the system changes the
        registration status to 'Withdrawn' and displays a confirmation message.
    Double: Registration Service refuses the withdrawal [Stub].
    """
    monkeypatch.setattr(
        clients.httpx,
        "patch",
        Mock(return_value=response(403, {"code": "REGISTRATION_NOT_OWNED", "message": "Not yours"})),
    )

    with pytest.raises(clients.RegistrationConflictError) as caught:
        clients.withdraw_saved_registration("registration-1")

    assert caught.value.code == "REGISTRATION_NOT_OWNED"


def test_withdraw_saved_registration_when_failing_raises_http_error(monkeypatch):
    """
    Summary: Any other Registration Service failure is passed up, so no confirmation is shown.
    AC2: Given the Attendee confirms withdrawal, the system changes the
        registration status to 'Withdrawn' and displays a confirmation message.
    Double: Registration Service answers with an error [Stub].
    """
    monkeypatch.setattr(clients.httpx, "patch", Mock(return_value=response(503, {})))

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
    AC4: Given the Attendee attempts to withdraw after the registration
        withdrawal deadline (if applicable), the system displays a message to
        contact the organisers and the withdrawal does not go through.
    Double: None
    """
    deadline = datetime(2026, 10, 24, 9, 0, tzinfo=ZoneInfo("Asia/Singapore"))
    now = deadline + timedelta(minutes=minutes_after_deadline)
    event = {"withdrawalDeadline": deadline.isoformat(), "preferredStartDate": "2026-11-10T09:00:00+08:00"}

    assert withdrawal_deadline_has_passed(event, now) is passed


def test_withdraw_registration_not_in_my_list_returns_404(client, monkeypatch):
    """
    Summary: An attendee can only withdraw a registration of their own; anyone else's is treated as not found.
    AC2: Given the Attendee confirms withdrawal, the system changes the
        registration status to 'Withdrawn' and displays a confirmation message.
    Double: The signed-in attendee has no registration with this id [Stub]; we
        check nothing is withdrawn [Mock].
    """
    withdraw = Mock()
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda: [])
    monkeypatch.setattr("app.routes.withdraw_saved_registration", withdraw)

    response = client.patch("/registrations/11111111-1111-4111-8111-111111111111/withdraw")

    assert response.status_code == 404
    assert response.json["code"] == "REGISTRATION_NOT_FOUND"
    withdraw.assert_not_called()


def test_withdraw_when_registration_service_refuses_passes_reason_on(client, monkeypatch):
    """
    Summary: If Registration Service refuses the withdrawal at the last step, the attendee sees its reason and nothing changes.
    AC2: Given the Attendee confirms withdrawal, the system changes the
        registration status to 'Withdrawn' and displays a confirmation message.
    Double: Registration Service refuses the withdrawal [Stub].
    """
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda: [registration()])
    monkeypatch.setattr("app.routes.get_confirmed_event", lambda event_id: confirmed_event())
    monkeypatch.setattr(
        "app.routes.withdraw_saved_registration",
        Mock(side_effect=RegistrationConflictError("REGISTRATION_NOT_OWNED", "Not yours")),
    )

    response = client.patch("/registrations/11111111-1111-4111-8111-111111111111/withdraw")

    assert response.status_code == 409
    assert response.json == {"code": "REGISTRATION_NOT_OWNED", "message": "Not yours"}


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_withdraw_when_event_dates_unreadable_returns_502(client, monkeypatch):
    """
    Summary: If the event's deadline cannot be read, withdrawal is refused with an error rather than allowed.
    Supporting design check: missing or unreadable event dates fail safely
    Double: The event's deadline and start time are unreadable [Stub].
    """
    withdraw = Mock()
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda: [registration()])
    monkeypatch.setattr(
        "app.routes.get_confirmed_event",
        lambda event_id: confirmed_event(preferredStartDate="", withdrawalDeadline="bad"),
    )
    monkeypatch.setattr("app.routes.withdraw_saved_registration", withdraw)

    response = client.patch("/registrations/11111111-1111-4111-8111-111111111111/withdraw")

    assert response.status_code == 502
    assert response.json == {"message": "The withdrawal deadline is unavailable."}
    withdraw.assert_not_called()


def test_withdrawal_deadline_without_any_date_raises():
    """
    Summary: Without a deadline or a start time, the deadline cannot be judged, so it is not treated as open.
    Supporting design check: missing event data fails safely
    Double: None
    """
    with pytest.raises(ValueError):
        withdrawal_deadline_has_passed({})
