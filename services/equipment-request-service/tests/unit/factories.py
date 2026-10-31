"""Shared unit-test helpers (import as `from tests.unit.factories import ...`)."""

import time

import jwt
from cryptography.hazmat.primitives.asymmetric import ec


# Stands in for Supabase's ES256 signing key; the unit conftest makes the
# verifier trust its public half (SCRUM-8).
TEST_SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())


def bearer(user_id, role, key=TEST_SIGNING_KEY, **claims):
    """Authorization header for a signed-in user, as Supabase would issue it."""
    payload = {"sub": user_id, "aud": "authenticated", "exp": int(time.time()) + 3600, "user_role": role}
    payload.update(claims)
    return {"Authorization": f"Bearer {jwt.encode(payload, key, algorithm='ES256')}"}


def signed_in(client, user_id="00000000-0000-4000-8000-000000000001", role="Event Coordinator"):
    """Send every request from this test client with a signed-in user's token."""
    client.environ_base["HTTP_AUTHORIZATION"] = bearer(user_id, role)["Authorization"]
    return client


USER_ID = "ad3d6da3-7220-4f80-9157-2ee4abc0455c"
REQUEST_ID = "2a1bfb57-a3c0-4450-897e-cc5c73690000"
EVENT_ID = "4a569df8-b7e4-44a2-af9f-d60000000000"
MIC = "2ebcd2d3-636b-48e7-8784-d00000000000"
TABLE = "3ebcd2d3-636b-48e7-8784-d00000000000"
ORIGIN = "http://localhost:5174"


def approval_context(event_id=EVENT_ID, request_ids=None, equipment_ids=None, total=100) -> dict:
    """Trusted stock/window responses supplied by the reservation composite in tests."""
    return dict(eventId=event_id, requestIds=[REQUEST_ID] if request_ids is None else request_ids,
        events=[dict(id=event_id, status="Under Review", startTime="2030-01-01T10:00:00", endTime="2030-01-01T18:00:00")],
        equipment=[dict(id=eid, status="Available", totalQuantity=total) for eid in (equipment_ids or [MIC, TABLE])])


def db_row(**overrides):
    """An EquipmentRequest row as PostgreSQL would return it; override what the test is about."""
    row = {
        "equipment_request_id": REQUEST_ID,
        "event_id": EVENT_ID,
        "equipment_id": MIC,
        "quantity_requested": 15,
        "technical_requirements": "For vendor booths",
        "status": "Pending",
        "reviewed_by": None,
    }
    row.update(overrides)
    return row


def item(equipment_id=MIC, quantity=2, requirements="  Two handheld  "):
    """One line of an equipment request submission."""
    return {"equipmentId": equipment_id, "quantityRequested": quantity, "technicalRequirements": requirements}
