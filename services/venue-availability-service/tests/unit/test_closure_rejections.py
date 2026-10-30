"""
SCRUM-171: Reject Affected Bookings

User Story
----------
As a Venue Staff, I want the system to automatically reject existing venue
requests when I mark a venue as temporarily unavailable, so that I do not have
to manually reject each affected venue request.

Acceptance Criteria
-------------------
AC1: Given a closure is recorded, then requests for the same venue with
     overlapping booking intervals and status Pending, Pending Review, or
     Approved are changed to Rejected.
AC2: Given a request belongs to another venue, does not overlap the closure, or
     is already rejected or cancelled, then that request is not changed by the
     closure.
AC3: Given a request is rejected because of a closure, when its details are
     viewed, then the closure period and operational reason are displayed.
AC4: Given an affected venue request is rejected, the existing event itself or
     other venue requests under that event are not rejected and remain
     unchanged.

Real
----
- Requests rejected by a closure: immutability of every closure-rejected
  request, the shared write gate taken before row locks by every booking
  writer, and the rejection snapshot in Singapore time.
- Assertions are on the codes returned and the SQL order.

Doubled
-------
- psycopg2.connect: Stub (`setup`/`client` fixtures) - fresh MagicMock
  connection; the cursor returns canned VenueBooking / VenueClosure rows (or
  raises); executed SQL, parameters and locks are inspected.

Not proven
----------
- That the SQL, locks and constraints behave the same on real PostgreSQL (->
  tests/integration/, throwaway postgres:17.6).
"""

import pytest
from datetime import datetime
from app import models
from tests.unit.factories import BOOKING_ID, bearer, EVENT_ID, USER_ID, VENUE_ID, booking_row


@pytest.mark.parametrize("action", ["edit", "cancel", "approve", "reject"], ids=["edit", "cancel", "approve", "reject"])
def test_change_closure_rejected_request_is_refused(setup, action):
    """
    Summary: A request rejected by a closure cannot be edited, cancelled, approved or rejected again.
    AC4: Given an affected venue request is rejected, the existing event itself
        or other venue requests under that event are not rejected and remain
        unchanged.
    Double: Stub (cursor returns a closure-rejected row)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = booking_row(status="Rejected")
    payload = dict(
        eventId=EVENT_ID,
        venueId=VENUE_ID,
        requestedStartTime="2027-10-01T09:00",
        requestedEndTime="2027-10-01T12:00",
        requiredCapacity=80,
        venueRequirements="Projector",
        reviewedBy=USER_ID,
        # SCRUM-29 AC4: a reject now needs a reason to reach the state check.
        rejectionReason="Venue unsuitable",
    )
    suffix = "" if action == "edit" else "/" + action
    # Decisions are Venue Staff's (SCRUM-10); edit and cancel are the coordinator's.
    role = "Venue Staff" if action in ("approve", "reject") else "Event Coordinator"

    # Act (When)
    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}{suffix}", json=payload, headers=bearer(USER_ID, role)
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "BOOKING_IMMUTABLE"
    assert not any(
        "UPDATE public" in call.args[0] for call in cursor.execute.call_args_list
    )


@pytest.mark.parametrize("action", ["create", "update", "cancel", "approve", "hold"], ids=["create", "update", "cancel", "approve", "hold"])
def test_booking_writes_take_shared_gate_before_row_locks(setup, action):
    """
    Summary: Every booking write waits for an in-progress closure, so none slips past it.
    AC1: Given a closure is recorded, then requests for the same venue with
        overlapping booking intervals and status Pending, Pending Review, or
        Approved are changed to Rejected.
    Double: Stub (cursor; SQL order inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = booking_row()

    # Act (When)
    try:
        if action == "create":
            models.create_booking(
                "unused",
                EVENT_ID,
                VENUE_ID,
                datetime(2027, 1, 1),
                datetime(2027, 1, 2),
                10,
                "",
                USER_ID,
            )
        elif action == "update":
            models.update_booking(
                "unused",
                BOOKING_ID,
                EVENT_ID,
                VENUE_ID,
                datetime(2027, 1, 1),
                datetime(2027, 1, 2),
                10,
                "",
            )
        elif action == "cancel":
            models.cancel_booking("unused", BOOKING_ID, EVENT_ID)
        elif action == "approve":
            models.decide_booking("unused", BOOKING_ID, USER_ID, "Approved")
        else:
            models.create_hold("unused", VENUE_ID, datetime(2027, 1, 1), USER_ID)
    except models.HoldConflictError:
        pass

    # Assert (Then)
    assert "pg_advisory_xact_lock" in cursor.execute.call_args_list[0].args[0]


def test_closure_rejected_request_shows_period_and_reason_in_singapore_time():
    """
    Summary: A request rejected by a closure shows the closure period and reason in Singapore time.
    AC3: Given a request is rejected because of a closure, when its details are
        viewed, then the closure period and operational reason are displayed.
    Double: Stub (cursor returns rows with and without the snapshot)
    """
    # Arrange (Given)
    row = booking_row(status="Rejected")

    # Act + Assert (When / Then)
    assert models.serialize(row)["closureRejection"] is None
    row.update(
        rejection_closure_id=BOOKING_ID,
        rejection_closure_start=datetime.fromisoformat("2027-01-01T00:00:00+00:00"),
        rejection_closure_end=datetime.fromisoformat("2027-01-02T00:00:00+00:00"),
        rejection_closure_reason="Maintenance\n<script>plain text</script>",
        rejected_at=datetime.fromisoformat("2026-10-16T00:00:00+00:00"),
    )
    result = models.serialize(models._localize(row))["closureRejection"]
    assert result == dict(
        closureId=BOOKING_ID,
        startDateTime="2027-01-01T08:00:00+08:00",
        endDateTime="2027-01-02T08:00:00+08:00",
        reason=row["rejection_closure_reason"],
        rejectedAt="2026-10-16T08:00:00+08:00",
    )


def test_buffer_reconciliation_takes_shared_gate_before_row_locks(setup):
    """
    Summary: Buffer reconciliation also waits for an in-progress closure.
    AC1: Given a closure is recorded, then requests for the same venue with
        overlapping booking intervals and status Pending, Pending Review, or
        Approved are changed to Rejected.
    Double: Stub (cursor; SQL order inspected)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = []
    models.reconcile_legacy_conflicts("mocked", VENUE_ID, 30, 45)
    statements = [call.args[0] for call in cursor.execute.call_args_list]

    # Act + Assert (When / Then)
    assert "pg_advisory_xact_lock(171, 1)" in statements[0]
    assert "FOR UPDATE" in statements[1]
