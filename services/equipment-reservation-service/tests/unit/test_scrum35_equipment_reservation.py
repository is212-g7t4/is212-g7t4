"""
SCRUM-35: Equipment Reservation

User Story
----------
As a Technical Support Staff member, I want to reserve available equipment for
a specific event so that the items are secured and cannot be double-booked by
other overlapping events.

Acceptance Criteria
-------------------
AC1: The system must immediately deduct the reserved quantity from the
     available pool for the duration of the event to prevent double-booking
AC2: The reserved equipment record must remain explicitly associated with the
     specific event ID for which it was reserved.

Real
----
- The Equipment Reservation routes and app.clients run for real against a fake
  world; the two-stage availability rules in app.availability run for real.
- Assertions are on the status, the response body and which downstream calls
  the composite makes.

Doubled
-------
- Event, Equipment and Equipment Request Services: Fake (tests/unit/fakes.py
  `World`, wired in by the `world` fixture) - in-memory events, assignments,
  catalogue and request lines; world.calls records which calls were made.
- httpx.request (client tests): Stub (`sent` fixture) - canned FakeResponse;
  the recorded method, URL and headers are inspected.

Not proven
----------
- That two Technical Support staff approving overlapping events at the same
  moment cannot both take the last units: the check-then-approve is not atomic
  across services (NOT COVERED ANYWHERE; raised as a finding).
- That Event Service's overlap query returns exactly the events whose windows
  intersect (-> event-service unit and integration tests).
"""

import pytest

from app import clients, create_app
from app.availability import RESERVING_EVENT_STATUSES, effective_available_stock, evaluate_request
from app.clients import DownstreamError
from tests.unit.factories import COORDINATOR, CREATE_URL, LEAD, TS, bearer, new_item, rows
from tests.unit.fakes import END, LAPTOP, MIC, OTHER, START, TABLE, TARGET, THIRD, USER, FakeResponse, equipment, line

HEADERS = {"Authorization": "Bearer user-token", "Cookie": "must-not-be-forwarded"}
MIC_STOCK = {"id": "e1", "status": "Available", "totalQuantity": 10}


def test_review_list_when_no_event_overlaps_shows_full_stock(world, client):
    """
    Summary: With no overlapping event, the whole stock is available to the request.
    AC1: The system must immediately deduct the reserved quantity from the
        available pool for the duration of the event to prevent double-booking
    Double: Fake (world: no overlapping events)
    """
    world.requests = [line("r1", TARGET, MIC, 10)]

    request = rows(client)[0]["requests"][0]

    assert request["availability"] == {"reservedQuantity": 0, "availableStock": 10, "isInsufficient": False}


def test_review_list_when_overlapping_event_holds_some_subtracts_only_that(world, client):
    """
    Summary: Units approved for an overlapping event are deducted; the rest stays available.
    AC1: The system must immediately deduct the reserved quantity from the
        available pool for the duration of the event to prevent double-booking
    Double: Fake (world: one overlapping event holds part of the stock)
    """
    # Another confirmed event holds 4 of 10 mics in the same window; a third holds 3 more.
    world.overlapping = [{"id": OTHER}, {"id": THIRD}]
    world.requests = [
        line("r1", TARGET, MIC, 3),
        line("held-1", OTHER, MIC, 4, "Approved"),
        line("held-2", THIRD, MIC, 3, "Approved"),
        line("held-pending", OTHER, MIC, 5, "Pending"),
    ]

    event = next(e for e in rows(client) if e["eventId"] == TARGET)

    assert event["requests"][0]["availability"] == {"reservedQuantity": 7, "availableStock": 3, "isInsufficient": False}
    assert ("overlapping", START, END, RESERVING_EVENT_STATUSES, TARGET) in world.calls
    assert ("list_requests", "Approved", [OTHER, THIRD]) in world.calls


def test_review_list_when_overlapping_event_only_submitted_reserves_nothing(world, client, monkeypatch):
    """
    Summary: An overlapping event that is only Submitted does not hold stock, even with approved lines.
    AC1: The system must immediately deduct the reserved quantity from the
        available pool for the duration of the event to prevent double-booking
    Double: Fake (world: overlapping Submitted event)
    """
    world.events[OTHER] = {"id": OTHER, "status": "Submitted"}
    world.events[THIRD] = {"id": THIRD, "status": "Under Review"}
    world.requests = [
        line("target", TARGET, MIC, 6),
        line("legacy", OTHER, MIC, 10, "Approved"),
        line("held", THIRD, MIC, 4, "Approved"),
    ]

    def overlapping_events(start, end, statuses, exclude_event_id):
        return [world.events[event_id] for event_id in (OTHER, THIRD)
                if world.events[event_id]["status"] in statuses]

    monkeypatch.setattr("app.clients.get_overlapping_events", overlapping_events)

    target = next(event for event in rows(client) if event["eventId"] == TARGET)

    assert target["requests"][0]["availability"] == {
        "reservedQuantity": 4, "availableStock": 6, "isInsufficient": False,
    }
    assert ("list_requests", "Approved", [THIRD]) in world.calls


def test_review_list_when_overlapping_lines_pending_or_rejected_deducts_only_approved(world, client):
    """
    Summary: Only approved lines of overlapping events reduce what is available.
    AC1: The system must immediately deduct the reserved quantity from the
        available pool for the duration of the event to prevent double-booking
    Double: Fake (world: overlapping event with Approved and Pending lines)
    """
    outside_window = "00000000-0000-4000-8000-0000000000d4"
    world.overlapping = [{"id": OTHER}]
    world.requests = [
        line("r1", TARGET, MIC, 6),
        line("held", OTHER, MIC, 4, "Approved"),
        line("pending", OTHER, MIC, 3, "Pending"),
        line("outside", outside_window, MIC, 5, "Approved"),
    ]

    request = rows(client)[0]["requests"][0]

    assert request["availability"] == {"reservedQuantity": 4, "availableStock": 6, "isInsufficient": False}
    assert ("list_requests", "Approved", [OTHER]) in world.calls


@pytest.mark.parametrize("event_status", ["Pending Safety Check", "Safety Changes Requested"], ids=["pending_safety_check", "safety_changes_requested"])
@pytest.mark.parametrize("request_status", ["Approved", "Pending", "Rejected"], ids=["approved", "pending", "rejected"])
def test_review_list_when_overlapping_event_in_safety_check_still_holds_approved_stock(world, client, event_status, request_status):
    """
    Summary: An overlapping event under safety review keeps its approved equipment held.
    AC1: The system must immediately deduct the reserved quantity from the
        available pool for the duration of the event to prevent double-booking
    Double: Fake (world: overlapping event in a safety status)
    """
    world.overlapping = [{"id": OTHER, "status": event_status}]
    world.requests = [
        line("r1", TARGET, MIC, 7),
        line("held", OTHER, MIC, 4, request_status),
    ]

    request = rows(client)[0]["requests"][0]

    reserved = 4 if request_status == "Approved" else 0
    assert request["availability"] == {
        "reservedQuantity": reserved,
        "availableStock": 10 - reserved,
        "isInsufficient": request_status == "Approved",
    }
    assert ("overlapping", START, END, RESERVING_EVENT_STATUSES, TARGET) in world.calls
    assert ("list_requests", "Approved", [OTHER]) in world.calls
    assert "Pending Safety Check" in RESERVING_EVENT_STATUSES
    assert "Safety Changes Requested" in RESERVING_EVENT_STATUSES
    assert "Clarification Requested" in RESERVING_EVENT_STATUSES
    assert "Cancelled" not in RESERVING_EVENT_STATUSES


def test_review_list_when_overlapping_line_rejected_reserves_nothing(world, client):
    """
    Summary: A rejected line of an overlapping event holds no stock.
    AC1: The system must immediately deduct the reserved quantity from the
        available pool for the duration of the event to prevent double-booking
    Double: Fake (world: overlapping event with a Rejected line)
    """
    world.overlapping = [{"id": OTHER}]
    world.requests = [
        line("r1", TARGET, MIC, 8),
        line("rejected", OTHER, MIC, 10, "Rejected"),
    ]

    request = rows(client)[0]["requests"][0]

    assert request["availability"] == {"reservedQuantity": 0, "availableStock": 10, "isInsufficient": False}
    assert ("list_requests", "Approved", [OTHER]) in world.calls


def test_review_list_when_request_one_above_remaining_is_insufficient(world, client):
    """
    Summary: Asking for one unit more than remains is marked insufficient.
    AC1: (boundary: requested = remaining + 1)
    Double: Fake (world: overlapping event holds part of the stock)
    """
    world.overlapping = [{"id": OTHER}]
    world.requests = [line("r1", TARGET, MIC, 7), line("r2", TARGET, TABLE, 50), line("held", OTHER, MIC, 4, "Approved")]

    event = next(e for e in rows(client) if e["eventId"] == TARGET)
    by_id = {r["id"]: r["availability"] for r in event["requests"]}

    assert by_id["r1"] == {"reservedQuantity": 4, "availableStock": 6, "isInsufficient": True}
    assert by_id["r2"] == {"reservedQuantity": 0, "availableStock": 50, "isInsufficient": False}


def test_review_list_when_event_has_no_dates_reserves_nothing(world, client):
    """
    Summary: An event with no dates yet is not checked against other events.
    AC1: The system must immediately deduct the reserved quantity from the
        available pool for the duration of the event to prevent double-booking
    Double: Fake (world: TARGET without start/end)
    """
    world.events[TARGET] = {"id": TARGET, "eventName": "Hackday", "status": "Submitted", "startTime": None, "endTime": None}
    world.requests = [line("r1", TARGET, MIC, 10)]

    assert rows(client)[0]["requests"][0]["availability"] == {"reservedQuantity": 0, "availableStock": 10, "isInsufficient": False}
    assert not any(call[0] == "overlapping" for call in world.calls)


@pytest.mark.parametrize("reserved,expected", [(0, 10), (4, 6), (10, 0)], ids=["none_reserved", "some_reserved", "all_reserved"])
def test_effective_stock_when_part_reserved_leaves_the_rest(reserved, expected):
    """
    Summary: Reserved units are taken out of the pool and the rest stay available.
    AC1: The system must immediately deduct the reserved quantity from the
        available pool for the duration of the event to prevent double-booking
    Double: None
    """
    assert effective_available_stock(MIC_STOCK, reserved) == expected


def test_effective_stock_when_over_reserved_is_zero():
    """
    Summary: An over-reserved pool shows zero available, never a negative number.
    AC1: The system must immediately deduct the reserved quantity from the
        available pool for the duration of the event to prevent double-booking
    Double: None
    """
    assert effective_available_stock(MIC_STOCK, 13) == 0


@pytest.mark.parametrize("requested,insufficient", [(6, False), (7, True)], ids=["at_remaining", "one_above_remaining"])
def test_evaluate_request_when_near_remaining_balance_flags_only_excess(requested, insufficient):
    """
    Summary: A request is insufficient only when it asks for more than remains.
    AC1: (boundary: requested = remaining, remaining + 1)
    Double: None
    """
    result = evaluate_request({"quantityRequested": requested}, MIC_STOCK, 4)
    assert result == {"reservedQuantity": 4, "availableStock": 6, "isInsufficient": insufficient}


def test_reserving_statuses_include_amendment_requested():
    """
    Summary: An event sent back for amendment keeps its approved equipment held.
    AC1: The system must immediately deduct the reserved quantity from the
        available pool for the duration of the event to prevent double-booking
    Double: None
    """
    assert "Amendment Requested" in RESERVING_EVENT_STATUSES


def test_overlap_and_catalogue_clients_call_event_and_equipment_services(sent):
    """
    Summary: Overlapping events and the catalogue come from Event and Equipment Services.
    AC1: The system must immediately deduct the reserved quantity from the
        available pool for the duration of the event to prevent double-booking
    AC2: reservations stay associated with their event id
    Double: Stub (httpx.request returns events and equipment)
    """
    calls, fake = sent
    fake.response = FakeResponse(body={"events": [], "equipment": [{"id": "e"}]})

    assert clients.get_overlapping_events("s", "e", ("Approved", "Confirmed", "Submitted"), "ev") == []
    assert clients.list_equipment() == [{"id": "e"}]
    assert calls[0][2]["params"] == {"start": "s", "end": "e", "statuses": "Approved,Confirmed,Submitted", "excludeEventId": "ev"}
    assert calls[1][1] == "http://localhost:5002/equipment"
