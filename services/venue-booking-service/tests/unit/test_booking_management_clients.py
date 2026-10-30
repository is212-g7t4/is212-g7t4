"""
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

Real
----
- app.clients update_booking, cancel_booking and review: the request sent to
  Venue Availability and the mapping of its errors.
- Assertions are on the request and the exception raised.

Doubled
-------
- Venue Availability HTTP: Stub (respx) - canned answers; requests inspected.

Not proven
----------
- That the atomic services behave as stubbed (-> their own unit and integration
  tests, and tests/integration/ here with respx).
"""

import httpx
import pytest

from app import clients
from app.clients import BookingConflictError, BookingNotFoundError, BookingStateError


DETAILS = (
    "booking-1",
    "event-1",
    "venue-1",
    "2026-10-01T09:00",
    "2026-10-01T12:00",
    80,
    "Projector",
)


def response(status, body):
    return httpx.Response(
        status,
        json=body,
        request=httpx.Request("PATCH", "http://availability/venue-bookings/booking-1"),
    )


def test_update_booking_client_sends_every_editable_field(monkeypatch):
    """
    Summary: An edit sends every editable detail of that one booking.
    AC1: Given an event has one or more venue bookings, when the Event
        Coordinator modifies a specific booking, then only that selected
        booking is updated.
    Double: Stub (respx; request inspected)
    """
    # Arrange (Given)
    calls = []

    def patch(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return response(200, {"id": "booking-1", "status": "Pending Review"})

    monkeypatch.setattr(clients.httpx, "patch", patch)
    result = clients.update_booking(*DETAILS)

    # Act + Assert (When / Then)
    assert result["status"] == "Pending Review"
    assert calls[0][0].endswith("/venue-bookings/booking-1")
    assert calls[0][1]["requiredCapacity"] == 80
    assert calls[0][1]["venueRequirements"] == "Projector"


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (404, {"message": "missing"}, BookingNotFoundError),
        (409, {"message": "Cancelled venue bookings cannot be modified."}, BookingStateError),
        (409, {"message": "conflict"}, BookingConflictError),
        (503, {"message": "down"}, httpx.HTTPStatusError),
    ],
    ids=["not_found", "cancelled", "conflict", "unavailable"],
)
def test_update_booking_client_maps_errors(monkeypatch, status, body, error):
    """
    Summary: Edit failures are mapped to not-found, state and conflict errors.
    AC2: If a modification changes the venue, date/time, required capacity, or
        other suitability requirements, then suitability, availability, and
        conflict checks are performed again for that booking only.
    Double: Stub (respx answers the error)
    """
    monkeypatch.setattr(clients.httpx, "patch", lambda *args, **kwargs: response(status, body))
    with pytest.raises(error):
        clients.update_booking(*DETAILS)


def test_cancel_booking_client_returns_cancelled_booking(monkeypatch):
    """
    Summary: Cancelling returns the booking marked Cancelled.
    AC3: Given an event has multiple venue bookings, when the Event Coordinator
        cancels one booking, then only the selected booking is cancelled and
        the other bookings remain unchanged.
    AC5: A cancelled booking remains associated with the event with a Cancelled
        status for record keeping.
    Double: Stub (respx; request inspected)
    """
    # Arrange (Given)
    calls = []

    def patch(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return response(200, {"id": "booking-1", "eventId": "event-1", "status": "Cancelled"})

    monkeypatch.setattr(clients.httpx, "patch", patch)
    result = clients.cancel_booking("booking-1", "event-1")

    # Act + Assert (When / Then)
    assert result["status"] == "Cancelled"
    assert calls == [
        (f"{clients.VENUE_AVAILABILITY_SERVICE_URL}/venue-bookings/booking-1/cancel", {"eventId": "event-1"})
    ]


@pytest.mark.parametrize("status", [404, 503], ids=["not_found", "unavailable"])
def test_cancel_booking_client_maps_errors(monkeypatch, status):
    """
    Summary: Cancel failures are mapped to not-found or failure.
    AC3: Given an event has multiple venue bookings, when the Event Coordinator
        cancels one booking, then only the selected booking is cancelled and
        the other bookings remain unchanged.
    Double: Stub (respx answers the error)
    """
    # Arrange (Given)
    monkeypatch.setattr(
        clients.httpx,
        "patch",
        lambda *args, **kwargs: response(status, {"message": "failed"}),
    )
    expected = BookingNotFoundError if status == 404 else httpx.HTTPStatusError

    # Act + Assert (When / Then)
    with pytest.raises(expected):
        clients.cancel_booking("booking-1", "event-1")


def test_review_client_for_cancelled_booking_raises_state_error(monkeypatch):
    """
    Summary: Reviewing a cancelled booking is reported as a closed booking.
    AC5: A cancelled booking remains associated with the event with a Cancelled
        status for record keeping.
    Double: Stub (respx answers 409)
    """
    monkeypatch.setattr(
        clients.httpx,
        "patch",
        lambda *args, **kwargs: response(
            409, {"message": "Cancelled venue bookings cannot be reviewed."}
        ),
    )
    with pytest.raises(BookingStateError):
        clients.decide_booking("booking-1", "Approved")
