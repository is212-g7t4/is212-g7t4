"""Issue 8: preserve equipment decisions on the safety-reset endpoint.

Approved narrow bug-fix rules (no Jira story key was assigned):
1. Only affected Approved equipment requests return to Pending.
2. Pending and Rejected requests, including review metadata, stay unchanged.
3. Unknown or foreign IDs reject the whole reset; repeated resets are safe.
Real: Flask route, signed caller checks, model SQL and disposable PostgreSQL
      with the full unmodified migration chain.
Doubled: only the Supabase signing-key lookup (shared test fixture).
Not proven: composite flag selection, Supabase sign-in or browser workflows.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from uuid import uuid4

import psycopg2
import pytest

from tests.integration.factories import mixed_requests
from tests.integration.owner_postgres import TOKEN, wait_for
from tests.unit.factories import bearer

pytestmark = pytest.mark.integration


def reset(owner, ids):
    """Submit selected IDs through the real reset route as a signed Safety Officer."""
    return owner.client.post(
        f"/events/{owner.event}/equipment-requests/safety-reset",
        headers={**bearer(owner.other, "Safety Officer"), "X-Internal-Service-Token": TOKEN},
        json={"requestIds": ids},
    )


def test_mixed_reset_changes_only_selected_approved_requests(safety_reset_owner):
    """Normal: a mixed reset changes only the Approved row and creates no notification intent."""
    owner = safety_reset_owner
    (approved, rejected, pending, unrelated), before = mixed_requests(owner)

    response = reset(owner, [approved, rejected, pending])

    assert response.status_code == 200
    after = owner.db.snapshot()
    expected = before
    for row in expected["EquipmentRequest"]:
        if str(row["equipment_request_id"]) == approved:
            row.update(status="Pending", reviewed_by=None, rejection_reason=None)
    assert after == expected
    assert [row["id"] for row in response.json["requests"]] == [approved]
    assert response.json["requests"][0]["status"] == "Pending"
    assert response.json["requests"][0]["reviewedBy"] is None
    assert response.json["requests"][0]["rejectionReason"] is None


@pytest.mark.parametrize("position", [1, 2], ids=["rejected", "pending"])
def test_ineligible_only_reset_preserves_every_field(safety_reset_owner, position):
    """Boundary: a valid but ineligible target returns no changed requests and preserves all rows."""
    owner = safety_reset_owner
    identifiers, before = mixed_requests(owner)

    response = reset(owner, [identifiers[position]])

    assert response.status_code == 200
    assert response.json == {"requests": []}
    assert owner.db.snapshot() == before


def test_repeated_reset_is_a_noop(safety_reset_owner):
    """Boundary: replaying the same mixed IDs after a reset cannot change any row or outbox."""
    owner = safety_reset_owner
    (approved, rejected, pending, _), _before = mixed_requests(owner)
    identifiers = [approved, rejected, pending]
    assert reset(owner, identifiers).status_code == 200
    after_first = owner.db.snapshot()

    response = reset(owner, identifiers)

    assert response.status_code == 200
    assert response.json == {"requests": []}
    assert owner.db.snapshot() == after_first


@pytest.mark.parametrize("foreign_status", [None, "Approved", "Rejected", "Pending"],
                         ids=["unknown", "foreign-approved", "foreign-rejected", "foreign-pending"])
def test_invalid_member_aborts_mixed_reset(safety_reset_owner, foreign_status):
    """Failure: unknown or foreign IDs reject the whole request regardless of eligibility."""
    owner = safety_reset_owner
    (approved, rejected, pending, _), _before = mixed_requests(owner)
    invalid_id = str(uuid4())
    if foreign_status is not None:
        foreign_event = str(uuid4())
        owner.db.execute('INSERT INTO public."Event" (event_id) VALUES (%s)', [foreign_event])
        owner.db.execute(
            '''INSERT INTO public."EquipmentRequest"
               (equipment_request_id, event_id, status, reviewed_by, rejection_reason)
               VALUES (%s, %s, %s, %s, %s)''',
            [invalid_id, foreign_event, foreign_status, owner.reviewer,
             "Foreign rejection" if foreign_status == "Rejected" else None],
        )
    before = owner.db.snapshot()

    response = reset(owner, [approved, rejected, pending, invalid_id])

    assert response.status_code == 404
    assert response.json["message"] == "Every equipment request must belong to this event."
    assert owner.db.snapshot() == before


def test_waiting_reset_preserves_concurrently_committed_rejection(safety_reset_owner):
    """Conflict: a reset waiting on a real review lock uses the committed Rejected state."""
    owner = safety_reset_owner
    identifier = owner.seed_requests(1)[0]
    # Represents a stale Approved ID selected before an earlier reset and staff review.
    with closing(psycopg2.connect(owner.db.dsn)) as reviewer:
        with reviewer.cursor() as cursor:
            cursor.execute(
                '''UPDATE public."EquipmentRequest" SET status = 'Rejected', reviewed_by = %s,
                   rejection_reason = 'Concurrent review' WHERE equipment_request_id = %s''',
                [owner.reviewer, identifier],
            )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(reset, owner, [identifier])
            try:
                wait_for(lambda: owner.db.execute(
                    '''SELECT pid FROM pg_stat_activity WHERE datname = %s
                       AND %s = ANY(pg_blocking_pids(pid)) AND wait_event_type = 'Lock' ''',
                    [owner.db.name, reviewer.get_backend_pid()],
                ))
                reviewer.commit()
                response = future.result(timeout=10)
            finally:
                # Release the lock even if observing the expected wait fails.
                reviewer.rollback()

    assert response.status_code == 200
    assert response.json == {"requests": []}
    row = owner.db.snapshot()["EquipmentRequest"][0]
    assert (row["status"], str(row["reviewed_by"]), row["rejection_reason"]) == (
        "Rejected", owner.reviewer, "Concurrent review",
    )
    assert owner.outbox() == []
