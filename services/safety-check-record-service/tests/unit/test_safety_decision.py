"""SCRUM-150: deciding the open SafetyCheck round.

AC2 ... the safety check is recorded with the status 'Safety Approved',
    together with my identity, the approval timestamp and any optional
    remarks, in the event's history.
AC3 ... the approve action is not available and an API call is rejected
    without changing the event — the race-guard half of this lives here:
    only one decide can win the open round.

Database calls are mocked; no live database writes.
"""
import psycopg2
import pytest
from unittest.mock import MagicMock

from app import create_app
from tests.unit.factories import EVENT_ID, OFFICER_ID, RECORD_ID, record_row, signed_in


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client(), OFFICER_ID, "Safety Officer"), connection, cursor


@pytest.fixture
def no_database():
    app = create_app({"TESTING": True, "DATABASE_URL": None})
    return signed_in(app.test_client(), OFFICER_ID, "Safety Officer")


def decide(client, safety_check_id=RECORD_ID, **overrides):
    body = {"status": "Safety Approved", **overrides}
    return client.patch(f"/safety-check-records/{safety_check_id}/decision", json=body)


def reopen(client, safety_check_id=RECORD_ID, **overrides):
    body = {"decidedAt": "2026-11-02T03:00:00+00:00", **overrides}
    return client.post(f"/safety-check-records/{safety_check_id}/reopen", json=body)


# --- AC2: deciding the open round --------------------------------------------


def test_pending_latest_round_is_decided(setup):
    """AC2: status, decidedBy and decidedAt are set, and remarks are stored."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Safety Approved", decided=True),
    ]

    response = decide(client, remarks="Looks safe.")

    assert response.status_code == 200
    assert response.json["status"] == "Safety Approved"
    assert response.json["decidedBy"] == OFFICER_ID
    assert response.json["decidedAt"] == "2026-11-02T03:00:00+00:00"
    assert response.json["remarks"] == "Looks safe."
    update_sql, update_params = cursor.execute.call_args_list[-1].args
    assert 'UPDATE public."SafetyCheck"' in update_sql
    assert update_params == ["Safety Approved", OFFICER_ID, "Looks safe.", RECORD_ID]


def test_blank_remarks_are_stored_as_null(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Safety Approved", decided=True),
    ]

    response = decide(client, remarks="   ")

    assert response.status_code == 200
    update_params = cursor.execute.call_args_list[-1].args[1]
    assert update_params[2] is None


def test_remarks_over_the_limit_are_rejected(setup):
    client, _, cursor = setup

    response = decide(client, remarks="x" * 2001)

    assert response.status_code == 400
    assert response.json["message"] == "remarks must be 2000 characters or fewer."
    cursor.execute.assert_not_called()


def test_non_text_remarks_are_rejected(setup):
    client, _, cursor = setup

    response = decide(client, remarks={"nested": "object"})

    assert response.status_code == 400
    assert response.json["message"] == "remarks must be text."
    cursor.execute.assert_not_called()


def test_already_decided_round_cannot_be_decided_again(setup):
    """AC3 / race: the loser of the race finds the round already decided."""
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(status="Safety Approved", decided=True)

    response = decide(client)

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_DECIDED"
    assert response.json["safetyCheck"]["status"] == "Safety Approved"
    # Only the SELECT ran: no UPDATE.
    assert cursor.execute.call_count == 1


def test_older_round_cannot_be_decided_while_a_newer_round_exists(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=1, status="Pending"),
        record_row(round_number=2, status="Pending"),
    ]

    response = decide(client)

    assert response.status_code == 409
    assert response.json["code"] == "NOT_LATEST_ROUND"
    assert cursor.execute.call_count == 2


@pytest.mark.parametrize("status", ["Pending", "Approved"])
def test_status_not_in_decision_statuses_is_rejected(status, setup):
    """SCRUM-151 widens DECISION_STATUSES to include Changes Requested and
    Safety Rejected, so only these remain invalid."""
    client, _, cursor = setup

    response = decide(client, status=status)

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_missing_round_is_404(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = decide(client)

    assert response.status_code == 404
    assert response.json["message"] == "Safety check not found."


@pytest.mark.parametrize(
    "safety_check_id",
    ["not-a-uuid"],
)
def test_bad_round_id_is_rejected(safety_check_id, setup):
    client, _, cursor = setup

    response = decide(client, safety_check_id=safety_check_id)

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_decider_is_the_signed_in_officer_not_the_body(setup):
    """SCRUM-8: a forged decidedBy is ignored; the token names the decider."""
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row()

    decide(client, decidedBy="99999999-9999-4999-8999-999999999999")

    assert all("99999999-9999-4999-8999-999999999999" not in str(c.args) for c in cursor.execute.call_args_list)
    assert any(OFFICER_ID in str(c.args) for c in cursor.execute.call_args_list)


def test_decide_non_object_body_is_rejected(setup):
    client, _, cursor = setup

    response = client.patch(
        f"/safety-check-records/{RECORD_ID}/decision", json=["not", "an", "object"]
    )

    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    cursor.execute.assert_not_called()


def test_decide_without_database_url(no_database):
    response = no_database.patch(
        f"/safety-check-records/{RECORD_ID}/decision",
        json={"status": "Safety Approved"},
    )

    assert response.status_code == 503


def test_decide_runs_under_row_lock(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Safety Approved", decided=True),
    ]

    decide(client)

    select_sql = cursor.execute.call_args_list[0].args[0]
    assert "FOR UPDATE" in select_sql


def test_decide_database_failure_is_503(setup):
    client, _, cursor = setup
    cursor.execute.side_effect = psycopg2.OperationalError("connection refused")

    response = decide(client)

    assert response.status_code == 503
    assert "connection refused" not in response.json["message"]


# --- Compensation: reopen -----------------------------------------------------


def test_reopen_with_matching_decided_at_reverts_to_pending(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(status="Safety Approved", decided=True),
        record_row(status="Pending"),
    ]

    response = reopen(client)

    assert response.status_code == 200
    assert response.json["status"] == "Pending"
    assert response.json["decidedBy"] is None
    update_sql, update_params = cursor.execute.call_args_list[-1].args
    assert 'UPDATE public."SafetyCheck"' in update_sql
    assert update_params == ["Pending", RECORD_ID]


def test_reopen_with_mismatched_decided_at_is_409(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(status="Safety Approved", decided=True)

    response = reopen(client, decidedAt="2099-01-01T00:00:00+00:00")

    assert response.status_code == 409
    assert cursor.execute.call_count == 1


def test_reopen_of_an_undecided_round_is_409(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(status="Pending")

    response = reopen(client)

    assert response.status_code == 409


def test_reopen_of_a_missing_round_is_404(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = reopen(client)

    assert response.status_code == 404


def test_reopen_non_object_body_is_rejected(setup):
    client, _, cursor = setup

    response = client.post(
        f"/safety-check-records/{RECORD_ID}/reopen", json=["not", "an", "object"]
    )

    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    cursor.execute.assert_not_called()


def test_reopen_requires_decided_at(setup):
    client, _, cursor = setup

    response = reopen(client, decidedAt=None)

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_reopen_requires_a_valid_round_id(setup):
    client, _, cursor = setup

    response = client.post(
        "/safety-check-records/not-a-uuid/reopen",
        json={"decidedAt": "2026-11-02T03:00:00+00:00"},
    )

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_reopen_without_database_url(no_database):
    response = no_database.post(
        f"/safety-check-records/{RECORD_ID}/reopen",
        json={"decidedAt": "2026-11-02T03:00:00+00:00"},
    )

    assert response.status_code == 503


def test_cors_allows_patch(setup):
    client, _, _ = setup

    response = client.options(
        f"/safety-check-records/{RECORD_ID}/decision",
        headers={"Origin": "http://localhost:5174"},
    )

    assert "PATCH" in response.headers["Access-Control-Allow-Methods"]
