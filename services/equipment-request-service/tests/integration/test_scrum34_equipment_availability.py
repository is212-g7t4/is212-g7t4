"""
SCRUM-34: Equipment Availability Checking

User Story
----------
As a Technical Support Staff, I want the system to automatically filter out equipment that's marked unavailable so that I can review equipment that can be used for the Event Request.

Acceptance Criteria
-------------------
AC1: The equipment list shown to Technical Support Staff for a given request must display: item name, requested quantity, and current status (Available, Unavailable).
AC2: Given a unit of equipment is marked Unavailable in the system, when the equipment list is generated, then that unit is excluded from the units counted as available for this request.

Real
----
- Flask routes, token signature/role checks, models/allocation SQL, separate real PostgreSQL connections in fixture-owned databases.

Doubled
-------
- Synthetic external Event/catalogue snapshots; JWKS key lookup only. No other service or broker runs.

Not proven
----------
- Browser behaviour, real upstream snapshots, concurrent catalogue/schedule edits and notification delivery are not proved. Existing fixture loads selected baseline FK tables plus owner outbox migration, NOT the full migration chain; this is a known integration-guide exception, unchanged here. See docs/testing/integration-testing.md (repository root) for fixture limits and commands; collection alone is not execution.
"""

from concurrent.futures import ThreadPoolExecutor

from contextlib import closing

import psycopg2

from app.allocation import APPROVAL_LOCK

from tests.integration.equipment_request_db_helpers import uid, wait_for, TOKEN

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


@pytest.mark.parametrize("case", ["equipment"], ids=["missing_catalogue_item"])
def test_ac2_missing_equipment_cannot_consume_stock(owner, case):
    """Summary: A missing catalogue item fails closed without changing requests or jobs; supporting AC2 guard.
    AC2: Given a unit of equipment is marked Unavailable in the system, when the equipment list is generated, then that unit is excluded from the units counted as available for this request.
    Double: Stub (Supabase JWKS lookup supplies a test signing key); Stub (JWT clock fixed for local token verification); Stub (supplied external event/catalogue or notification context; no upstream service runs); PostgreSQL connections, SQL and transactions are real, not doubles
    """
    ids = owner.seed_requests(1)
    payload = approval_payload(owner, ids)
    checked = payload["approvalContext"]
    checked["equipment"] = []
    before = owner.db.snapshot()
    assert decide(owner, payload).status_code == 409
    assert owner.db.snapshot() == before


@pytest.mark.parametrize("catalogue_status,expected", [("Available", 200), ("Unavailable", 409)], ids=["available_control", "unavailable_has_zero_usable_stock"])
def test_ac2_existing_unavailable_item_is_not_approved_despite_positive_catalogue_total(owner, catalogue_status, expected):
    """Summary: The supplied Unavailable item contributes zero, not its positive catalogue quantity, at the real owner transaction.
    AC2: Given a unit of equipment is marked Unavailable in the system, when the equipment list is generated, then that unit is excluded from the units counted as available for this request.
    Double: Stub (Supabase JWKS lookup supplies a test signing key); Stub (JWT clock fixed for local token verification); Stub (supplied external event/catalogue or notification context; no upstream service runs); PostgreSQL connections, SQL and transactions are real, not doubles
    """
    ids = owner.seed_requests(1)
    payload = approval_payload(owner, ids)
    item = next(item for item in payload["approvalContext"]["equipment"] if item["id"] == owner.equipment[0])
    item["status"] = catalogue_status
    assert item["totalQuantity"] == 20
    before = owner.db.snapshot()
    response = decide(owner, payload)
    assert response.status_code == expected, response.json
    if expected == 409:
        assert owner.db.snapshot() == before
    else:
        persisted = owner.db.execute('SELECT status,event_id,quantity_requested FROM public."EquipmentRequest" WHERE equipment_request_id=%s', ids)
        assert len(persisted) == 1
        assert persisted[0]["status"] == "Approved"
        assert str(persisted[0]["event_id"]) == owner.event
        assert persisted[0]["quantity_requested"] == 5
        assert len(owner.outbox()) == 1
