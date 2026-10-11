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


def test_cancelled_booking_cannot_be_approved_or_rejected(setup):
    client, cursor = setup
    cursor.fetchone.return_value = booking_row(status="Cancelled")

    approve = client.patch(
        f"/venue-bookings/{BOOKING_ID}/approve", json={"reviewedBy": USER_ID}
    )
    reject = client.patch(
        f"/venue-bookings/{BOOKING_ID}/reject", json={"reviewedBy": USER_ID}
    )

    assert approve.status_code == 409
    assert reject.status_code == 409
    assert "cannot be reviewed" in approve.json["message"]


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


def test_update_booking_changes_only_selected_row_and_resets_review(setup):
    client, cursor = setup
    cursor.fetchone.side_effect = [
        booking_row(status="Approved", reviewed_by=USER_ID),
        None,
        booking_row(
            required_capacity=50,
            venue_requirements="Revised breakout layout",
            status="Pending Review",
            reviewed_by=None,
        ),
    ]

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


def test_update_booking_rechecks_conflicts_for_only_that_booking(setup):
    client, cursor = setup
    cursor.fetchone.side_effect = [booking_row(), {"booking_id": "other"}]

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


def test_cancelled_booking_cannot_be_modified(setup):
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


def test_cancel_booking_retains_row_with_cancelled_status(setup):
    client, cursor = setup
    cursor.fetchone.side_effect = [
        booking_row(status="Approved", reviewed_by=USER_ID),
        booking_row(status="Cancelled", reviewed_by=USER_ID),
    ]

    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}/cancel", json={"eventId": EVENT_ID}
    )

    assert response.status_code == 200
    assert response.json["eventId"] == EVENT_ID
    assert response.json["status"] == "Cancelled"
    update_query, update_params = cursor.execute.call_args_list[-1].args
    assert "SET status = 'Cancelled'" in update_query
    assert "WHERE booking_id = %s AND event_id = %s" in update_query
    assert update_params == [BOOKING_ID, EVENT_ID]


def test_cancel_booking_is_idempotent(setup):
    client, cursor = setup
    cursor.fetchone.return_value = booking_row(status="Cancelled")

    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}/cancel", json={"eventId": EVENT_ID}
    )

    assert response.status_code == 200
    assert response.json["status"] == "Cancelled"
    assert cursor.execute.call_count == 1


def test_update_and_cancel_require_booking_to_belong_to_event(setup):
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

    assert client.patch(f"/venue-bookings/{BOOKING_ID}", json=details).status_code == 404
    assert client.patch(
        f"/venue-bookings/{BOOKING_ID}/cancel", json={"eventId": EVENT_ID}
    ).status_code == 404


def test_update_booking_validates_each_mutable_field(setup):
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


def test_update_and_cancel_report_missing_database_configuration():
    client = create_app({"TESTING": True, "DATABASE_URL": None}).test_client()
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


def test_cancel_requires_event_id(setup):
    client, _ = setup
    assert client.patch(
        f"/venue-bookings/{BOOKING_ID}/cancel", json={}
    ).status_code == 400

