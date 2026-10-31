"""
SCRUM-35: Equipment Reservation

User Story
----------
As a Technical Support Staff member, I want approving equipment requests to reserve the requested quantities for a specific event, so that the total reserved equipment does not exceed the available stock, including when multiple requests are approved at the same time.

Acceptance Criteria
-------------------
AC1: Given a Pending equipment request has sufficient available stock for the event’s duration, when I approve it, then its status changes to Approved and its quantity is immediately counted as reserved when checking further requests.
AC2: Given an equipment request is approved, then its reservation remains associated with the specific event ID for which it was approved.
AC3: Given an equipment request is being checked for approval, then the system calculates the remaining usable quantity for that event’s time period by subtracting quantities already reserved through Approved requests for the same event and other overlapping events whose reservations remain active. Pending and Rejected requests do not reserve equipment.
AC4: Given I select multiple Pending equipment requests for bulk approval, when the system checks availability, then it adds together the selected quantities for each equipment item. If every item has sufficient stock, all selected requests are approved. If any item has insufficient stock, none of the selected requests is approved and all remain Pending.
AC5: Given multiple approval actions compete for the same available equipment, when they are processed at the same time, then the total approved quantity must not exceed the available stock. Any approval that no longer has sufficient stock leaves its selected requests Pending.
AC6: Given the quantity being approved exactly equals the remaining available quantity, when I approve it, then approval succeeds. If the quantity exceeds the remaining available quantity, approval is refused and the selected requests remain Pending.

Real
----
- Real Equipment Request Flask validation, allocation arithmetic and model SQL construction; observes refusal/status responses and absence of UPDATE SQL.

Doubled
-------
- Stub (database connection/cursor returning fresh selected and held rows); Mock (database connection and SQL calls inspected). Fake (CompositeClient adds trusted request context); Stub (JWKS key lookup).

Not proven
----------
- Real database persistence, lock contention and rollback are not proved here; maintained cases are tests/integration/test_scrum35_equipment_reservation.py, executed against fixture-owned PostgreSQL; see docs/testing/integration-testing.md (repository root) for fixture limits and commands.
- AC2 persisted event association and AC5 concurrency require the owner integration tier. AC6 exact-limit success is not independently demonstrated by this unit module.
- UI, overlap-query completeness, concurrent catalogue/event changes and notification delivery are NOT COVERED ANYWHERE in this module.
- Malformed snapshot fields and exact selection revalidation are supporting fail-closed checks; their precise API error contracts remain a Jira requirement gap, not invented ACs.
"""

import pytest

from tests.unit.factories import EVENT_ID, MIC, REQUEST_ID, USER_ID, bearer, db_row, approval_context



def test_approval_refuses_missing_availability_context(setup):
    """Summary: A trusted caller without stock/window context cannot approve anything.
    AC1: Given a Pending equipment request has sufficient available stock for the event’s duration, when I approve it, then its status changes to Approved and its quantity is immediately counted as reserved when checking further requests.
    Double: Stub (canned database results/errors); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    client, cursor, _ = setup
    cursor.fetchone.return_value = db_row(status="Approved")
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    response = client.patch(f"/equipment-requests/{REQUEST_ID}", headers=bearer(USER_ID, "Technical Support"), json={"status": "Approved", "approvalContext": None})
    assert response.status_code == 409


def test_approval_counts_own_approved_stock(setup):
    """Summary: Fresh own Approved 10 plus selected Pending 15 cannot fit a stock of 20.
    AC3: Given an equipment request is being checked for approval, then the system calculates the remaining usable quantity for that event’s time period by subtracting quantities already reserved through Approved requests for the same event and other overlapping events whose reservations remain active. Pending and Rejected requests do not reserve equipment.
    Double: Stub (canned database results/errors); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    client, cursor, _ = setup
    held = db_row(equipment_request_id="00000000-0000-4000-8000-000000000001", status="Approved", quantity_requested=10)
    cursor.fetchall.side_effect = [[db_row()], [held]]
    cursor.fetchone.return_value = db_row(status="Approved")
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    response = client.patch(f"/equipment-requests/{REQUEST_ID}", headers=bearer(USER_ID, "Technical Support"), json={"status": "Approved", "approvalContext": approval_context(total=20)})
    assert response.status_code == 409


@pytest.mark.parametrize("case", [
    "bad_event_id", "missing_ids", "bad_id", "duplicate_ids", "wrong_selection",
    "bad_events", "bad_catalogue", "bad_event", "unknown_status", "duplicate_events",
    "missing_target", "released_target", "bad_window", "reverse_window", "bad_equipment",
    "duplicate_equipment", "bad_quantity", "unknown_equipment_status", "wrong_bulk_event",
], ids=lambda case: case)
def test_invalid_approval_context_fails_closed_before_database(setup, case):
    """Summary: Malformed/unknown Event, catalogue or exact selection values cannot approve stock.
    AC1: Given a Pending equipment request has sufficient available stock for the event’s duration, when I approve it, then its status changes to Approved and its quantity is immediately counted as reserved when checking further requests.
    Double: Stub (canned database results/errors); Mock (database interactions inspected); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    client, _, connect = setup
    checked = approval_context(total=20)
    path = f"/equipment-requests/{REQUEST_ID}"
    if case == "bad_event_id": checked["eventId"] = "bad"
    elif case == "missing_ids": checked["requestIds"] = None
    elif case == "bad_id": checked["requestIds"] = [None]
    elif case == "duplicate_ids": checked["requestIds"] *= 2
    elif case == "wrong_selection": checked["requestIds"] = [USER_ID]
    elif case == "bad_events": checked["events"] = {}
    elif case == "bad_catalogue": checked["equipment"] = None
    elif case == "bad_event": checked["events"] = [None]
    elif case == "unknown_status": checked["events"][0]["status"] = "Unknown"
    elif case == "duplicate_events": checked["events"] *= 2
    elif case == "missing_target": checked["events"] = []
    elif case == "released_target": checked["events"][0]["status"] = "Cancelled"
    elif case == "bad_window": checked["events"][0]["startTime"] = None
    elif case == "reverse_window": checked["events"][0]["endTime"] = "2000-01-01"
    elif case == "bad_equipment": checked["equipment"] = [None]
    elif case == "duplicate_equipment": checked["equipment"] *= 2
    elif case == "bad_quantity": checked["equipment"][0]["totalQuantity"] = True
    elif case == "unknown_equipment_status": checked["equipment"][0]["status"] = "Unknown"
    else: path = f"/events/{USER_ID}/equipment-requests"
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    response = client.patch(path, headers=bearer(USER_ID, "Technical Support"), json={"status": "Approved", "approvalContext": checked})
    assert response.status_code == 409, response.json
    connect.assert_not_called()


@pytest.mark.parametrize("case", ["partial_selection", "foreign", "reviewed", "unknown_holder"], ids=lambda case: case)
def test_stale_owner_rows_are_refused_without_update(setup, case):
    """Summary: Every selected row must still be Pending in this event and every holder known.
    AC4: Given I select multiple Pending equipment requests for bulk approval, when the system checks availability, then it adds together the selected quantities for each equipment item. If every item has sufficient stock, all selected requests are approved. If any item has insufficient stock, none of the selected requests is approved and all remain Pending.
    Double: Stub (canned database results/errors); Mock (database interactions inspected); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    client, cursor, _ = setup
    selected = db_row()
    checked = approval_context(total=20)
    approved = []
    if case == "partial_selection": checked["requestIds"].append(USER_ID)
    elif case == "foreign": selected["event_id"] = USER_ID
    elif case == "reviewed": selected["status"] = "Rejected"
    else: approved = [db_row(event_id=USER_ID, status="Approved")]
    cursor.fetchall.side_effect = [[selected], approved]
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    response = client.patch(f"/events/{EVENT_ID}/equipment-requests", headers=bearer(USER_ID, "Technical Support"), json={"status": "Approved", "approvalContext": checked})
    assert response.status_code == 409, response.json
    assert not any(call.args[0].lstrip().startswith("UPDATE") for call in cursor.execute.call_args_list)


@pytest.mark.parametrize("case", ["available", "nonoverlap", "cancelled"], ids=lambda case: case)
def test_approval_when_holders_do_not_apply_keeps_their_stock_available(setup, case):
    """Summary: Approved reservations outside the requested period or on cancelled events do not prevent approval.
    AC3: Given an equipment request is being checked for approval, then the system calculates the remaining usable quantity for that event’s time period by subtracting quantities already reserved through Approved requests for the same event and other overlapping events whose reservations remain active. Pending and Rejected requests do not reserve equipment.
    Double: Stub (canned database results/errors); Stub (test JWKS public key for user-token verification); Fake (CompositeClient adds synthetic service context to JSON writes; no HTTP service runs)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    client, cursor, _ = setup
    checked = approval_context(total=20)
    held = []
    if case in ("nonoverlap", "cancelled"):
        event = {**checked["events"][0], "id": USER_ID}
        if case == "cancelled": event["status"] = "Cancelled"
        else: event.update(startTime="2030-01-01T18:00:00+08:00", endTime="2030-01-02T00:00:00+08:00")
        checked["events"].append(event)
        held = [db_row(event_id=USER_ID, status="Approved", quantity_requested=20)]
    cursor.fetchall.side_effect = [[db_row()], held, [db_row(status="Approved")]]
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    response = client.patch(f"/equipment-requests/{REQUEST_ID}", headers=bearer(USER_ID, "Technical Support"), json={"status": "Approved", "approvalContext": checked})
    assert response.status_code == 200
    assert response.json["request"]["status"] == "Approved"
