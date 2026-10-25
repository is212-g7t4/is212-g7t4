"""SCRUM-28 Part B: an edited venue request rejoins the Venue Staff queue in order.

Decided by Clarice on 25 Oct: an edited booking goes back to Pending Review
for Venue Staff to re-review (and, for a Confirmed event, its safety approval
is withdrawn by Safety Check Service). This atomic's part is to restamp
`requested_at`, so the staff queue (oldest submission first, SCRUM-28 AC4)
places the edited request by when it was changed. The behaviour against real
SQL is in tests/integration/test_booking_change_safety_withdrawal.py.
"""

from datetime import datetime

from app.calendar import SINGAPORE
from tests.unit.factories import BOOKING_ID, EVENT_ID, USER_ID, VENUE_ID, booking_row


def test_edit_restamps_requested_at_with_database_now(setup):
    """Normal: the UPDATE that resets the booking to Pending Review also sets requested_at = now()."""
    client, cursor = setup
    cursor.fetchone.side_effect = [booking_row(status="Approved", reviewed_by=USER_ID), booking_row()]
    cursor.fetchall.return_value = []

    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}",
        json={
            "eventId": EVENT_ID,
            "venueId": VENUE_ID,
            "requestedStartTime": "2026-10-01T09:00",
            "requestedEndTime": "2026-10-01T12:00",
            "requiredCapacity": 80,
            "venueRequirements": "Projector",
        },
    )

    assert response.status_code == 200
    update = next(call.args[0] for call in cursor.execute.call_args_list if "UPDATE public" in call.args[0])
    assert "status = 'Pending Review'" in update
    assert "requested_at = now()" in update


def test_edit_sends_singapore_aware_times_and_returns_local_ones(setup):
    """Regression: naive times would be read as UTC by Postgres, shifting the booking 8 hours."""
    client, cursor = setup
    cursor.fetchone.side_effect = [booking_row(), booking_row()]
    cursor.fetchall.return_value = []

    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}",
        json={
            "eventId": EVENT_ID,
            "venueId": VENUE_ID,
            "requestedStartTime": "2026-10-01T09:00",
            "requestedEndTime": "2026-10-01T12:00",
            "requiredCapacity": 80,
            "venueRequirements": "Projector",
        },
    )

    params = next(call.args[1] for call in cursor.execute.call_args_list if "UPDATE public" in call.args[0])
    assert params[1] == datetime(2026, 10, 1, 9, tzinfo=SINGAPORE)
    assert params[2] == datetime(2026, 10, 1, 12, tzinfo=SINGAPORE)
    assert response.json["requestedStartTime"] == "2026-10-01T09:00:00"
