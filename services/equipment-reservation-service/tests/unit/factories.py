"""SCRUM48 reservation-only HTTP boundary doubles; no other service code runs."""

import time

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from tests.unit import fakes
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock
import httpx
import pytest
from app import create_app

EVENT, MIC, PROJECTOR, A, B, TSS1, TSS2, R1, R2 = [
    f"10000000-0000-4000-8000-{i:012d}" for i in range(1, 10)]


def identity(user, role):
    return bearer(user, role)


def row(identifier=R1, equipment=MIC, quantity=5, status="Pending"):
    return dict(id=identifier, eventId=EVENT, equipmentId=equipment,
                quantityRequested=quantity, status=status, requestedBy=A)


@pytest.fixture
def boundary(monkeypatch):
    """Fresh external HTTP responses/call log; never emulate SQL or delivery."""
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "synthetic")
    for name, host in [("EQUIPMENT_REQUEST", "owner"), ("EVENT", "events"),
                       ("EQUIPMENT", "equipment"), ("USER", "users")]:
        monkeypatch.setenv(name + "_SERVICE_URL", f"http://{host}.invalid")
    state = SimpleNamespace(event=dict(id=EVENT, eventName="Community Fair",
        coordinatorId=A, status="Under Review", startTime="2030-12-12T10:00:00",
        endTime="2030-12-12T18:00:00"), rows=[row()],
        saved=[row()], write_code=200)
    def http(method, url, **kwargs):
        code = 200
        if url.startswith("http://owner.invalid"):
            if method in ("POST", "PATCH"):
                code = 201 if method == "POST" else state.write_code
                saved = deepcopy(state.saved)
                if method == "PATCH":
                    saved = [{**item, "status": kwargs["json"]["status"]} for item in saved]
                # Owner routes return one request for single review, requests for bulk/create.
                body = ({"request": saved[0]} if method == "PATCH" and "/events/" not in url
                        else {"requests": saved})
                if code >= 400:
                    body = {"message": "There are no Pending requests to review."}
            elif url.endswith("/equipment-requests"):
                rows = deepcopy(state.rows)
                params = kwargs.get("params", {})
                if params.get("status"):
                    rows = [r for r in rows if r["status"] == params["status"]]
                body = dict(requests=rows)
            else:
                body = dict(request=deepcopy(state.rows[0]))
        elif url.endswith("/notification-context"):
            body = deepcopy(state.event)
        elif url.endswith(("/events", "/events/summaries")):
            body = dict(events=[deepcopy(state.event)])
        elif url.endswith("/events/overlapping"):
            body = dict(events=[])
        elif url == "http://equipment.invalid/equipment":
            body = dict(equipment=[dict(id=MIC, description="Microphone", type="Audio", totalQuantity=20, status="Available"),
                                   dict(id=PROJECTOR, description="Projector", type="Visual", totalQuantity=10, status="Available")])
        elif url == "http://users.invalid/users":
            body = dict(users=[dict(user_id=u, role="Technical Support") for u in (TSS1,TSS2)])
        else:
            raise AssertionError(f"Unexpected external HTTP: {method} {url}")
        return httpx.Response(code, json=body, request=httpx.Request(method,url))
    state.http = MagicMock(side_effect=http)
    monkeypatch.setattr(httpx, "request", state.http)
    state.client = create_app({"TESTING":True}).test_client()
    return state


def mutations(boundary):
    return [c for c in boundary.http.call_args_list if c.args[0] in ("POST", "PATCH")]


# Stands in for Supabase's ES256 signing key; the unit conftest makes the
# verifier trust its public half (SCRUM-8).
TEST_SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())


def bearer(user_id, role, key=TEST_SIGNING_KEY, **claims):
    """Authorization header for a signed-in user, as Supabase would issue it."""
    payload = {"sub": user_id, "aud": "authenticated", "exp": 1893456000 + 3600, "user_role": role}
    payload.update(claims)
    return {"Authorization": f"Bearer {jwt.encode(payload, key, algorithm='ES256')}"}


def signed_in(client, user_id="00000000-0000-4000-8000-000000000001", role="Event Coordinator"):
    """Send every request from this test client with a signed-in user's token."""
    client.environ_base["HTTP_AUTHORIZATION"] = bearer(user_id, role)["Authorization"]
    return client


# Review/create headers for the fake world in tests/unit/fakes.py (its USER, TARGET and MIC,
# not the SCRUM-48 identifiers above).
TS = bearer(fakes.USER, "Technical Support")
COORDINATOR = bearer(fakes.USER, "Event Coordinator")
LEAD = bearer(fakes.USER, "Event Coordinator Lead")
CREATE_URL = f"/equipment-reservations/events/{fakes.TARGET}/requests"


def rows(client, **query):
    """The Technical Support review list, asserting it loaded."""
    response = client.get("/equipment-reservations", headers=TS, query_string=query)
    assert response.status_code == 200
    return response.json["events"]


def new_item(equipment_id=fakes.MIC, quantity=3, requirements=" Two handheld "):
    """One line of an equipment request submission."""
    return {"equipmentId": equipment_id, "quantityRequested": quantity, "technicalRequirements": requirements}
