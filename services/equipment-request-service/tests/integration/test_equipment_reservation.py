"""SCRUM-35: Equipment Reservation

Agreed revision from this conversation; pending confirmation that Jira has been updated

User Story
----------
As a Technical Support Staff member, I want approving equipment requests to reserve the requested quantities for a specific event, so that the total reserved equipment does not exceed the available stock, including when multiple requests are approved at the same time.

Acceptance Criteria
-------------------
AC1: Given a Pending equipment request has sufficient available stock for the event’s duration, when I approve it, then its status changes to Approved and its quantity is immediately counted as reserved when checking further requests.
AC2: Given an equipment request is approved, then its reservation remains associated with the specific event ID for which it was approved.
AC3: Given equipment already has Approved requests for the same event or other overlapping events whose reservations still apply, when the system checks a new approval, then it subtracts those reserved quantities from the usable stock. Pending and Rejected requests do not reserve stock.
AC4: Given I select multiple Pending equipment requests for bulk approval, when the system checks availability, then it adds together the selected quantities for each equipment item. If every item has sufficient stock, all selected requests are approved. If any item has insufficient stock, none of the selected requests is approved and all remain Pending.
AC5: Given multiple approval actions compete for the same available equipment, when they are processed at the same time, then the total approved quantity must not exceed the available stock. Any approval that no longer has sufficient stock leaves its selected requests Pending.
AC6: Given the quantity being approved exactly equals the remaining available quantity, when I approve it, then approval succeeds. If the quantity exceeds the remaining available quantity, approval is refused and the selected requests remain Pending.

Real: Flask routes, token signature/role checks, models/allocation SQL, separate real PostgreSQL connections in fixture-owned databases.
Doubled: Synthetic external Event/catalogue snapshots; JWKS key lookup only. No other service or broker runs.
Not proven: Browser behaviour, real upstream snapshots, concurrent catalogue/schedule edits and notification delivery are not proved. Existing fixture loads selected baseline FK tables plus owner outbox migration, NOT the full migration chain; this is a known integration-guide exception, unchanged here. Execution is collected but not executed during this reorganisation because an unrelated backend-ngrok-1 auto-restarts; the container-preservation guard is unchanged.
"""

from concurrent.futures import ThreadPoolExecutor

from contextlib import closing

import psycopg2

from app.allocation import APPROVAL_LOCK

from tests.integration.owner_postgres import uid, wait_for, TOKEN

import pytest

pytestmark = pytest.mark.integration

def approval_payload(owner, ids, *, event_id=None, events=None, total=20) -> dict:
    """Trusted external Event/catalogue responses frozen before the owner mutation."""
    event_id = event_id or owner.event
    context = {**owner.context, "eventId": event_id}
    checked = owner.approval_context(ids, event_id)
    if events is not None:
        checked["events"] = events
    for item in checked["equipment"]:
        item["totalQuantity"] = total
    return dict(status="Approved", notificationContext=context, approvalContext=checked)

def decide(owner, payload, identifier=None, headers=None):
    """Each caller gets a separate Flask client and a real new PostgreSQL connection."""
    path = f"/equipment-requests/{identifier}" if identifier else f"/events/{payload['approvalContext']['eventId']}/equipment-requests"
    with owner.app.test_client() as client:
        return client.patch(path, headers=owner.identity() if headers is None else headers, json=payload)



# AC1 ----
@pytest.mark.parametrize("case", ["event_status", "date"], ids=lambda case: case)
def test_ac1_unknown_event_context_saves_no_decision(owner, case):
    """Failure: Missing equipment, unknown Event status or invalid dates save no decision/job."""
    ids = owner.seed_requests(1)
    payload = approval_payload(owner, ids)
    checked = payload["approvalContext"]
    if case == "equipment":
        checked["equipment"] = []
    elif case == "event_status":
        checked["events"][0]["status"] = "Unknown"
    else:
        checked["events"][0]["startTime"] = None
    before = owner.db.snapshot()
    assert decide(owner, payload).status_code == 409
    assert owner.db.snapshot() == before


# AC3 ----
def test_ac3_sequential_same_event_approvals_cannot_exceed_total(owner):
    """Conflict: Conflict: two pending lines of 15 cannot both use the same 20 items."""
    ids = owner.seed_requests(3)[::2]
    owner.db.execute('UPDATE public."EquipmentRequest" SET quantity_requested=15 WHERE equipment_request_id=ANY(%s::uuid[])', [ids])
    first = owner.review(ids[0])
    second = owner.review(ids[1])
    assert first.status_code == 200, first.json
    assert second.status_code == 409, second.json
    assert len(owner.outbox()) == 1


# AC3 ----
def test_ac3_missing_fresh_approved_holder_context_fails_closed(owner):
    """Conflict: A competing Approved row with no supplied Event summary is not ignored."""
    ids = owner.seed_requests(1)
    payload = approval_payload(owner, ids)
    competitor = uid()
    owner.db.execute('INSERT INTO public."Event" (event_id) VALUES (%s)', [competitor])
    owner.db.execute('INSERT INTO public."EquipmentRequest" (event_id,equipment_id,quantity_requested,status) VALUES (%s,%s,1,%s)', [competitor, owner.equipment[0], "Approved"])
    before = owner.db.snapshot()
    assert decide(owner, payload).status_code == 409
    assert owner.db.snapshot() == before


# AC3 ----
def test_ac3_rejected_requests_do_not_consume_stock_and_rejection_skips_context(owner):
    """Boundary: Reject remains stock-independent; its previous quantity cannot block later approval."""
    ids = owner.seed_requests(3)[::2]
    owner.db.execute('UPDATE public."EquipmentRequest" SET quantity_requested=20 WHERE equipment_request_id=ANY(%s::uuid[])', [ids])
    assert owner.review(ids[0], status="Rejected").status_code == 200
    assert decide(owner, approval_payload(owner, [ids[1]]), ids[1]).status_code == 200
    assert len(owner.outbox()) == 2


# AC4 ----
def test_ac4_bulk_duplicate_quantities_are_all_or_nothing(owner):
    """Conflict: Grouped Pending 15+15 over stock 20 leaves every line Pending and no jobs."""
    ids = owner.seed_requests(3)[::2]
    owner.db.execute('UPDATE public."EquipmentRequest" SET quantity_requested=15 WHERE equipment_request_id=ANY(%s::uuid[])', [ids])
    before = owner.db.snapshot()
    response = decide(owner, approval_payload(owner, ids))
    assert response.status_code == 409, response.json
    assert owner.db.snapshot() == before


# AC4 ----
def test_ac4_bulk_approves_only_checked_ids_not_later_submissions(owner):
    """Normal: A Pending line added after the snapshot is not silently included in Approve All."""
    ids = owner.seed_requests(1)
    payload = approval_payload(owner, ids)
    later = owner.seed_requests(1)[0]
    response = decide(owner, payload)
    assert response.status_code == 200, response.json
    assert [row["id"] for row in response.json["requests"]] == ids
    assert owner.db.execute('SELECT status FROM public."EquipmentRequest" WHERE equipment_request_id=%s', [later]) == [{"status": "Pending"}]
    assert len(owner.outbox()) == 1


# AC4 ----
@pytest.mark.parametrize("change", ["foreign", "missing", "already_reviewed"], ids=lambda change: change)
def test_ac4_exact_selection_membership_and_pending_state_are_revalidated(owner, change):
    """Conflict: Unknown, foreign or already-decided selected rows never partially approve a batch."""
    ids = owner.seed_requests(3)
    payload = approval_payload(owner, ids)
    if change == "foreign":
        foreign = uid()
        owner.db.execute('INSERT INTO public."Event" (event_id) VALUES (%s)', [foreign])
        owner.db.execute('UPDATE public."EquipmentRequest" SET event_id=%s WHERE equipment_request_id=%s', [foreign, ids[1]])
    elif change == "missing":
        payload["approvalContext"]["requestIds"].append(uid())
    else:
        assert owner.review(ids[1], status="Rejected").status_code == 200
    before = owner.db.snapshot()
    assert decide(owner, payload).status_code == 409
    assert owner.db.snapshot() == before


# AC5 ----
@pytest.mark.parametrize("bulk", [False, True], ids=["single-vs-single", "single-vs-bulk"])
@pytest.mark.parametrize("total,other_event,nonoverlap,expected", [
    (20, False, False, [200, 409]),
    (20, True, False, [200, 409]),
    (30, True, False, [200, 200]),
    (20, True, True, [200, 200]),
], ids=["same_event_insufficient", "overlapping_events_insufficient", "overlapping_events_exact_stock", "nonoverlapping_events_reuse"])
def test_ac5_two_connections_serialize_fresh_stock_checks(owner, total, other_event, nonoverlap, expected, bulk):
    """Boundary: Two approvals queued at the real DB lock consume one shared stock pool."""
    ids = owner.seed_requests(3)[::2]
    owner.db.execute('UPDATE public."EquipmentRequest" SET quantity_requested=15 WHERE equipment_request_id=ANY(%s::uuid[])', [ids])
    events = approval_payload(owner, ids)["approvalContext"]["events"]
    target = owner.event
    if other_event:
        target = uid()
        owner.db.execute('INSERT INTO public."Event" (event_id,event_name) VALUES (%s,%s)', [target, "Competing event"])
        owner.db.execute('UPDATE public."EquipmentRequest" SET event_id=%s WHERE equipment_request_id=%s', [target, ids[1]])
        events.append(dict(id=target, status="Under Review", startTime="2030-01-01T18:00:00" if nonoverlap else "2030-01-01T10:00:00", endTime="2030-01-02T10:00:00"))
    payloads = [approval_payload(owner, [identifier], event_id=event, events=events, total=total) for identifier, event in zip(ids, [owner.event, target])]
    with closing(psycopg2.connect(owner.db.dsn)) as blocker:
        with blocker.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [APPROVAL_LOCK])
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(decide, owner, payload, None if bulk and index == 1 else identifier)
                       for index, (identifier, payload) in enumerate(zip(ids, payloads))]
            try:
                blocked = wait_for(lambda: owner.db.execute("SELECT pid FROM (SELECT pid,count(*) OVER () AS n FROM pg_locks WHERE locktype='advisory' AND NOT granted AND objid=%s) waiting WHERE n >= 2", [APPROVAL_LOCK]))
                assert len({row["pid"] for row in blocked}) == 2
            finally:
                blocker.commit()
            responses = [future.result(timeout=15) for future in futures]
    assert sorted(response.status_code for response in responses) == expected, [response.json for response in responses]
    approved = owner.db.execute('SELECT quantity_requested FROM public."EquipmentRequest" WHERE status=%s', ["Approved"])
    assert len(approved) == expected.count(200)
    assert len(owner.outbox()) == expected.count(200)


# AC6 ----
def test_ac6_changed_quantity_is_read_from_owner_not_snapshot(owner):
    """Conflict: A selected row increased from 5 to 21 after checking cannot use stock 20."""
    ids = owner.seed_requests(1)
    payload = approval_payload(owner, ids)
    owner.db.execute('UPDATE public."EquipmentRequest" SET quantity_requested=21 WHERE equipment_request_id=%s', ids)
    before = owner.db.snapshot()
    assert decide(owner, payload).status_code == 409
    assert owner.db.snapshot() == before
