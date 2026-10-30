"""Equipment availability checking and review validation. Every atomic is stubbed; no network."""
import pytest
from flask import g

from app import create_app
from app.availability import RESERVING_EVENT_STATUSES
from app.clients import DownstreamError
from tests.unit.factories import bearer

USER = "ad3d6da3-7220-4f80-9157-2ee4abc0455c"
TS = bearer(USER, "Technical Support")
COORDINATOR = bearer(USER, "Event Coordinator")
LEAD = bearer(USER, "Event Coordinator Lead")

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
        self.safety_rounds = []

    def get_event_safety_checks(self, event_id):
        self.calls.append(("safety_checks", event_id))
        return self.safety_rounds

    def list_requests(self, status=None, event_ids=None):
        self.calls.append(("list_requests", status, event_ids))
        return [r for r in self.requests if (status is None or r["status"] == status) and (event_ids is None or r["eventId"] in event_ids)]

    def get_request(self, request_id):
        return next(r for r in self.requests if r["id"] == request_id)

    def review_request(self, request_id, status, rejection_reason=None):
        self.calls.append(("review_request", request_id, status))
        return {**self.get_request(request_id), "status": status, "reviewedBy": USER, "rejectionReason": rejection_reason}

    def review_event_requests(self, event_id, status, rejection_reason=None):
        self.calls.append(("review_event_requests", event_id, status))
        return [{**r, "status": status, "reviewedBy": USER, "rejectionReason": rejection_reason} for r in self.requests if r["eventId"] == event_id and r["status"] == "Pending"]

    def get_event_summaries(self, ids):
        return [self.events[i] for i in ids if i in self.events]

    def list_assigned_event_ids(self):
        coordinator_id = g.user_id  # Event Service reads the coordinator from the forwarded token.
        self.calls.append(("assigned_events", coordinator_id))
        return [event_id for event_id, assigned_id in self.coordinator_assignments.items() if assigned_id == coordinator_id]

    def list_assigned_events(self):
        return [self.events[event_id] for event_id in self.list_assigned_event_ids() if event_id in self.events]

    def create_event_requests(self, event_id, items):
        self.calls.append(("create_event_requests", event_id, items))
        return [{"id": f"new-{i}", "eventId": event_id, **item, "status": "Pending", "reviewedBy": None} for i, item in enumerate(items)]

    def get_overlapping_events(self, start, end, statuses, exclude_event_id):
        self.calls.append(("overlapping", start, end, tuple(statuses), exclude_event_id))
        return self.overlapping

    def list_equipment(self):
        return self.catalogue


@pytest.fixture
def world(monkeypatch):
    fake = World()
    for name in ("list_requests", "get_request", "review_request", "review_event_requests",
                 "get_event_summaries", "list_assigned_event_ids", "list_assigned_events",
                 "get_overlapping_events", "list_equipment", "create_event_requests", "get_event_safety_checks"):
        monkeypatch.setattr(f"app.clients.{name}", getattr(fake, name))
    return fake


@pytest.fixture
def client():
    return create_app({"FRONTEND_ORIGIN": "http://localhost:5174"}).test_client()


def rows(client, **query):
    response = client.get("/equipment-reservations", headers=TS, query_string=query)
    assert response.status_code == 200
    return response.json["events"]


# Supporting service health check; no story AC is directly verified.
def test_health(client):
    assert client.get("/health").json == {"status": "ok"}


def test_safety_feedback_matches_individual_equipment_and_only_latest_round(world, client):
    world.events[TARGET]["status"] = "Safety Changes Requested"
    world.requests = [line("r1", TARGET, MIC, 1), line("r2", TARGET, TABLE, 2, "Approved")]
    world.safety_rounds = [
        {"roundNumber": 1, "status": "Changes Requested", "remarks": "Old reason.", "flags": [
            {"area": "technical arrangement", "equipmentRequestId": "r2", "changeRequired": "Old change."}]},
        {"roundNumber": 2, "status": "Changes Requested", "remarks": "Trip hazard.", "flags": [
            {"area": "technical arrangement", "equipmentRequestId": "r1", "changeRequired": "Move microphone cables."},
            {"area": "venue arrangement", "changeRequired": "Change room."}]},
    ]
    requests = rows(client)[0]["requests"]
    assert requests[0]["safetyFeedback"] == {"reason": "Trip hazard.", "requestedChanges": ["Move microphone cables."]}
    assert requests[1]["safetyFeedback"] is None
    assert world.calls.count(("safety_checks", TARGET)) == 1


def test_area_wide_technical_feedback_applies_to_each_equipment_request(world, client):
    world.events[TARGET]["status"] = "Safety Changes Requested"
    world.requests = [line("r1", TARGET, MIC, 1), line("r2", TARGET, TABLE, 2)]
    world.safety_rounds = [{"roundNumber": 1, "status": "Changes Requested", "remarks": None, "flags": [
        {"area": "technical arrangement", "equipmentRequestId": None, "changeRequired": "Keep exits clear."}]}]
    assert all(request["safetyFeedback"] == {"reason": None, "requestedChanges": ["Keep exits clear."]}
        for request in rows(client)[0]["requests"])


@pytest.mark.parametrize("rounds", [[], [{"roundNumber": 1, "status": "Pending", "flags": []}]])
def test_missing_or_undecided_round_has_no_safety_feedback(world, client, rounds):
    world.events[TARGET]["status"] = "Safety Changes Requested"
    world.requests = [line("r1", TARGET, MIC, 1)]
    world.safety_rounds = rounds
    assert rows(client)[0]["requests"][0]["safetyFeedback"] is None


def test_non_revision_events_do_not_fetch_safety_records(world, client):
    world.requests = [line("r1", TARGET, MIC, 1)]
    assert rows(client)[0]["requests"][0]["safetyFeedback"] is None
    assert not any(call[0] == "safety_checks" for call in world.calls)


def test_unavailable_safety_records_are_reported_not_mislabelled_unflagged(world, client, monkeypatch):
    world.events[TARGET]["status"] = "Safety Changes Requested"
    world.requests = [line("r1", TARGET, MIC, 1)]
    def unavailable(event_id):
        raise DownstreamError(503, "Safety feedback is unavailable.")
    monkeypatch.setattr("app.clients.get_event_safety_checks", unavailable)
    response = client.get("/equipment-reservations", headers=TS)
    assert response.status_code == 503
    assert response.json["message"] == "Safety feedback is unavailable."


# Reservation AC1: the full pool remains usable without overlapping reservations.
def test_full_stock_is_available_when_no_other_event_overlaps(world, client):
    world.requests = [line("r1", TARGET, MIC, 10)]

    request = rows(client)[0]["requests"][0]

    assert request["availability"] == {"reservedQuantity": 0, "availableStock": 10, "isInsufficient": False}


# Reservation AC1/AC2: subtract Approved quantities belonging to the other overlapping event IDs.
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
    assert ("overlapping", START, END, RESERVING_EVENT_STATUSES, TARGET) in world.calls
    assert ("list_requests", "Approved", [OTHER, THIRD]) in world.calls


# Reservation AC1 (eligibility): legacy Submitted-event requests do not reserve stock.
def test_submitted_events_do_not_reserve_stock_even_with_approved_requests(world, client, monkeypatch):
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


# Reservation AC1: ignore Pending requests and reservations outside the overlapping event set.
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


# Reservation AC1: preserve equipment holds while overlapping events proceed through safety checks.
@pytest.mark.parametrize("event_status", ["Pending Safety Check", "Safety Changes Requested"])
@pytest.mark.parametrize("request_status", ["Approved", "Pending", "Rejected"])
def test_overlapping_safety_event_only_approved_equipment_holds_stock(world, client, event_status, request_status):
    """SCRUM-152 B7: SCRUM-149 moved approved-and-submitted events into
    'Pending Safety Check', outside the pre-Week-7 status list, which had
    silently freed their held equipment for a second overlapping event to
    take. 'Pending Safety Check' and 'Safety Changes Requested' are back in
    RESERVING_EVENT_STATUSES, so the hold survives a safety-check round.
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


# Reservation AC1: Rejected requests do not deduct stock from the usable pool.
def test_rejected_request_from_an_overlapping_event_does_not_reserve_stock(world, client):
    world.overlapping = [{"id": OTHER}]
    world.requests = [
        line("r1", TARGET, MIC, 8),
        line("rejected", OTHER, MIC, 10, "Rejected"),
    ]

    request = rows(client)[0]["requests"][0]

    assert request["availability"] == {"reservedQuantity": 0, "availableStock": 10, "isInsufficient": False}
    assert ("list_requests", "Approved", [OTHER]) in world.calls


# Reservation AC1: flag excess demand for one equipment item without reducing another item's stock.
def test_a_request_one_above_the_remaining_balance_is_insufficient(world, client):
    world.overlapping = [{"id": OTHER}]
    world.requests = [line("r1", TARGET, MIC, 7), line("r2", TARGET, TABLE, 50), line("held", OTHER, MIC, 4, "Approved")]

    event = next(e for e in rows(client) if e["eventId"] == TARGET)
    by_id = {r["id"]: r["availability"] for r in event["requests"]}

    assert by_id["r1"] == {"reservedQuantity": 4, "availableStock": 6, "isInsufficient": True}
    assert by_id["r2"] == {"reservedQuantity": 0, "availableStock": 50, "isInsufficient": False}


# Availability AC1/AC2: expose the item's physical status and exclude all Unavailable units from stock.
def test_physically_unavailable_equipment_has_zero_stock_whatever_is_reserved(world, client):
    world.requests = [line("r1", TARGET, LAPTOP, 1)]

    event = rows(client)[0]

    assert event["requests"][0]["availability"]["availableStock"] == 0
    assert event["requests"][0]["availability"]["isInsufficient"] is True
    assert event["requests"][0]["equipment"] == {"description": "Laptop", "type": "Microphone", "totalQuantity": 8, "status": "Unavailable"}
    assert world.catalogue[2]["status"] == "Unavailable"  # never written to


# Availability AC2 (fallback): unknown catalogue references cannot contribute usable equipment.
def test_equipment_missing_from_the_catalogue_has_no_stock(world, client):
    world.requests = [line("r1", TARGET, "00000000-0000-4000-8000-00000000ffff", 1)]
    request = rows(client)[0]["requests"][0]
    assert request["equipment"] is None and request["availability"]["isInsufficient"] is True


# Availability AC2 / Reservation AC1: reject approval when the equipment has no usable stock.
@pytest.mark.parametrize("equipment_id", [LAPTOP, "00000000-0000-4000-8000-00000000ffff"])
def test_approval_is_blocked_for_unavailable_or_unknown_equipment(world, client, equipment_id):
    request_id = "00000000-0000-4000-8000-0000000000d5"
    world.requests = [line(request_id, TARGET, equipment_id, 1)]

    response = client.patch(f"/equipment-reservations/requests/{request_id}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 409
    assert not any(call[0] == "review_request" for call in world.calls)


# Review AC1/AC2 (decided state): already-reviewed lines need no new availability evaluation.
def test_decided_lines_carry_no_availability_and_trigger_no_window_lookup(world, client):
    world.requests = [line("r1", TARGET, MIC, 3, "Approved"), line("r2", TARGET, TABLE, 3, "Rejected")]

    event = rows(client)[0]

    assert [r["availability"] for r in event["requests"]] == [None, None]
    assert not any(call[0] == "overlapping" for call in world.calls)


# Reservation AC1 (legacy fallback only): documents missing-window behavior, not overlap safety.
def test_event_without_a_window_is_treated_as_having_nothing_reserved(world, client):
    world.events[TARGET] = {"id": TARGET, "eventName": "Hackday", "status": "Submitted", "startTime": None, "endTime": None}
    world.requests = [line("r1", TARGET, MIC, 10)]

    assert rows(client)[0]["requests"][0]["availability"] == {"reservedQuantity": 0, "availableStock": 10, "isInsufficient": False}
    assert not any(call[0] == "overlapping" for call in world.calls)


# Review AC1 / Reservation AC2 (fallback): identify unknown event references without inventing a schedule.
def test_unknown_event_is_labelled_and_has_no_window(world, client):
    world.requests = [line("r1", OTHER, MIC, 1)]
    event = rows(client)[0]
    assert event["eventName"] == "Unknown event" and event["startTime"] is None


# Review AC3 (supporting identity): include the event's assigned coordinator in the response.
def test_event_view_includes_coordinator_id_for_frontend_name_resolution(world, client):
    coordinator_id = "00000000-0000-4000-8000-00000000c001"
    world.events[TARGET]["coordinatorId"] = coordinator_id
    world.requests = [line("r1", TARGET, MIC, 1)]

    assert rows(client)[0]["coordinatorId"] == coordinator_id


# Review AC1 (empty state): return an empty review list when no equipment requests exist.
def test_no_requests_returns_no_events(world, client):
    assert rows(client) == []


# Review AC1/AC2 (supporting filter): fetch requests matching the selected decision status.
def test_status_filter_is_passed_to_the_request_service(world, client):
    rows(client, status="Approved")
    assert world.calls[0] == ("list_requests", "Approved", None)


# Review AC2/AC3 (access): coordinators may read decisions but cannot make staff decisions.
def test_event_coordinator_can_view_but_not_review(world, client):
    assert client.get("/equipment-reservations", headers=COORDINATOR).status_code == 200
    assert client.patch(f"/equipment-reservations/events/{TARGET}", headers=COORDINATOR, json={"status": "Rejected"}).status_code == 403
    assert client.patch("/equipment-reservations/requests/r1", headers=COORDINATOR, json={"status": "Rejected"}).status_code == 403


# Review AC3: scope coordinator visibility to requests for currently assigned event IDs.
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


# Review AC3 (access boundary): no assignments means no coordinator-visible requests.
def test_coordinator_with_no_assigned_events_sees_no_requests(world, client):
    world.requests = [line("unassigned", TARGET, MIC, 2)]

    response = client.get("/equipment-reservations", headers=COORDINATOR)

    assert response.status_code == 200
    assert response.json["events"] == []
    assert ("list_requests", None, []) in world.calls


# Review AC3: request visibility follows the current coordinator after reassignment.
def test_reassigned_coordinator_loses_access_and_new_coordinator_gains_it(world, client):
    event_id = "00000000-0000-4000-8000-0000000000e1"
    world.requests = [line("assigned", event_id, MIC, 2)]
    world.coordinator_assignments = {event_id: THIRD}

    old_coordinator = client.get("/equipment-reservations", headers=COORDINATOR)
    new_coordinator = client.get("/equipment-reservations", headers=bearer(THIRD, "Event Coordinator"))

    assert old_coordinator.json["events"] == []
    assert [event["eventId"] for event in new_coordinator.json["events"]] == [event_id]


@pytest.mark.parametrize("headers,code", [({}, 401), ({"X-Dev-User-Id": USER, "X-Dev-Role": "Technical Support"}, 401), (bearer(USER, "Attendee"), 403)])
def test_requires_a_signed_in_authorised_user(world, client, headers, code):
    # Review AC1/AC3 (access): deny anonymous (SCRUM-8: DEV headers are not a sign-in) and unrelated-role readers.
    assert client.get("/equipment-reservations", headers=headers).status_code == code
    assert world.calls == []


# Review AC1/AC2 (validation): reject unsupported decision-status filters.
def test_rejects_unknown_status_filter(world, client):
    assert client.get("/equipment-reservations?status=Broken", headers=TS).status_code == 400


# --- batch review -----------------------------------------------------------

# Review AC2 / Reservation AC1: block the whole bulk approval when one line exceeds the pool.
def test_batch_approve_is_blocked_when_any_line_is_insufficient(world, client):
    world.overlapping = [{"id": OTHER}]
    world.requests = [line("r1", TARGET, MIC, 7), line("r2", TARGET, TABLE, 2), line("held", OTHER, MIC, 4, "Approved")]

    response = client.patch(f"/equipment-reservations/events/{TARGET}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 409
    assert "Wireless mic (requested 7, available 6)" in response.json["message"]
    assert "Table" not in response.json["message"]
    assert not any(call[0] == "review_event_requests" for call in world.calls)


# Review AC2: rejection remains possible without sufficient stock.
def test_batch_reject_is_allowed_even_when_a_line_is_insufficient(world, client):
    world.requests = [line("r1", TARGET, LAPTOP, 1), line("r2", TARGET, TABLE, 2)]

    response = client.patch(f"/equipment-reservations/events/{TARGET}", headers=TS, json={"status": "Rejected", "rejectionReason": "No technician available."})

    assert response.status_code == 200
    assert [r["status"] for r in response.json["requests"]] == ["Rejected", "Rejected"]
    assert [r["rejectionReason"] for r in response.json["requests"]] == ["No technician available."] * 2
    assert ("review_event_requests", TARGET, "Rejected") in world.calls
    assert not any(call[0] == "overlapping" for call in world.calls)


# Review AC2 / Reservation AC1/AC2: forward a sufficient bulk approval for the selected event.
def test_batch_approve_succeeds_when_every_line_fits(world, client):
    world.requests = [line("r1", TARGET, MIC, 10), line("r2", TARGET, TABLE, 2)]

    response = client.patch(f"/equipment-reservations/events/{TARGET}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 200
    assert ("review_event_requests", TARGET, "Approved") in world.calls


# Review AC2 (conflict): surface the absence of Pending lines instead of reporting a new decision.
def test_batch_approve_with_nothing_pending_defers_to_the_request_service(world, client, monkeypatch):
    def conflict(event_id, status, rejection_reason=None):
        raise DownstreamError(409, "This event has no Pending equipment requests.")

    monkeypatch.setattr("app.clients.review_event_requests", conflict)
    response = client.patch(f"/equipment-reservations/events/{TARGET}", headers=TS, json={"status": "Approved"})
    assert response.status_code == 409 and response.json["message"] == "This event has no Pending equipment requests."


# --- single review ----------------------------------------------------------

# Reservation AC1 / Review AC2: block an individual approval exceeding current availability.
def test_approving_an_insufficient_line_is_blocked(world, client):
    rid = "00000000-0000-4000-8000-0000000000d1"
    world.requests = [line(rid, TARGET, MIC, 11)]

    response = client.patch(f"/equipment-reservations/requests/{rid}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 409
    assert "requested 11, available 10" in response.json["message"]
    assert not any(call[0] == "review_request" for call in world.calls)


# Review AC2 / Reservation AC1: permit an approval that fits the available pool.
def test_approving_a_line_that_fits_is_forwarded(world, client):
    rid = "00000000-0000-4000-8000-0000000000d2"
    world.requests = [line(rid, TARGET, MIC, 10)]

    response = client.patch(f"/equipment-reservations/requests/{rid}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 200 and response.json["request"]["status"] == "Approved"


# Review AC2: rejecting a request does not require reservable stock.
def test_rejecting_an_insufficient_line_needs_no_stock_check(world, client):
    rid = "00000000-0000-4000-8000-0000000000d3"
    world.requests = [line(rid, TARGET, LAPTOP, 5)]

    response = client.patch(f"/equipment-reservations/requests/{rid}", headers=TS, json={"status": "Rejected", "rejectionReason": "  Equipment unavailable.  "})

    assert response.status_code == 200
    assert world.calls == [("review_request", rid, "Rejected")]
    assert response.json["request"]["rejectionReason"] == "Equipment unavailable."


# Review AC2 (delegation): the owning atomic handles decisions on already-reviewed records.
def test_approving_an_already_decided_line_defers_to_the_request_service(world, client):
    rid = "00000000-0000-4000-8000-0000000000d4"
    world.requests = [line(rid, TARGET, LAPTOP, 5, "Approved")]

    assert client.patch(f"/equipment-reservations/requests/{rid}", headers=TS, json={"status": "Approved"}).status_code == 200
    assert ("review_request", rid, "Approved") in world.calls


@pytest.mark.parametrize("path", ["/equipment-reservations/requests/nope", "/equipment-reservations/events/nope"])
def test_review_rejects_non_uuid_ids(world, client, path):
    # Review AC2 / Reservation AC2 (validation): decisions require valid request/event references.
    assert client.patch(path, headers=TS, json={"status": "Approved"}).status_code == 400


@pytest.mark.parametrize("payload", [None, {}, {"status": "Pending"}, {"status": "Maybe"}, ["Approved"]])
def test_review_rejects_invalid_status(world, client, payload):
    # Review AC2 (validation): only Approved and Rejected are supported decisions.
    for path in (f"/equipment-reservations/events/{TARGET}", f"/equipment-reservations/requests/{TARGET}"):
        assert client.patch(path, headers=TS, json=payload).status_code == 400
    assert world.calls == []


# Review AC1 (failure): preserve downstream read failures instead of returning a misleading request list.
def test_downstream_failures_are_reported_with_their_status(world, client, monkeypatch):
    def down(*args, **kwargs):
        raise DownstreamError(503, "Unable to reach a service this request depends on.")

    monkeypatch.setattr("app.clients.list_requests", down)
    response = client.get("/equipment-reservations", headers=TS)
    assert response.status_code == 503 and "Unable to reach" in response.json["message"]


# Review AC1/AC2 (supporting transport): allow browser reads and status updates from the frontend origin.
def test_cors_allows_the_frontend_origin_and_patch(client):
    response = client.options("/equipment-reservations", headers={"Origin": "http://localhost:5174"})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert "PATCH" in response.headers["Access-Control-Allow-Methods"]
    assert "Authorization" in response.headers["Access-Control-Allow-Headers"]
    assert "Access-Control-Allow-Origin" not in client.options("/equipment-reservations", headers={"Origin": "http://evil.example"}).headers


# --- create (Event Coordinator requests equipment for an assigned event) ----

CREATE_URL = f"/equipment-reservations/events/{TARGET}/requests"


def new_item(equipment_id=MIC, quantity=3, requirements=" Two handheld "):
    return {"equipmentId": equipment_id, "quantityRequested": quantity, "technicalRequirements": requirements}


@pytest.fixture
def assigned(world):
    world.coordinator_assignments = {TARGET: USER}
    return world


# Create request AC1/AC2/AC3: forward event-linked equipment needs and return Pending lines.
@pytest.mark.parametrize("event_status", ["Under Review", "Safety Changes Requested"])
def test_coordinator_creates_pending_lines_for_an_assigned_open_event(assigned, client, event_status):
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


# Create request AC1 (scope): record requested needs; stock sufficiency is decided during review.
def test_create_does_not_check_stock_over_the_event_window(assigned, client):
    assigned.overlapping = [{"id": OTHER}]
    assigned.requests = [line("held", OTHER, MIC, 10, "Approved")]

    assert client.post(CREATE_URL, headers=COORDINATOR, json={"items": [new_item(MIC, 10)]}).status_code == 201
    assert not any(call[0] == "overlapping" for call in assigned.calls)


# Create request AC1 (additional submission): existing requests do not block recording further needs.
def test_create_allows_equipment_the_event_has_already_requested(assigned, client):
    assigned.requests = [line("existing", TARGET, MIC, 2)]
    assert client.post(CREATE_URL, headers=COORDINATOR, json={"items": [new_item()]}).status_code == 201


# Create request AC1/AC2 (access): requests must refer to an event assigned to the caller.
def test_create_is_forbidden_for_an_event_not_assigned_to_the_coordinator(world, client):
    world.coordinator_assignments = {TARGET: THIRD}

    response = client.post(CREATE_URL, headers=COORDINATOR, json={"items": [new_item()]})

    assert response.status_code == 403
    assert not any(call[0] == "create_event_requests" for call in world.calls)


# Create request AC1/AC2 (eligibility): only assigned Under Review events accept equipment needs.
@pytest.mark.parametrize("event_status", ["Submitted", "Approved", "Confirmed", "Rejected", "Cancelled"])
def test_create_is_blocked_once_the_event_is_no_longer_open(assigned, client, event_status):
    assigned.events[TARGET]["status"] = event_status

    response = client.post(CREATE_URL, headers=COORDINATOR, json={"items": [new_item()]})

    assert response.status_code == 409
    assert response.json["message"] == "Equipment can only be requested while the event is Under Review or Safety Changes Requested."
    assert not any(call[0] == "create_event_requests" for call in assigned.calls)


# The Lead requests equipment like a coordinator, for events assigned to them.
def test_lead_creates_pending_lines_for_an_assigned_event(assigned, client):
    response = client.post(CREATE_URL, headers=LEAD, json={"items": [new_item()]})

    assert response.status_code == 201
    assert [r["status"] for r in response.json["requests"]] == ["Pending"]


def test_lead_cannot_create_for_an_event_assigned_to_someone_else(world, client):
    world.coordinator_assignments = {TARGET: THIRD}

    assert client.post(CREATE_URL, headers=LEAD, json={"items": [new_item()]}).status_code == 403


def test_lead_lists_only_requests_for_assigned_events(world, client):
    event_id = "00000000-0000-4000-8000-0000000000e1"
    world.requests = [line("assigned", event_id, MIC, 2), line("other", OTHER, MIC, 1)]
    world.coordinator_assignments = {event_id: USER, OTHER: THIRD}

    response = client.get("/equipment-reservations", headers=LEAD)

    assert response.status_code == 200
    assert [event["eventId"] for event in response.json["events"]] == [event_id]


# Create request AC1 (selection rule): physically Unavailable equipment cannot be requested.
def test_create_is_blocked_for_unavailable_equipment(assigned, client):
    response = client.post(CREATE_URL, headers=COORDINATOR, json={"items": [new_item(), new_item(LAPTOP, 1)]})

    assert response.status_code == 409
    assert response.json["message"] == "This equipment is Unavailable: Laptop."
    assert not any(call[0] == "create_event_requests" for call in assigned.calls)


# Create request AC1 (integrity): selected equipment must exist in the catalogue.
def test_create_rejects_equipment_missing_from_the_catalogue(assigned, client):
    missing = "00000000-0000-4000-8000-00000000ffff"
    assert client.post(CREATE_URL, headers=COORDINATOR, json={"items": [new_item(missing)]}).status_code == 404


# Create request AC1 (access): other roles cannot record a coordinator's equipment needs.
@pytest.mark.parametrize("headers,code", [({}, 401), (TS, 403), (bearer(USER, "Event Organiser"), 403)])
def test_only_event_coordinators_can_create(world, client, headers, code):
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
)
def test_create_rejects_invalid_items(world, client, payload):
    # Create request AC1 (validation): malformed equipment needs must not reach persistence.
    assert client.post(CREATE_URL, headers=COORDINATOR, json=payload).status_code == 400
    assert world.calls == []


# Create request AC2 (integrity): reject an invalid corresponding event reference.
def test_create_rejects_a_non_uuid_event_id(world, client):
    assert client.post("/equipment-reservations/events/nope/requests", headers=COORDINATOR, json={"items": [new_item()]}).status_code == 400


# Create request AC1 (supporting transport): permit browser submission through the composite.
def test_cors_allows_post_for_request_creation(client):
    response = client.options(CREATE_URL, headers={"Origin": "http://localhost:5174"})
    assert "POST" in response.headers["Access-Control-Allow-Methods"]
