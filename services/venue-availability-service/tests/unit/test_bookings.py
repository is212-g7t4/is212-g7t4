"""Venue Availability: booking creation, approval/rejection, and conflict-checking."""

from datetime import datetime

from app import create_app
from app.models import _has_conflict
from tests.unit.factories import (
    BOOKING_ID,
    EVENT_ID,
    USER_ID,
    VENUE_ID,
    booking_row,
)


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
            "requiredCapacity": 80,
            "venueRequirements": "Projector and movable seating",
            "requestedBy": USER_ID,
        },
    )

    assert response.status_code == 201
    assert response.json["status"] == "Pending Review"
    assert response.json["eventId"] == EVENT_ID
    assert response.json["requiredCapacity"] == 80
    assert response.json["venueRequirements"] == "Projector and movable seating"


def test_conflicts_are_scoped_to_venue_and_time_not_event(setup):
    """AC6: another venue may overlap even when both bookings share an event."""
    _, cursor = setup
    cursor.fetchone.return_value = None

    assert not _has_conflict(
        cursor, VENUE_ID, datetime(2026, 10, 1, 9), datetime(2026, 10, 1, 12)
    )

    query, params = cursor.execute.call_args.args
    assert "WHERE venue_id = %s" in query
    assert "event_id" not in query
    assert params[0] == VENUE_ID


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
            "requiredCapacity": 80,
            "venueRequirements": "",
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
            "requiredCapacity": 80,
            "venueRequirements": "",
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

    client.application.config["CALENDAR_DEV_MODE"] = True
    response = client.get(
        f"/venue-bookings?venueId={VENUE_ID}&dateFrom=2026-10-01T00:00&dateTo=2026-10-02T00:00",
        headers={"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Venue Staff"},
    )

    assert response.status_code == 200
    assert len(response.json["bookings"]) == 1


def test_get_event_bookings_lists_each_booking_separately(setup):
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

    response = client.get(f"/events/{EVENT_ID}/venue-bookings")

    assert response.status_code == 200
    assert [booking["requiredCapacity"] for booking in response.json["bookings"]] == [80, 50]
    query, params = cursor.execute.call_args.args
    assert "WHERE event_id = %s" in query
    assert params == [EVENT_ID]

