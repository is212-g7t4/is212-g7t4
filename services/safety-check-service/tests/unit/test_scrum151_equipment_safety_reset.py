"""
SCRUM-151: Reject or Request Changes to Safety Arrangements

User Story
----------
As a Safety Officer, I want to reject an event's safety arrangement or request
changes, stating which planning area must be revisited, so that the Event
Coordinator knows exactly what to fix before the event can proceed.

Acceptance Criteria
-------------------
AC1: Given an event is 'Pending Safety Check', when I request changes, then I
     must select at least one affected area (venue arrangement,
     technical/equipment arrangement, event details) and describe the change
     needed; otherwise the decision is not saved.
AC2: Given changes are requested, then the event status changes to 'Safety
     Changes Requested', the event returns to the planning stage for each
     selected area, and its existing arrangements are preserved. For equipment
     requests affected by the requested changes, only requests with status
     'Approved' return to 'Pending' for review. Requests already 'Pending' or
     'Rejected' remain unchanged, including any recorded reviewer and rejection
     reason.
AC3: Given an event is 'Pending Safety Check', when I reject it, then a reason
     is required and I must confirm the rejection before it is saved.
AC4: Given I confirm a rejection, then the event status changes to 'Cancelled',
     and the event cannot be resubmitted for a safety check or moved to any
     further stage.
AC5: Given an event is cancelled by a safety rejection, then its venue bookings
     and equipment reservations are released so they no longer block other
     events, while their records remain in the event's history.
AC6: Given either decision, then the safety check is recorded with the status
     'Changes Requested' or 'Safety Rejected' respectively, together with my
     identity, the timestamp and the reason (plus the selected areas for a
     change request), and the original event information is retained.
AC7: Given an event is not 'Pending Safety Check', then these actions are not
     available and an API call is rejected without changing the event.

Real
----
- Which equipment requests a technical change request sends back for review:
  only approved ones, whether the whole technical area or specific requests are
  flagged; rejected and pending requests keep their status and review details;
  and a flag naming another event's request is refused.
- We check which requests are sent back, and that the decision is still
  recorded.

Doubled
-------
- Event, Safety Check Record, Equipment Request and User Services: hold the
  event, its round and a mix of approved, rejected and pending equipment
  requests [Stub]; we check which requests are sent back and whether the
  decision and event move happen [Mock].
- Sign-in: a test key signs the caller's token (tests/conftest.py) [Stub].

Not proven
----------
- That Equipment Request Service keeps the review details of requests it does
  not reset (-> equipment-request-service tests).
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
    """
    Summary: Flagging specific equipment requests sends back only the flagged one that was approved; its approved sibling, and the flagged rejected and pending ones, are left as they were.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests with
        status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The event has an approved, a rejected and a pending equipment
        request, and the other services accept the decision [Stub]; we check
        which requests are sent back for review [Mock].
    """
    client, calls, requests = decision
    requests.append(equipment_request("Approved", OTHER_ID))
    flags = [technical_flag(identifier) for identifier in [REQUEST_ID, REJECTED_ID, PENDING_ID]]

    response = request_changes(client, flags)

    assert response.status_code == 200
    calls["reset_equipment_safety_requests"].assert_called_once_with(EVENT_ID, [REQUEST_ID])
    assert calls["decide_safety_check_record"].call_args.args[-1] == flags


@pytest.mark.parametrize("known_id", [REJECTED_ID, PENDING_ID])
def test_unknown_target_beside_ineligible_target_is_rejected(decision, known_id):
    """
    Summary: A flag naming an equipment request that is not this event's is refused, even beside a valid flag, and nothing is saved.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: The event's equipment requests do not include the named one
        [Stub]; we check no decision, reset or event move happens [Mock].
    """
    client, calls, _ = decision

    response = request_changes(client, [technical_flag(known_id), technical_flag(OTHER_ID)])

    assert response.status_code == 400
    assert response.json["message"] == "Flagged equipment requests must belong to this event."
    calls["decide_safety_check_record"].assert_not_called()
    calls["reset_equipment_safety_requests"].assert_not_called()
    calls["set_event_safety_status"].assert_not_called()


def test_broad_flag_with_no_approved_equipment_skips_reset(decision):
    """
    Summary: When the event has no approved equipment, flagging the technical area changes no equipment request, and the change request is still recorded.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests with
        status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The event has only a rejected and a pending equipment request
        [Stub]; we check none is sent back for review [Mock].
    """
    client, calls, requests = decision
    requests.pop(0)

    response = request_changes(client, [technical_flag()])

    assert response.status_code == 200
    calls["reset_equipment_safety_requests"].assert_not_called()
    calls["set_event_safety_status"].assert_called_once()


def test_broad_technical_flag_resets_only_approved_equipment(decision):
    """
    Summary: Flagging the whole technical area sends back only the approved equipment requests; rejected and pending ones keep their status and review details.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests with
        status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The event has an approved, a rejected and a pending equipment
        request, and the other services accept the decision [Stub]; we check
        which requests are sent back for review [Mock].
    """
    client, calls, _ = decision

    response = request_changes(client, [technical_flag()])

    assert response.status_code == 200
    calls["reset_equipment_safety_requests"].assert_called_once_with(EVENT_ID, [REQUEST_ID])
    calls["set_event_safety_status"].assert_called_once()


@pytest.mark.parametrize("request_id", [REJECTED_ID, PENDING_ID])
def test_targeted_ineligible_request_skips_reset_but_records_change(decision, request_id):
    """
    Summary: Flagging a rejected or pending equipment request records the requested change without reopening that request.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests with
        status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: The event has an approved, a rejected and a pending equipment
        request, and the other services accept the decision [Stub]; we check
        which requests are sent back for review [Mock].
    """
    client, calls, _ = decision

    response = request_changes(client, [technical_flag(request_id)])

    assert response.status_code == 200
    calls["reset_equipment_safety_requests"].assert_not_called()
    assert calls["decide_safety_check_record"].call_args.args[-1] == [technical_flag(request_id)]
    calls["set_event_safety_status"].assert_called_once()
