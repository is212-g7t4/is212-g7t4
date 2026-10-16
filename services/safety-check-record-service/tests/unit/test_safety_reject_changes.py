"""SCRUM-151: deciding a round as 'Changes Requested' or 'Safety Rejected'.

AC1 ... when I request changes, then I must select at least one affected
    area and describe the change needed; otherwise the decision is not saved.
AC3 ... when I reject it, then a reason is required.
AC6 ... the safety check is recorded with the status 'Changes Requested' or
    'Safety Rejected', together with identity, timestamp and reason (plus
    the selected areas for a change request).

Database calls are mocked; no live database writes.
"""
import psycopg2
import pytest
from unittest.mock import MagicMock

from app import create_app
from tests.unit.factories import EVENT_ID, OFFICER_ID, RECORD_ID, record_row


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), connection, cursor


def flag_row(area="venue arrangement", change_required="Move the stage.", flag_id="55555555-5555-4555-8555-555555555555"):
    return {
        "flag_id": flag_id,
        "safety_check_id": RECORD_ID,
        "area": area,
        "booking_id": None,
        "equip_request_id": None,
        "change_required": change_required,
    }


def request_changes(client, safety_check_id=RECORD_ID, **overrides):
    body = {
        "status": "Changes Requested",
        "decidedBy": OFFICER_ID,
        "remarks": "Needs another look.",
        "flags": [
            {"area": "venue arrangement", "changeRequired": "Move the stage."},
        ],
        **overrides,
    }
    return client.patch(f"/safety-check-records/{safety_check_id}/decision", json=body)


def reject(client, safety_check_id=RECORD_ID, **overrides):
    body = {
        "status": "Safety Rejected",
        "decidedBy": OFFICER_ID,
        "remarks": "Unsafe egress plan.",
        **overrides,
    }
    return client.patch(f"/safety-check-records/{safety_check_id}/decision", json=body)


# --- AC1: Changes Requested needs areas + change text ------------------------


def test_changes_requested_with_two_flags_inserts_both(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Pending"),
        record_row(
            round_number=1,
            status="Changes Requested",
            decided=True,
            remarks="Needs another look.",
        ),
        flag_row(area="venue arrangement"),
        flag_row(area="event details", flag_id="66666666-6666-4666-8666-666666666666"),
    ]

    response = request_changes(
        client,
        flags=[
            {"area": "venue arrangement", "changeRequired": "Move the stage."},
            {"area": "event details", "changeRequired": "Fix the start time."},
        ],
    )

    assert response.status_code == 200
    assert response.json["status"] == "Changes Requested"
    assert response.json["decidedBy"] == OFFICER_ID
    assert response.json["remarks"] == "Needs another look."
    assert [flag["area"] for flag in response.json["flags"]] == [
        "venue arrangement",
        "event details",
    ]
    insert_calls = [
        call for call in cursor.execute.call_args_list
        if 'INSERT INTO public."SafetyCheckFlag"' in call.args[0]
    ]
    assert len(insert_calls) == 2


def test_individual_technical_flags_persist_each_equipment_request_link(setup):
    client, _, cursor = setup
    request_ids = [f"77777777-7777-4777-8777-{index:012d}" for index in range(5)]
    rows = [{**flag_row(area="technical arrangement"), "equip_request_id": request_id}
        for request_id in request_ids]
    cursor.fetchone.side_effect = [record_row(), record_row(),
        record_row(status="Changes Requested", decided=True), *rows]
    response = request_changes(client, flags=[{
        "area": "technical arrangement", "equipmentRequestId": request_id, "changeRequired": "Move cables."
    } for request_id in request_ids])
    assert response.status_code == 200
    assert [flag["equipmentRequestId"] for flag in response.json["flags"]] == request_ids
    inserts = [call.args[1] for call in cursor.execute.call_args_list if 'INSERT INTO public."SafetyCheckFlag"' in call.args[0]]
    assert inserts == [[RECORD_ID, "technical arrangement", "Move cables.", request_id, None] for request_id in request_ids]


def test_targeted_venue_flags_persist_booking_ids(setup):
    client, _, cursor = setup
    booking_ids = [f"88888888-8888-4888-8888-{index:012d}" for index in range(4)]
    rows = [{**flag_row(), "booking_id": booking_id} for booking_id in booking_ids]
    cursor.fetchone.side_effect = [record_row(), record_row(), record_row(status="Changes Requested", decided=True), *rows]
    response = request_changes(client, flags=[{"area": "venue arrangement", "bookingId": booking_id, "changeRequired": "Move stage."} for booking_id in booking_ids])
    assert response.status_code == 200
    assert [flag["bookingId"] for flag in response.json["flags"]] == booking_ids
    inserts = [call.args[1] for call in cursor.execute.call_args_list if 'INSERT INTO public."SafetyCheckFlag"' in call.args[0]]
    assert inserts == [[RECORD_ID, "venue arrangement", "Move stage.", None, booking_id] for booking_id in booking_ids]


@pytest.mark.parametrize("area,reference", [("venue arrangement", "bad"), ("event details", EVENT_ID)])
def test_targeted_venue_flags_validate_scope(setup, area, reference):
    client, _, cursor = setup
    assert request_changes(client, flags=[{"area": area, "bookingId": reference, "changeRequired": "Move."}]).status_code == 400
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("area,reference", [("technical arrangement", "bad"), ("venue arrangement", EVENT_ID)])
def test_targeted_flags_validate_area_and_request_id(setup, area, reference):
    client, _, cursor = setup
    assert request_changes(client, flags=[{
        "area": area, "equipmentRequestId": reference, "changeRequired": "Move."
    }]).status_code == 400
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("references", [[EVENT_ID, EVENT_ID], [None, EVENT_ID], [EVENT_ID, None]])
def test_targeted_flags_reject_duplicate_or_mixed_area_scope(setup, references):
    client, _, cursor = setup
    assert request_changes(client, flags=[{
        "area": "technical arrangement", "equipmentRequestId": reference, "changeRequired": "Move."
    } for reference in references]).status_code == 400
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    "flags",
    [
        [],
        [{"area": "not a real area", "changeRequired": "x"}],
        [
            {"area": "venue arrangement", "changeRequired": "x"},
            {"area": "venue arrangement", "changeRequired": "y"},
        ],
        [{"area": "venue arrangement", "changeRequired": ""}],
        [{"area": "venue arrangement", "changeRequired": "x" * 2001}],
        [
            {"area": "venue arrangement", "changeRequired": "a"},
            {"area": "technical arrangement", "changeRequired": "b"},
            {"area": "event details", "changeRequired": "c"},
            {"area": "venue arrangement", "changeRequired": "d"},
        ],
        ["not an object"],
    ],
)
def test_changes_requested_rejects_bad_flags(flags, setup):
    client, _, cursor = setup

    response = request_changes(client, flags=flags)

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_flags_must_be_a_list(setup):
    client, _, cursor = setup

    response = request_changes(client, flags="not a list")

    assert response.status_code == 400
    assert response.json["message"] == "flags must be a list."
    cursor.execute.assert_not_called()


def test_null_flags_are_treated_as_empty_for_approval(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Safety Approved", decided=True),
    ]

    response = client.patch(
        f"/safety-check-records/{RECORD_ID}/decision",
        json={"status": "Safety Approved", "decidedBy": OFFICER_ID, "flags": None},
    )

    assert response.status_code == 200


def test_changes_requested_requires_remarks(setup):
    client, _, cursor = setup

    response = request_changes(client, remarks=None)

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_changes_requested_rejects_blank_remarks(setup):
    client, _, cursor = setup

    response = request_changes(client, remarks="   ")

    assert response.status_code == 400
    cursor.execute.assert_not_called()


# --- AC3/AC6: Safety Rejected needs a reason, no flags -----------------------


def test_safety_rejected_with_remarks_succeeds_without_flags(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Safety Rejected", decided=True),
    ]

    response = reject(client)

    assert response.status_code == 200
    assert response.json["status"] == "Safety Rejected"
    assert response.json["flags"] == []
    insert_calls = [
        call for call in cursor.execute.call_args_list
        if 'INSERT INTO public."SafetyCheckFlag"' in call.args[0]
    ]
    assert insert_calls == []


def test_safety_rejected_requires_remarks(setup):
    client, _, cursor = setup

    response = reject(client, remarks=None)

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_safety_rejected_rejects_flags(setup):
    client, _, cursor = setup

    response = reject(
        client,
        flags=[{"area": "venue arrangement", "changeRequired": "x"}],
    )

    assert response.status_code == 400
    cursor.execute.assert_not_called()


# --- Regression: Safety Approved behaviour is unchanged -----------------------


def test_safety_approved_rejects_flags(setup):
    client, _, cursor = setup

    response = client.patch(
        f"/safety-check-records/{RECORD_ID}/decision",
        json={
            "status": "Safety Approved",
            "decidedBy": OFFICER_ID,
            "flags": [{"area": "venue arrangement", "changeRequired": "x"}],
        },
    )

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_safety_approved_without_remarks_still_succeeds(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Safety Approved", decided=True),
    ]

    response = client.patch(
        f"/safety-check-records/{RECORD_ID}/decision",
        json={"status": "Safety Approved", "decidedBy": OFFICER_ID},
    )

    assert response.status_code == 200


# --- Race guard: already decided / not latest, no flag insert ----------------


def test_already_decided_round_blocks_changes_requested(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(status="Changes Requested", decided=True)

    response = request_changes(client)

    assert response.status_code == 409
    assert cursor.execute.call_count == 1


def test_not_latest_round_blocks_reject(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=1, status="Pending"),
        record_row(round_number=2, status="Pending"),
    ]

    response = reject(client)

    assert response.status_code == 409
    assert response.json["code"] == "NOT_LATEST_ROUND"


# --- Compensation: reopen deletes flags ---------------------------------------


def test_reopen_deletes_the_rounds_flags(setup):
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(status="Changes Requested", decided=True),
        record_row(status="Pending"),
    ]

    response = client.post(
        f"/safety-check-records/{RECORD_ID}/reopen",
        json={"decidedAt": "2026-11-02T03:00:00+00:00"},
    )

    assert response.status_code == 200
    delete_sql = cursor.execute.call_args_list[1].args[0]
    assert 'DELETE FROM public."SafetyCheckFlag"' in delete_sql


# --- Listing: flags attached to each round ------------------------------------


def test_list_rounds_attaches_flags_only_to_their_own_round(setup):
    client, _, cursor = setup
    other_id = "77777777-7777-4777-8777-777777777777"
    cursor.fetchall.side_effect = [
        [
            record_row(round_number=2, status="Changes Requested", decided=True),
            record_row(
                round_number=1,
                status="Safety Rejected",
                decided=True,
                safety_check_id=other_id,
            ),
        ],
        [flag_row()],
    ]

    response = client.get(f"/safety-check-records?eventId={EVENT_ID}")

    assert response.status_code == 200
    rounds = response.json["safetyChecks"]
    assert rounds[0]["flags"][0]["area"] == "venue arrangement"
    assert rounds[1]["flags"] == []
