"""SCRUM-153: the event-side half of "re-check safety after a high-impact change".

AC1 Given an event is 'Confirmed', when its date/time, expected attendance,
    venue requirements, equipment requirements or accessibility needs change,
    then its status returns to 'Pending Safety Check' and the coordinator is
    told why.
AC2 Given only a low-impact field changes (name, description, purpose,
    registration needs), then the event stays 'Confirmed'.
AC3 Given a safety approval is withdrawn, then it stays visible in the event's
    safety history — the event-side line lives in `actionHistory` here; the
    `SafetyCheck` rounds themselves belong to Safety Check Record Service.

`PATCH /events/<id>/details` is the only endpoint that classifies a change as
low- or high-impact, and the gate lives here: a high-impact edit of a
'Confirmed' event is refused unless it arrives from Safety Check Service with
the approval already withdrawn. So the UI can be skipped and the rule still
holds.

Database calls are mocked; no live database writes.
"""
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.models import (
    EDITABLE_FIELDS,
    FIELDS,
    HIGH_IMPACT_FIELDS,
    LOW_IMPACT_FIELDS,
    SAFETY_TRANSITIONS,
)
from tests.unit.factories import signed_in

EVENT_ID = "00000000-0000-0000-0000-000000000001"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OTHER_COORDINATOR_ID = "22222222-2222-4222-8222-222222222222"
OFFICER_ID = "33333333-3333-4333-8333-333333333333"
ROUND_TWO_ID = "55555555-5555-4555-8555-555555555555"
ROUND_THREE_ID = "66666666-6666-4666-8666-666666666666"
OTHER_ROUND_ID = "77777777-7777-4777-8777-777777777777"
INTERNAL_TOKEN = "test-internal-token"
INTERNAL_HEADERS = {"X-Internal-Service-Token": INTERNAL_TOKEN}

RECHECK = {
    "withdrawnSafetyCheckId": ROUND_TWO_ID,
    "safetyCheckId": ROUND_THREE_ID,
    "roundNumber": 3,
    # SCRUM-46: rechecks preserve the last effective actual venue before edits.
    "venueBefore": "Grand Hall",
}

# The coordinator's approve decision, which an edit must never erase.
DECISION = {
    "status": "Approved",
    "coordinatorId": COORDINATOR_ID,
    "decidedAt": "2026-10-02T01:00:00+00:00",
    "reason": None,
}
# The history a 'Confirmed' event carries: submitted for its check, then
# approved. SCRUM-150 writes the second entry, and its `safetyCheckId` is what
# the gate matches the withdrawn round against.
APPROVED_HISTORY = [
    {
        "status": "Pending Safety Check",
        "details": "Submitted for Operational Safety Check (round 2).",
        "coordinatorId": COORDINATOR_ID,
        "safetyCheckId": ROUND_TWO_ID,
        "recordedAt": "2026-10-03T01:00:00+00:00",
    },
    {
        "status": "Confirmed",
        "details": "Operational Safety Check approved (round 2).",
        "decidedBy": OFFICER_ID,
        "safetyCheckId": ROUND_TWO_ID,
        "remarks": "Looks safe.",
        "recordedAt": "2026-10-04T01:00:00+00:00",
    },
]


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": "unused-test-url",
            "INTERNAL_SERVICE_TOKEN": INTERNAL_TOKEN,
        }
    )
    return signed_in(app.test_client()), connection, cursor


@pytest.fixture
def no_token(monkeypatch):
    """No INTERNAL_SERVICE_TOKEN configured: the token-locked paths fail closed (SCRUM-10)."""
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": "unused-test-url",
            "INTERNAL_SERVICE_TOKEN": None,
        }
    )
    return signed_in(app.test_client()), connection, cursor


@pytest.fixture
def no_database():
    app = create_app({"TESTING": True, "DATABASE_URL": None})
    return signed_in(app.test_client())


def event_row(
    status="Confirmed",
    coordinator_id=COORDINATOR_ID,
    description="A workshop for the community.",
    purpose="Skills sharing.",
    decision=None,
    action_history=None,
    event_name="Community Workshop",
    start=datetime(2026, 11, 10, 9),
    end=datetime(2026, 11, 10, 12),
    expected_attendance=120,
    venue_requirements="Hall A",
    equipment_requirements="Two microphones",
    accessibility_needs="Step-free access",
    registration_needs="Name and email",
):
    row = {column: "" for column in FIELDS.values()}
    row.update(
        event_id=EVENT_ID,
        event_name=event_name,
        status=status,
        coordinator_id=coordinator_id,
        organiser_id=None,
        submission_date=datetime(2026, 10, 1, 8, tzinfo=UTC),
        preferred_start_date=start,
        preferred_end_date=end,
        expected_attendance=expected_attendance,
        venue_requirements=venue_requirements,
        equipment_requirements=equipment_requirements,
        accessibility_needs=accessibility_needs,
        registration_needs=registration_needs,
        description=json.dumps(
            {
                "_connectsphere": "event-submission-v1",
                "description": description,
                "purpose": purpose,
                "decision": decision if decision is not None else DECISION,
                "decisionHistory": [decision if decision is not None else DECISION],
                "actionDetails": "Venue confirmed with Venue Staff.",
                "actionHistory": (
                    APPROVED_HISTORY if action_history is None else action_history
                ),
            }
        ),
    )
    return row


def patch_details(client, changes, headers=None, **overrides):
    body = {"coordinatorId": COORDINATOR_ID, "changes": changes, **overrides}
    return client.patch(f"/events/{EVENT_ID}/details", json=body, headers=headers or {})


def saved_metadata(cursor):
    """The metadata JSON the UPDATE wrote."""
    params = cursor.execute.call_args_list[1].args[1]
    return json.loads(params[-3])


def saved_status(cursor):
    return cursor.execute.call_args_list[1].args[1][-2]


# A changed value per high-impact field, for the parametrised gate tests. The
# start moves earlier and the end later, so each one alone still leaves the
# event's window valid (end after start) and the test exercises the gate
# rather than validation.
HIGH_IMPACT_CHANGES = {
    "preferredStartDate": "2026-11-10T08:00:00",
    "preferredEndDate": "2026-11-10T18:00:00",
    "expectedAttendance": "400",
    "venueRequirements": "Hall B, with a stage",
    "equipmentRequirements": "Four microphones and a projector",
    "accessibilityNeeds": "Step-free access and a hearing loop",
}
LOW_IMPACT_CHANGES = {
    "eventName": "Community Workshop (Autumn)",
    "description": "A rewritten description of the same workshop.",
    "purpose": "Skills sharing and networking.",
    "registrationNeeds": "Name, email and dietary requirements",
}


# --- AC1: the gate ------------------------------------------------------------


@pytest.mark.parametrize("field", list(HIGH_IMPACT_FIELDS))
def test_high_impact_change_to_a_confirmed_event_is_gated(field, setup):
    """AC1: each of the five AC1 details alone is enough to require a re-check.

    Refused without `safetyRecheck`, and nothing is written — the approval has
    to be withdrawn by the safety workflow first.
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()

    response = patch_details(client, {field: HIGH_IMPACT_CHANGES[field]})

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_RECHECK_REQUIRED"
    assert response.json["highImpactFields"] == [field]
    assert response.json["changedFields"] == [field]
    assert response.json["labels"]
    assert response.json["labels"][0] in response.json["message"]
    assert "withdraw this event's safety approval" in response.json["message"]
    assert "Pending Safety Check" in response.json["message"]
    # Only the SELECT ran.
    assert cursor.execute.call_count == 1


def test_a_recheck_saves_the_fields_and_moves_the_event(setup):
    """AC1: with the approval withdrawn, the edit and the status move land together."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row(),
        event_row(
            status="Pending Safety Check",
            expected_attendance=400,
            start=datetime(2026, 11, 10, 8),
        ),
    ]

    response = patch_details(
        client,
        {"expectedAttendance": "400", "preferredStartDate": "2026-11-10T08:00:00"},
        headers=INTERNAL_HEADERS,
        safetyRecheck=RECHECK,
    )

    assert response.status_code == 200
    assert response.json["status"] == "Pending Safety Check"
    assert response.json["expectedAttendance"] == "400"
    # One UPDATE, carrying both the columns and the new status, so AC1's
    # status change can never land without the change that caused it.
    update_sql, params = cursor.execute.call_args_list[1].args
    assert 'UPDATE public."Event"' in update_sql
    assert "expected_attendance = %s" in update_sql
    assert "status = %s" in update_sql
    assert saved_status(cursor) == "Pending Safety Check"
    assert 400 in params
    # SCRUM-168 also saves the new round notification in this transaction.
    assert cursor.execute.call_count == 3


def test_the_recheck_history_entry_says_why(setup):
    """AC1 "the coordinator is told why": the history line names the changed details."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row(status="Pending Safety Check")]

    patch_details(
        client,
        {"expectedAttendance": "400", "venueRequirements": "Hall B, with a stage"},
        headers=INTERNAL_HEADERS,
        safetyRecheck=RECHECK,
    )

    entry = saved_metadata(cursor)["actionHistory"][-1]
    assert entry["status"] == "Pending Safety Check"
    assert entry["details"] == (
        "Safety approval withdrawn because Expected attendance and Venue "
        "requirements changed after approval. The event needs a new "
        "Operational Safety Check (round 3) before it can proceed to preparation."
    )
    assert entry["changedFields"] == ["expectedAttendance", "venueRequirements"]
    assert entry["highImpactFields"] == ["expectedAttendance", "venueRequirements"]
    assert entry["coordinatorId"] == COORDINATOR_ID
    assert entry["withdrawnSafetyCheckId"] == ROUND_TWO_ID
    assert entry["safetyCheckId"] == ROUND_THREE_ID
    assert entry["recordedAt"]


def test_both_date_fields_read_as_one_label(setup):
    """AC1: changing start and end is one "Date/time" change, said once."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row(status="Pending Safety Check")]

    patch_details(
        client,
        {
            "preferredStartDate": "2026-11-11T09:00:00",
            "preferredEndDate": "2026-11-11T12:00:00",
        },
        headers=INTERNAL_HEADERS,
        safetyRecheck=RECHECK,
    )

    details = saved_metadata(cursor)["actionHistory"][-1]["details"]
    assert details.count("Date/time") == 1
    assert details.startswith("Safety approval withdrawn because Date/time changed")


def test_the_gate_message_lists_both_date_fields_once(setup):
    """The 409 the confirm step renders reads the same way."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()

    response = patch_details(
        client,
        {
            "preferredStartDate": "2026-11-11T09:00:00",
            "preferredEndDate": "2026-11-11T12:00:00",
        },
    )

    assert response.json["labels"] == ["Date/time"]
    assert response.json["message"].count("Date/time") == 1


def test_the_new_round_is_what_the_safety_officer_decides(setup):
    """AC1 -> SCRUM-150: the approve path finds round N+1 with no change of its own.

    The re-check entry carries `safetyCheckId` = round N+1, which is exactly
    what `_stale_safety_check_check` looks for (the latest 'Pending Safety
    Check' entry with a round id), so approving round N+1 works unchanged.
    """
    from app.models import update_event_safety_status

    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row(status="Pending Safety Check")]
    patch_details(
        client,
        {"expectedAttendance": "400"},
        headers=INTERNAL_HEADERS,
        safetyRecheck=RECHECK,
    )
    after_recheck = saved_metadata(cursor)

    cursor.reset_mock()
    row = event_row(status="Pending Safety Check")
    row["description"] = json.dumps(after_recheck)
    cursor.fetchone.side_effect = [row, event_row(status="Confirmed")]

    updated = update_event_safety_status(
        "unused-test-url",
        EVENT_ID,
        "Confirmed",
        ROUND_THREE_ID,
        3,
        decided_by=OFFICER_ID,
        remarks="Re-reviewed and safe.",
        # The final direct owner call supplies the corresponding approved venue.
        attendee_venue="Grand Hall",
    )

    assert updated["status"] == "Confirmed"


# --- AC2: low-impact edits ----------------------------------------------------


@pytest.mark.parametrize("field", list(LOW_IMPACT_FIELDS))
def test_low_impact_change_keeps_a_confirmed_event_confirmed(field, setup):
    """AC2: name, description, purpose and registration needs never withdraw an approval.

    `description` and `purpose` live inside the `description` JSON rather than
    in columns of their own, so both are covered here.
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row()]

    response = patch_details(client, {field: LOW_IMPACT_CHANGES[field]})

    assert response.status_code == 200
    assert response.json["status"] == "Confirmed"
    assert saved_status(cursor) == "Confirmed"
    entry = saved_metadata(cursor)["actionHistory"][-1]
    assert entry["status"] == "Confirmed"
    assert entry["changedFields"] == [field]
    assert "withdrawn" not in entry["details"]
    # No safety fields on a plain edit's entry.
    assert "safetyCheckId" not in entry
    assert "withdrawnSafetyCheckId" not in entry
    assert "highImpactFields" not in entry


def test_a_low_impact_edit_records_what_changed(setup):
    """The history says which details were edited, by label."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row()]

    patch_details(
        client,
        {
            "eventName": LOW_IMPACT_CHANGES["eventName"],
            "purpose": LOW_IMPACT_CHANGES["purpose"],
        },
    )

    entry = saved_metadata(cursor)["actionHistory"][-1]
    assert entry["details"] == "Event details updated: Event name, Purpose."


def test_description_and_purpose_are_written_into_the_metadata(setup):
    """Both live in the `description` JSON, not in columns."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row()]

    patch_details(
        client,
        {
            "description": LOW_IMPACT_CHANGES["description"],
            "purpose": LOW_IMPACT_CHANGES["purpose"],
        },
    )

    metadata = saved_metadata(cursor)
    assert metadata["description"] == LOW_IMPACT_CHANGES["description"]
    assert metadata["purpose"] == LOW_IMPACT_CHANGES["purpose"]


def test_a_mixed_edit_on_a_confirmed_event_saves_nothing(setup):
    """AC1/AC2: the low-impact half is not quietly saved while the rest is refused.

    An edit is one change. Saving half of it would leave the coordinator
    unsure which fields took effect.
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()

    response = patch_details(
        client,
        {
            "eventName": LOW_IMPACT_CHANGES["eventName"],
            "expectedAttendance": "400",
        },
    )

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_RECHECK_REQUIRED"
    assert response.json["changedFields"] == ["eventName", "expectedAttendance"]
    assert response.json["highImpactFields"] == ["expectedAttendance"]
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"expectedAttendance": "120"},
        {"expectedAttendance": " 120 "},
        {"venueRequirements": " Hall A "},
        {"preferredStartDate": "2026-11-10T09:00:00.000"},
        {"preferredStartDate": "2026-11-10T09:00"},
        {"eventName": "Community Workshop"},
        {"description": "A workshop for the community."},
        {
            "preferredStartDate": "2026-11-10T09:00",
            "expectedAttendance": "120",
            "venueRequirements": "Hall A",
        },
    ],
)
def test_resaving_unchanged_values_changes_nothing(changes, setup):
    """AC2: "changed" is decided on normalised values, so re-saving the form is safe.

    Without this, opening the edit dialog and pressing save would withdraw a
    safety approval that nothing had invalidated.
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()

    response = patch_details(client, changes)

    assert response.status_code == 200
    assert response.json["status"] == "Confirmed"
    # No UPDATE at all: no status change and no history entry.
    assert cursor.execute.call_count == 1
    assert len(response.json["actionHistory"]) == len(APPROVED_HISTORY)


# --- Regression: the rest of the event's metadata survives --------------------


@pytest.mark.parametrize(
    "changes",
    [
        {"eventName": LOW_IMPACT_CHANGES["eventName"]},
        {"description": LOW_IMPACT_CHANGES["description"]},
        {"registrationNeeds": LOW_IMPACT_CHANGES["registrationNeeds"]},
    ],
)
def test_an_edit_preserves_the_decision_and_earlier_history(changes, setup):
    """Rewriting `description` must not drop the metadata stored alongside it."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row()]

    patch_details(client, changes)

    metadata = saved_metadata(cursor)
    assert metadata["decision"] == DECISION
    assert metadata["decisionHistory"] == [DECISION]
    assert metadata["actionDetails"] == "Venue confirmed with Venue Staff."
    assert metadata["actionHistory"][: len(APPROVED_HISTORY)] == APPROVED_HISTORY
    assert len(metadata["actionHistory"]) == len(APPROVED_HISTORY) + 1
    assert metadata["_connectsphere"] == "event-submission-v1"


def test_a_recheck_preserves_the_decision_and_earlier_history(setup):
    """AC3: the approval entry stays in the history, with the withdrawal after it."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row(status="Pending Safety Check")]

    patch_details(
        client,
        {"expectedAttendance": "400"},
        headers=INTERNAL_HEADERS,
        safetyRecheck=RECHECK,
    )

    metadata = saved_metadata(cursor)
    assert metadata["decision"] == DECISION
    assert metadata["actionHistory"][1] == APPROVED_HISTORY[1]
    assert metadata["actionHistory"][1]["details"] == (
        "Operational Safety Check approved (round 2)."
    )


# --- Races and the gate's edges ----------------------------------------------


@pytest.mark.parametrize("withdrawn_id", [OTHER_ROUND_ID, ROUND_THREE_ID])
def test_withdrawing_the_wrong_round_is_refused(withdrawn_id, setup):
    """A stale or made-up round can't move the event, with no call to another service."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()

    response = patch_details(
        client,
        {"expectedAttendance": "400"},
        headers=INTERNAL_HEADERS,
        safetyRecheck={**RECHECK, "withdrawnSafetyCheckId": withdrawn_id},
    )

    assert response.status_code == 409
    assert response.json["code"] == "STALE_SAFETY_CHECK"
    assert cursor.execute.call_count == 1


def test_a_confirmed_event_with_no_approval_entry_is_refused(setup):
    """Nothing in the history names the approval this round claims to withdraw."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(action_history=[])

    response = patch_details(
        client,
        {"expectedAttendance": "400"},
        headers=INTERNAL_HEADERS,
        safetyRecheck=RECHECK,
    )

    assert response.status_code == 409
    assert response.json["code"] == "STALE_SAFETY_CHECK"


@pytest.mark.parametrize(
    "headers",
    [{}, {"X-Internal-Service-Token": "wrong-token"}],
    ids=["missing", "wrong"],
)
def test_the_recheck_block_without_the_token_is_still_gated(headers, setup):
    """The gate: `safetyRecheck` is only believed from Safety Check Service.

    Otherwise a browser could claim the approval was withdrawn and move the
    event itself.
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()

    response = patch_details(
        client, {"expectedAttendance": "400"}, headers=headers, safetyRecheck=RECHECK
    )

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_RECHECK_REQUIRED"
    assert cursor.execute.call_count == 1


def test_without_a_configured_token_the_recheck_is_refused(no_token):
    """Failure (SCRUM-10): the lock fails closed, so a `safetyRecheck` block alone no longer suffices."""
    client, _, cursor = no_token

    response = patch_details(
        client, {"expectedAttendance": "400"}, safetyRecheck=RECHECK
    )

    assert response.status_code == 503
    assert response.json["code"] == "INTERNAL_AUTH_NOT_CONFIGURED"
    cursor.execute.assert_not_called()


def test_without_a_configured_token_a_plain_coordinator_edit_still_works(no_token):
    """Normal: only the re-check and the Lead's edit need the lock; an ordinary edit does not."""
    client, _, cursor = no_token
    cursor.fetchone.side_effect = [event_row(), event_row()]

    response = patch_details(client, {"eventName": LOW_IMPACT_CHANGES["eventName"]})

    assert response.status_code == 200


def test_without_a_configured_token_the_lead_edit_is_refused(no_token):
    """Failure (SCRUM-10): acting as the Lead needs the lock too, so it is refused when unconfigured."""
    client, _, cursor = no_token

    response = patch_details(client, {"eventName": "X"}, actorRole="Event Coordinator Lead")

    assert response.status_code == 503
    cursor.execute.assert_not_called()


def test_safety_status_cannot_make_the_recheck_move_on_its_own(setup):
    """The gate's other half: 'Confirmed -> Pending Safety Check' needs the edit.

    `/safety-status` can reach every other safety move, but not this one — a
    `Confirmed` event may only go back for re-review together with the
    high-impact change that invalidated its approval.
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(status="Confirmed")

    response = client.patch(
        f"/events/{EVENT_ID}/safety-status",
        json={
            "status": "Pending Safety Check",
            "safetyCheckId": ROUND_THREE_ID,
            "roundNumber": 3,
            "coordinatorId": COORDINATOR_ID,
        },
        headers=INTERNAL_HEADERS,
    )

    assert response.status_code == 409
    assert response.json["code"] == "INVALID_SAFETY_TRANSITION"
    assert response.json["currentStatus"] == "Confirmed"
    # Only the SELECT ran: nothing was written.
    assert cursor.execute.call_count == 1


def test_the_recheck_move_is_the_only_way_out_of_confirmed():
    """AC1: 'Confirmed' gains exactly one outgoing safety move, and only via /details."""
    from app.models import RECHECK_ONLY_MOVES

    assert SAFETY_TRANSITIONS["Confirmed"] == {"Pending Safety Check"}
    assert RECHECK_ONLY_MOVES == {("Confirmed", "Pending Safety Check")}
    # 'Cancelled' stays terminal (SCRUM-151 AC4).
    assert "Cancelled" not in SAFETY_TRANSITIONS


# --- Statuses other than 'Confirmed' -----------------------------------------


@pytest.mark.parametrize("field", list(HIGH_IMPACT_FIELDS))
def test_high_impact_edits_are_blocked_while_the_check_is_pending(field, setup):
    """Q3: don't move the goalposts under a Safety Officer who is mid-review."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(status="Pending Safety Check")

    response = patch_details(client, {field: HIGH_IMPACT_CHANGES[field]})

    assert response.status_code == 409
    assert response.json["code"] == "EVENT_UNDER_SAFETY_REVIEW"
    assert response.json["currentStatus"] == "Pending Safety Check"
    assert "after the Safety Officer's decision" in response.json["message"]
    assert cursor.execute.call_count == 1


def test_low_impact_edits_are_allowed_while_the_check_is_pending(setup):
    """Q3: a rename doesn't affect the review, so it saves as usual."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row(status="Pending Safety Check"),
        event_row(status="Pending Safety Check"),
    ]

    response = patch_details(client, {"eventName": LOW_IMPACT_CHANGES["eventName"]})

    assert response.status_code == 200
    assert response.json["status"] == "Pending Safety Check"
    assert saved_status(cursor) == "Pending Safety Check"


@pytest.mark.parametrize(
    "status", ["Submitted", "Under Review", "Approved", "Safety Changes Requested"]
)
def test_before_confirmation_a_high_impact_edit_just_saves(status, setup):
    """AC1's scope: only a 'Confirmed' event has a safety approval to withdraw.

    A 'Safety Changes Requested' event is ordinary rework (SCRUM-164), and the
    rest never reached a safety decision, so none of them is gated.
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(status=status), event_row(status=status)]

    response = patch_details(client, {"expectedAttendance": "400"})

    assert response.status_code == 200
    assert response.json["status"] == status
    assert saved_status(cursor) == status
    entry = saved_metadata(cursor)["actionHistory"][-1]
    assert entry["details"] == "Event details updated: Expected attendance."
    assert "highImpactFields" not in entry


@pytest.mark.parametrize("status", ["Rejected", "Cancelled"])
def test_a_terminal_event_cannot_be_edited(status, setup):
    """A rejected or cancelled event's details are history, not a working draft."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(status=status)

    response = patch_details(client, {"eventName": LOW_IMPACT_CHANGES["eventName"]})

    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_EDITABLE"
    assert response.json["currentStatus"] == status
    assert cursor.execute.call_count == 1


# --- Access and input ---------------------------------------------------------


def test_a_stranger_is_refused_before_any_status_logic(setup):
    """403 and nothing else: a caller who isn't the coordinator learns nothing."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=OTHER_COORDINATOR_ID)

    response = patch_details(client, {"expectedAttendance": "400"})

    assert response.status_code == 403
    assert "not assigned to the current coordinator" in response.json["message"]
    assert "SAFETY_RECHECK_REQUIRED" not in response.get_data(as_text=True)
    assert cursor.execute.call_count == 1


def test_an_unassigned_event_is_refused(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=None)

    response = patch_details(client, {"eventName": "Renamed"})

    assert response.status_code == 403


def test_a_missing_event_is_404(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = patch_details(client, {"eventName": "Renamed"})

    assert response.status_code == 404
    assert response.json["message"] == "Event request not found."


def test_a_signed_in_coordinator_is_required(setup):
    """SCRUM-8: the editor is the signed-in user, never a coordinatorId in the body."""
    _, _, cursor = setup
    client = setup[0].application.test_client()

    response = client.patch(
        f"/events/{EVENT_ID}/details",
        json={"coordinatorId": COORDINATOR_ID, "changes": {"eventName": "Renamed"}},
    )

    assert response.status_code == 401
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("changes", [{}, None, [], "eventName", 7])
def test_changes_must_be_a_non_empty_object(changes, setup):
    client, _, cursor = setup

    response = patch_details(client, changes)

    assert response.status_code == 400
    assert response.json["message"] == (
        "changes must be a non-empty object of fields to update."
    )
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("field", ["status", "coordinatorId", "organiserId", "id"])
def test_fields_that_are_not_editable_are_rejected(field, setup):
    """Status and ownership have their own endpoints and their own rules."""
    client, _, cursor = setup

    response = patch_details(client, {field: "whatever"})

    assert response.status_code == 400
    assert field in response.json["message"]
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("value", [120, None, {"nested": "object"}, ["a"]])
def test_every_change_value_must_be_text(value, setup):
    """As on submit: the API takes text and converts at the boundary."""
    client, _, cursor = setup

    response = patch_details(client, {"expectedAttendance": value})

    assert response.status_code == 400
    assert response.json["message"] == "Every value in changes must be text."
    cursor.execute.assert_not_called()


def test_a_non_object_body_is_rejected(setup):
    client, _, cursor = setup

    response = client.patch(f"/events/{EVENT_ID}/details", json=["not", "an", "object"])

    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"expectedAttendance": "0"}, "Expected Attendance"),
        ({"expectedAttendance": "-5"}, "Expected Attendance"),
        ({"expectedAttendance": "not a number"}, "Expected Attendance"),
        ({"preferredEndDate": "2026-11-10T08:00:00"}, "Preferred End Date & Time"),
        ({"preferredStartDate": "not a date"}, "Preferred dates"),
    ],
)
def test_the_merged_values_are_validated(changes, expected, setup):
    """An edit is held to the same rules as a submission, on the merged event."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()

    response = patch_details(client, changes, headers=INTERNAL_HEADERS)

    assert response.status_code == 400
    assert response.json["message"] == "Please correct the event details."
    assert any(expected in error for error in response.json["errors"])
    # Validation runs before the gate, so nothing is written.
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("field", ["eventName", "description", "purpose"])
def test_a_required_field_cannot_be_blanked(field, setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()

    response = patch_details(client, {field: "   "})

    assert response.status_code == 400
    assert response.json["missingFields"]


def test_filling_in_a_date_an_event_never_had_is_a_change(setup):
    """An event stored without its dates: setting one is a high-impact change.

    The merged event is valid, so this reaches the comparison rather than
    validation — a blank stored date is not "the same as" a real one.
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(start=None)

    response = patch_details(client, {"preferredStartDate": "2026-11-10T09:00:00"})

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_RECHECK_REQUIRED"
    assert response.json["highImpactFields"] == ["preferredStartDate"]


@pytest.mark.parametrize(
    ("field", "column", "recheck"),
    [
        ("registrationNeeds", "registration_needs", False),
        ("accessibilityNeeds", "accessibility_needs", True),
    ],
)
def test_an_optional_field_can_be_cleared(field, column, recheck, setup):
    """Only the required six have to stay filled in.

    Clearing `accessibilityNeeds` is a high-impact change, so it needs the
    re-check; clearing `registrationNeeds` doesn't.
    """
    client, _, cursor = setup
    cleared = event_row()
    cleared[column] = ""
    cursor.fetchone.side_effect = [event_row(), cleared]

    response = patch_details(
        client,
        {field: ""},
        headers=INTERNAL_HEADERS,
        **({"safetyRecheck": RECHECK} if recheck else {}),
    )

    assert response.status_code == 200
    assert response.json[field] == ""


@pytest.mark.parametrize(
    "recheck",
    [
        "not-an-object",
        {"safetyCheckId": ROUND_THREE_ID, "roundNumber": 3},
        {"withdrawnSafetyCheckId": "nope", "safetyCheckId": ROUND_THREE_ID, "roundNumber": 3},
        {"withdrawnSafetyCheckId": ROUND_TWO_ID, "safetyCheckId": "nope", "roundNumber": 3},
        {**RECHECK, "roundNumber": 0},
        {**RECHECK, "roundNumber": "3"},
        {**RECHECK, "roundNumber": True},
        {k: v for k, v in RECHECK.items() if k != "roundNumber"},
    ],
)
def test_a_malformed_recheck_block_is_rejected(recheck, setup):
    client, _, cursor = setup

    response = patch_details(
        client,
        {"expectedAttendance": "400"},
        headers=INTERNAL_HEADERS,
        safetyRecheck=recheck,
    )

    assert response.status_code == 400
    assert "safetyRecheck" in response.json["message"]
    cursor.execute.assert_not_called()


def test_every_editable_field_is_classified_exactly_once():
    """The two sets partition the editable fields — no field is both or neither."""
    assert set(LOW_IMPACT_FIELDS) | set(HIGH_IMPACT_FIELDS) == set(EDITABLE_FIELDS)
    assert not set(LOW_IMPACT_FIELDS) & set(HIGH_IMPACT_FIELDS)
    # Every editable field is a column this service owns, or lives in the
    # `description` JSON (`purpose`).
    # withdrawalDeadline is set by the organiser during event creation and is
    # deliberately not part of coordinator edits or safety re-checks.
    assert set(EDITABLE_FIELDS) - {"purpose"} == set(FIELDS) - {
        "withdrawalDeadline"
    }


def test_details_without_database_url(no_database):
    response = patch_details(no_database, {"eventName": "Renamed"})

    assert response.status_code == 503
    assert "DATABASE_URL" in response.json["message"]


def test_details_database_failure_is_503(setup):
    client, _, cursor = setup
    cursor.execute.side_effect = __import__("psycopg2").OperationalError(
        "connection refused"
    )

    response = patch_details(client, {"eventName": "Renamed"})

    assert response.status_code == 503
    assert "connection refused" not in response.json["message"]
