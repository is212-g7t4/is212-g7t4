"""Characterization tests: SCRUM-25 must not change the existing write contract."""

import pytest
from tests.unit.factories import BOOKING_ID, EVENT_ID, USER_ID, VENUE_ID, booking_row

PAYLOAD = dict(
    eventId=EVENT_ID,
    venueId=VENUE_ID,
    requestedBy=USER_ID,
    requestedStartTime="2026-10-01T09:00",
    requestedEndTime="2026-10-01T12:00",
)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        PAYLOAD | {"eventId": "bad"},
        PAYLOAD | {"requestedStartTime": "bad"},
        PAYLOAD | {"requestedStartTime": None},
        PAYLOAD | {"requestedStartTime": "2026-10-01"},
        PAYLOAD | {"requestedStartTime": "2026-10-01T09:00+08:00"},
    ],
)
def test_write_validation_unchanged(setup, payload):
    client, cursor = setup
    assert client.post("/venue-bookings", json=payload).status_code == 400
    cursor.execute.assert_not_called()


def test_write_database_unconfigured(setup):
    client, cursor = setup
    client.application.config["DATABASE_URL"] = None
    assert client.post("/venue-bookings", json=PAYLOAD).status_code == 503
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("payload", [None, [], {}, {"reviewedBy": "bad"}])
def test_decision_validation_unchanged(setup, payload):
    client, cursor = setup
    assert (
        client.patch(f"/venue-bookings/{BOOKING_ID}/approve", json=payload).status_code
        == 400
    )
    cursor.execute.assert_not_called()


def test_decision_database_unconfigured(setup):
    client, cursor = setup
    client.application.config["DATABASE_URL"] = None
    assert (
        client.patch(
            f"/venue-bookings/{BOOKING_ID}/reject", json={"reviewedBy": USER_ID}
        ).status_code
        == 503
    )
    cursor.execute.assert_not_called()


def test_write_remains_naive_pending_without_dev_gate(setup):
    client, cursor = setup
    client.application.config["CALENDAR_DEV_MODE"] = False
    cursor.fetchone.side_effect = [None, booking_row()]
    response = client.post("/venue-bookings", json=PAYLOAD)
    assert response.status_code == 201
    assert response.json["requestedStartTime"] == "2026-10-01T09:00:00"
    assert response.json["status"] == "Pending Review"
    assert "blocksSelection" not in response.json
    sql, params = cursor.execute.call_args_list[1].args
    assert "status = 'Approved'" in sql
    assert "requested_start_time < %s AND requested_end_time > %s" in sql
    assert params == [
        VENUE_ID,
        booking_row()["requested_end_time"],
        booking_row()["requested_start_time"],
    ]
    assert "'Pending Review'" in cursor.execute.call_args.args[0]
