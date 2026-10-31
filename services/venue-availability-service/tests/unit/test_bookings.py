"""SCRUM-156: Book Multiple Venues for an Event

User Story
----------
As an Event Coordinator, I want to create multiple venue booking requests for a
single event, so that I can arrange the different spaces required for the event

Acceptance Criteria
-------------------
AC1: Given an event exists, when the Event Coordinator creates venue booking
     requests, then more than one venue booking can be associated with the same
     event.
AC2: Each venue booking records its own venue, date/time, required
     capacity/expected attendance, venue requirements, and booking status.
AC3: Given multiple venue bookings exist for an event, when the Event
     Coordinator views the event, then each booking is displayed separately
     while remaining associated with the same event.
AC4: When a venue booking is submitted, its suitability, availability, and
     booking conflicts are evaluated using the requirements of that specific
     booking.
AC5: If one venue booking fails a suitability, availability, or conflict check,
     other valid venue bookings for the same event can still proceed.
AC6: Different venues requested for the same event during overlapping time
     periods are not considered conflicting solely because they belong to the
     same event.

SCRUM-157: Manage Individual Venue Arrangements

User Story
----------
As an Event Coordinator, I want to modify or cancel a specific venue booking
for an event, so that I can adjust one venue arrangement without affecting the
event's other venue arrangements.

Acceptance Criteria
-------------------
AC1: Given an event has one or more venue bookings, when the Event Coordinator
     modifies a specific booking, then only that selected booking is updated.
AC2: If a modification changes the venue, date/time, required capacity, or
     other suitability requirements, then suitability, availability, and
     conflict checks are performed again for that booking only.
AC3: Given an event has multiple venue bookings, when the Event Coordinator
     cancels one booking, then only the selected booking is cancelled and the
     other bookings remain unchanged.
AC4: Cancelling or modifying one venue booking does not automatically change
     the status of the event's other venue bookings.
AC5: A cancelled booking remains associated with the event with a Cancelled
     status for record keeping.

SCRUM-29: Venue Booking Review and Decision

User Story
----------
As a Venue Staff member, I want to review and decide on a pending venue booking
request, so that I can determine whether the requested venue arrangement can be
accepted and provide the Event Coordinator with the outcome.

Acceptance Criteria
-------------------
AC1: Given a venue booking request is pending review, when Venue Staff open the
     request, then they can view the relevant event timing and venue
     requirements needed to assess the booking.
AC2: Given Venue Staff determine that a pending venue booking request can be
     accepted, when they approve the request, then the booking decision is
     recorded as approved and the outcome is available to the relevant Event
     Coordinator.
AC3: Given Venue Staff determine that a pending venue booking request cannot be
     accepted, when they reject the request, then the booking decision is
     recorded as rejected and the outcome is available to the relevant Event
     Coordinator.
AC4: Given a venue booking request cannot be accepted, when Venue Staff record
     their decision, then they can provide relevant information or a reason
     explaining why the booking cannot be accepted.
AC5: Given Venue Staff have recorded an approval or rejection for a pending
     venue booking request, when the decision is completed, then the request is
     no longer presented as awaiting a booking decision.
AC6: Given a booking request has been rejected and Venue Staff have provided
     relevant information or a reason, when the Event Coordinator views the
     booking decision, then they can view that information so that they can
     continue planning the event.

SCRUM-164: Revise Arrangements and Resubmit for Safety Check

Agreed revision from this conversation; pending confirmation that Jira has been updated

User Story
----------
As an Event Coordinator, I want to see the Safety Officer's feedback and revise
the affected arrangements, so that I can resubmit the event for a safety check
without redoing unaffected planning.

Acceptance Criteria
-------------------
AC1: Given my event is 'Safety Changes Requested', when I open it, then I see
     the decision, reason, requested changes and affected areas.
AC2: Given the venue arrangement is flagged, then the affected venue booking
     must be reviewed again by Venue Staff (revised booking or replacement
     request) before the event can be resubmitted.
AC3: Given the technical arrangement is flagged, then the affected equipment requests that were previously 'Approved' return to 'Pending' and must be approved again by Technical Support Staff before the event can be resubmitted. The safety-change action does not reopen existing 'Rejected' requests or clear their rejection reasons, and requests already 'Pending' remain 'Pending'.
AC4: Given an arrangement was not flagged, then it stays confirmed and does not
     need to be reviewed again.
AC5: Given all flagged arrangements are confirmed again, when I resubmit, then
     the status returns to 'Pending Safety Check' as a new review round, and
     earlier rounds remain in the history.

Real
----
- The booking routes: create with venue-and-time conflict scope, approve with a
  fresh conflict check, reject, list per venue and per event, edit one booking
  (reset to review, re-check only it), cancel (kept as Cancelled, idempotent)
  and the Safety Officer reset of selected bookings.
- Assertions are on the status, rows returned and SQL sent.

Doubled
-------
- psycopg2.connect: Stub (`setup`/`client` fixtures) - fresh MagicMock
  connection; the cursor returns canned VenueBooking / VenueClosure rows (or
  raises); executed SQL, parameters and locks are inspected.

Not proven
----------
- That the overlap SQL, locks and constraints behave the same on real
  PostgreSQL (-> tests/integration/, throwaway postgres:17.6, and the opt-in
  tests/live/test_calendar.py).
"""

from datetime import datetime
import pytest

from app import create_app
from app.models import _has_conflict
from tests.unit.factories import (
    signed_in,
    bearer,
    BOOKING_ID,
    EVENT_ID,
    USER_ID,
    VENUE_ID,
    assert_no_booking_intent,
    booking_row,
)


def test_booking_reads_include_closure_history_when_present(setup, monkeypatch):
    """
    Summary: Booking reads include closure rejection history when the columns exist, and still work without them.
    SCRUM-29 AC6: Given a booking request has been rejected and Venue Staff
        have provided relevant information or a reason, when the Event
        Coordinator views the booking decision, then they can view that
        information so that they can continue planning the event.
    Double: Stub (cursor rows with and without closure columns)
    """
    # Arrange (Given)
    monkeypatch.setenv("VENUE_BOOKING_LEGACY_SCHEMA", "true")
    client, cursor = setup
    cursor.fetchall.return_value = [booking_row()]

    # Act (When)
    response = client.get(f"/events/{EVENT_ID}/venue-bookings")

    # Assert (Then)
    assert response.status_code == 200
    sql = cursor.execute.call_args.args[0]
    assert 'to_jsonb("VenueBooking")->>\'rejection_closure_id\'' in sql
    assert 'to_jsonb("VenueBooking")->>\'rejected_at\'' in sql


def test_safety_reset_returns_selected_bookings_to_review(setup):
    """
    Summary: A flagged venue arrangement sends only the selected bookings back to Venue Staff.
    SCRUM-164 AC2: Given the venue arrangement is flagged, then the affected
        venue booking must be reviewed again by Venue Staff (revised booking or
        replacement request) before the event can be resubmitted.
    Double: Stub (cursor returns the selected rows)
    """
    # Arrange (Given)
    client, cursor = setup
    client.application.config["INTERNAL_SERVICE_TOKEN"] = "test-token"
    cursor.fetchall.side_effect = [[booking_row(status="Approved")], [booking_row(status="Pending Review")]]

    # Act (When)
    response = client.post(f"/events/{EVENT_ID}/venue-bookings/safety-reset",
        headers={"X-Internal-Token": "test-token", **bearer(USER_ID, "Safety Officer")}, json={"bookingIds": [BOOKING_ID]})

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["bookings"][0]["status"] == "Pending Review"
    sql, params = cursor.execute.call_args.args
    assert "reviewed_by = NULL" in sql
    assert "status IN ('Approved', 'Pending', 'Pending Review')" in sql
    assert params == [EVENT_ID, [BOOKING_ID]]


def test_safety_reset_with_other_events_booking_returns_404(setup):
    """
    Summary: A booking of another event is not reset.
    SCRUM-164 AC4: Given an arrangement was not flagged, then it stays
        confirmed and does not need to be reviewed again.
    Double: Stub (cursor finds none for this event)
    """
    # Arrange (Given)
    client, cursor = setup
    client.application.config["INTERNAL_SERVICE_TOKEN"] = "test-token"
    cursor.fetchall.return_value = []

    # Act + Assert (When / Then)
    assert client.post(f"/events/{EVENT_ID}/venue-bookings/safety-reset",
        headers={"X-Internal-Token": "test-token", **bearer(USER_ID, "Safety Officer")}, json={"bookingIds": [BOOKING_ID]}).status_code == 404
    assert not any('UPDATE public."VenueBooking"' in call.args[0] for call in cursor.execute.call_args_list)


@pytest.mark.parametrize("token,headers,code", [(None, {}, 503), ("test-token", {}, 403)], ids=["token_unconfigured", "no_service_token"])
def test_safety_reset_without_service_credentials_is_refused(setup, token, headers, code):
    """
    Summary: Only Safety Check Service can reset bookings.
    SCRUM-164 AC2: Given the venue arrangement is flagged, then the affected
        venue booking must be reviewed again by Venue Staff (revised booking or
        replacement request) before the event can be resubmitted.
    Double: None
    """
    # Arrange (Given)
    headers = {**headers, **bearer(USER_ID, "Safety Officer")}
    client, cursor = setup
    client.application.config["INTERNAL_SERVICE_TOKEN"] = token

    # Act + Assert (When / Then)
    assert client.post(f"/events/{EVENT_ID}/venue-bookings/safety-reset", headers=headers,
        json={"bookingIds": [BOOKING_ID]}).status_code == code
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("payload", [None, {}, {"bookingIds": []}, {"bookingIds": ["bad"]},
    {"bookingIds": [BOOKING_ID, BOOKING_ID]}, {"bookingIds": [BOOKING_ID] * 501}], ids=["none", "empty", "bookingids", "bookingids_bad", "bookingids_booking_id_booking_id", "bookingids_booking_id_501"])
def test_safety_reset_with_invalid_booking_ids_returns_400(setup, payload):
    """
    Summary: A reset must name valid, distinct bookings.
    SCRUM-164 AC2: Given the venue arrangement is flagged, then the affected
        venue booking must be reviewed again by Venue Staff (revised booking or
        replacement request) before the event can be resubmitted.
    Double: None
    """
    # Arrange (Given)
    client, cursor = setup
    client.application.config["INTERNAL_SERVICE_TOKEN"] = "test-token"

    # Act + Assert (When / Then)
    assert client.post(f"/events/{EVENT_ID}/venue-bookings/safety-reset",
        headers={"X-Internal-Token": "test-token", **bearer(USER_ID, "Safety Officer")}, json=payload).status_code == 400
    cursor.execute.assert_not_called()


def test_create_booking_without_conflict_saves_it(setup):
    """
    Summary: A booking with no conflict is saved.
    AC1: Given an event exists, when the Event Coordinator creates venue
        booking requests, then more than one venue booking can be associated
        with the same event.
    AC4: When a venue booking is submitted, its suitability, availability, and
        booking conflicts are evaluated using the requirements of that specific
        booking.
    Double: Stub (no overlap; inserted row)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [booking_row()]

    # Act (When)
    response = client.post(
        "/venue-bookings",
        json={
            "eventId": EVENT_ID,
            "venueId": VENUE_ID,
            "requestedStartTime": "2026-10-01T09:00",
            "requestedEndTime": "2026-10-01T12:00",
            "requiredCapacity": 80,
            "venueRequirements": "Projector and movable seating",
            "requestedBy": USER_ID,
        },
    )

    # Assert (Then)
    assert response.status_code == 201
    assert response.json["status"] == "Pending Review"
    assert response.json["eventId"] == EVENT_ID
    assert response.json["requiredCapacity"] == 80
    assert response.json["venueRequirements"] == "Projector and movable seating"


def test_create_booking_at_other_venue_same_event_is_not_a_conflict(setup):
    """
    Summary: Another venue booked for the same event at the same time is not a conflict.
    AC6: Different venues requested for the same event during overlapping time
        periods are not considered conflicting solely because they belong to
        the same event.
    Double: Stub (overlap query scoped to the venue)
    """
    _, cursor = setup
    cursor.fetchone.return_value = None

    assert not _has_conflict(
        cursor, VENUE_ID, datetime(2026, 10, 1, 9), datetime(2026, 10, 1, 12)
    )

    query, params = cursor.execute.call_args.args
    assert "WHERE venue_id = %s" in query
    assert "event_id" not in query
    assert params[0] == VENUE_ID


def test_create_booking_overlapping_approved_booking_returns_409_without_alert(setup):
    """
    Summary: An overlapping request is refused and no alert is queued.
    AC4: When a venue booking is submitted, its suitability, availability, and
        booking conflicts are evaluated using the requirements of that specific
        booking.
    Double: Stub (overlap found), Mock (no outbox insert)
    """
    client, cursor = setup
    cursor.fetchall.return_value = [{"conflict_type": "APPROVED_BOOKING"}]

    response = client.post(
        "/venue-bookings",
        json={
            "eventId": EVENT_ID,
            "venueId": VENUE_ID,
            "requestedStartTime": "2026-10-01T09:00",
            "requestedEndTime": "2026-10-01T12:00",
            "requiredCapacity": 80,
            "venueRequirements": "",
            "requestedBy": USER_ID,
        },
    )

    assert response.status_code == 409
    assert_no_booking_intent(cursor)


def test_create_booking_with_end_not_after_start_returns_400(setup):
    """
    Summary: A booking must end after it starts.
    AC2: Each venue booking records its own venue, date/time, required
        capacity/expected attendance, venue requirements, and booking status.
    Double: None
    """
    client, _ = setup
    response = client.post(
        "/venue-bookings",
        json={
            "eventId": EVENT_ID,
            "venueId": VENUE_ID,
            "requestedStartTime": "2026-10-01T12:00",
            "requestedEndTime": "2026-10-01T09:00",
            "requiredCapacity": 80,
            "venueRequirements": "",
            "requestedBy": USER_ID,
        },
    )
    assert response.status_code == 400


def test_approve_booking_without_conflict_approves_it(setup):
    """
    Summary: A booking with no conflict can be approved.
    SCRUM-29 AC2: Given Venue Staff determine that a pending venue booking
        request can be accepted, when they approve the request, then the
        booking decision is recorded as approved and the outcome is available
        to the relevant Event Coordinator.
    Double: Stub (no overlap; updated row)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [
        booking_row(),
        booking_row(status="Approved", reviewed_by=USER_ID),
    ]

    # Act (When)
    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}/approve", headers=bearer(USER_ID, "Venue Staff"), json={"reviewedBy": USER_ID}
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Approved"


def test_approve_booking_when_slot_now_taken_returns_409_without_alert(setup):
    """
    Summary: A booking whose slot has since been taken cannot be approved.
    SCRUM-29 AC2: Given Venue Staff determine that a pending venue booking
        request can be accepted, when they approve the request, then the
        booking decision is recorded as approved and the outcome is available
        to the relevant Event Coordinator.
    Double: Stub (overlap found), Mock (no outbox insert)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [booking_row()]
    cursor.fetchall.return_value = [{"conflict_type": "APPROVED_BOOKING"}]

    # Act (When)
    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}/approve", headers=bearer(USER_ID, "Venue Staff"), json={"reviewedBy": USER_ID}
    )

    # Assert (Then)
    assert response.status_code == 409
    assert_no_booking_intent(cursor)


def test_approve_unknown_booking_returns_404_without_alert(setup):
    """
    Summary: Approving an unknown booking is refused and no alert queued.
    SCRUM-29 AC2: Given Venue Staff determine that a pending venue booking
        request can be accepted, when they approve the request, then the
        booking decision is recorded as approved and the outcome is available
        to the relevant Event Coordinator.
    Double: Stub (cursor finds nothing)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [None]

    # Act (When)
    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}/approve", headers=bearer(USER_ID, "Venue Staff"), json={"reviewedBy": USER_ID}
    )

    # Assert (Then)
    assert response.status_code == 404
    assert_no_booking_intent(cursor)


def test_reject_booking_needs_no_conflict_check(setup):
    """
    Summary: Rejecting needs no conflict check.
    SCRUM-29 AC3: Given Venue Staff determine that a pending venue booking
        request cannot be accepted, when they reject the request, then the
        booking decision is recorded as rejected and the outcome is available
        to the relevant Event Coordinator.
    Double: Stub (cursor), Mock (no overlap query)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [
        booking_row(),
        booking_row(status="Rejected", reviewed_by=USER_ID),
    ]

    # Act (When)
    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}/reject", headers=bearer(USER_ID, "Venue Staff"),
        # SCRUM-29 AC4: a reject now carries a reason.
        json={"reviewedBy": USER_ID, "rejectionReason": "Venue unsuitable"},
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Rejected"


def test_decide_cancelled_booking_returns_409_without_alert(setup):
    """
    Summary: A cancelled booking can be neither approved nor rejected.
    SCRUM-29 AC5: Given Venue Staff have recorded an approval or rejection for
        a pending venue booking request, when the decision is completed, then
        the request is no longer presented as awaiting a booking decision.
    Double: Stub (cursor returns a Cancelled row)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = booking_row(status="Cancelled")

    approve = client.patch(
        f"/venue-bookings/{BOOKING_ID}/approve", headers=bearer(USER_ID, "Venue Staff"), json={"reviewedBy": USER_ID}
    )

    # Act (When)
    reject = client.patch(
        f"/venue-bookings/{BOOKING_ID}/reject", headers=bearer(USER_ID, "Venue Staff"),
        # SCRUM-29 AC4: a reject now carries a reason.
        json={"reviewedBy": USER_ID, "rejectionReason": "Venue unsuitable"},
    )

    # Assert (Then)
    assert approve.status_code == 409
    assert reject.status_code == 409
    assert "cannot be reviewed" in approve.json["message"]
    assert_no_booking_intent(cursor)


def test_list_bookings_for_venue_returns_its_bookings(setup):
    """
    Summary: A venue's bookings can be listed.
    AC3: Given multiple venue bookings exist for an event, when the Event
        Coordinator views the event, then each booking is displayed separately
        while remaining associated with the same event.
    Double: Stub (cursor returns rows)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = [booking_row()]

    # Act (When)
    response = client.get(
        f"/venue-bookings?venueId={VENUE_ID}&dateFrom=2026-10-01T00:00&dateTo=2026-10-02T00:00",
        headers=bearer(USER_ID, "Venue Staff"),
    )

    # Assert (Then)
    assert response.status_code == 200
    assert len(response.json["bookings"]) == 1


def test_list_event_bookings_returns_each_booking_separately(setup):
    """
    Summary: Each of an event's bookings is listed separately.
    AC3: Given multiple venue bookings exist for an event, when the Event
        Coordinator views the event, then each booking is displayed separately
        while remaining associated with the same event.
    Double: Stub (cursor returns two bookings)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = [
        booking_row(),
        booking_row(
            booking_id="00000000-0000-0000-0000-00000000000c",
            venue_id="00000000-0000-0000-0000-0000000000f2",
            required_capacity=50,
            venue_requirements="Breakout layout",
        ),
    ]

    # Act (When)
    response = client.get(f"/events/{EVENT_ID}/venue-bookings")

    # Assert (Then)
    assert response.status_code == 200
    assert [booking["requiredCapacity"] for booking in response.json["bookings"]] == [80, 50]
    query, params = cursor.execute.call_args.args
    assert "WHERE event_id = %s" in query
    assert params == [EVENT_ID]


def test_edit_booking_changes_only_that_booking_and_resets_review(setup):
    """
    Summary: Editing a booking changes only that one and sends it back for review.
    SCRUM-157 AC1: Given an event has one or more venue bookings, when the
        Event Coordinator modifies a specific booking, then only that selected
        booking is updated.
    SCRUM-157 AC4: Cancelling or modifying one venue booking does not
        automatically change the status of the event's other venue bookings.
    Double: Stub (cursor; SQL inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [
        booking_row(status="Approved", reviewed_by=USER_ID),
        booking_row(
            required_capacity=50,
            venue_requirements="Revised breakout layout",
            status="Pending Review",
            reviewed_by=None,
        ),
    ]

    # Act (When)
    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}",
        json={
            "eventId": EVENT_ID,
            "venueId": VENUE_ID,
            "requestedStartTime": "2026-10-01T10:00",
            "requestedEndTime": "2026-10-01T13:00",
            "requiredCapacity": 50,
            "venueRequirements": "Revised breakout layout",
        },
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Pending Review"
    assert response.json["reviewedBy"] is None
    update_query, update_params = cursor.execute.call_args_list[-1].args
    assert "WHERE booking_id = %s AND event_id = %s" in update_query
    assert "reviewed_by = NULL" in update_query
    assert update_params[-2:] == [BOOKING_ID, EVENT_ID]
    conflict_query, conflict_params = cursor.execute.call_args_list[-2].args
    assert "booking_id <> %s" in conflict_query
    assert BOOKING_ID in conflict_params


def test_edit_booking_rechecks_conflicts_for_only_that_booking(setup):
    """
    Summary: An edit re-checks conflicts for that booking only.
    SCRUM-157 AC2: If a modification changes the venue, date/time, required
        capacity, or other suitability requirements, then suitability,
        availability, and conflict checks are performed again for that booking
        only.
    Double: Stub (cursor; SQL inspected)
    """
    client, cursor = setup
    cursor.fetchone.side_effect = [booking_row()]
    cursor.fetchall.return_value = [{"conflict_type": "APPROVED_BOOKING"}]

    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}",
        json={
            "eventId": EVENT_ID,
            "venueId": VENUE_ID,
            "requestedStartTime": "2026-10-01T10:00",
            "requestedEndTime": "2026-10-01T13:00",
            "requiredCapacity": 50,
            "venueRequirements": "Breakout layout",
        },
    )

    assert response.status_code == 409


def test_edit_cancelled_booking_returns_409(setup):
    """
    Summary: A cancelled booking cannot be edited.
    SCRUM-157 AC5: A cancelled booking remains associated with the event with a
        Cancelled status for record keeping.
    Double: Stub (cursor returns a Cancelled row)
    """
    client, cursor = setup
    cursor.fetchone.return_value = booking_row(status="Cancelled")

    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}",
        json={
            "eventId": EVENT_ID,
            "venueId": VENUE_ID,
            "requestedStartTime": "2026-10-01T10:00",
            "requestedEndTime": "2026-10-01T13:00",
            "requiredCapacity": 50,
            "venueRequirements": "Breakout layout",
        },
    )

    assert response.status_code == 409
    assert "cannot be modified" in response.json["message"]


def test_cancel_booking_keeps_row_as_cancelled(setup):
    """
    Summary: A cancelled booking stays with the event, marked Cancelled.
    SCRUM-157 AC3: Given an event has multiple venue bookings, when the Event
        Coordinator cancels one booking, then only the selected booking is
        cancelled and the other bookings remain unchanged.
    SCRUM-157 AC5: A cancelled booking remains associated with the event with a
        Cancelled status for record keeping.
    Double: Stub (cursor; SQL inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [
        booking_row(status="Approved", reviewed_by=USER_ID),
        booking_row(status="Cancelled", reviewed_by=USER_ID),
    ]

    # Act (When)
    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}/cancel", json={"eventId": EVENT_ID}
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["eventId"] == EVENT_ID
    assert response.json["status"] == "Cancelled"
    update_query, update_params = cursor.execute.call_args_list[-1].args
    assert "SET status = 'Cancelled'" in update_query
    assert "WHERE booking_id = %s AND event_id = %s" in update_query
    assert update_params == [BOOKING_ID, EVENT_ID]


def test_cancel_booking_twice_has_same_result(setup):
    """
    Summary: Cancelling twice has the same result as once.
    SCRUM-157 AC3: Given an event has multiple venue bookings, when the Event
        Coordinator cancels one booking, then only the selected booking is
        cancelled and the other bookings remain unchanged.
    Double: Stub (cursor returns a Cancelled row)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = booking_row(status="Cancelled")

    # Act (When)
    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}/cancel", json={"eventId": EVENT_ID}
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Cancelled"
    assert cursor.execute.call_count == 2


def test_edit_or_cancel_booking_of_other_event_returns_404(setup):
    """
    Summary: A booking can only be changed through its own event.
    SCRUM-157 AC1: Given an event has one or more venue bookings, when the
        Event Coordinator modifies a specific booking, then only that selected
        booking is updated.
    Double: Stub (cursor finds none for the event)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = None
    details = {
        "eventId": EVENT_ID,
        "venueId": VENUE_ID,
        "requestedStartTime": "2026-10-01T10:00",
        "requestedEndTime": "2026-10-01T13:00",
        "requiredCapacity": 50,
        "venueRequirements": "Breakout layout",
    }

    # Act + Assert (When / Then)
    assert client.patch(f"/venue-bookings/{BOOKING_ID}", json=details).status_code == 404
    assert client.patch(
        f"/venue-bookings/{BOOKING_ID}/cancel", json={"eventId": EVENT_ID}
    ).status_code == 404


def test_edit_booking_with_invalid_field_returns_400(setup):
    """
    Summary: Each editable field is validated.
    SCRUM-157 AC2: If a modification changes the venue, date/time, required
        capacity, or other suitability requirements, then suitability,
        availability, and conflict checks are performed again for that booking
        only.
    Double: None
    """
    client, _ = setup
    valid = {
        "eventId": EVENT_ID,
        "venueId": VENUE_ID,
        "requestedStartTime": "2026-10-01T10:00",
        "requestedEndTime": "2026-10-01T13:00",
        "requiredCapacity": 50,
        "venueRequirements": "Breakout layout",
    }
    invalid_payloads = [
        [],
        valid | {"eventId": "invalid"},
        valid | {"requestedEndTime": "2026-10-01T09:00"},
        valid | {"requiredCapacity": 0},
        valid | {"venueRequirements": None},
    ]

    for payload in invalid_payloads:
        response = client.patch(f"/venue-bookings/{BOOKING_ID}", json=payload)
        assert response.status_code == 400


def test_cancel_booking_without_event_id_returns_400(setup):
    """
    Summary: A cancellation must name the event.
    SCRUM-157 AC3: Given an event has multiple venue bookings, when the Event
        Coordinator cancels one booking, then only the selected booking is
        cancelled and the other bookings remain unchanged.
    Double: None
    """
    # Arrange (Given)
    client, _ = setup

    # Act + Assert (When / Then)
    assert client.patch(
        f"/venue-bookings/{BOOKING_ID}/cancel", json={}
    ).status_code == 400


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_health_when_called_returns_ok():
    """
    Summary: Anyone can check the service is up.
    Supporting design check: /health answers without a token
    Double: None
    """
    client = signed_in(create_app().test_client())
    response = client.get("/health")
    assert response.status_code == 200


def test_safety_reset_when_database_url_missing_returns_503(setup):
    """
    Summary: A reset reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured service answers 503
    Double: None
    """
    client, _ = setup
    client.application.config.update(INTERNAL_SERVICE_TOKEN="test-token", DATABASE_URL=None)
    assert client.post(f"/events/{EVENT_ID}/venue-bookings/safety-reset",
        headers={"X-Internal-Token": "test-token", **bearer(USER_ID, "Safety Officer")}, json={"bookingIds": [BOOKING_ID]}).status_code == 503


def test_edit_or_cancel_when_database_url_missing_returns_503():
    """
    Summary: Editing or cancelling reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured service answers 503
    Double: None
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client())
    details = {
        "eventId": EVENT_ID,
        "venueId": VENUE_ID,
        "requestedStartTime": "2026-10-01T10:00",
        "requestedEndTime": "2026-10-01T13:00",
        "requiredCapacity": 50,
        "venueRequirements": "Breakout layout",
    }

    assert client.patch(f"/venue-bookings/{BOOKING_ID}", json=details).status_code == 503
    assert client.patch(
        f"/venue-bookings/{BOOKING_ID}/cancel", json={"eventId": EVENT_ID}
    ).status_code == 503
