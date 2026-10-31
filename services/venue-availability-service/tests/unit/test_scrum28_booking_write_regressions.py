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

Real
----
- POST /venue-bookings and the decision routes: input validation and the
  missing-database guard, kept unchanged by the closure work, and the Pending
  Review status on create.
- Assertions are on the status and the SQL sent.

Doubled
-------
- psycopg2.connect: Stub (`setup`/`client` fixtures) - fresh MagicMock
  connection; the cursor returns canned VenueBooking / VenueClosure rows (or
  raises); executed SQL, parameters and locks are inspected.

Not proven
----------
- That the SQL, locks and constraints behave the same on real PostgreSQL (->
  tests/integration/, throwaway postgres:17.6).
- AC3/AC4 Venue Staff reads are owned by Venue Booking Service; AC5/AC6
  association and non-overlap behaviour are covered by
  `test_scrum28_booking_request_submission.py` and the booking suite.
"""

import pytest
from app.calendar import SINGAPORE
from tests.unit.factories import BOOKING_ID, bearer, EVENT_ID, USER_ID, VENUE_ID, booking_row

PAYLOAD = dict(
    eventId=EVENT_ID,
    venueId=VENUE_ID,
    requestedBy=USER_ID,
    requestedStartTime="2026-10-01T09:00",
    requestedEndTime="2026-10-01T12:00",
    requiredCapacity=80,
    venueRequirements="Projector",
)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        PAYLOAD | {"eventId": "bad"},
        PAYLOAD | {"requestedStartTime": "bad"},
        PAYLOAD | {"requestedStartTime": None},
        PAYLOAD | {"requestedStartTime": "2026-10-01"},
        PAYLOAD | {"requestedStartTime": "2026-10-01T09:00+08:00"},
        PAYLOAD | {"requiredCapacity": 0},
        PAYLOAD | {"requiredCapacity": True},
        PAYLOAD | {"venueRequirements": None},
    ],
    ids=["none", "empty", "empty_2", "payload_eventid_bad", "payload_requestedstarttime_bad", "payload_requestedstarttime_none", "payload_requestedstarttime_2026_10_01", "payload_requestedstarttime_2026_10_01t09_00_08_0", "payload_requiredcapacity_0", "payload_requiredcapacity_true", "payload_venuerequirements_none"],
)
def test_ac1_create_booking_with_invalid_input_returns_400(setup, payload):
    """
    Summary: A booking request without a valid event, times, capacity or requirements is refused.
    AC1: Given an Event Coordinator is preparing a venue booking request for an
        event, when they enter the booking information, then they can provide
        the relevant event timing and venue requirements needed for Venue Staff
        to assess the booking.
    Double: Mock (cursor not executed)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act + Assert (When / Then)
    assert client.post("/venue-bookings", json=payload).status_code == 400
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("payload", [{"setupTimeMinutes": -1}, {"turnaroundTimeMinutes": "x"}], ids=["negative_setup", "negative_turnaround"])
def test_ac1_approve_booking_with_negative_buffer_returns_400(setup, payload):
    """
    Summary: A decision with negative setup or turnaround time is refused.
    AC1: Given an Event Coordinator is preparing a venue booking request for an
        event, when they enter the booking information, then they can provide
        the relevant event timing and venue requirements needed for Venue Staff
        to assess the booking.
    Double: None
    """
    # Arrange (Given)
    client, cursor = setup

    # Act + Assert (When / Then)
    assert (
        client.patch(f"/venue-bookings/{BOOKING_ID}/approve", headers=bearer(USER_ID, "Venue Staff"), json=payload).status_code
        == 400
    )
    cursor.execute.assert_not_called()


def test_ac2_create_booking_saves_pending_review_with_naive_times(setup):
    """
    Summary: A new request is saved as Pending Review with naive Singapore times.
    AC2: Given the relevant event timing and venue requirements have been
        provided, when the Event Coordinator submits the venue booking request,
        then the request is recorded and made available to Venue Staff for
        review.
    Double: Stub (cursor returns the inserted row; parameters inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [booking_row()]

    # Act (When)
    response = client.post("/venue-bookings", json=PAYLOAD)

    # Assert (Then)
    assert response.status_code == 201
    assert response.json["requestedStartTime"] == "2026-10-01T09:00:00"
    assert response.json["status"] == "Pending Review"
    assert "blocksSelection" not in response.json
    sql, params = cursor.execute.call_args_list[2].args
    assert "status IN ('Approved', 'On Hold')" in sql
    assert "requested_start_time < %s AND requested_end_time > %s" in sql
    assert params == [
        VENUE_ID,
        booking_row()["requested_end_time"].replace(tzinfo=SINGAPORE),
        booking_row()["requested_start_time"].replace(tzinfo=SINGAPORE),
    ] * 2
    assert "VenueHold" not in sql
    # SCRUM-47 adds an outbox insert after the booking, so inspect the booking SQL.
    booking_insert = next(call.args[0] for call in cursor.execute.call_args_list
                          if 'INSERT INTO public."VenueBooking"' in call.args[0])
    assert "'Pending Review'" in booking_insert


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_support_create_booking_when_database_url_missing_returns_503(setup):
    """
    Summary: Requesting a booking reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured service answers 503
    Double: None
    """
    client, cursor = setup
    client.application.config["DATABASE_URL"] = None
    assert client.post("/venue-bookings", json=PAYLOAD).status_code == 503
    cursor.execute.assert_not_called()


def test_support_decide_booking_when_database_url_missing_returns_503(setup):
    """
    Summary: Deciding reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured service answers 503
    Double: None
    """
    client, cursor = setup
    client.application.config["DATABASE_URL"] = None
    assert (
        client.patch(
            f"/venue-bookings/{BOOKING_ID}/reject", headers=bearer(USER_ID, "Venue Staff"),
            json={"reviewedBy": USER_ID, "rejectionReason": "Venue unsuitable"},
        ).status_code
        == 503
    )
    cursor.execute.assert_not_called()
