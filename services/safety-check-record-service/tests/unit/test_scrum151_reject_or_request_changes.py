"""
SCRUM-151: Reject or Request Changes to Safety Arrangements

User Story
----------
As a Safety Officer, I want to reject an event's safety arrangement or request
changes, stating which planning area must be revisited, so that the Event
Coordinator knows exactly what to fix before the event can proceed.

Acceptance Criteria
-------------------
AC1: Given an event is 'Pending Safety Check', when I request changes, then I
     must select at least one affected area (venue arrangement,
     technical/equipment arrangement, event details) and describe the change
     needed; otherwise the decision is not saved.
AC2: Given changes are requested, then the event status changes to 'Safety
     Changes Requested', the event returns to the planning stage for each
     selected area, and its existing arrangements are preserved. For equipment
     requests affected by the requested changes, only requests with status
     'Approved' return to 'Pending' for review. Requests already 'Pending' or
     'Rejected' remain unchanged, including any recorded reviewer and rejection
     reason.
AC3: Given an event is 'Pending Safety Check', when I reject it, then a reason
     is required and I must confirm the rejection before it is saved.
AC4: Given I confirm a rejection, then the event status changes to 'Cancelled',
     and the event cannot be resubmitted for a safety check or moved to any
     further stage.
AC5: Given an event is cancelled by a safety rejection, then its venue bookings
     and equipment reservations are released so they no longer block other
     events, while their records remain in the event's history.
AC6: Given either decision, then the safety check is recorded with the status
     'Changes Requested' or 'Safety Rejected' respectively, together with my
     identity, the timestamp and the reason (plus the selected areas for a
     change request), and the original event information is retained.
AC7: Given an event is not 'Pending Safety Check', then these actions are not
     available and an API call is rejected without changing the event.

Real
----
- Recording a change request or a rejection: the affected areas (whole
  arrangement, or specific bookings and equipment requests) each with the
  change needed, the reason, refusing invalid or contradictory flags, and
  removing the flags again if the decision is undone.
- We check the decision returned and what is saved.

Doubled
-------
- Safety records (database): hold the rounds each test needs, accept new ones,
  or cannot be reached [Stub]; we check what is saved, and that rounds are
  locked before they change [Mock].
- Sign-in: a test key signs the caller's token (tests/unit/conftest.py) [Stub].

Not proven
----------
- That the event moves to 'Safety Changes Requested' or 'Cancelled', and that
  bookings and equipment requests are reopened or released (->
  safety-check-service, event-service and equipment/venue service tests).
- That the saving and locking really work in Postgres, including two people
  acting at the same moment (-> tests/integration/, against a throwaway
  postgres:17.6).
"""
import pytest
from unittest.mock import MagicMock

from app import create_app
from tests.unit.factories import EVENT_ID, OFFICER_ID, RECORD_ID, flag_row, record_row, signed_in


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client(), OFFICER_ID, "Safety Officer"), connection, cursor


def request_changes(client, safety_check_id=RECORD_ID, **overrides):
    body = {
        "status": "Changes Requested",
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
        "remarks": "Unsafe egress plan.",
        **overrides,
    }
    return client.patch(f"/safety-check-records/{safety_check_id}/decision", json=body)


# --- AC1: Changes Requested needs areas + change text ------------------------


def test_request_changes_with_two_areas_saves_both_flags(setup):
    """
    Summary: Requesting changes in two areas saves a flag for each.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    AC6: Given either decision, then the safety check is recorded with the
        status 'Changes Requested' or 'Safety Rejected' respectively, together
        with my identity, the timestamp and the reason (plus the selected areas
        for a change request), and the original event information is retained.
    Double: The safety records hold the rounds this case needs [Stub]; we check
        what is added [Mock].
    """
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


def test_request_changes_on_specific_equipment_saves_each_request_link(setup):
    """
    Summary: Flags on specific equipment requests keep the link to each request.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The safety records hold the rounds this case needs [Stub]; we check
        what is added [Mock].
    """
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


def test_request_changes_on_specific_bookings_saves_each_booking_link(setup):
    """
    Summary: Flags on specific venue bookings keep the link to each booking.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The safety records hold the rounds this case needs [Stub]; we check
        what is added [Mock].
    """
    client, _, cursor = setup
    booking_ids = [f"88888888-8888-4888-8888-{index:012d}" for index in range(4)]
    rows = [{**flag_row(), "booking_id": booking_id} for booking_id in booking_ids]
    cursor.fetchone.side_effect = [record_row(), record_row(), record_row(status="Changes Requested", decided=True), *rows]

    response = request_changes(client, flags=[{"area": "venue arrangement", "bookingId": booking_id, "changeRequired": "Move stage."} for booking_id in booking_ids])

    assert response.status_code == 200
    assert [flag["bookingId"] for flag in response.json["flags"]] == booking_ids
    inserts = [call.args[1] for call in cursor.execute.call_args_list if 'INSERT INTO public."SafetyCheckFlag"' in call.args[0]]
    assert inserts == [[RECORD_ID, "venue arrangement", "Move stage.", None, booking_id] for booking_id in booking_ids]


@pytest.mark.parametrize("area,reference", [("venue arrangement", "bad"), ("event details", EVENT_ID)], ids=["bad_booking_id", "booking_on_event_details"])
def test_request_changes_with_bad_booking_reference_returns_400(setup, area, reference):
    """
    Summary: A venue flag must point at a valid booking, and only venue flags may point at bookings.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: None
    """
    client, _, cursor = setup

    assert request_changes(client, flags=[{"area": area, "bookingId": reference, "changeRequired": "Move."}]).status_code == 400
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("area,reference", [("technical arrangement", "bad"), ("venue arrangement", EVENT_ID)], ids=["bad_request_id", "request_on_venue_area"])
def test_request_changes_with_bad_equipment_reference_returns_400(setup, area, reference):
    """
    Summary: A technical flag must point at a valid request, and only technical flags may.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: None
    """
    client, _, cursor = setup

    assert request_changes(client, flags=[{
        "area": area, "equipmentRequestId": reference, "changeRequired": "Move."
    }]).status_code == 400
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("references", [[EVENT_ID, EVENT_ID], [None, EVENT_ID], [EVENT_ID, None]], ids=["duplicate_item", "whole_then_item", "item_then_whole"])
def test_request_changes_with_duplicate_or_mixed_scope_flags_returns_400(setup, references):
    """
    Summary: An area cannot be flagged twice for the same item, or both as a whole and per item.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: None
    """
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
    ids=["no_flags", "unknown_area", "duplicate_area", "blank_change", "change_too_long", "too_many_flags", "flag_not_object"],
)
def test_request_changes_with_bad_flags_returns_400_and_saves_nothing(flags, setup):
    """
    Summary: Requesting changes needs one to three valid areas, each with the change needed.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: None
    """
    client, _, cursor = setup

    response = request_changes(client, flags=flags)

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_request_changes_with_flags_not_a_list_returns_400(setup):
    """
    Summary: Flags must be sent as a list.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: None
    """
    client, _, cursor = setup

    response = request_changes(client, flags="not a list")

    assert response.status_code == 400
    assert response.json["message"] == "flags must be a list."
    cursor.execute.assert_not_called()


def test_request_changes_without_reason_returns_400(setup):
    """
    Summary: Requesting changes needs a description of what to change.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: None
    """
    client, _, cursor = setup

    response = request_changes(client, remarks=None)

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_request_changes_with_blank_reason_returns_400(setup):
    """
    Summary: A blank description is not enough to request changes.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: None
    """
    client, _, cursor = setup

    response = request_changes(client, remarks="   ")

    assert response.status_code == 400
    cursor.execute.assert_not_called()


# --- AC3/AC6: Safety Rejected needs a reason, no flags -----------------------


def test_reject_with_reason_records_safety_rejected(setup):
    """
    Summary: A rejection with a reason is recorded as Safety Rejected.
    AC3: Given an event is 'Pending Safety Check', when I reject it, then a
        reason is required and I must confirm the rejection before it is saved.
    AC6: Given either decision, then the safety check is recorded with the
        status 'Changes Requested' or 'Safety Rejected' respectively, together
        with my identity, the timestamp and the reason (plus the selected areas
        for a change request), and the original event information is retained.
    Double: The safety records hold the rounds this case needs [Stub]; we check
        what is saved [Mock].
    """
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


def test_reject_without_reason_returns_400(setup):
    """
    Summary: A rejection needs a reason.
    AC3: Given an event is 'Pending Safety Check', when I reject it, then a
        reason is required and I must confirm the rejection before it is saved.
    Double: None
    """
    client, _, cursor = setup

    response = reject(client, remarks=None)

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_reject_with_flags_returns_400(setup):
    """
    Summary: A rejection cannot carry change flags.
    AC3: Given an event is 'Pending Safety Check', when I reject it, then a
        reason is required and I must confirm the rejection before it is saved.
    Double: None
    """
    client, _, cursor = setup

    response = reject(
        client,
        flags=[{"area": "venue arrangement", "changeRequired": "x"}],
    )

    assert response.status_code == 400
    cursor.execute.assert_not_called()


# --- Regression: Safety Approved behaviour is unchanged -----------------------


# --- Race guard: already decided / not latest, no flag insert ----------------


def test_request_changes_on_decided_round_returns_409(setup):
    """
    Summary: Changes cannot be requested on a round already decided.
    AC7: Given an event is not 'Pending Safety Check', then these actions are
        not available and an API call is rejected without changing the event.
    Double: The round has already been decided [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(status="Changes Requested", decided=True)

    response = request_changes(client)

    assert response.status_code == 409
    assert cursor.execute.call_count == 1


def test_reject_older_round_returns_409(setup):
    """
    Summary: Only the latest round can be rejected.
    AC7: Given an event is not 'Pending Safety Check', then these actions are
        not available and an API call is rejected without changing the event.
    Double: The event already has a newer round [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=1, status="Pending"),
        record_row(round_number=2, status="Pending"),
    ]

    response = reject(client)

    assert response.status_code == 409
    assert response.json["code"] == "NOT_LATEST_ROUND"


# --- Compensation: reopen deletes flags ---------------------------------------


def test_reopen_after_changes_requested_removes_its_flags(setup):
    """
    Summary: Undoing a change request also removes its flags.
    AC6: Given either decision, then the safety check is recorded with the
        status 'Changes Requested' or 'Safety Rejected' respectively, together
        with my identity, the timestamp and the reason (plus the selected areas
        for a change request), and the original event information is retained.
    Double: The round has been decided [Stub]; we check how it is changed
        [Mock].
    """
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


def test_list_rounds_shows_each_rounds_own_flags(setup):
    """
    Summary: Each round in the history shows only its own flags.
    AC6: Given either decision, then the safety check is recorded with the
        status 'Changes Requested' or 'Safety Rejected' respectively, together
        with my identity, the timestamp and the reason (plus the selected areas
        for a change request), and the original event information is retained.
    Double: The safety records hold the rounds and their flagged areas [Stub].
    """
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
