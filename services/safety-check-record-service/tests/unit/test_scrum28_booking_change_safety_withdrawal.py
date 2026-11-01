"""
SCRUM-28: Venue Booking Request Submission

User Story
----------
As an Event Coordinator, I want to submit a venue booking request for an event,
so that Venue Staff can assess whether the requested venue arrangement can be
accepted.

Acceptance Criteria
-------------------
AC1: Given an Event Coordinator is preparing a venue booking request for an
     event, when they enter the booking information, then they can provide the
     relevant event timing and venue requirements needed for Venue Staff to
     assess the booking.
AC2: Given the relevant event timing and venue requirements have been provided,
     when the Event Coordinator submits the venue booking request, then the
     request is recorded and made available to Venue Staff for review.
AC3: Given a venue booking request has been submitted, when Venue Staff access
     the request, then they can view the event to which the request relates
     together with the relevant event timing and venue requirements.
AC4: Given a venue booking request has been submitted and has not yet received
     a booking decision, when Venue Staff view requests requiring action, then
     the request can be identified as awaiting Venue Staff review.
AC5: Given an Event Coordinator submits a venue booking request for an event,
     when the request is recorded, then it remains associated with that event
     so that the booking can be assessed in the context of the corresponding
     event requirements.
AC6: Given an Event Coordinator submits a venue booking request for a venue and
     time slot, when the same venue has already been requested or booked for
     another event, and the requested event timing does not overlap with that
     other event's timing, then the request is accepted for Venue Staff review
     as normal, so the same venue can be booked for multiple events across
     non-overlapping time slots.
AC7: Given an event is 'Confirmed' after passing its Operational Safety Check,
     when the Event Coordinator edits or cancels one of its venue bookings,
     then the event's safety approval is withdrawn without opening a new safety
     check round, the event returns to 'Approved', and an edited booking
     returns to awaiting Venue Staff review, so the event must be submitted for
     a safety check again. If the booking change cannot be saved, the safety
     approval is restored and the event stays 'Confirmed'. While the event is
     'Pending Safety Check', its venue bookings cannot be edited or cancelled.

Real
----
- What a booking change on a Confirmed event does to its safety rounds: the
  approval is withdrawn without opening a new round, it can be reinstated if
  the booking change fails (but not once a later round exists), and the next
  submission opens the following round.
- We check the rounds returned and what is saved.

Doubled
-------
- Safety records (database): hold the rounds each test needs, accept new ones,
  or cannot be reached [Stub]; we check what is saved, and that rounds are
  locked before they change [Mock].
- Sign-in: a test key signs the caller's token (tests/unit/conftest.py) [Stub].

Not proven
----------
- The whole chain across Venue Booking, Safety Check, Safety Check Record and
  Event Services (run by hand against the stack).
- That the saving and locking really work in Postgres, including two people
  acting at the same moment (-> tests/integration/, against a throwaway
  postgres:17.6).
"""
from unittest.mock import MagicMock

import pytest

from app import create_app
from tests.unit.factories import COORDINATOR_ID, EVENT_ID, NEXT_RECORD_ID, RECORD_ID, record_row, signed_in

REASON = "Venue booking for Grand Hall changed after safety approval."


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client(), COORDINATOR_ID), cursor


def approved(round_number=2):
    return record_row(round_number=round_number, status="Safety Approved", decided=True)


def withdrawn(round_number=2):
    return record_row(round_number=round_number, status="Approval Withdrawn", decided=True, withdrawn=True)


def statements(cursor):
    return [call.args[0] for call in cursor.execute.call_args_list]


# --- withdraw without opening a round ----------------------------------------


def test_withdraw_for_booking_change_withdraws_without_opening_round(setup):
    """
    Summary: A booking change withdraws the approval without opening a new round.
    AC7: Given an event is 'Confirmed' after passing its Operational Safety
        Check, when the Event Coordinator edits or cancels one of its venue
        bookings, then the event's safety approval is withdrawn without opening
        a new safety check round, the event returns to 'Approved', and an
        edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: The round is approved [Stub]; we check it is withdrawn without a
        new round being added [Mock].
    """
    client, cursor = setup
    cursor.fetchone.side_effect = [approved(), approved(), withdrawn()]

    response = client.post(
        f"/safety-check-records/{RECORD_ID}/withdraw",
        json={"reason": REASON, "openNextRound": False},
    )

    assert response.status_code == 201
    assert response.json["withdrawn"]["status"] == "Approval Withdrawn"
    assert response.json["opened"] is None
    assert not any("INSERT" in sql for sql in statements(cursor))
    assert "FOR UPDATE" in statements(cursor)[0]


@pytest.mark.parametrize("value", ["false", 0, None], ids=["text_false", "zero", "null"])
def test_withdraw_with_non_boolean_open_next_round_returns_400(setup, value):
    """
    Summary: Whether to open a round must be a plain true or false.
    AC7: Given an event is 'Confirmed' after passing its Operational Safety
        Check, when the Event Coordinator edits or cancels one of its venue
        bookings, then the event's safety approval is withdrawn without opening
        a new safety check round, the event returns to 'Approved', and an
        edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: None
    """
    client, cursor = setup

    response = client.post(
        f"/safety-check-records/{RECORD_ID}/withdraw",
        json={"reason": REASON, "openNextRound": value},
    )

    assert response.status_code == 400
    assert response.json["message"] == "openNextRound must be true or false."
    cursor.execute.assert_not_called()


# --- restore a withdrawal that opened no round -------------------------------


def restore_without_round(client):
    return client.post(f"/safety-check-records/{RECORD_ID}/restore", json={"nextRoundOpened": False})


def test_restore_after_booking_change_reinstates_approval(setup):
    """
    Summary: If the booking change fails, the approval is reinstated.
    AC7: Given an event is 'Confirmed' after passing its Operational Safety
        Check, when the Event Coordinator edits or cancels one of its venue
        bookings, then the event's safety approval is withdrawn without opening
        a new safety check round, the event returns to 'Approved', and an
        edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: The round's approval has been withdrawn [Stub].
    """
    client, cursor = setup
    cursor.fetchone.side_effect = [withdrawn(), withdrawn(), approved()]

    response = restore_without_round(client)

    assert response.status_code == 200
    assert response.json["status"] == "Safety Approved"
    assert not any("DELETE" in sql for sql in statements(cursor))
    assert "withdrawn_at = NULL" in statements(cursor)[-1]


def test_restore_after_booking_change_with_later_round_returns_409(setup):
    """
    Summary: The approval is not reinstated once a later round exists.
    AC7: Given an event is 'Confirmed' after passing its Operational Safety
        Check, when the Event Coordinator edits or cancels one of its venue
        bookings, then the event's safety approval is withdrawn without opening
        a new safety check round, the event returns to 'Approved', and an
        edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: A later round exists for the event [Stub].
    """
    client, cursor = setup
    cursor.fetchone.side_effect = [withdrawn(), record_row(round_number=3, safety_check_id=NEXT_RECORD_ID)]

    response = restore_without_round(client)

    assert response.status_code == 409
    assert response.json["code"] == "NOT_RESTORABLE"
    assert not any(sql.lstrip().startswith("UPDATE") for sql in statements(cursor))


def test_restore_after_booking_change_twice_has_same_result(setup):
    """
    Summary: Restoring twice has the same result as once.
    AC7: Given an event is 'Confirmed' after passing its Operational Safety
        Check, when the Event Coordinator edits or cancels one of its venue
        bookings, then the event's safety approval is withdrawn without opening
        a new safety check round, the event returns to 'Approved', and an
        edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: The approval has already been reinstated [Stub].
    """
    client, cursor = setup
    cursor.fetchone.side_effect = [approved(), approved()]

    response = restore_without_round(client)

    assert response.status_code == 200
    assert response.json["status"] == "Safety Approved"


@pytest.mark.parametrize(
    "body, message",
    [
        ({"nextRoundOpened": "no"}, "nextRoundOpened must be true or false."),
        (
            {"nextRoundOpened": False, "openedSafetyCheckId": NEXT_RECORD_ID},
            "openedSafetyCheckId must be omitted when nextRoundOpened is false.",
        ),
    ],
    ids=["bad_flag", "id_without_round"],
)
def test_restore_after_booking_change_with_bad_body_returns_400(setup, body, message):
    """
    Summary: A restore must say plainly whether a new round was opened, and name none if it was not.
    AC7: Given an event is 'Confirmed' after passing its Operational Safety
        Check, when the Event Coordinator edits or cancels one of its venue
        bookings, then the event's safety approval is withdrawn without opening
        a new safety check round, the event returns to 'Approved', and an
        edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: None
    """
    client, cursor = setup

    response = client.post(f"/safety-check-records/{RECORD_ID}/restore", json=body)

    assert response.status_code == 400
    assert response.json["message"] == message
    cursor.execute.assert_not_called()


def test_open_round_after_booking_change_withdrawal_uses_next_number(setup):
    """
    Summary: Resubmitting after a booking-change withdrawal opens the next round and leaves the withdrawn one in the history.
    AC7: Given an event is 'Confirmed' after passing its Operational Safety
        Check, when the Event Coordinator edits or cancels one of its venue
        bookings, then the event's safety approval is withdrawn without opening
        a new safety check round, the event returns to 'Approved', and an
        edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: The event's latest round had its approval withdrawn, and the safety
        records accept the new round [Stub]; we check its number [Mock].
    """
    client, cursor = setup
    cursor.fetchone.side_effect = [withdrawn(round_number=2), record_row(round_number=3)]

    response = client.post("/safety-check-records", json={"eventId": EVENT_ID})

    assert response.status_code == 201
    assert response.json["roundNumber"] == 3
    insert = next(call for call in cursor.execute.call_args_list if "INSERT" in call.args[0])
    assert insert.args[1][1] == 3
    assert not any(sql.lstrip().startswith("UPDATE") for sql in statements(cursor))
