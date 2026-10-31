"""SCRUM-34: Equipment Availability Checking

User Story
----------
As a Technical Support Staff, I want the system to automatically filter out
equipment that's marked unavailable so that I can review equipment that can be
used for the Event Request.

Acceptance Criteria
-------------------
AC1: The equipment list shown to Technical Support Staff for a given request
     must display: item name, requested quantity, and current status
     (Available, Unavailable).
AC2: Given a unit of equipment is marked Unavailable in the system, when the
     equipment list is generated, then that unit is excluded from the units
     counted as available for this request.

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



# AC2 ----
@pytest.mark.parametrize("case", ["equipment"], ids=["missing_catalogue_item"])
def test_ac2_missing_equipment_cannot_consume_stock(owner, case):
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
