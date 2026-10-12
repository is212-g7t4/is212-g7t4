"""SCRUM-149 AC1/AC2: the rule for whether an event's arrangements are approved.

AC1 Given an event ... has every venue booking approved and every equipment
    request approved/reserved (or no equipment requested), when the Event
    Coordinator submits it for a safety check, then its status changes ...
AC2 Given any venue booking or equipment request for the event is still
    pending or rejected, when the Event Coordinator tries to submit, then
    submission is blocked and the outstanding arrangements are listed.

A pure function, so these tests need no HTTP and no app. The rule fails closed:
anything it can't read as approved counts as outstanding.
"""
import pytest

from app.readiness import booking_label, outstanding_arrangements
from tests.unit.factories import BOOKING_ID, REQUEST_ID, booking, equipment_request

OTHER_BOOKING_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER_REQUEST_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


# --- AC1: ready --------------------------------------------------------------


def test_approved_booking_and_no_equipment_is_ready():
    """AC1: "or no equipment requested" — an event may need no equipment."""
    assert outstanding_arrangements([booking("Approved")], []) == []


def test_approved_bookings_and_approved_equipment_are_ready():
    """AC1: every booking and every request approved."""
    assert (
        outstanding_arrangements(
            [booking("Approved"), booking("Approved", OTHER_BOOKING_ID)],
            [equipment_request("Approved"), equipment_request("Reserved", OTHER_REQUEST_ID)],
        )
        == []
    )


def test_cancelled_and_expired_bookings_are_ignored():
    """Boundary: a withdrawn or lapsed booking is one the event no longer relies on.

    Since SCRUM-156 a coordinator can cancel a rejected booking and book
    elsewhere, so these must not keep blocking.
    """
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


def test_cancelled_equipment_request_is_ignored():
    """Future-proofing: no endpoint sets 'Cancelled' on a request today."""
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
        (
            "Rejected",
            "Rejected by Venue Staff. Cancel this booking or book another venue.",
        ),
    ],
)
def test_unapproved_booking_is_listed_with_its_reason(status, reason):
    """AC2: a pending or rejected booking blocks, and says why."""
    outstanding = outstanding_arrangements([booking(status)], [])

    assert outstanding == [
        {
            "type": "venue",
            "id": BOOKING_ID,
            "status": status,
            "label": "Booking 12 Nov 2026 09:00–17:00 (120 people)",
            "reason": reason,
        }
    ]


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        ("Pending", "Waiting for Technical Support approval."),
        ("Rejected", "Rejected by Technical Support."),
    ],
)
def test_unapproved_equipment_request_is_listed_with_its_reason(status, reason):
    """AC2: a pending or rejected equipment request blocks, and says why.

    A rejected request keeps blocking: equipment requests have no withdraw
    path today, unlike venue bookings.
    """
    outstanding = outstanding_arrangements(
        [booking("Approved")], [equipment_request(status)]
    )

    assert outstanding == [
        {
            "type": "equipment",
            "id": REQUEST_ID,
            "status": status,
            "label": "Equipment request × 2",
            "reason": reason,
        }
    ]


def test_one_unapproved_booking_among_several_blocks():
    """AC2 with SCRUM-156's multi-venue events: one pending booking is enough."""
    outstanding = outstanding_arrangements(
        [booking("Approved"), booking("Pending Review", OTHER_BOOKING_ID)], []
    )

    assert [item["id"] for item in outstanding] == [OTHER_BOOKING_ID]


def test_venue_items_come_before_equipment_items():
    """AC2's list is stable: venues first, then equipment, in service order."""
    outstanding = outstanding_arrangements(
        [booking("Pending Review")], [equipment_request("Rejected")]
    )

    assert [item["type"] for item in outstanding] == ["venue", "equipment"]


def test_every_unapproved_arrangement_is_listed():
    """AC2 lists *the* outstanding arrangements, not just the first one."""
    outstanding = outstanding_arrangements(
        [booking("Pending Review"), booking("Rejected", OTHER_BOOKING_ID)],
        [
            equipment_request("Pending"),
            equipment_request("Rejected", OTHER_REQUEST_ID),
        ],
    )

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
    [[], None, [booking("Cancelled")], [booking("Cancelled"), booking("Expired")]],
)
def test_event_without_a_live_booking_is_blocked(bookings):
    """AC1 allows no equipment but never no venue: an event needs somewhere to be.

    Only cancelled or expired bookings means the event has nowhere to happen,
    which reads the same as never having booked.
    """
    outstanding = outstanding_arrangements(bookings, [])

    assert outstanding == [
        {
            "type": "venue",
            "id": None,
            "status": None,
            "label": "No venue booking",
            "reason": "No venue booking has been made for this event.",
        }
    ]


def test_no_equipment_requests_is_not_an_outstanding_item():
    assert outstanding_arrangements([booking("Approved")], None) == []


# --- Fail closed -------------------------------------------------------------


@pytest.mark.parametrize("status", ["On Hold", "approved", "Something New", "", None])
def test_unrecognised_booking_status_is_outstanding(status):
    """Failure case: "couldn't interpret" must never read as "approved"."""
    outstanding = outstanding_arrangements([booking(status)], [])

    assert len(outstanding) == 1
    assert outstanding[0]["reason"] == (
        f"Status '{status}' isn't recognised, so it can't be treated as approved."
    )


@pytest.mark.parametrize("status", ["approved", "Allocated", None])
def test_unrecognised_equipment_status_is_outstanding(status):
    outstanding = outstanding_arrangements(
        [booking("Approved")], [equipment_request(status)]
    )

    assert len(outstanding) == 1
    assert outstanding[0]["type"] == "equipment"
    assert "isn't recognised" in outstanding[0]["reason"]


def test_booking_with_no_status_field_is_outstanding():
    """A malformed row is still a row the rule must not wave through."""
    outstanding = outstanding_arrangements([{"id": BOOKING_ID}], [])

    assert len(outstanding) == 1
    assert outstanding[0]["id"] == BOOKING_ID


# --- Labels ------------------------------------------------------------------


def test_label_shows_a_multi_day_window_in_full():
    label = booking_label(
        booking(
            "Pending",
            requestedStartTime="2026-11-12T09:00:00",
            requestedEndTime="2026-11-14T17:00:00",
        )
    )

    assert label == "Booking 12 Nov 2026 09:00–14 Nov 2026 17:00 (120 people)"


def test_label_falls_back_when_times_are_unparseable():
    """Labels are cosmetic: a malformed time must not break the blocked list."""
    label = booking_label(
        booking("Pending", requestedStartTime="soon", requestedEndTime="later")
    )

    assert label == "Booking soon later (120 people)"


def test_label_without_times_or_capacity_is_still_readable():
    assert booking_label({"id": BOOKING_ID}) == "Booking"


def test_equipment_label_without_a_quantity():
    outstanding = outstanding_arrangements(
        [booking("Approved")], [{"id": REQUEST_ID, "status": "Pending"}]
    )

    assert outstanding[0]["label"] == "Equipment request"
