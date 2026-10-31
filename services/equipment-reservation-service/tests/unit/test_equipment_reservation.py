"""SCRUM-35: Equipment Reservation

Agreed revision from this conversation; pending confirmation that Jira has been updated

User Story
----------
As a Technical Support Staff member, I want approving equipment requests to reserve the requested quantities for a specific event, so that the total reserved equipment does not exceed the available stock, including when multiple requests are approved at the same time.

Acceptance Criteria
-------------------
AC1: Given a Pending equipment request has sufficient available stock for the event’s duration, when I approve it, then its status changes to Approved and its quantity is immediately counted as reserved when checking further requests.
AC2: Given an equipment request is approved, then its reservation remains associated with the specific event ID for which it was approved.
AC3: Given equipment already has Approved requests for the same event or other overlapping events whose reservations still apply, when the system checks a new approval, then it subtracts those reserved quantities from the usable stock. Pending and Rejected requests do not reserve stock.
AC4: Given I select multiple Pending equipment requests for bulk approval, when the system checks availability, then it adds together the selected quantities for each equipment item. If every item has sufficient stock, all selected requests are approved. If any item has insufficient stock, none of the selected requests is approved and all remain Pending.
AC5: Given multiple approval actions compete for the same available equipment, when they are processed at the same time, then the total approved quantity must not exceed the available stock. Any approval that no longer has sufficient stock leaves its selected requests Pending.
AC6: Given the quantity being approved exactly equals the remaining available quantity, when I approve it, then approval succeeds. If the quantity exceeds the remaining available quantity, approval is refused and the selected requests remain Pending.

Real
----
- Real Flask review routes, availability arithmetic and HTTP client construction; response values, selected event/request IDs and refused mutations are asserted.

Doubled
-------
- Fake (Event, Equipment and Equipment Request service world), Stub (canned HTTP responses), Mock (outbound review calls inspected). Supabase JWKS key lookup is a Stub; token verification is real.

Not proven
----------
- Owner SQL persistence and concurrent approvals (AC5) are not proved by these doubles. The maintained owner regressions are equipment-request-service/tests/integration/test_equipment_reservation.py; collection is verified, but execution is blocked by an unrelated auto-restarting backend-ngrok-1 container. The strict preservation guard is unchanged.
- AC1/AC2 approval is simulated at the owner boundary, not persisted here. AC6 arithmetic boundary is checked; concurrent catalogue quantities or event schedule/status changes are outside the approval guarantee.
- Event Service overlap-query correctness, UI rendering and end-to-end reservation/notification delivery are NOT COVERED ANYWHERE in this module.
- Supporting reliability checks (missing dates, status eligibility, transport payloads) are not independent new ACs; exact fail-closed/transport contracts need Jira confirmation.
"""

import pytest

from app import clients, create_app

from app.availability import RESERVING_EVENT_STATUSES, effective_available_stock, evaluate_request

from app.clients import DownstreamError

from tests.unit.factories import COORDINATOR, CREATE_URL, LEAD, TS, bearer, new_item, rows

from tests.unit.fakes import END, LAPTOP, MIC, OTHER, START, TABLE, TARGET, THIRD, USER, FakeResponse, equipment, line

HEADERS = {"Authorization": "Bearer user-token", "Cookie": "must-not-be-forwarded"}

MIC_STOCK = {"id": "e1", "status": "Available", "totalQuantity": 10}


import httpx

import pytest

from tests.unit.factories import boundary, identity, mutations, EVENT, A, R1, R2, row


import httpx

import pytest

from app import clients, create_app

from app.availability import RESERVING_EVENT_STATUSES, effective_available_stock, evaluate_request

from app.clients import DownstreamError

from tests.unit.factories import COORDINATOR, CREATE_URL, LEAD, TS, bearer, new_item, rows

from tests.unit.fakes import END, LAPTOP, MIC, OTHER, START, TABLE, TARGET, THIRD, USER, FakeResponse, equipment, line

HEADERS = {"Authorization": "Bearer user-token", "Cookie": "must-not-be-forwarded"}

MIC_STOCK = {"id": "e1", "status": "Available", "totalQuantity": 10}



def test_review_list_when_no_event_overlaps_shows_full_stock(world, client):
    """Summary: With no overlapping event, the whole stock is available to the request.
    AC3: Count only still-applicable Approved reservations when computing the remaining stock.
    Double: Fake (world: no overlapping events)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    world.requests = [line("r1", TARGET, MIC, 10)]

    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    request = rows(client)[0]["requests"][0]

    assert request["availability"] == {"reservedQuantity": 0, "availableStock": 10, "isInsufficient": False}


def test_review_list_when_overlapping_event_holds_some_subtracts_only_that(world, client):
    """Summary: Units approved for an overlapping event are deducted; the rest stays available.
    AC3: Count only still-applicable Approved reservations when computing the remaining stock.
    Double: Fake (world: one overlapping event holds part of the stock)
    """
    # Another confirmed event holds 4 of 10 mics in the same window; a third holds 3 more.
    # Arrange (Given): test data and external adapters from fixtures.
    world.overlapping = [{"id": OTHER}, {"id": THIRD}]
    world.requests = [
        line("r1", TARGET, MIC, 3),
        line("held-1", OTHER, MIC, 4, "Approved"),
        line("held-2", THIRD, MIC, 3, "Approved"),
        line("held-pending", OTHER, MIC, 5, "Pending"),
    ]

    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    event = next(e for e in rows(client) if e["eventId"] == TARGET)

    assert event["requests"][0]["availability"] == {"reservedQuantity": 7, "availableStock": 3, "isInsufficient": False}
    assert ("overlapping", START, END, RESERVING_EVENT_STATUSES, TARGET) in world.calls
    assert ("list_requests", "Approved", [OTHER, THIRD]) in world.calls


def test_review_list_when_overlapping_event_only_submitted_reserves_nothing(world, client, monkeypatch):
    """Summary: An overlapping event that is only Submitted does not hold stock, even with approved lines.
    AC3: Count only still-applicable Approved reservations when computing the remaining stock.
    Double: Fake (world: overlapping Submitted event)
    """
    # Arrange (Given): test data and external adapters from fixtures.
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

    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    target = next(event for event in rows(client) if event["eventId"] == TARGET)

    assert target["requests"][0]["availability"] == {
        "reservedQuantity": 4, "availableStock": 6, "isInsufficient": False,
    }
    assert ("list_requests", "Approved", [THIRD]) in world.calls


def test_review_list_when_overlapping_lines_pending_or_rejected_deducts_only_approved(world, client):
    """Summary: Only approved lines of overlapping events reduce what is available.
    AC3: Count only still-applicable Approved reservations when computing the remaining stock.
    Double: Fake (world: overlapping event with Approved and Pending lines)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    outside_window = "00000000-0000-4000-8000-0000000000d4"
    world.overlapping = [{"id": OTHER}]
    world.requests = [
        line("r1", TARGET, MIC, 6),
        line("held", OTHER, MIC, 4, "Approved"),
        line("pending", OTHER, MIC, 3, "Pending"),
        line("outside", outside_window, MIC, 5, "Approved"),
    ]

    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    request = rows(client)[0]["requests"][0]

    assert request["availability"] == {"reservedQuantity": 4, "availableStock": 6, "isInsufficient": False}
    assert ("list_requests", "Approved", [OTHER]) in world.calls


@pytest.mark.parametrize("event_status", ["Pending Safety Check", "Safety Changes Requested"], ids=["pending_safety_check", "safety_changes_requested"])
@pytest.mark.parametrize("request_status", ["Approved", "Pending", "Rejected"], ids=["approved", "pending", "rejected"])
def test_review_list_when_overlapping_event_in_safety_check_still_holds_approved_stock(world, client, event_status, request_status):
    """Summary: An overlapping event under safety review keeps its approved equipment held.
    AC3: Count only still-applicable Approved reservations when computing the remaining stock.
    Double: Fake (world: overlapping event in a safety status)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    world.overlapping = [{"id": OTHER, "status": event_status}]
    world.requests = [
        line("r1", TARGET, MIC, 7),
        line("held", OTHER, MIC, 4, request_status),
    ]

    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
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
    """Summary: A rejected line of an overlapping event holds no stock.
    AC3: Count only still-applicable Approved reservations when computing the remaining stock.
    Double: Fake (world: overlapping event with a Rejected line)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    world.overlapping = [{"id": OTHER}]
    world.requests = [
        line("r1", TARGET, MIC, 8),
        line("rejected", OTHER, MIC, 10, "Rejected"),
    ]

    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    request = rows(client)[0]["requests"][0]

    assert request["availability"] == {"reservedQuantity": 0, "availableStock": 10, "isInsufficient": False}
    assert ("list_requests", "Approved", [OTHER]) in world.calls


def test_review_list_when_request_one_above_remaining_is_insufficient(world, client):
    """Summary: Asking for one unit more than remains is marked insufficient.
    AC6: Exactly remaining stock fits; excess is insufficient.
    Double: Fake (world: overlapping event holds part of the stock)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    world.overlapping = [{"id": OTHER}]
    world.requests = [line("r1", TARGET, MIC, 7), line("r2", TARGET, TABLE, 50), line("held", OTHER, MIC, 4, "Approved")]

    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    event = next(e for e in rows(client) if e["eventId"] == TARGET)
    by_id = {r["id"]: r["availability"] for r in event["requests"]}

    assert by_id["r1"] == {"reservedQuantity": 4, "availableStock": 6, "isInsufficient": True}
    assert by_id["r2"] == {"reservedQuantity": 0, "availableStock": 50, "isInsufficient": False}


def test_review_list_when_event_has_no_dates_reserves_nothing(world, client):
    """Summary: An event with no dates yet is not checked against other events.
    AC3: Count only still-applicable Approved reservations when computing the remaining stock.
    Double: Fake (world: TARGET without start/end)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    world.events[TARGET] = {"id": TARGET, "eventName": "Hackday", "status": "Submitted", "startTime": None, "endTime": None}
    world.requests = [line("r1", TARGET, MIC, 10)]

    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    assert rows(client)[0]["requests"][0]["availability"] == {"reservedQuantity": 0, "availableStock": 10, "isInsufficient": False}
    assert not any(call[0] == "overlapping" for call in world.calls)


@pytest.mark.parametrize("reserved,expected", [(0, 10), (4, 6), (10, 0)], ids=["none_reserved", "some_reserved", "all_reserved"])
def test_effective_stock_when_part_reserved_leaves_the_rest(reserved, expected):
    """Summary: Reserved units are taken out of the pool and the rest stay available.
    AC3: Count only still-applicable Approved reservations when computing the remaining stock.
    Double: None
    """
    # Arrange (Given): test data and external adapters from fixtures.
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    assert effective_available_stock(MIC_STOCK, reserved) == expected


def test_effective_stock_when_over_reserved_is_zero():
    """Summary: An over-reserved pool shows zero available, never a negative number.
    AC3: Count only still-applicable Approved reservations when computing the remaining stock.
    Double: None
    """
    # Arrange (Given): test data and external adapters from fixtures.
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    assert effective_available_stock(MIC_STOCK, 13) == 0


@pytest.mark.parametrize("requested,insufficient", [(6, False), (7, True)], ids=["at_remaining", "one_above_remaining"])
def test_evaluate_request_when_near_remaining_balance_flags_only_excess(requested, insufficient):
    """Summary: A request is insufficient only when it asks for more than remains.
    AC6: Exactly remaining stock fits; excess is insufficient.
    Double: None
    """
    # Arrange (Given): test data and external adapters from fixtures.
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    result = evaluate_request({"quantityRequested": requested}, MIC_STOCK, 4)
    assert result == {"reservedQuantity": 4, "availableStock": 6, "isInsufficient": insufficient}


def test_reserving_statuses_include_amendment_requested():
    """Summary: An event sent back for amendment keeps its approved equipment held.
    AC3: Count only still-applicable Approved reservations when computing the remaining stock.
    Double: None
    """
    # Arrange (Given): test data and external adapters from fixtures.
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    assert "Amendment Requested" in RESERVING_EVENT_STATUSES


def test_overlap_and_catalogue_clients_call_event_and_equipment_services(sent):
    """Summary: Overlapping events and the catalogue come from Event and Equipment Services.
    AC2: Keep event identity in the request context.
    Double: Stub (httpx.request returns events and equipment)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    calls, fake = sent
    fake.response = FakeResponse(body={"events": [], "equipment": [{"id": "e"}]})

    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    assert clients.get_overlapping_events("s", "e", ("Approved", "Confirmed", "Submitted"), "ev") == []
    assert clients.list_equipment() == [{"id": "e"}]
    assert calls[0][2]["params"] == {"start": "s", "end": "e", "statuses": "Approved,Confirmed,Submitted", "excludeEventId": "ev"}
    assert calls[1][1] == "http://localhost:5002/equipment"


def test_approval_sends_complete_context_and_exact_selection(boundary):
    """Summary: The owner receives stock, event windows and precisely the checked Pending IDs.
    AC2: Preserve the event and exact selected requests in the approval context.
    Double: Stub (external HTTP responses); Mock (outbound mutation call log)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    response = boundary.client.patch(f"/equipment-reservations/events/{EVENT}", headers=identity(A, "Technical Support"), json={"status": "Approved"})
    assert response.status_code == 200
    call = mutations(boundary)[0]
    assert call.kwargs["json"]["approvalContext"]["requestIds"] == [R1]
    assert call.kwargs["json"]["approvalContext"]["events"] == [boundary.event]
    assert call.kwargs["headers"]["X-Internal-Token"] == "synthetic"


def test_single_approval_counts_own_approved_quantity(boundary):
    """Summary: Own Approved 15 leaves only 5; approving Pending 10 is refused before writing.
    AC3: Own Approved quantities reserve stock before another approval.
    Double: Stub (external HTTP responses); Mock (outbound mutation call log)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    boundary.rows = [row(R1, quantity=10), row(R2, quantity=15, status="Approved")]
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    response = boundary.client.patch(f"/equipment-reservations/requests/{R1}", headers=identity(A, "Technical Support"), json={"status": "Approved"})
    assert response.status_code == 409
    assert mutations(boundary) == []


def test_bulk_groups_duplicate_equipment_quantities(boundary):
    """Summary: Two Pending lines of 15 cannot together fit stock 20, although each fits alone.
    AC4: Group quantities for the same equipment across selected Pending lines.
    Double: Stub (external HTTP responses); Mock (outbound mutation call log)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    boundary.rows = [row(R1, quantity=15), row(R2, quantity=15)]
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    response = boundary.client.patch(f"/equipment-reservations/events/{EVENT}", headers=identity(A, "Technical Support"), json={"status": "Approved"})
    assert response.status_code == 409
    assert mutations(boundary) == []


@pytest.mark.parametrize("window", [None, "missing_start", "missing_end"], ids=["missing_event", "missing_start", "missing_end"])
def test_missing_target_window_never_sends_an_approval(boundary, window):
    """Summary: No Event summary or either missing endpoint fails closed before owner mutation.
    AC1: Approval needs a checkable event duration (supporting fail-closed check).
    Double: Stub (external HTTP responses); Mock (outbound mutation call log)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    if window == "missing_start": boundary.event["startTime"] = None
    elif window == "missing_end": boundary.event["endTime"] = None
    else:
        original = boundary.http.side_effect
        def http(method, url, **kwargs):
            if url.endswith("/events/summaries"):
                return httpx.Response(200, json={"events": []}, request=httpx.Request(method, url))
            return original(method, url, **kwargs)
        boundary.http.side_effect = http
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    response = boundary.client.patch(f"/equipment-reservations/events/{EVENT}", headers=identity(A, "Technical Support"), json={"status": "Approved"})
    assert response.status_code == 409
    assert mutations(boundary) == []


def test_context_includes_eligible_overlap_without_approved_requests(boundary):
    """Summary: Pending-only and even request-free overlaps are supplied for post-lock owner reads.
    AC5: Supply eligible competing event context before the owner fresh-read check (supporting boundary check; no race is proved).
    Double: Stub (external HTTP responses); Mock (outbound mutation call log)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    competitor = {**boundary.event, "id": R2}
    original = boundary.http.side_effect
    def http(method, url, **kwargs):
        if url.endswith("/events/overlapping"):
            return httpx.Response(200, json={"events": [competitor]}, request=httpx.Request(method, url))
        return original(method, url, **kwargs)
    boundary.http.side_effect = http
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    response = boundary.client.patch(f"/equipment-reservations/events/{EVENT}", headers=identity(A, "Technical Support"), json={"status": "Approved"})
    assert response.status_code == 200
    assert mutations(boundary)[0].kwargs["json"]["approvalContext"]["events"] == [boundary.event, competitor]


def test_bulk_approve_when_any_line_insufficient_returns_409_without_deciding(world, client):
    """Summary: An event's equipment cannot be approved in one go while any line lacks stock.
    AC4: Bulk approval succeeds only if every selected item fits; otherwise none is changed.
    Double: Fake (world: one line exceeds the remaining stock)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    world.overlapping = [{"id": OTHER}]
    world.requests = [line("r1", TARGET, MIC, 7), line("r2", TARGET, TABLE, 2), line("held", OTHER, MIC, 4, "Approved")]

    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    response = client.patch(f"/equipment-reservations/events/{TARGET}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 409
    assert "Wireless mic (requested 7, available 6)" in response.json["message"]
    assert "Table" not in response.json["message"]
    assert not any(call[0] == "review_event_requests" for call in world.calls)


def test_bulk_approve_when_every_line_fits_approves_all(world, client):
    """Summary: When every pending line fits the stock, the whole event can be approved at once.
    AC4: Bulk approval succeeds only if every selected item fits; otherwise none is changed.
    Double: Fake (world: enough stock for every line)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    world.requests = [line("r1", TARGET, MIC, 10), line("r2", TARGET, TABLE, 2)]

    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    response = client.patch(f"/equipment-reservations/events/{TARGET}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 200
    assert ("review_event_requests", TARGET, "Approved") in world.calls


def test_approve_line_when_insufficient_returns_409_without_deciding(world, client):
    """Summary: A single line cannot be approved when there is not enough stock for it.
    AC6: Approval respects the remaining stock boundary.
    Double: Fake (world: the line exceeds the remaining stock)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    rid = "00000000-0000-4000-8000-0000000000d1"
    world.requests = [line(rid, TARGET, MIC, 11)]

    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    response = client.patch(f"/equipment-reservations/requests/{rid}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 409
    assert "requested 11, available 10" in response.json["message"]
    assert not any(call[0] == "review_request" for call in world.calls)


def test_approve_line_when_it_fits_is_approved(world, client):
    """Summary: A single line that fits the stock can be approved.
    AC1: Approval respects the remaining stock boundary.
    Double: Fake (world: enough stock)
    """
    # Arrange (Given): test data and external adapters from fixtures.
    rid = "00000000-0000-4000-8000-0000000000d2"
    world.requests = [line(rid, TARGET, MIC, 10)]

    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    response = client.patch(f"/equipment-reservations/requests/{rid}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 200 and response.json["request"]["status"] == "Approved"
