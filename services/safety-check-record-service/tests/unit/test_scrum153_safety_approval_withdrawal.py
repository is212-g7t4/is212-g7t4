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

Real
----
- Withdrawing an approval after a high-impact change: the approved round is
  marked withdrawn but kept in the history with its original decision, a new
  pending round opens with the earlier notes, and the withdrawal can be undone
  if the event change fails.
- We check the rounds returned and what is saved.

Doubled
-------
- Safety records (database): hold the rounds each test needs, accept new ones,
  or cannot be reached [Stub]; we check what is saved, and that rounds are
  locked before they change [Mock].
- Sign-in: a test key signs the caller's token (tests/unit/conftest.py) [Stub].

Not proven
----------
- That the event returns to 'Pending Safety Check' and the coordinator is told
  why (-> safety-check-service and event-service SCRUM-153 tests).
- That the saving and locking really work in Postgres, including two people
  acting at the same moment (-> tests/integration/, against a throwaway
  postgres:17.6).
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
    Double: The round is approved, and the safety records accept the next round
        [Stub]; we check what is saved [Mock].
    """
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


def test_withdraw_approval_keeps_original_decision(setup):
    """
    Summary: The withdrawn round keeps who approved it and when.
    AC3: Given a safety approval is withdrawn, then it stays visible in the
        event's safety history.
    Double: The safety records hold the rounds this case needs [Stub]; we check
        what is saved [Mock].
    """
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


def test_withdraw_approval_carries_notes_into_new_round(setup):
    """
    Summary: The new round starts with the previous round's notes.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: The safety records hold the rounds this case needs [Stub]; we check
        what is added [Mock].
    """
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


def test_withdraw_approval_records_coordinator_as_submitter(setup):
    """
    Summary: The coordinator who changed the event is recorded as submitting the new round.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: The safety records hold the rounds this case needs [Stub]; we check
        what is added [Mock].
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        approved_round(),
        approved_round(),
        record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True),
        record_row(round_number=3, safety_check_id=NEXT_RECORD_ID),
    ]

    withdraw(client)

    assert cursor.execute.call_args_list[3].args[1][2] == COORDINATOR_ID


def test_withdraw_approval_locks_round_first(setup):
    """
    Summary: Two changes made at the same moment cannot both withdraw the approval: the round is locked first.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: The safety records hold the round [Stub]; we check it is locked
        before it changes, so two people cannot change it at once [Mock].
    """
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
    ids=["pending", "changes_requested", "safety_rejected", "already_withdrawn"],
)
def test_withdraw_round_that_is_not_approved_returns_409(status, decided, withdrawn, setup):
    """
    Summary: Only an approved round can be withdrawn.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: The round is in a status this action does not apply to [Stub].
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


def test_withdraw_older_round_returns_409(setup):
    """
    Summary: Only the latest round can be withdrawn.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: The event already has a newer round [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        approved_round(round_number=1),
        record_row(round_number=2, status="Pending", safety_check_id=NEXT_RECORD_ID),
    ]

    response = withdraw(client)

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
    Double: The safety records hold no such round [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = withdraw(client)

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
    client, _, cursor = setup

    response = withdraw(client, reason=reason)

    assert response.status_code == 400
    assert response.json["message"] == "reason is required."
    cursor.execute.assert_not_called()


def test_withdraw_with_reason_at_limit_is_accepted(setup):
    """
    Summary: A reason up to the length limit is accepted.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: The safety records hold the rounds this case needs [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        approved_round(),
        approved_round(),
        record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True),
        record_row(round_number=3, safety_check_id=NEXT_RECORD_ID),
    ]

    response = withdraw(client, reason="x" * 2000)

    assert response.status_code == 201


def test_withdraw_with_reason_over_limit_returns_400(setup):
    """
    Summary: A reason over the limit is refused.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: None
    """
    client, _, cursor = setup

    response = withdraw(client, reason="x" * 2001)

    assert response.status_code == 400
    assert response.json["message"] == "reason must be 2000 characters or fewer."
    cursor.execute.assert_not_called()


def test_withdraw_with_withdrawer_in_body_records_signed_in_user(setup):
    """
    Summary: The coordinator recorded as withdrawing is the one signed in, never someone named in the request.
    AC3: Given a safety approval is withdrawn, then it stays visible in the
        event's safety history.
    Double: The safety records hold the rounds this case needs [Stub]; we check
        what is saved [Mock].
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(status="Safety Approved", decided=True)

    withdraw(client, withdrawnBy="99999999-9999-4999-8999-999999999999")

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
    client, _, cursor = setup

    response = withdraw(client, record_id="not-a-uuid")

    assert response.status_code == 400
    assert response.json["message"] == "The safety check ID must be a valid UUID."
    cursor.execute.assert_not_called()


def test_withdraw_with_non_object_body_returns_400(setup):
    """
    Summary: A withdrawal that is not in the expected form is refused.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: None
    """
    client, _, cursor = setup

    response = client.post(
        f"/safety-check-records/{RECORD_ID}/withdraw", json=["not", "an", "object"]
    )

    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    cursor.execute.assert_not_called()


# --- AC3: the withdrawn round stays in the history ---------------------------


def test_list_rounds_after_withdrawal_shows_withdrawn_and_new_round(setup):
    """
    Summary: The history shows the withdrawn approval alongside the new round.
    AC3: Given a safety approval is withdrawn, then it stays visible in the
        event's safety history.
    Double: The safety records hold the withdrawn approval and its replacement
        round [Stub].
    """
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


def test_list_rounds_accepts_approval_withdrawn_filter(setup):
    """
    Summary: Withdrawn approvals can be filtered for.
    AC3: Given a safety approval is withdrawn, then it stays visible in the
        event's safety history.
    Double: The safety records hold no such round [Stub].
    """
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


def test_decide_withdrawn_round_returns_409(setup):
    """
    Summary: A withdrawn approval cannot be decided again.
    AC3: Given a safety approval is withdrawn, then it stays visible in the
        event's safety history.
    Double: The round's approval has been withdrawn [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(
        round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True
    )

    response = client.patch(
        f"/safety-check-records/{RECORD_ID}/decision",
        json={"status": "Safety Approved"},
        headers=bearer(OFFICER_ID, "Safety Officer"),
    )

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_DECIDED"
    assert cursor.execute.call_count == 1


def test_delete_withdrawn_round_returns_409(setup):
    """
    Summary: A withdrawn approval cannot be deleted from the history.
    AC3: Given a safety approval is withdrawn, then it stays visible in the
        event's safety history.
    Double: The round's approval has been withdrawn [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(
        round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True
    )

    response = client.delete(f"/safety-check-records/{RECORD_ID}")

    assert response.status_code == 409
    assert cursor.execute.call_count == 1


# --- Compensation: restore ---------------------------------------------------


def test_restore_removes_new_round_and_reinstates_approval(setup):
    """
    Summary: If the edit fails, the new round is removed and the approval reinstated.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: The safety records hold the rounds this case needs [Stub]; we check
        how they are searched or changed [Mock].
    """
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


def test_restore_twice_has_same_result(setup):
    """
    Summary: Restoring twice has the same result as restoring once.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: The approval has already been reinstated [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [approved_round(), approved_round()]

    response = restore(client)

    assert response.status_code == 200
    assert response.json["status"] == "Safety Approved"
    # Only the two SELECTs: no second DELETE, no second UPDATE.
    assert cursor.execute.call_count == 2


def test_restore_when_new_round_decided_returns_409(setup):
    """
    Summary: An approval is not restored once its replacement round was decided.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: The replacement round has already been decided [Stub].
    """
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
def test_restore_with_round_it_did_not_open_returns_409(opened, setup):
    """
    Summary: Restore only removes the round the withdrawal opened.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: The safety records hold a different round from the one named
        [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=2, status="Approval Withdrawn", decided=True, withdrawn=True),
        opened,
    ]

    response = restore(client)

    assert response.status_code == 409
    assert response.json["code"] == "NOT_RESTORABLE"
    assert cursor.execute.call_count == 2


@pytest.mark.parametrize("status", ["Pending", "Changes Requested", "Safety Rejected"], ids=["pending", "changes_requested", "safety_rejected"])
def test_restore_round_never_withdrawn_returns_409(status, setup):
    """
    Summary: Only a withdrawn approval can be restored.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: The round is in a status this action does not apply to [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=2, status=status, decided=status != "Pending"),
        None,
    ]

    response = restore(client)

    assert response.status_code == 409
    assert response.json["code"] == "NOT_RESTORABLE"
    assert cursor.execute.call_count == 1


def test_restore_approved_round_with_later_round_returns_409(setup):
    """
    Summary: An approval with a later round still in place is not restored.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: The round is approved, but a later round exists [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        approved_round(round_number=2),
        record_row(round_number=3, status="Pending", safety_check_id=NEXT_RECORD_ID),
    ]

    response = restore(client)

    assert response.status_code == 409
    assert response.json["code"] == "NOT_RESTORABLE"
    assert cursor.execute.call_count == 2


def test_restore_missing_round_returns_404(setup):
    """
    Summary: Restoring a round that does not exist is refused.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: The safety records hold no such round [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = restore(client)

    assert response.status_code == 404
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("opened_id", ["not-a-uuid", "", None], ids=["not_a_uuid", "empty", "null"])
def test_restore_without_valid_opened_round_id_returns_400(opened_id, setup):
    """
    Summary: A restore must name the round the withdrawal opened.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: None
    """
    client, _, cursor = setup

    response = restore(client, openedSafetyCheckId=opened_id)

    assert response.status_code == 400
    assert response.json["message"] == "openedSafetyCheckId must be a valid UUID."
    cursor.execute.assert_not_called()


def test_restore_with_bad_round_id_returns_404(setup):
    """
    Summary: A restore must name a valid round.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: None
    """
    client, _, cursor = setup

    response = restore(client, record_id="not-a-uuid")

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_restore_with_non_object_body_returns_400(setup):
    """
    Summary: A restore that is not in the expected form is refused.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: None
    """
    client, _, cursor = setup

    response = client.post(
        f"/safety-check-records/{RECORD_ID}/restore", json=["not", "an", "object"]
    )

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
    Summary: If the safety records cannot be reached, the withdrawal reports the service as unavailable.
    Supporting design check: database errors answer 503 with a safe message
    Double: The safety records cannot be reached [Stub].
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
    Summary: If the safety records cannot be reached, the restore reports the service as unavailable.
    Supporting design check: database errors answer 503 with a safe message
    Double: The safety records cannot be reached [Stub].
    """
    client, _, cursor = setup
    cursor.execute.side_effect = psycopg2.OperationalError("connection refused")

    response = restore(client)

    assert response.status_code == 503
    assert "connection refused" not in response.json["message"]
