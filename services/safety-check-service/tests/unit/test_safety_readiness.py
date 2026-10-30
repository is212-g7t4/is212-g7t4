"""
SCRUM-149: Submit Event for Operational Safety Check

User Story
----------
As an Event Coordinator, I want to submit my event for an Operational Safety
Check once its venue and technical arrangements are confirmed, so that the
Safety Officer can review it before preparation begins.

Acceptance Criteria
-------------------
AC1: Given an event assigned to the Event Coordinator has at least one approved
     venue booking, and none of its venue bookings or equipment requests is
     still pending, when the Event Coordinator submits it for a safety check,
     then its status changes to 'Pending Safety Check' and the submission time
     is recorded. Rejected, cancelled or expired venue bookings and rejected
     equipment requests are no longer part of the event's arrangements and do
     not block submission.
AC2: Given any venue booking or equipment request for the event is still
     pending, or the event has no approved venue booking, when the Event
     Coordinator tries to submit, then submission is blocked and the
     outstanding arrangements are listed.
AC3: Given the Event Coordinator is submitting, when they enter equipment
     placement and expected crowd movement notes, then the notes are saved with
     the safety check.
AC4: Given the event is already 'Pending Safety Check', when the Event
     Coordinator submits it again, then no duplicate safety check is created.
AC5: Given the Event Coordinator is not the assigned coordinator, then the
     submit action is not available and an API call is rejected.

Real
----
- app.readiness: which bookings and equipment requests are still outstanding
  (approved, rejected, cancelled, expired, unknown statuses), the stable order
  of the list and its labels.
- Assertions are on whether the event is ready and what is listed.

Doubled
-------
- Nothing: pure logic over booking and request rows built in the test.

Not proven
----------
- That the rows match what the atomics return (-> test_safety_submit.py and
  tests/integration/).
"""
import pytest

from app.readiness import booking_label, outstanding_arrangements
from tests.unit.factories import BOOKING_ID, REQUEST_ID, booking, equipment_request

OTHER_BOOKING_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER_REQUEST_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


# --- AC1: ready --------------------------------------------------------------


def test_readiness_with_approved_booking_and_no_equipment_is_ready():
    """
    Summary: An approved booking and no equipment is ready.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: None
    """
    # Act + Assert (When / Then)
    assert outstanding_arrangements([booking("Approved")], []) == []


def test_readiness_with_everything_approved_is_ready():
    """
    Summary: Every booking and request approved is ready.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: None
    """
    # Act + Assert (When / Then)
    assert (
        outstanding_arrangements(
            [booking("Approved"), booking("Approved", OTHER_BOOKING_ID)],
            [equipment_request("Approved"), equipment_request("Reserved", OTHER_REQUEST_ID)],
        )
        == []
    )


def test_readiness_ignores_cancelled_and_expired_bookings():
    """
    Summary: Cancelled or lapsed bookings no longer count.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: None
    """
    # Act + Assert (When / Then)
    assert (
        outstanding_arrangements(
            [
                booking("Cancelled", OTHER_BOOKING_ID),
                booking("Expired", "cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
                booking("Approved"),
            ],
            [],
        )
        == []
    )


def test_readiness_ignores_cancelled_equipment_request():
    """
    Summary: A cancelled equipment request no longer counts.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: None
    """
    # Act + Assert (When / Then)
    assert (
        outstanding_arrangements(
            [booking("Approved")], [equipment_request("Cancelled")]
        )
        == []
    )


# --- AC2: outstanding --------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        ("Pending Review", "Waiting for Venue Staff approval."),
        ("Pending", "Waiting for Venue Staff approval."),
    ],
)
def test_readiness_lists_pending_booking_with_reason(status, reason):
    """
    Summary: A pending booking blocks and says why.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: None
    """
    # Arrange (Given): status, reason, from fixtures

    # Act (When)
    outstanding = outstanding_arrangements([booking(status)], [])

    # Assert (Then)
    assert outstanding == [
        {
            "type": "venue",
            "id": BOOKING_ID,
            "status": status,
            "label": "Booking 12 Nov 2026 09:00–17:00 (120 people)",
            "reason": reason,
        }
    ]


def test_readiness_lists_pending_equipment_with_reason():
    """
    Summary: A pending equipment request blocks and says why.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: None
    """
    # Act (When)
    outstanding = outstanding_arrangements(
        [booking("Approved")], [equipment_request("Pending")]
    )

    # Assert (Then)
    assert outstanding == [
        {
            "type": "equipment",
            "id": REQUEST_ID,
            "status": "Pending",
            "label": "Equipment request × 2",
            "reason": "Waiting for Technical Support approval.",
        }
    ]


def test_readiness_ignores_rejected_equipment_request():
    """
    Summary: A rejected equipment request no longer blocks.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: None
    """
    # Act + Assert (When / Then)
    assert (
        outstanding_arrangements(
            [booking("Approved")], [equipment_request("Rejected")]
        )
        == []
    )


def test_readiness_with_rejected_and_approved_equipment_is_ready():
    """
    Summary: An approved request counts and a rejected one is ignored.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: None
    """
    # Act + Assert (When / Then)
    assert (
        outstanding_arrangements(
            [booking("Approved")],
            [
                equipment_request("Approved"),
                equipment_request("Rejected", OTHER_REQUEST_ID),
            ],
        )
        == []
    )


def test_readiness_with_pending_and_rejected_equipment_still_blocks():
    """
    Summary: A pending request still blocks beside a rejected one.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: None
    """
    # Act (When)
    outstanding = outstanding_arrangements(
        [booking("Approved")],
        [
            equipment_request("Rejected"),
            equipment_request("Pending", OTHER_REQUEST_ID),
        ],
    )

    # Assert (Then)
    assert outstanding == [
        {
            "type": "equipment",
            "id": OTHER_REQUEST_ID,
            "status": "Pending",
            "label": "Equipment request × 2",
            "reason": "Waiting for Technical Support approval.",
        }
    ]


def test_readiness_without_live_venue_lists_only_missing_booking():
    """
    Summary: Without a live venue, only the missing booking is listed.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: None
    """
    # Act (When)
    outstanding = outstanding_arrangements(
        [booking("Rejected")], [equipment_request("Rejected")]
    )

    # Assert (Then)
    assert [item["label"] for item in outstanding] == ["No venue booking"]


def test_readiness_with_one_pending_booking_among_several_blocks():
    """
    Summary: One pending booking among several blocks the event.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: None
    """
    # Act (When)
    outstanding = outstanding_arrangements(
        [booking("Approved"), booking("Pending Review", OTHER_BOOKING_ID)], []
    )

    # Assert (Then)
    assert [item["id"] for item in outstanding] == [OTHER_BOOKING_ID]


def test_readiness_lists_venues_before_equipment():
    """
    Summary: Outstanding venues are listed before equipment.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: None
    """
    # Act (When)
    outstanding = outstanding_arrangements(
        [booking("Pending Review")], [equipment_request("Pending")]
    )

    # Assert (Then)
    assert [item["type"] for item in outstanding] == ["venue", "equipment"]


def test_readiness_lists_every_outstanding_arrangement():
    """
    Summary: Every outstanding arrangement is listed, not just the first.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: None
    """
    # Act (When)
    outstanding = outstanding_arrangements(
        [booking("Pending Review"), booking("Pending", OTHER_BOOKING_ID)],
        [
            equipment_request("Pending"),
            equipment_request("Pending", OTHER_REQUEST_ID),
        ],
    )

    # Assert (Then)
    assert len(outstanding) == 4
    assert [item["id"] for item in outstanding] == [
        BOOKING_ID,
        OTHER_BOOKING_ID,
        REQUEST_ID,
        OTHER_REQUEST_ID,
    ]


# --- No venue booking at all -------------------------------------------------


@pytest.mark.parametrize(
    "bookings",
    [[], None, [booking("Cancelled")], [booking("Rejected")], [booking("Cancelled"), booking("Expired")]],
    ids=["empty", "none", "booking_cancelled", "booking_rejected", "booking_cancelled_booking_expired"],
)
def test_readiness_without_live_booking_is_blocked(bookings):
    """
    Summary: An event with no live venue booking is not ready.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: None
    """
    # Arrange (Given): bookings, from fixtures

    # Act (When)
    outstanding = outstanding_arrangements(bookings, [])

    # Assert (Then)
    assert outstanding == [
        {
            "type": "venue",
            "id": None,
            "status": None,
            "label": "No venue booking",
            "reason": "No venue booking has been made for this event.",
        }
    ]


def test_readiness_without_equipment_lists_nothing_for_it():
    """
    Summary: Having no equipment requests is not an outstanding item.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: None
    """
    # Act + Assert (When / Then)
    assert outstanding_arrangements([booking("Approved")], None) == []


# --- Fail closed -------------------------------------------------------------


@pytest.mark.parametrize("status", ["On Hold", "approved", "Something New", "", None])
def test_readiness_treats_unknown_booking_status_as_outstanding(status):
    """
    Summary: A booking status it cannot interpret counts as outstanding.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: None
    """
    # Arrange (Given): status, from fixtures

    # Act (When)
    outstanding = outstanding_arrangements([booking(status)], [])

    # Assert (Then)
    assert len(outstanding) == 1
    assert outstanding[0]["reason"] == (
        f"Status '{status}' isn't recognised, so it can't be treated as approved."
    )


@pytest.mark.parametrize("status", ["approved", "Allocated", None])
def test_readiness_treats_unknown_equipment_status_as_outstanding(status):
    """
    Summary: An equipment status it cannot interpret counts as outstanding.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: None
    """
    # Arrange (Given): status, from fixtures

    # Act (When)
    outstanding = outstanding_arrangements(
        [booking("Approved")], [equipment_request(status)]
    )

    # Assert (Then)
    assert len(outstanding) == 1
    assert outstanding[0]["type"] == "equipment"
    assert "isn't recognised" in outstanding[0]["reason"]


def test_readiness_treats_booking_without_status_as_outstanding():
    """
    Summary: A booking without a status counts as outstanding.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: None
    """
    # Act (When)
    outstanding = outstanding_arrangements([{"id": BOOKING_ID}], [])

    # Assert (Then)
    assert len(outstanding) == 1
    assert outstanding[0]["id"] == BOOKING_ID


# --- Labels ------------------------------------------------------------------


def test_readiness_label_shows_multi_day_window():
    """
    Summary: A multi-day booking's label shows its whole period.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: None
    """
    # Act (When)
    label = booking_label(
        booking(
            "Pending",
            requestedStartTime="2026-11-12T09:00:00",
            requestedEndTime="2026-11-14T17:00:00",
        )
    )

    # Assert (Then)
    assert label == "Booking 12 Nov 2026 09:00–14 Nov 2026 17:00 (120 people)"


def test_readiness_label_with_bad_times_falls_back():
    """
    Summary: A label with unreadable times still reads sensibly.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: None
    """
    # Act (When)
    label = booking_label(
        booking("Pending", requestedStartTime="soon", requestedEndTime="later")
    )

    # Assert (Then)
    assert label == "Booking soon later (120 people)"


def test_readiness_label_without_times_or_capacity_is_readable():
    """
    Summary: A label without times or capacity is still readable.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: None
    """
    # Act + Assert (When / Then)
    assert booking_label({"id": BOOKING_ID}) == "Booking"


def test_readiness_equipment_label_without_quantity():
    """
    Summary: An equipment label without a quantity is still readable.
    AC2: Given any venue booking or equipment request for the event is still
        pending, or the event has no approved venue booking, when the Event
        Coordinator tries to submit, then submission is blocked and the
        outstanding arrangements are listed.
    Double: None
    """
    # Act (When)
    outstanding = outstanding_arrangements(
        [booking("Approved")], [{"id": REQUEST_ID, "status": "Pending"}]
    )

    # Assert (Then)
    assert outstanding[0]["label"] == "Equipment request"
