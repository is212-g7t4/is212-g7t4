"""SCRUM-28 Part B: a venue booking change on a Confirmed event withdraws its approval.

Decided by Clarice on 25 Oct: editing or cancelling a venue booking of a
'Confirmed' event withdraws the safety approval and sends the event back to
'Approved'. Venue Staff re-review the booking, then the coordinator resubmits
through SCRUM-149, which opens round N+1. So this service withdraws round N
**without** opening a round (`openNextRound: false`), and can undo exactly
that (`nextRoundOpened: false`) when Venue Booking Service couldn't save the
booking change. SCRUM-153's default behaviour is unchanged. Database calls
are mocked.
"""
from unittest.mock import MagicMock

import pytest

from app import create_app
from tests.unit.factories import COORDINATOR_ID, NEXT_RECORD_ID, RECORD_ID, record_row

REASON = "Venue booking for Grand Hall changed after safety approval."


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), cursor


def approved(round_number=2):
    return record_row(round_number=round_number, status="Safety Approved", decided=True)


def withdrawn(round_number=2):
    return record_row(round_number=round_number, status="Approval Withdrawn", decided=True, withdrawn=True)


def statements(cursor):
    return [call.args[0] for call in cursor.execute.call_args_list]


# --- withdraw without opening a round ----------------------------------------


def test_withdraw_without_next_round_opens_nothing(setup):
    """Normal: round N is withdrawn and no round N+1 is inserted."""
    client, cursor = setup
    cursor.fetchone.side_effect = [approved(), approved(), withdrawn()]

    response = client.post(
        f"/safety-check-records/{RECORD_ID}/withdraw",
        json={"withdrawnBy": COORDINATOR_ID, "reason": REASON, "openNextRound": False},
    )

    assert response.status_code == 201
    assert response.json["withdrawn"]["status"] == "Approval Withdrawn"
    assert response.json["opened"] is None
    assert not any("INSERT" in sql for sql in statements(cursor))
    assert "FOR UPDATE" in statements(cursor)[0]


def test_withdraw_by_default_still_opens_the_next_round(setup):
    """Regression (SCRUM-153): without the flag, round N+1 still opens."""
    client, cursor = setup
    cursor.fetchone.side_effect = [
        approved(), approved(), withdrawn(),
        record_row(round_number=3, safety_check_id=NEXT_RECORD_ID),
    ]

    response = client.post(
        f"/safety-check-records/{RECORD_ID}/withdraw",
        json={"withdrawnBy": COORDINATOR_ID, "reason": REASON},
    )

    assert response.status_code == 201
    assert response.json["opened"]["roundNumber"] == 3
    assert any("INSERT" in sql for sql in statements(cursor))


@pytest.mark.parametrize("value", ["false", 0, None])
def test_open_next_round_must_be_a_boolean(setup, value):
    """Failure: a non-boolean flag is refused before the database is touched."""
    client, cursor = setup

    response = client.post(
        f"/safety-check-records/{RECORD_ID}/withdraw",
        json={"withdrawnBy": COORDINATOR_ID, "reason": REASON, "openNextRound": value},
    )

    assert response.status_code == 400
    assert response.json["message"] == "openNextRound must be true or false."
    cursor.execute.assert_not_called()


# --- restore a withdrawal that opened no round -------------------------------


def restore_without_round(client):
    return client.post(f"/safety-check-records/{RECORD_ID}/restore", json={"nextRoundOpened": False})


def test_restore_without_round_reinstates_the_approval(setup):
    """Normal: the compensation puts round N back to 'Safety Approved' and deletes nothing."""
    client, cursor = setup
    cursor.fetchone.side_effect = [withdrawn(), withdrawn(), approved()]

    response = restore_without_round(client)

    assert response.status_code == 200
    assert response.json["status"] == "Safety Approved"
    assert not any("DELETE" in sql for sql in statements(cursor))
    assert "withdrawn_at = NULL" in statements(cursor)[-1]


def test_restore_without_round_refuses_when_a_later_round_exists(setup):
    """Conflict: this can never un-withdraw an approval whose round N+1 was opened."""
    client, cursor = setup
    cursor.fetchone.side_effect = [withdrawn(), record_row(round_number=3, safety_check_id=NEXT_RECORD_ID)]

    response = restore_without_round(client)

    assert response.status_code == 409
    assert response.json["code"] == "NOT_RESTORABLE"
    assert not any(sql.lstrip().startswith("UPDATE") for sql in statements(cursor))


def test_restore_without_round_is_idempotent(setup):
    """Boundary: a retried compensation returns the already-restored round."""
    client, cursor = setup
    cursor.fetchone.side_effect = [approved(), approved()]

    response = restore_without_round(client)

    assert response.status_code == 200
    assert response.json["status"] == "Safety Approved"


def test_restore_with_round_still_requires_its_id(setup):
    """Regression (SCRUM-153): the default restore still needs the opened round's id."""
    client, cursor = setup

    response = client.post(f"/safety-check-records/{RECORD_ID}/restore", json={})

    assert response.status_code == 400
    assert response.json["message"] == "openedSafetyCheckId must be a valid UUID."
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    "body, message",
    [
        ({"nextRoundOpened": "no"}, "nextRoundOpened must be true or false."),
        (
            {"nextRoundOpened": False, "openedSafetyCheckId": NEXT_RECORD_ID},
            "openedSafetyCheckId must be omitted when nextRoundOpened is false.",
        ),
    ],
)
def test_restore_without_round_validates_its_body(setup, body, message):
    """Failure: a contradictory or malformed restore is refused before the database."""
    client, cursor = setup

    response = client.post(f"/safety-check-records/{RECORD_ID}/restore", json=body)

    assert response.status_code == 400
    assert response.json["message"] == message
    cursor.execute.assert_not_called()
