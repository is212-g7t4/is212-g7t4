"""Equipment availability checking and review validation. Every atomic is stubbed; no network."""
import pytest

from app import create_app
from app.clients import DownstreamError

USER = "ad3d6da3-7220-4f80-9157-2ee4abc0455c"
TS = {"X-Dev-User-Id": USER, "X-Dev-Role": "Technical Support"}
COORDINATOR = {"X-Dev-User-Id": USER, "X-Dev-Role": "Event Coordinator"}

TARGET = "00000000-0000-4000-8000-0000000000a1"
OTHER = "00000000-0000-4000-8000-0000000000b2"
THIRD = "00000000-0000-4000-8000-0000000000c3"
MIC = "00000000-0000-4000-8000-00000000e001"
TABLE = "00000000-0000-4000-8000-00000000e002"
LAPTOP = "00000000-0000-4000-8000-00000000e003"
START, END = "2026-10-01T10:00:00", "2026-10-01T18:00:00"


def line(request_id, event_id, equipment_id, quantity, status="Pending"):
    return {"id": request_id, "eventId": event_id, "equipmentId": equipment_id, "quantityRequested": quantity,
            "technicalRequirements": "", "status": status, "reviewedBy": None}


def equipment(equipment_id, description, total, status="Available"):
    return {"id": equipment_id, "type": "Microphone", "description": description, "totalQuantity": total, "status": status,
            "location": "", "setupRequirements": ""}


class World:
    """In-memory stand-ins for Event, Equipment and Equipment Request Service."""

    def __init__(self):
        self.requests = []
        self.events = {TARGET: {"id": TARGET, "eventName": "Hackday", "status": "Under Review", "coordinatorId": None,
                                "startTime": START, "endTime": END}}
        self.coordinator_assignments = {}
        self.overlapping = []
        self.catalogue = [equipment(MIC, "Wireless mic", 10), equipment(TABLE, "Table", 50), equipment(LAPTOP, "Laptop", 8, "Unavailable")]
        self.calls = []

    def list_requests(self, headers, status=None, event_ids=None):
        self.calls.append(("list_requests", status, event_ids))
        return [r for r in self.requests if (status is None or r["status"] == status) and (event_ids is None or r["eventId"] in event_ids)]

    def get_request(self, headers, request_id):
        return next(r for r in self.requests if r["id"] == request_id)

    def review_request(self, headers, request_id, status):
        self.calls.append(("review_request", request_id, status))
        return {**self.get_request(headers, request_id), "status": status, "reviewedBy": USER}

    def review_event_requests(self, headers, event_id, status):
        self.calls.append(("review_event_requests", event_id, status))
        return [{**r, "status": status, "reviewedBy": USER} for r in self.requests if r["eventId"] == event_id and r["status"] == "Pending"]

    def get_event_summaries(self, ids):
        return [self.events[i] for i in ids if i in self.events]

    def list_assigned_event_ids(self, coordinator_id):
        self.calls.append(("assigned_events", coordinator_id))
        return [event_id for event_id, assigned_id in self.coordinator_assignments.items() if assigned_id == coordinator_id]

    def get_overlapping_events(self, start, end, statuses, exclude_event_id):
        self.calls.append(("overlapping", start, end, tuple(statuses), exclude_event_id))
        return self.overlapping

    def list_equipment(self):
        return self.catalogue


@pytest.fixture
def world(monkeypatch):
    fake = World()
    for name in ("list_requests", "get_request", "review_request", "review_event_requests",
                 "get_event_summaries", "list_assigned_event_ids", "get_overlapping_events", "list_equipment"):
        monkeypatch.setattr(f"app.clients.{name}", getattr(fake, name))
    return fake


@pytest.fixture
def client():
    return create_app({"FRONTEND_ORIGIN": "http://localhost:5174"}).test_client()


def rows(client, **query):
    response = client.get("/equipment-reservations", headers=TS, query_string=query)
    assert response.status_code == 200
    return response.json["events"]


def test_health(client):
    assert client.get("/health").json == {"status": "ok"}


def test_full_stock_is_available_when_no_other_event_overlaps(world, client):
    world.requests = [line("r1", TARGET, MIC, 10)]

    request = rows(client)[0]["requests"][0]

    assert request["availability"] == {"reservedQuantity": 0, "availableStock": 10, "isInsufficient": False}


def test_partial_allocation_only_subtracts_what_overlapping_events_hold(world, client):
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
    assert ("overlapping", START, END, ("Approved", "Confirmed", "Submitted", "Under Review"), TARGET) in world.calls
    assert ("list_requests", "Approved", [OTHER, THIRD]) in world.calls


def test_only_approved_requests_from_overlapping_events_reduce_available_stock(world, client):
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


def test_rejected_request_from_an_overlapping_event_does_not_reserve_stock(world, client):
    world.overlapping = [{"id": OTHER}]
    world.requests = [
        line("r1", TARGET, MIC, 8),
        line("rejected", OTHER, MIC, 10, "Rejected"),
    ]

    request = rows(client)[0]["requests"][0]

    assert request["availability"] == {"reservedQuantity": 0, "availableStock": 10, "isInsufficient": False}
    assert ("list_requests", "Approved", [OTHER]) in world.calls


def test_a_request_one_above_the_remaining_balance_is_insufficient(world, client):
    world.overlapping = [{"id": OTHER}]
    world.requests = [line("r1", TARGET, MIC, 7), line("r2", TARGET, TABLE, 50), line("held", OTHER, MIC, 4, "Approved")]

    event = next(e for e in rows(client) if e["eventId"] == TARGET)
    by_id = {r["id"]: r["availability"] for r in event["requests"]}

    assert by_id["r1"] == {"reservedQuantity": 4, "availableStock": 6, "isInsufficient": True}
    assert by_id["r2"] == {"reservedQuantity": 0, "availableStock": 50, "isInsufficient": False}


def test_physically_unavailable_equipment_has_zero_stock_whatever_is_reserved(world, client):
    world.requests = [line("r1", TARGET, LAPTOP, 1)]

    event = rows(client)[0]

    assert event["requests"][0]["availability"]["availableStock"] == 0
    assert event["requests"][0]["availability"]["isInsufficient"] is True
    assert event["requests"][0]["equipment"] == {"description": "Laptop", "type": "Microphone", "totalQuantity": 8, "status": "Unavailable"}
    assert world.catalogue[2]["status"] == "Unavailable"  # never written to


def test_equipment_missing_from_the_catalogue_has_no_stock(world, client):
    world.requests = [line("r1", TARGET, "00000000-0000-4000-8000-00000000ffff", 1)]
    request = rows(client)[0]["requests"][0]
    assert request["equipment"] is None and request["availability"]["isInsufficient"] is True


@pytest.mark.parametrize("equipment_id", [LAPTOP, "00000000-0000-4000-8000-00000000ffff"])
def test_approval_is_blocked_for_unavailable_or_unknown_equipment(world, client, equipment_id):
    request_id = "00000000-0000-4000-8000-0000000000d5"
    world.requests = [line(request_id, TARGET, equipment_id, 1)]

    response = client.patch(f"/equipment-reservations/requests/{request_id}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 409
    assert not any(call[0] == "review_request" for call in world.calls)


def test_decided_lines_carry_no_availability_and_trigger_no_window_lookup(world, client):
    world.requests = [line("r1", TARGET, MIC, 3, "Approved"), line("r2", TARGET, TABLE, 3, "Rejected")]

    event = rows(client)[0]

    assert [r["availability"] for r in event["requests"]] == [None, None]
    assert not any(call[0] == "overlapping" for call in world.calls)


def test_event_without_a_window_is_treated_as_having_nothing_reserved(world, client):
    world.events[TARGET] = {"id": TARGET, "eventName": "Hackday", "status": "Submitted", "startTime": None, "endTime": None}
    world.requests = [line("r1", TARGET, MIC, 10)]

    assert rows(client)[0]["requests"][0]["availability"] == {"reservedQuantity": 0, "availableStock": 10, "isInsufficient": False}
    assert not any(call[0] == "overlapping" for call in world.calls)


def test_unknown_event_is_labelled_and_has_no_window(world, client):
    world.requests = [line("r1", OTHER, MIC, 1)]
    event = rows(client)[0]
    assert event["eventName"] == "Unknown event" and event["startTime"] is None


def test_event_view_includes_coordinator_id_for_frontend_name_resolution(world, client):
    coordinator_id = "00000000-0000-4000-8000-00000000c001"
    world.events[TARGET]["coordinatorId"] = coordinator_id
    world.requests = [line("r1", TARGET, MIC, 1)]

    assert rows(client)[0]["coordinatorId"] == coordinator_id


def test_no_requests_returns_no_events(world, client):
    assert rows(client) == []


def test_status_filter_is_passed_to_the_request_service(world, client):
    rows(client, status="Approved")
    assert world.calls[0] == ("list_requests", "Approved", None)


def test_event_coordinator_can_view_but_not_review(world, client):
    assert client.get("/equipment-reservations", headers=COORDINATOR).status_code == 200
    assert client.patch(f"/equipment-reservations/events/{TARGET}", headers=COORDINATOR, json={"status": "Rejected"}).status_code == 403
    assert client.patch("/equipment-reservations/requests/r1", headers=COORDINATOR, json={"status": "Rejected"}).status_code == 403


def test_coordinator_sees_only_events_currently_assigned_to_them(world, client):
    assigned_event = "00000000-0000-4000-8000-0000000000e1"
    other_event = "00000000-0000-4000-8000-0000000000e2"
    world.coordinator_assignments = {assigned_event: USER, other_event: THIRD}
    world.requests = [line("assigned", assigned_event, MIC, 2), line("other", other_event, MIC, 2)]

    response = client.get("/equipment-reservations", headers=COORDINATOR)

    assert response.status_code == 200
    assert [event["eventId"] for event in response.json["events"]] == [assigned_event]
    assert ("assigned_events", USER) in world.calls
    assert ("list_requests", None, [assigned_event]) in world.calls


def test_coordinator_with_no_assigned_events_sees_no_requests(world, client):
    world.requests = [line("unassigned", TARGET, MIC, 2)]

    response = client.get("/equipment-reservations", headers=COORDINATOR)

    assert response.status_code == 200
    assert response.json["events"] == []
    assert ("list_requests", None, []) in world.calls


def test_reassigned_coordinator_loses_access_and_new_coordinator_gains_it(world, client):
    event_id = "00000000-0000-4000-8000-0000000000e1"
    world.requests = [line("assigned", event_id, MIC, 2)]
    world.coordinator_assignments = {event_id: THIRD}

    old_coordinator = client.get("/equipment-reservations", headers=COORDINATOR)
    new_coordinator = client.get("/equipment-reservations", headers={"X-Dev-User-Id": THIRD, "X-Dev-Role": "Event Coordinator"})

    assert old_coordinator.json["events"] == []
    assert [event["eventId"] for event in new_coordinator.json["events"]] == [event_id]


@pytest.mark.parametrize("headers,code", [({}, 401), ({"X-Dev-User-Id": "bad", "X-Dev-Role": "Technical Support"}, 401), ({"X-Dev-User-Id": USER, "X-Dev-Role": "Attendee"}, 403)])
def test_requires_an_authorised_dev_user(world, client, headers, code):
    assert client.get("/equipment-reservations", headers=headers).status_code == code
    assert world.calls == []


def test_rejects_unknown_status_filter(world, client):
    assert client.get("/equipment-reservations?status=Broken", headers=TS).status_code == 400


# --- batch review -----------------------------------------------------------

def test_batch_approve_is_blocked_when_any_line_is_insufficient(world, client):
    world.overlapping = [{"id": OTHER}]
    world.requests = [line("r1", TARGET, MIC, 7), line("r2", TARGET, TABLE, 2), line("held", OTHER, MIC, 4, "Approved")]

    response = client.patch(f"/equipment-reservations/events/{TARGET}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 409
    assert "Wireless mic (requested 7, available 6)" in response.json["message"]
    assert "Table" not in response.json["message"]
    assert not any(call[0] == "review_event_requests" for call in world.calls)


def test_batch_reject_is_allowed_even_when_a_line_is_insufficient(world, client):
    world.requests = [line("r1", TARGET, LAPTOP, 1), line("r2", TARGET, TABLE, 2)]

    response = client.patch(f"/equipment-reservations/events/{TARGET}", headers=TS, json={"status": "Rejected"})

    assert response.status_code == 200
    assert [r["status"] for r in response.json["requests"]] == ["Rejected", "Rejected"]
    assert ("review_event_requests", TARGET, "Rejected") in world.calls
    assert not any(call[0] == "overlapping" for call in world.calls)


def test_batch_approve_succeeds_when_every_line_fits(world, client):
    world.requests = [line("r1", TARGET, MIC, 10), line("r2", TARGET, TABLE, 2)]

    response = client.patch(f"/equipment-reservations/events/{TARGET}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 200
    assert ("review_event_requests", TARGET, "Approved") in world.calls


def test_batch_approve_with_nothing_pending_defers_to_the_request_service(world, client, monkeypatch):
    def conflict(headers, event_id, status):
        raise DownstreamError(409, "This event has no Pending equipment requests.")

    monkeypatch.setattr("app.clients.review_event_requests", conflict)
    response = client.patch(f"/equipment-reservations/events/{TARGET}", headers=TS, json={"status": "Approved"})
    assert response.status_code == 409 and response.json["message"] == "This event has no Pending equipment requests."


# --- single review ----------------------------------------------------------

def test_approving_an_insufficient_line_is_blocked(world, client):
    rid = "00000000-0000-4000-8000-0000000000d1"
    world.requests = [line(rid, TARGET, MIC, 11)]

    response = client.patch(f"/equipment-reservations/requests/{rid}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 409
    assert "requested 11, available 10" in response.json["message"]
    assert not any(call[0] == "review_request" for call in world.calls)


def test_approving_a_line_that_fits_is_forwarded(world, client):
    rid = "00000000-0000-4000-8000-0000000000d2"
    world.requests = [line(rid, TARGET, MIC, 10)]

    response = client.patch(f"/equipment-reservations/requests/{rid}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 200 and response.json["request"]["status"] == "Approved"


def test_rejecting_an_insufficient_line_needs_no_stock_check(world, client):
    rid = "00000000-0000-4000-8000-0000000000d3"
    world.requests = [line(rid, TARGET, LAPTOP, 5)]

    response = client.patch(f"/equipment-reservations/requests/{rid}", headers=TS, json={"status": "Rejected"})

    assert response.status_code == 200
    assert world.calls == [("review_request", rid, "Rejected")]


def test_approving_an_already_decided_line_defers_to_the_request_service(world, client):
    rid = "00000000-0000-4000-8000-0000000000d4"
    world.requests = [line(rid, TARGET, LAPTOP, 5, "Approved")]

    assert client.patch(f"/equipment-reservations/requests/{rid}", headers=TS, json={"status": "Approved"}).status_code == 200
    assert ("review_request", rid, "Approved") in world.calls


@pytest.mark.parametrize("path", ["/equipment-reservations/requests/nope", "/equipment-reservations/events/nope"])
def test_review_rejects_non_uuid_ids(world, client, path):
    assert client.patch(path, headers=TS, json={"status": "Approved"}).status_code == 400


@pytest.mark.parametrize("payload", [None, {}, {"status": "Pending"}, {"status": "Maybe"}, ["Approved"]])
def test_review_rejects_invalid_status(world, client, payload):
    for path in (f"/equipment-reservations/events/{TARGET}", f"/equipment-reservations/requests/{TARGET}"):
        assert client.patch(path, headers=TS, json=payload).status_code == 400
    assert world.calls == []


def test_downstream_failures_are_reported_with_their_status(world, client, monkeypatch):
    def down(*args, **kwargs):
        raise DownstreamError(503, "Unable to reach a service this request depends on.")

    monkeypatch.setattr("app.clients.list_requests", down)
    response = client.get("/equipment-reservations", headers=TS)
    assert response.status_code == 503 and "Unable to reach" in response.json["message"]


def test_cors_allows_the_frontend_origin_and_patch(client):
    response = client.options("/equipment-reservations", headers={"Origin": "http://localhost:5174"})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert "PATCH" in response.headers["Access-Control-Allow-Methods"]
    assert "X-Dev-Role" in response.headers["Access-Control-Allow-Headers"]
    assert "Access-Control-Allow-Origin" not in client.options("/equipment-reservations", headers={"Origin": "http://evil.example"}).headers
