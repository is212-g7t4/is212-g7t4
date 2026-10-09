from datetime import datetime

from app import create_app
from tests.unit.factories import USER_ID, VENUE_ID


HOLD_HEADERS = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Venue Staff"}


def test_place_hold_requires_venue_staff(setup):
    client, _ = setup
    client.application.config["CALENDAR_DEV_MODE"] = True

    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2099-10-01T12:00"},
        headers={**HOLD_HEADERS, "X-Dev-Role": "Event Coordinator"},
    )

    assert response.status_code == 403


def test_place_hold_is_disabled_without_dev_mode(setup):
    client, cursor = setup

    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2099-10-01T12:00"},
        headers=HOLD_HEADERS,
    )

    assert response.status_code == 503
    cursor.execute.assert_not_called()


def test_place_hold_requires_identity_headers(setup):
    client, cursor = setup
    client.application.config["CALENDAR_DEV_MODE"] = True

    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2099-10-01T12:00"},
    )

    assert response.status_code == 401
    cursor.execute.assert_not_called()


def test_place_hold_requires_expiry(setup):
    client, _ = setup
    client.application.config["CALENDAR_DEV_MODE"] = True

    response = client.post(
        "/venue-holds", json={"venueId": VENUE_ID}, headers=HOLD_HEADERS
    )

    assert response.status_code == 400


def test_place_hold_requires_json_object(setup):
    client, cursor = setup
    client.application.config["CALENDAR_DEV_MODE"] = True

    response = client.post("/venue-holds", json=[], headers=HOLD_HEADERS)

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_place_hold_rejects_expiry_in_the_past(setup):
    client, _ = setup
    client.application.config["CALENDAR_DEV_MODE"] = True

    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2000-10-01T12:00"},
        headers=HOLD_HEADERS,
    )

    assert response.status_code == 400
    assert "future" in response.json["message"]


def test_place_hold_succeeds(setup):
    client, cursor = setup
    client.application.config["CALENDAR_DEV_MODE"] = True
    cursor.fetchone.side_effect = [
        {"venue_id": VENUE_ID},
        None,
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
    assert response.json["hold"]["venueId"] == VENUE_ID
    assert response.json["hold"]["expiresAt"] == "2099-10-01T12:00:00"


def test_place_hold_rejects_overlap_with_existing_booking(setup):
    client, cursor = setup
    client.application.config["CALENDAR_DEV_MODE"] = True
    cursor.fetchone.side_effect = [{"venue_id": VENUE_ID}, {"booking_id": "existing"}]

    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2099-10-01T12:00"},
        headers=HOLD_HEADERS,
    )

    assert response.status_code == 409
    assert "status NOT IN ('Rejected', 'Cancelled')" in cursor.execute.call_args_list[1].args[0]


def test_place_hold_rejects_overlap_with_another_active_hold(setup):
    client, cursor = setup
    client.application.config["CALENDAR_DEV_MODE"] = True
    cursor.fetchone.side_effect = [{"venue_id": VENUE_ID}, None, {"hold_id": "active"}]

    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2099-10-01T12:00"},
        headers=HOLD_HEADERS,
    )

    assert response.status_code == 409


def test_place_hold_returns_404_for_unknown_venue(setup):
    client, cursor = setup
    client.application.config["CALENDAR_DEV_MODE"] = True
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
    client.application.config.update(CALENDAR_DEV_MODE=True, DATABASE_URL=None)

    response = client.post(
        "/venue-holds",
        json={"venueId": VENUE_ID, "expiresAt": "2099-10-01T12:00"},
        headers=HOLD_HEADERS,
    )

    assert response.status_code == 503
    cursor.execute.assert_not_called()