"""Issue 8: preserve equipment decisions when safety requests technical changes.

Approved narrow bug-fix rules (no Jira story key was assigned):
1. Only affected Approved equipment requests return to Pending.
2. Pending and Rejected requests, including review metadata, stay unchanged.
3. Targeted IDs must belong to the event even when ineligible for reset.
Real: Flask route, token verification and decision orchestration.
Doubled: downstream service wrappers; persisted SQL is proved in the atomic tier.
Not proven: downstream HTTP contracts, database writes or the browser journey.
"""
from unittest.mock import Mock

import pytest

from app import clients, create_app
from tests.unit.factories import (
    EVENT_ID, OFFICER_ID, REQUEST_ID, bearer, equipment_request, event, record, user,
)

REJECTED_ID = "88888888-8888-4888-8888-888888888881"
PENDING_ID = "88888888-8888-4888-8888-888888888882"
OTHER_ID = "88888888-8888-4888-8888-888888888883"


@pytest.fixture
def decision(monkeypatch):
    """Supply mixed downstream requests; return the real client and recorded boundary calls."""
    requests = [
        equipment_request("Approved", REQUEST_ID, reviewedBy=OFFICER_ID),
        equipment_request("Rejected", REJECTED_ID, reviewedBy=OFFICER_ID, rejectionReason="Unsafe cabling"),
        equipment_request("Pending", PENDING_ID),
    ]
    calls = {}
    for name, result in {
        "get_user": user(),
        "get_event": event("Pending Safety Check"),
        "list_safety_check_records": [record()],
        "get_event_equipment_requests": requests,
        "decide_safety_check_record": record(status="Changes Requested"),
        "reset_equipment_safety_requests": [],
        "set_event_safety_status": event("Safety Changes Requested"),
    }.items():
        calls[name] = Mock(return_value=result)
        monkeypatch.setattr(clients, name, calls[name])
    return create_app().test_client(), calls, requests


def request_changes(client, flags):
    """Send technical flags as the Safety Officer and return the route response."""
    return client.post(
        "/safety-checks/request-changes",
        headers=bearer(OFFICER_ID, "Safety Officer"),
        json={"eventId": EVENT_ID, "reason": "Move cables.", "flags": flags},
    )


def technical_flag(request_id=None):
    """Build a broad or targeted technical-change flag from an optional request ID."""
    flag = {"area": "technical arrangement", "changeRequired": "Move cables."}
    if request_id is not None:
        flag["equipmentRequestId"] = request_id
    return flag


def test_targeted_mixed_flags_preserve_unaffected_approval(decision):
    """Normal: mixed targeted flags send only the affected approval, not its approved sibling."""
    client, calls, requests = decision
    requests.append(equipment_request("Approved", OTHER_ID))
    flags = [technical_flag(identifier) for identifier in [REQUEST_ID, REJECTED_ID, PENDING_ID]]

    response = request_changes(client, flags)

    assert response.status_code == 200
    calls["reset_equipment_safety_requests"].assert_called_once_with(EVENT_ID, [REQUEST_ID])
    assert calls["decide_safety_check_record"].call_args.args[-1] == flags


@pytest.mark.parametrize("known_id", [REJECTED_ID, PENDING_ID])
def test_unknown_target_beside_ineligible_target_is_rejected(decision, known_id):
    """Failure: filtering known ineligible targets must not hide an unknown or foreign ID."""
    client, calls, _ = decision

    response = request_changes(client, [technical_flag(known_id), technical_flag(OTHER_ID)])

    assert response.status_code == 400
    assert response.json["message"] == "Flagged equipment requests must belong to this event."
    calls["decide_safety_check_record"].assert_not_called()
    calls["reset_equipment_safety_requests"].assert_not_called()
    calls["set_event_safety_status"].assert_not_called()


def test_broad_flag_with_no_approved_equipment_skips_reset(decision):
    """Boundary: an event with only Pending and Rejected requests keeps their decisions."""
    client, calls, requests = decision
    requests.pop(0)

    response = request_changes(client, [technical_flag()])

    assert response.status_code == 200
    calls["reset_equipment_safety_requests"].assert_not_called()
    calls["set_event_safety_status"].assert_called_once()


def test_broad_technical_flag_resets_only_approved_equipment(decision):
    """Normal: mixed event requests produce only Approved IDs at the reset boundary."""
    client, calls, _ = decision

    response = request_changes(client, [technical_flag()])

    assert response.status_code == 200
    calls["reset_equipment_safety_requests"].assert_called_once_with(EVENT_ID, [REQUEST_ID])
    calls["set_event_safety_status"].assert_called_once()


@pytest.mark.parametrize("request_id", [REJECTED_ID, PENDING_ID])
def test_targeted_ineligible_request_skips_reset_but_records_change(decision, request_id):
    """Boundary: a known ineligible target records feedback without reopening its decision."""
    client, calls, _ = decision

    response = request_changes(client, [technical_flag(request_id)])

    assert response.status_code == 200
    calls["reset_equipment_safety_requests"].assert_not_called()
    assert calls["decide_safety_check_record"].call_args.args[-1] == [technical_flag(request_id)]
    calls["set_event_safety_status"].assert_called_once()
