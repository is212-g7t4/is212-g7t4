"""# Test scope and acceptance mapping — SCRUM-171 integration

- **Existing booking-write regression (no direct SCRUM-171 AC):** creation, conflict scope, approval/rejection, single-child edit/cancel, validation and configuration errors. Sibling-preserving CRUD is not closure-time AC2 proof.
- **SCRUM-171 compatibility only:** expected SQL-call ordering accounts for the shared transaction gate; existing response and mutation assertions remain.

## Case/group traceability

The named test functions/cases below implement the groups above; their existing
names and assertions specify the scenario. No group is credited with all five ACs.

## Existing test contract and detailed cases

Venue Availability: booking creation, approval/rejection, and conflict-checking.

SCRUM-47 Venue booking notification and decision alerts (additional assertions only).
Story: As an Event Coordinator and Venue Staff, I want to receive notifications
about venue booking requests and decisions, so that I can coordinate venue
arrangements efficiently.
AC1 Given an Event Coordinator submits a venue booking request, system sends
an in-app notification to Venue Staff with event name, requested venue,
date/time and link to review.
AC2 Given booking approved/rejected, sends an in-app notification to Event
Coordinator with event name, venue, decision.
AC means acceptance criterion; DR means supporting design rule. Original story
AC numbering below is unchanged; SCRUM-47 has only AC1 and AC2.
Real: Flask routes, validation and model transaction/SQL construction.
Doubled: psycopg2 connection/cursor; SQL ordering is not durable-commit proof.
SCRUM-47 DR: refused submission/decision writes enqueue no notification.
Successful intent snapshots are checked in the submission/review story modules.
Not proven here: all-staff fanout, display text, links or inbox delivery; the
three Venue Booking dispatcher unit cases cover content/recipients/links, not delivery.
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


def test_health():
    client = signed_in(create_app().test_client())
    response = client.get("/health")
    assert response.status_code == 200


def test_booking_reads_project_optional_closure_history_without_requiring_migration(setup, monkeypatch):
    monkeypatch.setenv("VENUE_BOOKING_LEGACY_SCHEMA", "true")
    client, cursor = setup
    cursor.fetchall.return_value = [booking_row()]
    response = client.get(f"/events/{EVENT_ID}/venue-bookings")
    assert response.status_code == 200
    sql = cursor.execute.call_args.args[0]
    assert 'to_jsonb("VenueBooking")->>\'rejection_closure_id\'' in sql
    assert 'to_jsonb("VenueBooking")->>\'rejected_at\'' in sql


# Safety revision AC2/AC4 (storage boundary): scope the reset to selected booking IDs and require staff review again.
def test_safety_reset_returns_only_selected_active_bookings_to_review(setup):
    client, cursor = setup
    client.application.config["INTERNAL_SERVICE_TOKEN"] = "test-token"
    cursor.fetchall.side_effect = [[booking_row(status="Approved")], [booking_row(status="Pending Review")]]
    response = client.post(f"/events/{EVENT_ID}/venue-bookings/safety-reset",
        headers={"X-Internal-Service-Token": "test-token"}, json={"bookingIds": [BOOKING_ID]})
    assert response.status_code == 200
    assert response.json["bookings"][0]["status"] == "Pending Review"
    sql, params = cursor.execute.call_args.args
    assert "reviewed_by = NULL" in sql
    assert "status IN ('Approved', 'Pending', 'Pending Review')" in sql
    assert params == [EVENT_ID, [BOOKING_ID]]


def test_safety_reset_rejects_booking_from_another_event(setup):
    client, cursor = setup
    client.application.config["INTERNAL_SERVICE_TOKEN"] = "test-token"
    cursor.fetchall.return_value = []
    assert client.post(f"/events/{EVENT_ID}/venue-bookings/safety-reset",
        headers={"X-Internal-Service-Token": "test-token"}, json={"bookingIds": [BOOKING_ID]}).status_code == 404
    assert not any('UPDATE public."VenueBooking"' in call.args[0] for call in cursor.execute.call_args_list)


@pytest.mark.parametrize("token,headers,code", [(None, {}, 503), ("test-token", {}, 403)])
def test_safety_reset_requires_internal_authentication(setup, token, headers, code):
    client, cursor = setup
    client.application.config["INTERNAL_SERVICE_TOKEN"] = token
    assert client.post(f"/events/{EVENT_ID}/venue-bookings/safety-reset", headers=headers,
        json={"bookingIds": [BOOKING_ID]}).status_code == code
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("payload", [None, {}, {"bookingIds": []}, {"bookingIds": ["bad"]},
    {"bookingIds": [BOOKING_ID, BOOKING_ID]}, {"bookingIds": [BOOKING_ID] * 501}])
def test_safety_reset_validates_booking_ids(setup, payload):
    client, cursor = setup
    client.application.config["INTERNAL_SERVICE_TOKEN"] = "test-token"
    assert client.post(f"/events/{EVENT_ID}/venue-bookings/safety-reset",
        headers={"X-Internal-Service-Token": "test-token"}, json=payload).status_code == 400
    cursor.execute.assert_not_called()


def test_safety_reset_requires_database(setup):
    client, _ = setup
    client.application.config.update(INTERNAL_SERVICE_TOKEN="test-token", DATABASE_URL=None)
    assert client.post(f"/events/{EVENT_ID}/venue-bookings/safety-reset",
        headers={"X-Internal-Service-Token": "test-token"}, json={"bookingIds": [BOOKING_ID]}).status_code == 503


def test_create_booking_succeeds_when_no_conflict(setup):
    client, cursor = setup
    cursor.fetchone.side_effect = [booking_row()]

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
    """Conflict: an overlapping submission is refused without scheduling an alert."""
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
        booking_row(status="Approved", reviewed_by=USER_ID),
    ]

    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}/approve", json={"reviewedBy": USER_ID}
    )

    assert response.status_code == 200
    assert response.json["status"] == "Approved"


def test_approve_booking_rejects_when_now_conflicting(setup):
    """Conflict: a newly occupied slot refuses approval without scheduling an alert."""
    client, cursor = setup
    cursor.fetchone.side_effect = [booking_row()]
    cursor.fetchall.return_value = [{"conflict_type": "APPROVED_BOOKING"}]

    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}/approve", json={"reviewedBy": USER_ID}
    )

    assert response.status_code == 409
    assert_no_booking_intent(cursor)


def test_approve_booking_missing_returns_404(setup):
    """Failure: an unknown booking schedules no approval alert."""
    client, cursor = setup
    cursor.fetchone.side_effect = [None]

    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}/approve", json={"reviewedBy": USER_ID}
    )

    assert response.status_code == 404
    assert_no_booking_intent(cursor)


def test_reject_booking_does_not_recheck_conflicts(setup):
    client, cursor = setup
    cursor.fetchone.side_effect = [
        booking_row(),
        booking_row(status="Rejected", reviewed_by=USER_ID),
    ]

    response = client.patch(
        f"/venue-bookings/{BOOKING_ID}/reject",
        # SCRUM-29 AC4: a reject now carries a reason.
        json={"reviewedBy": USER_ID, "rejectionReason": "Venue unsuitable"},
    )

    assert response.status_code == 200
    assert response.json["status"] == "Rejected"


def test_cancelled_booking_cannot_be_approved_or_rejected(setup):
    """Conflict: neither decision on a cancelled booking schedules an alert."""
    client, cursor = setup
    cursor.fetchone.return_value = booking_row(status="Cancelled")

    approve = client.patch(
        f"/venue-bookings/{BOOKING_ID}/approve", json={"reviewedBy": USER_ID}
    )
    reject = client.patch(
        f"/venue-bookings/{BOOKING_ID}/reject",
        # SCRUM-29 AC4: a reject now carries a reason.
        json={"reviewedBy": USER_ID, "rejectionReason": "Venue unsuitable"},
    )

    assert approve.status_code == 409
    assert reject.status_code == 409
    assert "cannot be reviewed" in approve.json["message"]
    assert_no_booking_intent(cursor)


def test_get_bookings_lists_for_venue(setup):
    client, cursor = setup
    cursor.fetchall.return_value = [booking_row()]

    response = client.get(
        f"/venue-bookings?venueId={VENUE_ID}&dateFrom=2026-10-01T00:00&dateTo=2026-10-02T00:00",
        headers=bearer(USER_ID, "Venue Staff"),
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


# Safety revision AC2/AC4 (revised-booking path): editing one booking clears its review without editing siblings.
def test_update_booking_changes_only_selected_row_and_resets_review(setup):
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
    assert cursor.execute.call_count == 2


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


def test_cancel_requires_event_id(setup):
    client, _ = setup
    assert client.patch(
        f"/venue-bookings/{BOOKING_ID}/cancel", json={}
    ).status_code == 400
