"""SCRUM-32: Create Event Equipment Request

User Story
----------
As an Event Coordinator and Event Coordinator Lead, I want to record the equipment required for an event so that the technical team is informed of the resources needed as requested.

Acceptance Criteria
-------------------
AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
AC2: Recorded equipment request accurately reflects the date and time of the corresponding event
AC3: Ensure newly recorded equipment requests default to an initial status such as "Pending"

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
  catalogue and canned request lines; owner writes/persistence are not simulated;
  world.calls records which calls were made.
- httpx.request (client tests): Stub (`sent` fixture) - canned FakeResponse;
  the recorded method, URL and headers are inspected.

Not proven
----------
- AC1: Local item validation, assignment/role gate and outbound creation values are checked; durable records belong to Equipment Request Service.
- AC2: Event ID is forwarded but date/time fidelity is untested here; Event owns schedule storage.
- AC3: Pending replies are asserted from the fake owner; real default and persistence belong to Equipment Request Service.
- Supporting validation, transport, retry, authentication configuration and defensive checks retain useful regressions, but their exact limits/failure contracts are not separate Jira ACs; Product Owner clarification remains pending.
- Real Supabase issuance, other services, browser rendering and actual broker durability are NOT COVERED ANYWHERE in this module.
"""

import pytest

from app import clients, create_app
from app.availability import RESERVING_EVENT_STATUSES, effective_available_stock, evaluate_request
from app.clients import DownstreamError
from tests.unit.factories import COORDINATOR, CREATE_URL, LEAD, TS, bearer, new_item, rows
from tests.unit.fakes import END, LAPTOP, MIC, OTHER, START, TABLE, TARGET, THIRD, USER, FakeResponse, equipment, line

HEADERS = {"Authorization": "Bearer user-token", "Cookie": "must-not-be-forwarded"}
MIC_STOCK = {"id": "e1", "status": "Available", "totalQuantity": 10}


@pytest.mark.parametrize("event_status", ["Under Review", "Safety Changes Requested"], ids=["under_review", "safety_changes_requested"])
def test_create_request_when_coordinator_assigned_and_event_open_saves_pending_lines(assigned, client, event_status):
    """Summary: The assigned coordinator can record equipment for an event still in planning, and every line starts Pending.
AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
AC3: Ensure newly recorded equipment requests default to an initial status such as "Pending"
Double: Fake (world: TARGET assigned to the coordinator)
"""
    assigned.events[TARGET]["status"] = event_status

    response = client.post(CREATE_URL, headers=COORDINATOR, json={"items": [new_item(), new_item(TABLE, 60, "")]})

    assert response.status_code == 201
    assert [(r["equipmentId"], r["quantityRequested"], r["status"]) for r in response.json["requests"]] == [
        (MIC, 3, "Pending"), (TABLE, 60, "Pending"),
    ]
    forwarded = next(call for call in assigned.calls if call[0] == "create_event_requests")
    assert forwarded == ("create_event_requests", TARGET, [
        {"equipmentId": MIC, "quantityRequested": 3, "technicalRequirements": "Two handheld"},
        {"equipmentId": TABLE, "quantityRequested": 60, "technicalRequirements": ""},
    ])


def test_create_request_when_stock_is_short_still_records_the_need(assigned, client):
    """Summary: Recording a need does not depend on stock; availability is checked at review.
AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
Double: Fake (world: overlapping events hold the stock)
"""
    assigned.overlapping = [{"id": OTHER}]
    assigned.requests = [line("held", OTHER, MIC, 10, "Approved")]

    assert client.post(CREATE_URL, headers=COORDINATOR, json={"items": [new_item(MIC, 10)]}).status_code == 201
    assert not any(call[0] == "overlapping" for call in assigned.calls)


def test_create_request_for_already_requested_equipment_records_another_line(assigned, client):
    """Summary: An event can ask for more of equipment it already requested.
AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
Double: Fake (world: TARGET already has a line for MIC)
"""
    assigned.requests = [line("existing", TARGET, MIC, 2)]
    assert client.post(CREATE_URL, headers=COORDINATOR, json={"items": [new_item()]}).status_code == 201


def test_create_request_when_event_not_assigned_to_coordinator_returns_403(world, client):
    """Summary: A coordinator cannot record equipment for someone else's event.
AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
Double: Fake (world: TARGET unassigned)
"""
    world.coordinator_assignments = {TARGET: THIRD}

    response = client.post(CREATE_URL, headers=COORDINATOR, json={"items": [new_item()]})

    assert response.status_code == 403
    assert not any(call[0] == "create_event_requests" for call in world.calls)


@pytest.mark.parametrize("event_status", ["Submitted", "Approved", "Confirmed", "Rejected", "Cancelled"], ids=["submitted", "approved", "confirmed", "rejected", "cancelled"])
def test_create_request_when_event_no_longer_in_planning_returns_409(assigned, client, event_status):
    """Summary: Equipment cannot be added once an event is submitted-only, approved, confirmed, rejected or cancelled.
AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
Double: Fake (world: TARGET in the given status)
"""
    assigned.events[TARGET]["status"] = event_status

    response = client.post(CREATE_URL, headers=COORDINATOR, json={"items": [new_item()]})

    assert response.status_code == 409
    assert response.json["message"] == "Equipment can only be requested while the event is Under Review or Safety Changes Requested."
    assert not any(call[0] == "create_event_requests" for call in assigned.calls)


def test_create_request_when_lead_assigned_saves_pending_lines(assigned, client):
    """Summary: The Lead can record equipment for an event assigned to them.
AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
AC3: Ensure newly recorded equipment requests default to an initial status such as "Pending"
Double: Fake (world: TARGET assigned to the Lead)
"""
    response = client.post(CREATE_URL, headers=LEAD, json={"items": [new_item()]})

    assert response.status_code == 201
    assert [r["status"] for r in response.json["requests"]] == ["Pending"]


def test_create_request_when_lead_not_assigned_returns_403(world, client):
    """Summary: The Lead cannot record equipment for an event assigned to another coordinator.
AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
Double: Fake (world: TARGET assigned to someone else)
"""
    world.coordinator_assignments = {TARGET: THIRD}

    assert client.post(CREATE_URL, headers=LEAD, json={"items": [new_item()]}).status_code == 403


def test_create_request_for_unavailable_equipment_returns_409(assigned, client):
    """Summary: Equipment marked Unavailable cannot be requested.
AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
Double: Fake (world: catalogue marks LAPTOP Unavailable)
"""
    response = client.post(CREATE_URL, headers=COORDINATOR, json={"items": [new_item(), new_item(LAPTOP, 1)]})

    assert response.status_code == 409
    assert response.json["message"] == "This equipment is Unavailable: Laptop."
    assert not any(call[0] == "create_event_requests" for call in assigned.calls)


def test_create_request_for_equipment_not_in_catalogue_returns_404(assigned, client):
    """Summary: Equipment that is not in the catalogue cannot be requested.
AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
Double: Fake (world: catalogue without the id)
"""
    missing = "00000000-0000-4000-8000-00000000ffff"
    assert client.post(CREATE_URL, headers=COORDINATOR, json={"items": [new_item(missing)]}).status_code == 404


@pytest.mark.parametrize("headers,code", [({}, 401), (TS, 403), (bearer(USER, "Event Organiser"), 403)], ids=["no_token", "technical_support", "event_organiser"])
def test_create_request_when_not_a_coordinator_is_refused(world, client, headers, code):
    """Summary: Only signed-in coordinators and the Lead can record equipment needs.
AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
Double: Fake (world)
"""
    # Arrange (Given): world, client, headers, code, from fixtures

    # Act + Assert (When / Then)
    assert client.post(CREATE_URL, headers=headers, json={"items": [new_item()]}).status_code == code
    assert world.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"items": []},
        {"items": ["mic"]},
        {"items": [new_item(equipment_id="nope")]},
        {"items": [new_item(quantity=0)]},
        {"items": [new_item(quantity="3")]},
        {"items": [new_item(quantity=True)]},
        {"items": [new_item(requirements=["x"])]},
        {"items": [new_item(requirements="x" * 1001)]},
        {"items": [new_item(), new_item()]},
        {"items": [new_item(f"{i:08d}-0000-4000-8000-00000000e001") for i in range(51)]},
    ],
    ids=["no_body", "empty_object", "empty_items", "item_as_text", "bad_equipment_id", "zero_quantity", "quantity_as_text", "quantity_as_bool", "requirements_not_text", "requirements_too_long", "duplicate_equipment", "too_many_items"],
)
def test_create_request_with_invalid_items_returns_400(world, client, payload):
    """Summary: A submission with no items, bad ids, quantities or requirements, duplicates or too many lines is refused.
AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
Double: Fake (world; nothing is created)
"""
    # Create request AC1 (validation): malformed equipment needs must not reach persistence.
    assert client.post(CREATE_URL, headers=COORDINATOR, json=payload).status_code == 400
    assert world.calls == []


def test_create_request_with_malformed_event_id_returns_400(world, client):
    """Summary: A request must name a valid event.
AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
Double: Fake (world)
"""
    assert client.post("/equipment-reservations/events/nope/requests", headers=COORDINATOR, json={"items": [new_item()]}).status_code == 400


def test_create_event_requests_client_posts_items_with_callers_token(sent):
    """Summary: The lines are sent to Equipment Request Service as the signed-in coordinator.
AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
Double: Stub (canned downstream HTTP responses), Mock (recorded outbound method, URL, headers or no-call contract).
"""
    calls, fake = sent
    fake.response = FakeResponse(201, body={"requests": [{"id": "r"}]})
    items = [{"equipmentId": "e", "quantityRequested": 2, "technicalRequirements": ""}]

    with create_app().test_request_context(headers=HEADERS):
        assert clients.create_event_requests("ev", items) == [{"id": "r"}]

    method, url, kwargs = calls[0]
    assert (method, url) == ("POST", "http://localhost:5011/events/ev/equipment-requests")
    assert kwargs["json"] == {"items": items, "notificationContext": {"eventId": "ev"}}
    assert kwargs["headers"] == {"Authorization": "Bearer user-token", "X-Internal-Token": "synthetic"}


def distinct_items(count):
    ids = [f"{i:08d}-0000-4000-8000-00000000e001" for i in range(count)]
    return ids, [new_item(equipment_id) for equipment_id in ids]


@pytest.mark.parametrize(
    "count, expected_status",
    [(49, 201), (50, 201), (51, 400)],
    ids=["below_limit", "at_limit", "above_limit"],
)
def test_create_request_when_line_count_near_limit_accepts_up_to_50(assigned, client, count, expected_status):
    """Summary: One submission can record up to 50 equipment lines.
AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
Double: Fake (world: catalogue holds every requested item)
"""
    ids, items = distinct_items(count)
    assigned.catalogue = [equipment(equipment_id, "Mic", 10) for equipment_id in ids]

    response = client.post(CREATE_URL, headers=COORDINATOR, json={"items": items})

    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "length, expected_status",
    [(999, 201), (1000, 201), (1001, 400)],
    ids=["below_limit", "at_limit", "above_limit"],
)
def test_create_request_when_requirements_near_limit_accepts_up_to_1000_characters(assigned, client, length, expected_status):
    """Summary: Technical requirements can be up to 1000 characters.
AC1: The system allows the Event Coordinator and Event Coordinator Lead to record the equipment, equipment type, quantity, and relevant technical requirements for an event.
Double: Fake (world)
"""
    response = client.post(CREATE_URL, headers=COORDINATOR, json={"items": [new_item(requirements="x" * length)]})

    assert response.status_code == expected_status
