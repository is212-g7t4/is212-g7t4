"""SCRUM-33: event name lookup used by the equipment review screen. Database calls are mocked."""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app import create_app

ID_A = "00000000-0000-4000-8000-000000000001"
ID_B = "00000000-0000-4000-8000-000000000002"


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr("app.models.psycopg2.connect", connect)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), cursor, connect


def test_returns_name_status_coordinator_and_window_for_requested_ids(setup):
    client, cursor, _ = setup
    cursor.fetchall.return_value = [
        {"event_id": ID_A, "event_name": "Hackday", "status": "Approved", "coordinator_id": ID_B,
         "preferred_start_date": datetime(2026, 10, 1, 9), "preferred_end_date": datetime(2026, 10, 1, 17)},
        {"event_id": ID_B, "event_name": "Gala", "status": "Submitted", "coordinator_id": None,
         "preferred_start_date": None, "preferred_end_date": None},
    ]

    response = client.get(f"/events/summaries?ids={ID_A},{ID_B}")

    assert response.status_code == 200
    assert response.json["events"] == [
        {"id": ID_A, "eventName": "Hackday", "status": "Approved", "coordinatorId": ID_B,
         "startTime": "2026-10-01T09:00:00", "endTime": "2026-10-01T17:00:00"},
        {"id": ID_B, "eventName": "Gala", "status": "Submitted", "coordinatorId": None,
         "startTime": None, "endTime": None},
    ]
    assert cursor.execute.call_args[0][1] == [[ID_A, ID_B]]


@pytest.mark.parametrize("query", ["", "?ids=", "?ids=nope", f"?ids={ID_A},nope", "?ids=" + ",".join([ID_A] * 101)])
def test_rejects_missing_or_invalid_ids(setup, query):
    client, _, connect = setup
    assert client.get(f"/events/summaries{query}").status_code == 400
    connect.assert_not_called()


def test_missing_database_url_is_503():
    client = create_app({"DATABASE_URL": None}).test_client()
    assert client.get(f"/events/summaries?ids={ID_A}").status_code == 503


WINDOW = "start=2026-10-01T09:00&end=2026-10-01T17:00&statuses=Approved,Confirmed"


def test_overlapping_events_use_strict_overlap_and_exclude_the_target(setup):
    client, cursor, _ = setup
    cursor.fetchall.return_value = [
        {"event_id": ID_A, "event_name": "Hackday", "status": "Confirmed", "coordinator_id": None,
         "preferred_start_date": datetime(2026, 10, 1, 16), "preferred_end_date": datetime(2026, 10, 1, 20)},
    ]

    response = client.get(f"/events/overlapping?{WINDOW}&excludeEventId={ID_B}")

    assert response.status_code == 200
    assert response.json["events"][0]["id"] == ID_A
    sql, params = cursor.execute.call_args[0]
    assert "preferred_start_date < %s AND preferred_end_date > %s" in sql and "event_id <> %s" in sql
    assert params == [["Approved", "Confirmed"], datetime(2026, 10, 1, 17), datetime(2026, 10, 1, 9), ID_B]


def test_overlapping_events_without_exclusion(setup):
    client, cursor, _ = setup
    cursor.fetchall.return_value = []

    assert client.get(f"/events/overlapping?{WINDOW}").json == {"events": []}
    assert "event_id <> %s" not in cursor.execute.call_args[0][0]


@pytest.mark.parametrize(
    "query",
    [
        "start=2026-10-01T09:00&end=2026-10-01T17:00",
        "start=2026-10-01T09:00&end=2026-10-01T17:00&statuses=Bogus",
        "start=nope&end=2026-10-01T17:00&statuses=Approved",
        "start=2026-10-01T09:00&statuses=Approved",
        f"start=2026-10-01T09:00&end=2026-10-01T17:00&statuses=Approved&excludeEventId=nope",
        "start=2026-10-01T17:00&end=2026-10-01T09:00&statuses=Approved",
    ],
)
def test_overlapping_events_reject_bad_input(setup, query):
    client, _, connect = setup
    assert client.get(f"/events/overlapping?{query}").status_code == 400
    connect.assert_not_called()


def test_overlapping_events_missing_database_url_is_503():
    client = create_app({"DATABASE_URL": None}).test_client()
    assert client.get(f"/events/overlapping?{WINDOW}").status_code == 503
