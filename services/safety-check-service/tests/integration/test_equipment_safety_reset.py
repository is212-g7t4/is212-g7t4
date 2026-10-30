"""Issue 8: only Approved equipment is sent for safety re-review.

Approved narrow bug-fix rules (no Jira story key was assigned):
1. Broad and targeted technical flags reset only affected Approved requests.
2. Pending and Rejected requests stay unchanged; ineligible targets are valid.
3. Unknown or foreign targeted IDs fail before any decision or reset write.
Real: Flask route, signed caller checks and real httpx client/request building.
Doubled: all downstream HTTP APIs, intercepted by strict respx stubs.
Not proven: downstream persistence (atomic integration tests cover it), sign-in,
            notification delivery or the browser journey.
"""
import json

import pytest
from httpx import Response

from app import clients
from tests.unit.factories import (
    EVENT_ID, OFFICER_ID, RECORD_ID, REQUEST_ID, bearer, equipment_request, event, record,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

REJECTED_ID = "88888888-8888-4888-8888-888888888881"
PENDING_ID = "88888888-8888-4888-8888-888888888882"
UNRELATED_ID = "88888888-8888-4888-8888-888888888883"
UNKNOWN_ID = "88888888-8888-4888-8888-888888888884"
TOKEN = "disposable-safety-reset-token"


def flags_for(targets):
    """Convert optional targeted IDs into valid technical-change flags."""
    return [
        {"area": "technical arrangement", "changeRequired": "Move cables.",
         **({"equipmentRequestId": target} if target is not None else {})}
        for target in targets
    ]


def stub_reads(stubs):
    """Stub the four real HTTP reads with this event's mixed equipment statuses."""
    stubs.get(f"{clients.USER_SERVICE_URL}/users/{OFFICER_ID}").mock(
        return_value=Response(200, json={"id": OFFICER_ID, "role": "Safety Officer"}),
    )
    stubs.get(f"{clients.EVENT_SERVICE_URL}/events/{EVENT_ID}",
              params={"viewerRole": "Safety Officer"}).mock(
        return_value=Response(200, json=event("Pending Safety Check")),
    )
    stubs.get(f"{clients.SAFETY_CHECK_RECORD_SERVICE_URL}/safety-check-records",
              params={"eventId": EVENT_ID, "status": "Pending"}).mock(
        return_value=Response(200, json={"safetyChecks": [record()]}),
    )
    # Shape: Equipment Request Service app/models.py::serialize, including review fields.
    stubs.get(f"{clients.EQUIPMENT_REQUEST_SERVICE_URL}/equipment-requests",
              params={"eventId": EVENT_ID}).mock(return_value=Response(200, json={"requests": [
        equipment_request("Approved", REQUEST_ID, reviewedBy=OFFICER_ID, rejectionReason=None),
        equipment_request("Rejected", REJECTED_ID, reviewedBy=OFFICER_ID, rejectionReason="Unsafe cabling"),
        equipment_request("Pending", PENDING_ID, rejectionReason=None),
        equipment_request("Approved", UNRELATED_ID, reviewedBy=OFFICER_ID, rejectionReason=None),
    ]}))


@pytest.mark.parametrize("targets,expected", [
    ([None], [REQUEST_ID, UNRELATED_ID]),
    ([REQUEST_ID, REJECTED_ID, PENDING_ID], [REQUEST_ID]),
    ([REJECTED_ID], []),
    ([PENDING_ID], []),
], ids=["broad-mixed", "targeted-mixed", "rejected-target", "pending-target"])
def test_only_affected_approved_ids_cross_the_reset_http_boundary(client, stubs, monkeypatch, targets, expected):
    """Normal/boundary: mixed flags produce the exact eligible reset body or no reset HTTP call."""
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", TOKEN)
    stub_reads(stubs)
    flags = flags_for(targets)
    decided = stubs.patch(
        f"{clients.SAFETY_CHECK_RECORD_SERVICE_URL}/safety-check-records/{RECORD_ID}/decision",
    ).mock(return_value=Response(200, json=record(status="Changes Requested")))
    reset = None
    if expected:
        reset = stubs.post(
            f"{clients.EQUIPMENT_REQUEST_SERVICE_URL}/events/{EVENT_ID}/equipment-requests/safety-reset",
        ).mock(return_value=Response(200, json={"requests": [
            equipment_request("Pending", identifier, rejectionReason=None) for identifier in expected
        ]}))
    moved = stubs.patch(f"{clients.EVENT_SERVICE_URL}/events/{EVENT_ID}/safety-status").mock(
        return_value=Response(200, json=event("Safety Changes Requested")),
    )
    headers = bearer(OFFICER_ID, "Safety Officer")

    response = client.post("/safety-checks/request-changes", headers=headers,
                           json={"eventId": EVENT_ID, "reason": "Move cables.", "flags": flags})

    assert response.status_code == 200
    assert response.json["event"]["status"] == "Safety Changes Requested"
    assert json.loads(decided.calls.last.request.content) == {
        "status": "Changes Requested", "remarks": "Move cables.", "flags": flags,
    }
    assert json.loads(moved.calls.last.request.content) == {
        "status": "Safety Changes Requested", "safetyCheckId": RECORD_ID, "roundNumber": 1,
        "remarks": "Move cables.", "areas": ["technical arrangement"],
    }
    if reset is not None:
        assert reset.call_count == 1
        assert json.loads(reset.calls.last.request.content) == {"requestIds": expected}
        assert reset.calls.last.request.headers["X-Internal-Service-Token"] == TOKEN
        assert list(stubs.calls).index(decided.calls.last) < list(stubs.calls).index(reset.calls.last)
        assert list(stubs.calls).index(reset.calls.last) < list(stubs.calls).index(moved.calls.last)
    assert {call.request.headers["Authorization"] for call in stubs.calls} == {headers["Authorization"]}


def test_unknown_target_beside_rejected_target_causes_no_http_writes(client, stubs):
    """Failure: rejecting a foreign/unknown target happens before any downstream write."""
    stub_reads(stubs)

    response = client.post(
        "/safety-checks/request-changes", headers=bearer(OFFICER_ID, "Safety Officer"),
        json={"eventId": EVENT_ID, "reason": "Move cables.",
              "flags": flags_for([REJECTED_ID, UNKNOWN_ID])},
    )

    assert response.status_code == 400
    assert response.json["message"] == "Flagged equipment requests must belong to this event."
    assert {call.request.method for call in stubs.calls} == {"GET"}
