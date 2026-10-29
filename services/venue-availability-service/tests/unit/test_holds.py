"""# Test scope and acceptance mapping — SCRUM-171 integration

- **Hold/reminder and buffer regressions (no direct SCRUM-171 AC):** staff/identity guards, expiry, conflict refusal, coordinator ownership, buffer-expanded overlap, active reminder filtering and configuration errors.
- **SCRUM-171 integration:** the shared write gate precedes the existing hold SQL; the coordinator/buffer case locates overlap and insert queries by purpose rather than positional indices. Both upstream behavior and its assertions are preserved.

## Case/group traceability

The named test functions/cases below implement the groups above; their existing
names and assertions specify the scenario. No group is credited with all five ACs.
"""

from datetime import datetime

from app.calendar import SINGAPORE
from tests.unit.factories import USER_ID, VENUE_ID, bearer


HOLD_HEADERS = bearer(USER_ID, "Venue Staff")


def test_place_hold_requires_venue_staff(setup):
    client, _ = setup

    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2099-10-01T12:00"},
        headers=bearer(USER_ID, "Event Coordinator"),
    )

    assert response.status_code == 403


def test_place_hold_requires_a_signed_in_user(setup, monkeypatch):
    """SCRUM-8: a background worker's internal token cannot place a hold."""
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "internal-test-token")
    client, cursor = setup

    response = client.application.test_client().post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2099-10-01T12:00"},
        headers={"X-Internal-Token": "internal-test-token"},
    )

    assert response.status_code == 401
    cursor.execute.assert_not_called()


def test_place_hold_requires_expiry(setup):
    client, _ = setup

    response = client.post(
        "/venue-holds", json={"venueId": VENUE_ID}, headers=HOLD_HEADERS
    )

    assert response.status_code == 400


def test_place_hold_requires_json_object(setup):
    client, cursor = setup

    response = client.post("/venue-holds", json=[], headers=HOLD_HEADERS)

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_place_hold_rejects_expiry_in_the_past(setup):
    client, _ = setup

    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2000-10-01T12:00"},
        headers=HOLD_HEADERS,
    )

    assert response.status_code == 400
    assert "future" in response.json["message"]


def test_place_hold_succeeds(setup):
    client, cursor = setup
    cursor.fetchone.side_effect = [
        {"venue_id": VENUE_ID},
        None,
        {
            "hold_id": "00000000-0000-0000-0000-000000000010",
            "venue_id": VENUE_ID,
            "created_at": datetime(2026, 10, 8, 9),
            "expires_at": datetime(2099, 10, 1, 12),
            "held_by": USER_ID,
        },
    ]

    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2099-10-01T12:00"},
        headers=HOLD_HEADERS,
    )

    assert response.status_code == 201
    sql, params = cursor.execute.call_args.args
    assert 'INSERT INTO public."VenueBooking"' in sql
    assert "'On Hold'" in sql
    assert "VenueHold" not in sql
    assert params[0] == VENUE_ID
    assert params[3] == USER_ID
    assert params[2] == params[5] == datetime(2099, 10, 1, 12, tzinfo=SINGAPORE)
    assert response.json["hold"]["venueId"] == VENUE_ID
    assert response.json["hold"]["expiresAt"] == "2099-10-01T12:00:00"


def test_place_hold_rejects_overlap_with_existing_booking(setup):
    client, cursor = setup
    cursor.fetchone.side_effect = [{"venue_id": VENUE_ID}, {"booking_id": "existing"}]

    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2099-10-01T12:00"},
        headers=HOLD_HEADERS,
    )

    assert response.status_code == 409
    assert (
        "status NOT IN ('Rejected', 'Cancelled', 'Expired')"
        in cursor.execute.call_args_list[2].args[0]
    )


def test_place_hold_rejects_overlap_with_another_active_hold(setup):
    """Holds are 'On Hold' VenueBooking rows, so the same overlap check sees them."""
    client, cursor = setup
    cursor.fetchone.side_effect = [{"venue_id": VENUE_ID}, {"booking_id": "active"}]

    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2099-10-01T12:00"},
        headers=HOLD_HEADERS,
    )

    assert response.status_code == 409


def test_place_hold_returns_404_for_unknown_venue(setup):
    client, cursor = setup
    cursor.fetchone.return_value = None

    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2099-10-01T12:00"},
        headers=HOLD_HEADERS,
    )

    assert response.status_code == 404


def test_list_active_holds(setup):
    client, cursor = setup
    cursor.fetchall.return_value = [
        {
            "hold_id": "00000000-0000-0000-0000-000000000010",
            "venue_id": VENUE_ID,
            "created_at": datetime(2026, 10, 8, 9),
            "expires_at": datetime(2099, 10, 1, 12),
            "held_by": USER_ID,
        }
    ]

    response = client.get("/venue-holds")

    assert response.status_code == 200
    assert response.json["holds"][0]["venueId"] == VENUE_ID


def test_list_active_holds_reads_on_hold_rows(setup):
    client, cursor = setup
    cursor.fetchall.return_value = []

    client.get("/venue-holds")

    sql = cursor.execute.call_args.args[0]
    assert "status = 'On Hold'" in sql
    assert "hold_expires_at > now()" in sql
    assert "VenueHold" not in sql


def test_list_active_holds_database_unconfigured(setup):
    client, cursor = setup
    client.application.config["DATABASE_URL"] = None

    response = client.get("/venue-holds")

    assert response.status_code == 503
    cursor.execute.assert_not_called()


def test_hold_cors_preflight(setup):
    client, cursor = setup

    response = client.options("/venue-holds")

    assert response.status_code == 200
    cursor.execute.assert_not_called()


def test_place_hold_database_unconfigured(setup):
    client, cursor = setup
    client.application.config.update(DATABASE_URL=None)

    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2099-10-01T12:00"},
        headers=HOLD_HEADERS,
    )

    assert response.status_code == 503
    cursor.execute.assert_not_called()

COORDINATOR_HEADERS = bearer(USER_ID, "Event Coordinator")
HOLD_ROW = {
    "hold_id": "00000000-0000-0000-0000-000000000010",
    "venue_id": VENUE_ID,
    "created_at": datetime(2026, 10, 8, 9),
    "expires_at": datetime(2026, 10, 19, 12),
    "held_by": USER_ID,
}


def test_place_hold_stores_the_coordinator_it_is_held_for(setup):
    client, cursor = setup
    cursor.fetchone.side_effect = [{"venue_id": VENUE_ID}, None, HOLD_ROW]

    response = client.post(
        "/venue-holds",
        json={
            "venueId": VENUE_ID,
            "expiresAt": "2099-10-01T12:00",
            "coordinatorId": USER_ID,
        },
        headers=HOLD_HEADERS,
    )

    assert response.status_code == 201
    sql, params = cursor.execute.call_args.args
    assert "held_for" in sql
    assert params[-1] == USER_ID


def test_place_hold_keeps_coordinator_and_buffer_conflict_rules_together(setup):
    """The reminder assignment must not discard the venue's buffer times."""
    client, cursor = setup
    cursor.fetchone.side_effect = [{"venue_id": VENUE_ID}, None, HOLD_ROW]

    response = client.post(
        "/venue-holds",
        json={
            "venueId": VENUE_ID,
            "expiresAt": "2099-10-01T12:00",
            "coordinatorId": USER_ID,
            "setupTimeMinutes": 30,
            "turnaroundTimeMinutes": 45,
        },
        headers=HOLD_HEADERS,
    )

    assert response.status_code == 201
    overlap_params = next(call.args[1] for call in cursor.execute.call_args_list if "SELECT 1 FROM" in call.args[0])
    insert_params = next(call.args[1] for call in cursor.execute.call_args_list if "INSERT INTO" in call.args[0])
    assert overlap_params[3] == datetime(2099, 10, 1, 12, 30, tzinfo=SINGAPORE)
    assert insert_params[-1] == USER_ID


def test_place_hold_rejects_malformed_coordinator_id(setup):
    client, cursor = setup

    response = client.post(
        "/venue-holds",
        json={
            "venueId": VENUE_ID,
            "expiresAt": "2099-10-01T12:00",
            "coordinatorId": "nope",
        },
        headers=HOLD_HEADERS,
    )

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_reminders_return_the_coordinators_holds_expiring_in_three_days(setup):
    """Coordinator is told which venue and when the hold expires."""
    client, cursor = setup
    cursor.fetchall.return_value = [HOLD_ROW]

    response = client.get("/venue-holds/reminders", headers=COORDINATOR_HEADERS)

    assert response.status_code == 200
    reminder = response.json["reminders"][0]
    assert reminder["venueId"] == VENUE_ID
    assert reminder["expiresAt"] == "2026-10-19T12:00:00"
    sql, params = cursor.execute.call_args.args
    assert params == [USER_ID]


def test_reminders_exclude_expired_and_no_longer_active_holds(setup):
    """No reminder once the hold has expired or is no longer 'On Hold'."""
    client, cursor = setup
    cursor.fetchall.return_value = []

    client.get("/venue-holds/reminders", headers=COORDINATOR_HEADERS)

    sql = cursor.execute.call_args.args[0]
    assert "status = 'On Hold'" in sql
    assert "hold_expires_at > now()" in sql
    assert "hold_expires_at <= now() + interval '3 days'" in sql
    assert "held_for = %s" in sql


def test_reminders_accept_the_coordinator_lead(setup):
    client, cursor = setup
    cursor.fetchall.return_value = []

    response = client.get(
        "/venue-holds/reminders",
        headers=bearer(USER_ID, "Event Coordinator Lead"),
    )

    assert response.status_code == 200


def test_reminders_require_coordinator_role(setup):
    client, cursor = setup

    response = client.get("/venue-holds/reminders", headers=HOLD_HEADERS)

    assert response.status_code == 403
    cursor.execute.assert_not_called()


def test_reminders_require_a_signed_in_user(setup, monkeypatch):
    """SCRUM-8: reminders are for the signed-in coordinator; an internal token has none."""
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "internal-test-token")
    client, cursor = setup

    response = client.application.test_client().get(
        "/venue-holds/reminders", headers={"X-Internal-Token": "internal-test-token"}
    )

    assert response.status_code == 401
    cursor.execute.assert_not_called()


def test_reminders_database_unconfigured(setup):
    client, cursor = setup
    client.application.config.update(DATABASE_URL=None)

    response = client.get("/venue-holds/reminders", headers=COORDINATOR_HEADERS)

    assert response.status_code == 503
    cursor.execute.assert_not_called()
