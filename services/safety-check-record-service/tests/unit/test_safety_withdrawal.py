"""SCRUM-153: the SafetyCheck records behind "re-check safety after a high-impact change".

AC1 Given an event is 'Confirmed', when its date/time, expected attendance,
    venue requirements, equipment requirements or accessibility needs change,
    then its status returns to 'Pending Safety Check' and the coordinator is
    told why — the record half is round N becoming 'Approval Withdrawn' and
    round N+1 opening as 'Pending'.
AC3 Given a safety approval is withdrawn, then it stays visible in the event's
    safety history — round N is kept, not deleted, with the Safety Officer's
    original decision fields intact plus who withdrew it, when and why.

The event's own status and history belong to Event Service; this service owns
only the rounds. Database calls are mocked; no live database writes.
"""
import psycopg2
import pytest
from unittest.mock import MagicMock

from app import create_app
from app.models import RECORD_STATUSES
from tests.unit.factories import (
    COORDINATOR_ID,
    EVENT_ID,
    NEXT_RECORD_ID,
    OFFICER_ID,
    RECORD_ID,
    record_row,
)

REASON = "Date/time and Expected attendance changed after safety approval."
OTHER_EVENT_ID = "00000000-0000-0000-0000-000000000002"


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), connection, cursor


@pytest.fixture
def no_database():
    app = create_app({"TESTING": True, "DATABASE_URL": None})
    return app.test_client()


def withdraw(client, record_id=RECORD_ID, **overrides):
    body = {"withdrawnBy": COORDINATOR_ID, "reason": REASON, **overrides}
    return client.post(f"/safety-check-records/{record_id}/withdraw", json=body)


def restore(client, record_id=RECORD_ID, **overrides):
    body = {"openedSafetyCheckId": NEXT_RECORD_ID, **overrides}
    return client.post(f"/safety-check-records/{record_id}/restore", json=body)


def approved_round(round_number=2, **overrides):
    return record_row(
        round_number=round_number, status="Safety Approved", decided=True, **overrides
    )


# --- AC1/AC3: withdrawing an approval and opening the next round -------------


def test_withdrawing_an_approval_opens_the_next_round(setup):
    """AC1: round N is withdrawn and round N+1 opens as 'Pending', in one transaction."""
    client, connection, cursor = setup
    cursor.fetchone.side_effect = [
        approved_round(round_number=2),            # SELECT ... FOR UPDATE
        approved_round(round_number=2),            # _latest_round
        record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True),
        record_row(round_number=3, safety_check_id=NEXT_RECORD_ID),
    ]

    response = withdraw(client)

    assert response.status_code == 201
    assert response.json["withdrawn"]["status"] == "Approval Withdrawn"
    assert response.json["withdrawn"]["roundNumber"] == 2
    assert response.json["opened"]["status"] == "Pending"
    assert response.json["opened"]["roundNumber"] == 3
    assert response.json["opened"]["id"] == NEXT_RECORD_ID
    # One UPDATE of round N, then one INSERT of round N+1, on the same
    # connection — so neither can land without the other.
    update_sql, update_params = cursor.execute.call_args_list[2].args
    assert 'UPDATE public."SafetyCheck"' in update_sql
    assert update_params[0] == "Approval Withdrawn"
    assert update_params[1] == COORDINATOR_ID
    assert update_params[2] == REASON
    insert_sql, insert_params = cursor.execute.call_args_list[3].args
    assert 'INSERT INTO public."SafetyCheck"' in insert_sql
    assert insert_params[1] == 3
    assert insert_params[-1] == "Pending"
    assert cursor.execute.call_count == 4
    connection.__enter__.assert_called_once()


def test_the_original_decision_is_kept(setup):
    """AC3: who approved, when and with what remarks survive the withdrawal."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        approved_round(),
        approved_round(),
        record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True),
        record_row(round_number=3, safety_check_id=NEXT_RECORD_ID),
    ]

    response = withdraw(client)

    withdrawn = response.json["withdrawn"]
    assert withdrawn["decidedBy"] == OFFICER_ID
    assert withdrawn["decidedAt"] == "2026-11-02T03:00:00+00:00"
    assert withdrawn["remarks"] == "Looks safe."
    assert withdrawn["withdrawnAt"] == "2026-11-03T04:00:00+00:00"
    assert withdrawn["withdrawnBy"] == COORDINATOR_ID
    assert withdrawn["withdrawalReason"] == "Date/time changed after safety approval."
    # The UPDATE's SET clause touches only the status and the withdrawal
    # columns — the decision fields are not among them.
    update_sql = cursor.execute.call_args_list[2].args[0]
    set_clause = update_sql.split("SET", 1)[1].split("WHERE", 1)[0]
    assert "decided_by" not in set_clause
    assert "decided_at" not in set_clause
    assert "remarks" not in set_clause


def test_round_n_notes_carry_forward_to_round_n_plus_one(setup):
    """The Safety Officer reviewing round N+1 starts from round N's notes, not a blank round."""
    client, _, cursor = setup
    placement = "Speakers either side of the stage."
    crowd = "Entry through Door A."
    cursor.fetchone.side_effect = [
        approved_round(equipment_placement_notes=placement, crowd_movement_notes=crowd),
        approved_round(equipment_placement_notes=placement, crowd_movement_notes=crowd),
        record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True),
        record_row(
            round_number=3,
            safety_check_id=NEXT_RECORD_ID,
            equipment_placement_notes=placement,
            crowd_movement_notes=crowd,
        ),
    ]

    response = withdraw(client)

    assert response.json["opened"]["equipmentPlacementNotes"] == placement
    assert response.json["opened"]["crowdMovementNotes"] == crowd
    assert cursor.execute.call_args_list[3].args[1][3:5] == [placement, crowd]


def test_the_coordinator_is_recorded_as_submitting_the_new_round(setup):
    """Round N+1 is the coordinator's re-check, so they are its `submitted_by`."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        approved_round(),
        approved_round(),
        record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True),
        record_row(round_number=3, safety_check_id=NEXT_RECORD_ID),
    ]

    withdraw(client)

    assert cursor.execute.call_args_list[3].args[1][2] == COORDINATOR_ID


def test_the_round_is_locked_before_it_is_withdrawn(setup):
    """The race guard: two simultaneous re-checks can't both open round N+1."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        approved_round(),
        approved_round(),
        record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True),
        record_row(round_number=3, safety_check_id=NEXT_RECORD_ID),
    ]

    withdraw(client)

    assert "FOR UPDATE" in cursor.execute.call_args_list[0].args[0]
    assert "FOR UPDATE" in cursor.execute.call_args_list[1].args[0]


# --- Races and refusals ------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "decided", "withdrawn"),
    [
        ("Pending", False, False),
        ("Changes Requested", True, False),
        ("Safety Rejected", True, False),
        ("Approval Withdrawn", True, True),
    ],
)
def test_only_an_approved_round_can_be_withdrawn(status, decided, withdrawn, setup):
    """There is no approval to withdraw, so nothing is written — including round N+1.

    'Approval Withdrawn' is in the list: the loser of a race between two
    re-checks finds the round already withdrawn and must not open a second
    round N+1.
    """
    client, _, cursor = setup
    row = record_row(
        round_number=2, status=status, decided=decided, withdrawn=withdrawn
    )
    cursor.fetchone.side_effect = [row, row]

    response = withdraw(client)

    assert response.status_code == 409
    assert response.json["code"] == "ROUND_NOT_APPROVED"
    assert response.json["currentStatus"] == status
    assert response.json["safetyCheck"]["roundNumber"] == 2
    # Only the two SELECTs ran: no UPDATE, no INSERT.
    assert cursor.execute.call_count == 2


def test_a_round_that_is_not_the_latest_cannot_be_withdrawn(setup):
    """An older round's approval is history; only the round in force can be withdrawn."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        approved_round(round_number=1),
        record_row(round_number=2, status="Pending", safety_check_id=NEXT_RECORD_ID),
    ]

    response = withdraw(client)

    assert response.status_code == 409
    assert response.json["code"] == "NOT_LATEST_ROUND"
    assert cursor.execute.call_count == 2


def test_withdrawing_a_missing_round_is_404(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = withdraw(client)

    assert response.status_code == 404
    assert response.json["message"] == "Safety check not found."
    assert cursor.execute.call_count == 1


# --- Input and configuration -------------------------------------------------


@pytest.mark.parametrize("reason", ["", "   ", None, 42, {"nested": "object"}])
def test_a_reason_is_required(reason, setup):
    """AC1 "told why": the reason is what the event's history quotes."""
    client, _, cursor = setup

    response = withdraw(client, reason=reason)

    assert response.status_code == 400
    assert response.json["message"] == "reason is required."
    cursor.execute.assert_not_called()


def test_a_reason_at_the_limit_is_accepted(setup):
    """Boundary: 2000 characters is the limit, not one under it."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        approved_round(),
        approved_round(),
        record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True),
        record_row(round_number=3, safety_check_id=NEXT_RECORD_ID),
    ]

    response = withdraw(client, reason="x" * 2000)

    assert response.status_code == 201


def test_a_reason_over_the_limit_is_rejected(setup):
    """Boundary: 2001 characters is refused, and nothing is written."""
    client, _, cursor = setup

    response = withdraw(client, reason="x" * 2001)

    assert response.status_code == 400
    assert response.json["message"] == "reason must be 2000 characters or fewer."
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("withdrawn_by", ["not-a-uuid", "", None])
def test_withdrawn_by_must_be_a_uuid(withdrawn_by, setup):
    client, _, cursor = setup

    response = withdraw(client, withdrawnBy=withdrawn_by)

    assert response.status_code == 400
    assert response.json["message"] == "withdrawnBy must be a valid UUID."
    cursor.execute.assert_not_called()


def test_withdraw_requires_a_valid_record_id(setup):
    client, _, cursor = setup

    response = withdraw(client, record_id="not-a-uuid")

    assert response.status_code == 400
    assert response.json["message"] == "The safety check ID must be a valid UUID."
    cursor.execute.assert_not_called()


def test_withdraw_rejects_a_non_object_body(setup):
    client, _, cursor = setup

    response = client.post(
        f"/safety-check-records/{RECORD_ID}/withdraw", json=["not", "an", "object"]
    )

    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    cursor.execute.assert_not_called()


def test_withdraw_without_database_url(no_database):
    response = withdraw(no_database)

    assert response.status_code == 503
    assert "DATABASE_URL" in response.json["message"]


def test_withdraw_database_failure_is_503(setup):
    client, _, cursor = setup
    cursor.execute.side_effect = psycopg2.OperationalError("connection refused")

    response = withdraw(client)

    assert response.status_code == 503
    assert "connection refused" not in response.json["message"]


# --- AC3: the withdrawn round stays in the history ---------------------------


def test_the_history_shows_the_withdrawn_round_and_the_new_one(setup):
    """AC3: both rounds come back, newest first, with the withdrawal recorded."""
    client, _, cursor = setup
    cursor.fetchall.side_effect = [
        [
            record_row(round_number=3, status="Pending", safety_check_id=NEXT_RECORD_ID),
            record_row(
                round_number=2,
                status="Approval Withdrawn",
                decided=True,
                withdrawn=True,
            ),
        ],
        [],
    ]

    response = client.get(f"/safety-check-records?eventId={EVENT_ID}")

    assert response.status_code == 200
    rounds = response.json["safetyChecks"]
    assert [r["roundNumber"] for r in rounds] == [3, 2]
    assert rounds[0]["withdrawnAt"] is None
    assert rounds[0]["withdrawnBy"] is None
    assert rounds[0]["withdrawalReason"] is None
    assert rounds[1]["status"] == "Approval Withdrawn"
    assert rounds[1]["withdrawnAt"] == "2026-11-03T04:00:00+00:00"
    assert rounds[1]["withdrawnBy"] == COORDINATOR_ID
    assert rounds[1]["decidedBy"] == OFFICER_ID


def test_approval_withdrawn_is_a_valid_status_filter(setup):
    """SCRUM-163 AC4 lists earlier decisions, a withdrawn approval among them."""
    client, _, cursor = setup
    cursor.fetchall.side_effect = [
        [record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True)],
        [],
    ]

    response = client.get(
        f"/safety-check-records?eventId={EVENT_ID}&status=Approval Withdrawn"
    )

    assert response.status_code == 200
    assert "Approval Withdrawn" in RECORD_STATUSES
    assert cursor.execute.call_args_list[0].args[1] == [EVENT_ID, "Approval Withdrawn"]


def test_a_withdrawn_round_cannot_be_decided(setup):
    """AC3: round N is history now. The Safety Officer decides round N+1 instead."""
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(
        round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True
    )

    response = client.patch(
        f"/safety-check-records/{RECORD_ID}/decision",
        json={"status": "Safety Approved", "decidedBy": OFFICER_ID},
    )

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_DECIDED"
    assert cursor.execute.call_count == 1


def test_a_withdrawn_round_cannot_be_deleted(setup):
    """Compensation must not take a round the history needs (AC3)."""
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(
        round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True
    )

    response = client.delete(f"/safety-check-records/{RECORD_ID}")

    assert response.status_code == 409
    assert cursor.execute.call_count == 1


# --- Compensation: restore ---------------------------------------------------


def test_restore_deletes_the_new_round_and_reinstates_the_approval(setup):
    """Compensation: the composite could not save the edit, so the withdrawal is undone."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True),
        record_row(round_number=3, status="Pending", safety_check_id=NEXT_RECORD_ID),
        approved_round(),
    ]

    response = restore(client)

    assert response.status_code == 200
    assert response.json["status"] == "Safety Approved"
    assert response.json["withdrawnAt"] is None
    delete_sql, delete_params = cursor.execute.call_args_list[2].args
    assert 'DELETE FROM public."SafetyCheck"' in delete_sql
    assert delete_params == [NEXT_RECORD_ID]
    update_sql, update_params = cursor.execute.call_args_list[3].args
    assert update_params[0] == "Safety Approved"
    assert "withdrawn_at = NULL" in update_sql
    assert "withdrawn_by = NULL" in update_sql
    assert "withdrawal_reason = NULL" in update_sql


def test_restore_is_idempotent(setup):
    """A retry finds round N already approved and round N+1 gone; nothing more to do."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [approved_round(), approved_round()]

    response = restore(client)

    assert response.status_code == 200
    assert response.json["status"] == "Safety Approved"
    # Only the two SELECTs: no second DELETE, no second UPDATE.
    assert cursor.execute.call_count == 2


def test_restore_refuses_when_the_new_round_was_already_decided(setup):
    """A Safety Officer decided round N+1 in the meantime; that decision stands."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True),
        record_row(
            round_number=3,
            status="Safety Approved",
            decided=True,
            safety_check_id=NEXT_RECORD_ID,
        ),
    ]

    response = restore(client)

    assert response.status_code == 409
    assert response.json["code"] == "NOT_RESTORABLE"
    assert cursor.execute.call_count == 2


@pytest.mark.parametrize(
    "opened",
    [
        None,
        record_row(round_number=4, status="Pending", safety_check_id=NEXT_RECORD_ID),
        record_row(
            round_number=3,
            status="Pending",
            safety_check_id=NEXT_RECORD_ID,
            event_id=OTHER_EVENT_ID,
        ),
    ],
    ids=["missing", "not-round-n-plus-1", "another-event"],
)
def test_restore_refuses_a_round_it_did_not_open(opened, setup):
    """This can only undo its own withdrawal, never delete an unrelated round."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True),
        opened,
    ]

    response = restore(client)

    assert response.status_code == 409
    assert response.json["code"] == "NOT_RESTORABLE"
    assert cursor.execute.call_count == 2


@pytest.mark.parametrize("status", ["Pending", "Changes Requested", "Safety Rejected"])
def test_restore_refuses_a_round_that_was_never_withdrawn(status, setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=2, status=status, decided=status != "Pending"),
        None,
    ]

    response = restore(client)

    assert response.status_code == 409
    assert response.json["code"] == "NOT_RESTORABLE"
    assert cursor.execute.call_count == 1


def test_restore_refuses_an_approved_round_that_still_has_a_later_round(setup):
    """Not our own withdrawal: an approved round with a later round is SCRUM-164 territory."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        approved_round(round_number=2),
        record_row(round_number=3, status="Pending", safety_check_id=NEXT_RECORD_ID),
    ]

    response = restore(client)

    assert response.status_code == 409
    assert response.json["code"] == "NOT_RESTORABLE"
    assert cursor.execute.call_count == 2


def test_restoring_a_missing_round_is_404(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = restore(client)

    assert response.status_code == 404
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("opened_id", ["not-a-uuid", "", None])
def test_restore_requires_the_opened_round_id(opened_id, setup):
    client, _, cursor = setup

    response = restore(client, openedSafetyCheckId=opened_id)

    assert response.status_code == 400
    assert response.json["message"] == "openedSafetyCheckId must be a valid UUID."
    cursor.execute.assert_not_called()


def test_restore_requires_a_valid_record_id(setup):
    client, _, cursor = setup

    response = restore(client, record_id="not-a-uuid")

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_restore_rejects_a_non_object_body(setup):
    client, _, cursor = setup

    response = client.post(
        f"/safety-check-records/{RECORD_ID}/restore", json=["not", "an", "object"]
    )

    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    cursor.execute.assert_not_called()


def test_restore_without_database_url(no_database):
    response = restore(no_database)

    assert response.status_code == 503


def test_restore_database_failure_is_503(setup):
    client, _, cursor = setup
    cursor.execute.side_effect = psycopg2.OperationalError("connection refused")

    response = restore(client)

    assert response.status_code == 503
    assert "connection refused" not in response.json["message"]
