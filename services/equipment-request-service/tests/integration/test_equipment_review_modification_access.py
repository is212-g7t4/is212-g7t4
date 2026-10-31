"""SCRUM-10: Role-Based Modification Control for Events

User Story
----------
As a registered user, I want to modify only information appropriate to my role
and relationship to an event, so that I can perform my responsibilities without
changing information outside my permissions.

Acceptance Criteria
-------------------
AC1: Given an authenticated user is permitted to modify information based on
     their role and relationship to the event, when they make a valid change to
     that information, then the change is allowed.
AC2: Given an authenticated user's role does not permit them to modify
     particular information, when they attempt to change that information, then
     the modification is prevented and the existing information remains
     unchanged.
AC3: Given an authenticated user's relationship to an event does not permit
     them to modify that event's information, when they attempt to make a
     change, then the modification is prevented and the existing information
     remains unchanged.
AC4: Given a user is permitted to view particular information but is not
     permitted to modify it, when they attempt to change that information, then
     the modification is prevented while their permitted viewing access remains
     unaffected.
AC5: Given a user is permitted to modify information for one event but does not
     have the required access to another event, when they attempt to modify
     information for both events, then only modifications to information for
     which they have the required access are allowed.

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
@pytest.mark.parametrize("headers,expected", [("untrusted", 400), ("wrong_token", 400), ("internal_only", 401), ("wrong_role", 403)], ids=["no_service_credential", "wrong_service_credential", "no_user_token", "wrong_user_role"])
def test_ac2_direct_approval_without_both_caller_and_service_authority_changes_nothing(owner, headers, expected):
    """Failure: Knowing stock values or the internal token alone never authorizes an approval."""
    ids = owner.seed_requests(1)
    supplied = {"untrusted": owner.identity(trusted=False),
                "wrong_token": {**owner.identity(), "X-Internal-Token": "wrong"},
                "internal_only": {"X-Internal-Token": TOKEN},
                "wrong_role": owner.identity("Event Coordinator")}[headers]
    before = owner.db.snapshot()
    assert decide(owner, approval_payload(owner, ids), headers=supplied).status_code == expected
    assert owner.db.snapshot() == before
