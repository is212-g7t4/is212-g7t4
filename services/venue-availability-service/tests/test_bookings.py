"""Venue Availability: booking creation, approval/rejection, and conflict-checking."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from app import create_app

EVENT_ID = "00000000-0000-0000-0000-0000000000e1"
VENUE_ID = "00000000-0000-0000-0000-0000000000f1"
USER_ID = "00000000-0000-0000-0000-000000000001"
BOOKING_ID = "00000000-0000-0000-0000-00000000000b"


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), cursor


def booking_row(**overrides):
    row = {
        "booking_id": BOOKING_ID,
        "event_id": EVENT_ID,
        "venue_id": VENUE_ID,
        "requested_start_time": datetime(2026, 10, 1, 9),
        "requested_end_time": datetime(2026, 10, 1, 12),
        "status": "Pending Review",
        "requested_by": USER_ID,
        "reviewed_by": None,
    }
    row.update(overrides)
    return row


def test_health():
    client = create_app().test_client()
    response = client.get("/health")
    assert response.status_code == 200


def test_create_booking_succeeds_when_no_conflict(setup):
    client, cursor = setup
    cursor.fetchone.side_effect = [None, booking_row()]

    response = client.post(
        "/venue-bookings",
        json={
            "eventId": EVENT_ID,
            "venueId": VENUE_ID,
            "requestedStartTime": "2026-10-01T09:00",
            "requestedEndTime": "2026-10-01T12:00",
            "requestedBy": USER_ID,
        },
    )

    assert response.status_code == 201
    assert response.json["status"] == "Pending Review"
    assert response.json["eventId"] == EVENT_ID


def test_create_booking_rejects_overlap_with_approved_booking(setup):
    client, cursor = setup
    cursor.fetchone.side_effect = [{"booking_id": BOOKING_ID}]

    response = client.post(
        "/venue-bookings",
        json={
            "eventId": EVENT_ID,
            "venueId": VENUE_ID,
            "requestedStartTime": "2026-10-01T09:00",
            "requestedEndTime": "2026-10-01T12:00",
            "requestedBy": USER_ID,
        },
    )

    assert response.status_code == 409


def test_create_booking_requires_end_after_start(setup):
    client, _ = setup
    response = client.post(
        "/venue-bookings",
        json={
            "eventId": EVENT_ID,
            "venueId": VENUE_ID,
            "requestedStartTime": "2026-10-01T12:00",
            "requestedEndTime": "2026-10-01T09:00",
            "requestedBy": USER_ID,
        },
    )
    assert response.status_code == 400


def test_approve_booking_succeeds_when_no_conflict(setup):
    client, cursor = setup
    cursor.fetchone.side_effect = [
        booking_row(),
        None,
        booking_row(status="Approved", reviewed_by=USER_ID),
    ]

    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}/approve", json={"reviewedBy": USER_ID}
    )

    assert response.status_code == 200
    assert response.json["status"] == "Approved"


def test_approve_booking_rejects_when_now_conflicting(setup):
    client, cursor = setup
    cursor.fetchone.side_effect = [booking_row(), {"booking_id": "other"}]

    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}/approve", json={"reviewedBy": USER_ID}
    )

    assert response.status_code == 409


def test_approve_booking_missing_returns_404(setup):
    client, cursor = setup
    cursor.fetchone.side_effect = [None]

    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}/approve", json={"reviewedBy": USER_ID}
    )

    assert response.status_code == 404


def test_reject_booking_does_not_recheck_conflicts(setup):
    client, cursor = setup
    cursor.fetchone.side_effect = [
        booking_row(),
        booking_row(status="Rejected", reviewed_by=USER_ID),
    ]

    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}/reject", json={"reviewedBy": USER_ID}
    )

    assert response.status_code == 200
    assert response.json["status"] == "Rejected"


def test_get_bookings_lists_for_venue(setup):
    client, cursor = setup
    cursor.fetchall.return_value = [booking_row()]

    response = client.get(f"/venue-bookings?venueId={VENUE_ID}")

    assert response.status_code == 200
    assert len(response.json["bookings"]) == 1
