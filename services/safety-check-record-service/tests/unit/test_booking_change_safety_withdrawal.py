"""
SCRUM-153: Re-check Safety After High-Impact Changes

User Story
----------
As an Event Coordinator, I want a safety approval to be withdrawn when a
high-impact detail changes afterwards, so that the event is never prepared on
the basis of an outdated safety review.

Acceptance Criteria
-------------------
AC1: Given an event is 'Confirmed', when its date/time, expected attendance,
     venue requirements, equipment requirements or accessibility needs change,
     then its status returns to 'Pending Safety Check' and the coordinator is
     told why.
AC2: Given only a low-impact field changes (name, description, purpose,
     registration needs), then the event stays 'Confirmed'.
AC3: Given a safety approval is withdrawn, then it stays visible in the event's
     safety history.
AC4: Given a high-impact change to a 'Confirmed' event is waiting for its new
     safety check, when a registered Attendee views the event, then they still
     see the previously approved details, and the changed details are shown to
     them only after the Safety Officer approves the new safety check.
AC5: Given the new safety check ends without approval (changes requested or the
     event is cancelled), then registered Attendees are never shown the
     unapproved change, and they continue to see the last approved details or
     the cancellation.

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
- POST /safety-check-records/<id>/withdraw with openNextRound=false (a booking
  change on a Confirmed event withdraws the approval without opening a round)
  and POST .../restore with nextRoundOpened=false (its undo) run for real.
- Assertions are on the status, error and the SQL sent.

Doubled
-------
- psycopg2.connect: Stub (`setup` fixture) - fresh MagicMock connection; the
  cursor returns canned SafetyCheck rows (or raises); executed SQL, parameters
  and the FOR UPDATE lock are inspected.

Not proven
----------
- The whole chain across Venue Booking, Safety Check, Safety Check Record and
  Event Services (-> docs/test-scripts/scrum-28-venue-booking-request-
  submission.md, Part B, run by hand against the stack).
- That Venue Booking Service calls this and restores on failure (->
  venue-booking-service unit tests).
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
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor returns the approved round; SQL inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [approved(), approved(), withdrawn()]

    # Act (When)
    response = client.post(
        f"/safety-check-records/{RECORD_ID}/withdraw",
        json={"reason": REASON, "openNextRound": False},
    )

    # Assert (Then)
    assert response.status_code == 201
    assert response.json["withdrawn"]["status"] == "Approval Withdrawn"
    assert response.json["opened"] is None
    assert not any("INSERT" in sql for sql in statements(cursor))
    assert "FOR UPDATE" in statements(cursor)[0]


def test_withdraw_by_default_still_opens_next_round(setup):
    """
    Summary: A withdrawal that does not say otherwise still opens the next round.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (cursor returns rows; SQL inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [
        approved(), approved(), withdrawn(),
        record_row(round_number=3, safety_check_id=NEXT_RECORD_ID),
    ]

    # Act (When)
    response = client.post(
        f"/safety-check-records/{RECORD_ID}/withdraw",
        json={"reason": REASON},
    )

    # Assert (Then)
    assert response.status_code == 201
    assert response.json["opened"]["roundNumber"] == 3
    assert any("INSERT" in sql for sql in statements(cursor))


@pytest.mark.parametrize("value", ["false", 0, None], ids=["text_false", "zero", "null"])
def test_withdraw_with_non_boolean_open_next_round_returns_400(setup, value):
    """
    Summary: Whether to open a round must be a plain true or false.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: None
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = client.post(
        f"/safety-check-records/{RECORD_ID}/withdraw",
        json={"reason": REASON, "openNextRound": value},
    )

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "openNextRound must be true or false."
    cursor.execute.assert_not_called()


# --- restore a withdrawal that opened no round -------------------------------


def restore_without_round(client):
    return client.post(f"/safety-check-records/{RECORD_ID}/restore", json={"nextRoundOpened": False})


def test_restore_after_booking_change_reinstates_approval(setup):
    """
    Summary: If the booking change fails, the approval is reinstated.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor returns the withdrawn round)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [withdrawn(), withdrawn(), approved()]

    # Act (When)
    response = restore_without_round(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Safety Approved"
    assert not any("DELETE" in sql for sql in statements(cursor))
    assert "withdrawn_at = NULL" in statements(cursor)[-1]


def test_restore_after_booking_change_with_later_round_returns_409(setup):
    """
    Summary: The approval is not reinstated once a later round exists.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor: a later round exists)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [withdrawn(), record_row(round_number=3, safety_check_id=NEXT_RECORD_ID)]

    # Act (When)
    response = restore_without_round(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "NOT_RESTORABLE"
    assert not any(sql.lstrip().startswith("UPDATE") for sql in statements(cursor))


def test_restore_after_booking_change_twice_has_same_result(setup):
    """
    Summary: Restoring twice has the same result as once.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor returns an already restored round)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [approved(), approved()]

    # Act (When)
    response = restore_without_round(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Safety Approved"


def test_restore_with_round_opened_still_needs_its_id(setup):
    """
    Summary: A restore that says a round was opened must name it.
    AC3: (rollback)
    Double: None
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = client.post(f"/safety-check-records/{RECORD_ID}/restore", json={})

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "openedSafetyCheckId must be a valid UUID."
    cursor.execute.assert_not_called()


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
    Summary: The restore body must say plainly whether a round was opened, and name none if not.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: None
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = client.post(f"/safety-check-records/{RECORD_ID}/restore", json=body)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == message
    cursor.execute.assert_not_called()


def test_open_round_after_booking_change_withdrawal_uses_next_number(setup):
    """
    Summary: Resubmitting after a booking-change withdrawal opens the next round and leaves the withdrawn one in the history.
    SCRUM-28 AC7: Given an event is 'Confirmed' after passing its Operational
        Safety Check, when the Event Coordinator edits or cancels one of its
        venue bookings, then the event's safety approval is withdrawn without
        opening a new safety check round, the event returns to 'Approved', and
        an edited booking returns to awaiting Venue Staff review, so the event
        must be submitted for a safety check again. If the booking change
        cannot be saved, the safety approval is restored and the event stays
        'Confirmed'. While the event is 'Pending Safety Check', its venue
        bookings cannot be edited or cancelled.
    Double: Stub (cursor: latest round 'Approval Withdrawn', the inserted row)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [withdrawn(round_number=2), record_row(round_number=3)]

    # Act (When)
    response = client.post("/safety-check-records", json={"eventId": EVENT_ID})

    # Assert (Then)
    assert response.status_code == 201
    assert response.json["roundNumber"] == 3
    insert = next(call for call in cursor.execute.call_args_list if "INSERT" in call.args[0])
    assert insert.args[1][1] == 3
    assert not any(sql.lstrip().startswith("UPDATE") for sql in statements(cursor))
