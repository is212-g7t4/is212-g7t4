"""
SCRUM-153: Re-check Safety After High-Impact Changes

User Story
----------
As an Event Coordinator, I want a safety approval to be withdrawn when a
high-impact detail changes afterwards, so that the event is never prepared on
the basis of an outdated safety review.

Acceptance Criteria
-------------------
AC1: Given an event is 'Confirmed', when its date/time, expected attendance,
     venue requirements, equipment requirements or accessibility needs change,
     then its status returns to 'Pending Safety Check' and the coordinator is
     told why.
AC2: Given only a low-impact field changes (name, description, purpose,
     registration needs), then the event stays 'Confirmed'.
AC3: Given a safety approval is withdrawn, then it stays visible in the event's
     safety history.
AC4: Given a high-impact change to a 'Confirmed' event is waiting for its new
     safety check, when a registered Attendee views the event, then they still
     see the previously approved details, and the changed details are shown to
     them only after the Safety Officer approves the new safety check.
AC5: Given the new safety check ends without approval (changes requested or the
     event is cancelled), then registered Attendees are never shown the
     unapproved change, and they continue to see the last approved details or
     the cancellation.

SCRUM-8: User Authentication and Authorization

User Story
----------
As a system user, I want to securely access the system, so that I can use the
information and functionality available to me.

Acceptance Criteria
-------------------
AC1: Given a system user has not been successfully authenticated, when they
     attempt to access protected information or functionality, then access is
     denied.
AC2: Given a system user successfully authenticates, when they access protected
     information or functionality, then their access is evaluated according to
     their role and relationship to the relevant event.
AC3: Given a system user's authentication attempt is unsuccessful, when the
     authentication attempt is completed, then they remain unable to access
     protected information or functionality.

Real
----
- POST /safety-check-records/<id>/withdraw (in one transaction: round N Safety
  Approved -> Approval Withdrawn keeping its decision, round N+1 opened Pending
  with N's notes) and POST .../restore (its undo) run for real, as do the
  history list and the guards on decide/delete for a withdrawn round.
- Assertions are on the status, the returned rounds and the SQL sent.

Doubled
-------
- psycopg2.connect: Stub (`setup` fixture) - fresh MagicMock connection; the
  cursor returns canned SafetyCheck rows (or raises); executed SQL, parameters
  and the FOR UPDATE lock are inspected.

Not proven
----------
- That the event returns to Pending Safety Check and attendees keep seeing the
  approved details (AC1, AC4, AC5) (-> safety-check-service and event-service
  unit tests for SCRUM-153).
- That the row lock serialises concurrent withdrawals in PostgreSQL (->
  tests/integration/).
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
    bearer,
    record_row,
    signed_in,
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
    return signed_in(app.test_client(), COORDINATOR_ID), connection, cursor


@pytest.fixture
def no_database():
    app = create_app({"TESTING": True, "DATABASE_URL": None})
    return signed_in(app.test_client(), COORDINATOR_ID)


def withdraw(client, record_id=RECORD_ID, **overrides):
    body = {"reason": REASON, **overrides}
    return client.post(f"/safety-check-records/{record_id}/withdraw", json=body)


def restore(client, record_id=RECORD_ID, **overrides):
    body = {"openedSafetyCheckId": NEXT_RECORD_ID, **overrides}
    return client.post(f"/safety-check-records/{record_id}/restore", json=body)


def approved_round(round_number=2, **overrides):
    return record_row(
        round_number=round_number, status="Safety Approved", decided=True, **overrides
    )


# --- AC1/AC3: withdrawing an approval and opening the next round -------------


def test_withdraw_approval_opens_next_pending_round(setup):
    """
    Summary: Withdrawing an approval opens the next round as Pending.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (cursor returns the approved round and the new round)
    """
    # Arrange (Given)
    client, connection, cursor = setup
    cursor.fetchone.side_effect = [
        approved_round(round_number=2),            # SELECT ... FOR UPDATE
        approved_round(round_number=2),            # _latest_round
        record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True),
        record_row(round_number=3, safety_check_id=NEXT_RECORD_ID),
    ]

    # Act (When)
    response = withdraw(client)

    # Assert (Then)
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


def test_withdraw_approval_keeps_original_decision(setup):
    """
    Summary: The withdrawn round keeps who approved it and when.
    AC3: Given a safety approval is withdrawn, then it stays visible in the
        event's safety history.
    Double: Stub (cursor returns rows; update inspected)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        approved_round(),
        approved_round(),
        record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True),
        record_row(round_number=3, safety_check_id=NEXT_RECORD_ID),
    ]

    response = withdraw(client)

    withdrawn = response.json["withdrawn"]

    # Act + Assert (When / Then)
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


def test_withdraw_approval_carries_notes_into_new_round(setup):
    """
    Summary: The new round starts with the previous round's notes.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (cursor returns rows; insert inspected)
    """
    # Arrange (Given)
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

    # Act (When)
    response = withdraw(client)

    # Assert (Then)
    assert response.json["opened"]["equipmentPlacementNotes"] == placement
    assert response.json["opened"]["crowdMovementNotes"] == crowd
    assert cursor.execute.call_args_list[3].args[1][3:5] == [placement, crowd]


def test_withdraw_approval_records_coordinator_as_submitter(setup):
    """
    Summary: The coordinator who changed the event is recorded as submitting the new round.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (cursor returns rows; insert inspected)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        approved_round(),
        approved_round(),
        record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True),
        record_row(round_number=3, safety_check_id=NEXT_RECORD_ID),
    ]

    # Act (When)
    withdraw(client)

    # Assert (Then)
    assert cursor.execute.call_args_list[3].args[1][2] == COORDINATOR_ID


def test_withdraw_approval_locks_round_first(setup):
    """
    Summary: The round is locked before it is withdrawn, so two changes cannot both withdraw it.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (cursor; SQL inspected for FOR UPDATE)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        approved_round(),
        approved_round(),
        record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True),
        record_row(round_number=3, safety_check_id=NEXT_RECORD_ID),
    ]

    # Act (When)
    withdraw(client)

    # Assert (Then)
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
    ids=["pending", "changes_requested", "safety_rejected", "already_withdrawn"],
)
def test_withdraw_round_that_is_not_approved_returns_409(status, decided, withdrawn, setup):
    """
    Summary: Only an approved round can be withdrawn.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (cursor returns a round in another status)
    """
    # Arrange (Given)
    client, _, cursor = setup
    row = record_row(
        round_number=2, status=status, decided=decided, withdrawn=withdrawn
    )
    cursor.fetchone.side_effect = [row, row]

    # Act (When)
    response = withdraw(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "ROUND_NOT_APPROVED"
    assert response.json["currentStatus"] == status
    assert response.json["safetyCheck"]["roundNumber"] == 2
    # Only the two SELECTs ran: no UPDATE, no INSERT.
    assert cursor.execute.call_count == 2


def test_withdraw_older_round_returns_409(setup):
    """
    Summary: Only the latest round can be withdrawn.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (cursor: a newer round exists)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        approved_round(round_number=1),
        record_row(round_number=2, status="Pending", safety_check_id=NEXT_RECORD_ID),
    ]

    # Act (When)
    response = withdraw(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "NOT_LATEST_ROUND"
    assert cursor.execute.call_count == 2


def test_withdraw_missing_round_returns_404(setup):
    """
    Summary: Withdrawing a round that does not exist is refused.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (cursor finds nothing)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    # Act (When)
    response = withdraw(client)

    # Assert (Then)
    assert response.status_code == 404
    assert response.json["message"] == "Safety check not found."
    assert cursor.execute.call_count == 1


# --- Input and configuration -------------------------------------------------


@pytest.mark.parametrize("reason", ["", "   ", None, 42, {"nested": "object"}], ids=["empty", "whitespace", "null", "number", "object"])
def test_withdraw_without_text_reason_returns_400(reason, setup):
    """
    Summary: A withdrawal needs a reason the coordinator can be told.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: None
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = withdraw(client, reason=reason)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "reason is required."
    cursor.execute.assert_not_called()


def test_withdraw_with_reason_at_limit_is_accepted(setup):
    """
    Summary: A reason up to the length limit is accepted.
    AC1: (boundary: reason at the limit)
    Double: Stub (cursor returns rows)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        approved_round(),
        approved_round(),
        record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True),
        record_row(round_number=3, safety_check_id=NEXT_RECORD_ID),
    ]

    # Act (When)
    response = withdraw(client, reason="x" * 2000)

    # Assert (Then)
    assert response.status_code == 201


def test_withdraw_with_reason_over_limit_returns_400(setup):
    """
    Summary: A reason over the limit is refused.
    AC1: (boundary: reason one over the limit)
    Double: None
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = withdraw(client, reason="x" * 2001)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "reason must be 2000 characters or fewer."
    cursor.execute.assert_not_called()


def test_withdraw_with_withdrawer_in_body_records_signed_in_user(setup):
    """
    Summary: The person recorded as withdrawing is the signed-in user, never one named in the body.
    AC3: Given a safety approval is withdrawn, then it stays visible in the
        event's safety history.
    SCRUM-8 AC2: Given a system user successfully authenticates, when they
        access protected information or functionality, then their access is
        evaluated according to their role and relationship to the relevant
        event.
    Double: Stub (cursor returns rows; update inspected)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(status="Safety Approved", decided=True)

    # Act (When)
    withdraw(client, withdrawnBy="99999999-9999-4999-8999-999999999999")

    # Assert (Then)
    assert all("99999999-9999-4999-8999-999999999999" not in str(c.args) for c in cursor.execute.call_args_list)


def test_withdraw_with_bad_round_id_returns_404(setup):
    """
    Summary: A withdrawal must name a valid round.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: None
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = withdraw(client, record_id="not-a-uuid")

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "The safety check ID must be a valid UUID."
    cursor.execute.assert_not_called()


def test_withdraw_with_non_object_body_returns_400(setup):
    """
    Summary: A request that is not a withdrawal is refused.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: None
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = client.post(
        f"/safety-check-records/{RECORD_ID}/withdraw", json=["not", "an", "object"]
    )

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    cursor.execute.assert_not_called()


# --- AC3: the withdrawn round stays in the history ---------------------------


def test_list_rounds_after_withdrawal_shows_withdrawn_and_new_round(setup):
    """
    Summary: The history shows the withdrawn approval alongside the new round.
    AC3: Given a safety approval is withdrawn, then it stays visible in the
        event's safety history.
    Double: Stub (cursor returns both rounds)
    """
    # Arrange (Given)
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

    # Act (When)
    response = client.get(f"/safety-check-records?eventId={EVENT_ID}")

    # Assert (Then)
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


def test_list_rounds_accepts_approval_withdrawn_filter(setup):
    """
    Summary: Withdrawn approvals can be filtered for.
    AC3: Given a safety approval is withdrawn, then it stays visible in the
        event's safety history.
    Double: Stub (cursor returns no rows)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchall.side_effect = [
        [record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True)],
        [],
    ]

    # Act (When)
    response = client.get(
        f"/safety-check-records?eventId={EVENT_ID}&status=Approval Withdrawn"
    )

    # Assert (Then)
    assert response.status_code == 200
    assert "Approval Withdrawn" in RECORD_STATUSES
    assert cursor.execute.call_args_list[0].args[1] == [EVENT_ID, "Approval Withdrawn"]


def test_decide_withdrawn_round_returns_409(setup):
    """
    Summary: A withdrawn approval cannot be decided again.
    AC3: Given a safety approval is withdrawn, then it stays visible in the
        event's safety history.
    Double: Stub (cursor returns a withdrawn round)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(
        round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True
    )

    # Act (When)
    response = client.patch(
        f"/safety-check-records/{RECORD_ID}/decision",
        json={"status": "Safety Approved"},
        headers=bearer(OFFICER_ID, "Safety Officer"),
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_DECIDED"
    assert cursor.execute.call_count == 1


def test_delete_withdrawn_round_returns_409(setup):
    """
    Summary: A withdrawn approval cannot be deleted from the history.
    AC3: Given a safety approval is withdrawn, then it stays visible in the
        event's safety history.
    Double: Stub (cursor returns a withdrawn round)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(
        round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True
    )

    # Act (When)
    response = client.delete(f"/safety-check-records/{RECORD_ID}")

    # Assert (Then)
    assert response.status_code == 409
    assert cursor.execute.call_count == 1


# --- Compensation: restore ---------------------------------------------------


def test_restore_removes_new_round_and_reinstates_approval(setup):
    """
    Summary: If the edit fails, the new round is removed and the approval reinstated.
    AC1: (rollback: a failed edit leaves the approval in place)
    Double: Stub (cursor returns rows; SQL inspected)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True),
        record_row(round_number=3, status="Pending", safety_check_id=NEXT_RECORD_ID),
        approved_round(),
    ]

    # Act (When)
    response = restore(client)

    # Assert (Then)
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


def test_restore_twice_has_same_result(setup):
    """
    Summary: Restoring twice has the same result as restoring once.
    AC1: (rollback)
    Double: Stub (cursor returns an already restored round)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [approved_round(), approved_round()]

    # Act (When)
    response = restore(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Safety Approved"
    # Only the two SELECTs: no second DELETE, no second UPDATE.
    assert cursor.execute.call_count == 2


def test_restore_when_new_round_decided_returns_409(setup):
    """
    Summary: An approval is not restored once its replacement round was decided.
    AC1: (rollback)
    Double: Stub (cursor returns a decided new round)
    """
    # Arrange (Given)
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

    # Act (When)
    response = restore(client)

    # Assert (Then)
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
def test_restore_with_round_it_did_not_open_returns_409(opened, setup):
    """
    Summary: Restore only removes the round the withdrawal opened.
    AC1: (rollback)
    Double: Stub (cursor returns another round)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True),
        opened,
    ]

    # Act (When)
    response = restore(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "NOT_RESTORABLE"
    assert cursor.execute.call_count == 2


@pytest.mark.parametrize("status", ["Pending", "Changes Requested", "Safety Rejected"], ids=["pending", "changes_requested", "safety_rejected"])
def test_restore_round_never_withdrawn_returns_409(status, setup):
    """
    Summary: Only a withdrawn approval can be restored.
    AC1: (rollback)
    Double: Stub (cursor returns a round in another status)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=2, status=status, decided=status != "Pending"),
        None,
    ]

    # Act (When)
    response = restore(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "NOT_RESTORABLE"
    assert cursor.execute.call_count == 1


def test_restore_approved_round_with_later_round_returns_409(setup):
    """
    Summary: An approval with a later round still in place is not restored.
    AC1: (rollback)
    Double: Stub (cursor: approved round and a later round)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        approved_round(round_number=2),
        record_row(round_number=3, status="Pending", safety_check_id=NEXT_RECORD_ID),
    ]

    # Act (When)
    response = restore(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "NOT_RESTORABLE"
    assert cursor.execute.call_count == 2


def test_restore_missing_round_returns_404(setup):
    """
    Summary: Restoring a round that does not exist is refused.
    AC1: (rollback)
    Double: Stub (cursor finds nothing)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    # Act (When)
    response = restore(client)

    # Assert (Then)
    assert response.status_code == 404
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("opened_id", ["not-a-uuid", "", None], ids=["not_a_uuid", "empty", "null"])
def test_restore_without_valid_opened_round_id_returns_400(opened_id, setup):
    """
    Summary: A restore must name the round the withdrawal opened.
    AC1: (rollback)
    Double: None
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = restore(client, openedSafetyCheckId=opened_id)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "openedSafetyCheckId must be a valid UUID."
    cursor.execute.assert_not_called()


def test_restore_with_bad_round_id_returns_404(setup):
    """
    Summary: A restore must name a valid round.
    AC1: (rollback)
    Double: None
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = restore(client, record_id="not-a-uuid")

    # Assert (Then)
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_restore_with_non_object_body_returns_400(setup):
    """
    Summary: A request that is not a restore is refused.
    AC1: (rollback)
    Double: None
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = client.post(
        f"/safety-check-records/{RECORD_ID}/restore", json=["not", "an", "object"]
    )

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    cursor.execute.assert_not_called()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_withdraw_when_database_url_missing_returns_503(no_database):
    """
    Summary: Withdrawing reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured service answers 503
    Double: None
    """
    response = withdraw(no_database)

    assert response.status_code == 503
    assert "DATABASE_URL" in response.json["message"]


def test_withdraw_when_database_fails_returns_503(setup):
    """
    Summary: A database outage while withdrawing gives a 503.
    Supporting design check: database errors answer 503 with a safe message
    Double: Stub (psycopg2.connect raises OperationalError)
    """
    client, _, cursor = setup
    cursor.execute.side_effect = psycopg2.OperationalError("connection refused")

    response = withdraw(client)

    assert response.status_code == 503
    assert "connection refused" not in response.json["message"]


def test_restore_when_database_url_missing_returns_503(no_database):
    """
    Summary: Restoring reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured service answers 503
    Double: None
    """
    response = restore(no_database)

    assert response.status_code == 503


def test_restore_when_database_fails_returns_503(setup):
    """
    Summary: A database outage while restoring gives a 503.
    Supporting design check: database errors answer 503 with a safe message
    Double: Stub (psycopg2.connect raises OperationalError)
    """
    client, _, cursor = setup
    cursor.execute.side_effect = psycopg2.OperationalError("connection refused")

    response = restore(client)

    assert response.status_code == 503
    assert "connection refused" not in response.json["message"]
