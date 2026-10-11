"""Client contract tests for modifying and cancelling one venue booking."""

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


def test_update_booking_sends_all_mutable_details(monkeypatch):
    calls = []

    def patch(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return response(200, {"id": "booking-1", "status": "Pending Review"})

    monkeypatch.setattr(clients.httpx, "patch", patch)
    result = clients.update_booking(*DETAILS)

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
)
def test_update_booking_maps_atomic_errors(monkeypatch, status, body, error):
    monkeypatch.setattr(clients.httpx, "patch", lambda *args, **kwargs: response(status, body))
    with pytest.raises(error):
        clients.update_booking(*DETAILS)


def test_cancel_booking_sends_event_and_returns_cancelled_record(monkeypatch):
    calls = []

    def patch(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return response(200, {"id": "booking-1", "eventId": "event-1", "status": "Cancelled"})

    monkeypatch.setattr(clients.httpx, "patch", patch)
    result = clients.cancel_booking("booking-1", "event-1")

    assert result["status"] == "Cancelled"
    assert calls == [
        (f"{clients.VENUE_AVAILABILITY_SERVICE_URL}/venue-bookings/booking-1/cancel", {"eventId": "event-1"})
    ]


@pytest.mark.parametrize("status", [404, 503])
def test_cancel_booking_maps_atomic_errors(monkeypatch, status):
    monkeypatch.setattr(
        clients.httpx,
        "patch",
        lambda *args, **kwargs: response(status, {"message": "failed"}),
    )
    expected = BookingNotFoundError if status == 404 else httpx.HTTPStatusError
    with pytest.raises(expected):
        clients.cancel_booking("booking-1", "event-1")


def test_review_cancelled_booking_maps_terminal_state(monkeypatch):
    monkeypatch.setattr(
        clients.httpx,
        "patch",
        lambda *args, **kwargs: response(
            409, {"message": "Cancelled venue bookings cannot be reviewed."}
        ),
    )
    with pytest.raises(BookingStateError):
        clients.decide_booking("booking-1", "staff-1", "Approved")
