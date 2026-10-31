"""SCRUM-33: Equipment Request Review

User Story
----------
As a Technical Support Staff, I want to review and update the status of an equipment request so that the Event Coordinator knows the technical arrangements are approved.

Acceptance Criteria
-------------------
AC1: Technical Support Staff can view the requested equipment, equipment type, quantity, and technical requirements for a given event.
AC2: System allows the Technical Support Staff to change the request status (eg: to "Approved", "Rejected").
AC3: Ensure the newly updated status is visible to the assigned Event Coordinator.

Real
----
- Real review routes, request/response validation and downstream client construction; decision/status visibility is observed.

Doubled
-------
- Fake (downstream service world), Stub (HTTP responses); Mock (recorded outbound calls inspected). JWKS key lookup is a Stub.

Not proven
----------
- AC1: Two distinct nonempty lines check the local equipment name/type/quantity/requirements projection and event identity; stored source values belong to downstream owners.
- AC2: Local decision forwarding and refusal paths are checked; committing the decision belongs to Equipment Request Service.
- AC3: Assigned-coordinator filtering has separate SCRUM-9 tests; a full decide-then-read workflow is untested here; browser visibility is outside this owner.
- Supporting validation, transport, retry, authentication configuration and defensive checks retain useful regressions, but their exact limits/failure contracts are not separate Jira ACs; Product Owner clarification remains pending.
- Real Supabase issuance, other services, browser rendering and actual broker durability are NOT COVERED ANYWHERE in this module.
- Unexpected downstream message redaction is checked at the client and public route; permitted 401/403/404/409 business refusals retain their existing message contract.
"""

import httpx

import pytest

from app import clients, create_app

from app.availability import RESERVING_EVENT_STATUSES, effective_available_stock, evaluate_request

from app.clients import DownstreamError

from tests.unit.factories import COORDINATOR, CREATE_URL, LEAD, TS, bearer, new_item, rows

from tests.unit.fakes import END, LAPTOP, MIC, OTHER, START, TABLE, TARGET, THIRD, USER, FakeResponse, equipment, line

HEADERS = {"Authorization": "Bearer user-token", "Cookie": "must-not-be-forwarded"}

MIC_STOCK = {"id": "e1", "status": "Available", "totalQuantity": 10}




from tests.unit.factories import boundary, identity, mutations, EVENT, A, R1, R2, row



def test_review_list_when_event_unknown_labels_it_without_dates(world, client):
    """Summary: Requests whose event cannot be found are still listed, clearly labelled.
AC1: Technical Support Staff can view the requested equipment, equipment type, quantity, and technical requirements for a given event.
Double: Fake (world: request for an event Event Service does not return)
"""
    world.requests = [line("r1", OTHER, MIC, 1)]
    event = rows(client)[0]
    assert event["eventName"] == "Unknown event" and event["startTime"] is None



def test_review_list_includes_each_events_coordinator(world, client):
    """Summary: Each event in the review list says who its coordinator is.
AC1: Technical Support Staff can view the requested equipment, equipment type, quantity, and technical requirements for a given event.
AC3: Ensure the newly updated status is visible to the assigned Event Coordinator.
Double: Fake (world: TARGET with a coordinator)
"""
    coordinator_id = "00000000-0000-4000-8000-00000000c001"
    world.events[TARGET]["coordinatorId"] = coordinator_id
    world.requests = [line("r1", TARGET, MIC, 1)]

    assert rows(client)[0]["coordinatorId"] == coordinator_id



def test_review_list_when_no_requests_returns_no_events(world, client):
    """Summary: With no equipment requests, the review list is empty.
AC1: Technical Support Staff can view the requested equipment, equipment type, quantity, and technical requirements for a given event.
Double: Fake (world: no requests)
"""
    assert rows(client) == []



def test_review_list_with_status_filter_asks_for_that_status(world, client):
    """Summary: Technical Support can narrow the review list to one status.
AC1: Technical Support Staff can view the requested equipment, equipment type, quantity, and technical requirements for a given event.
Double: Fake (world records the status asked for)
"""
    rows(client, status="Approved")
    assert world.calls[0] == ("list_requests", "Approved", None)



def test_review_when_caller_is_coordinator_can_view_but_not_decide(world, client):
    """Summary: A coordinator can see their event's requests and decisions but cannot make a decision.
AC3: Ensure the newly updated status is visible to the assigned Event Coordinator.
AC2: System allows the Technical Support Staff to change the request status (eg: to "Approved", "Rejected").
Double: Fake (world: TARGET assigned to the coordinator)
"""
    assert client.get("/equipment-reservations", headers=COORDINATOR).status_code == 200
    assert client.patch(f"/equipment-reservations/events/{TARGET}", headers=COORDINATOR, json={"status": "Rejected"}).status_code == 403
    assert client.patch("/equipment-reservations/requests/r1", headers=COORDINATOR, json={"status": "Rejected"}).status_code == 403



def test_review_list_with_unknown_status_returns_400(world, client):
    """Summary: An unknown status filter is refused.
AC1: Technical Support Staff can view the requested equipment, equipment type, quantity, and technical requirements for a given event.
Double: Fake (world)
"""
    assert client.get("/equipment-reservations?status=Broken", headers=TS).status_code == 400



def test_bulk_reject_when_a_line_insufficient_rejects_all(world, client):
    """Summary: An event's equipment can be rejected in one go whatever the stock.
AC2: System allows the Technical Support Staff to change the request status (eg: to "Approved", "Rejected").
Double: Fake (world: one line exceeds the remaining stock)
"""
    world.requests = [line("r1", TARGET, LAPTOP, 1), line("r2", TARGET, TABLE, 2)]

    response = client.patch(f"/equipment-reservations/events/{TARGET}", headers=TS, json={"status": "Rejected", "rejectionReason": "No technician available."})

    assert response.status_code == 200
    assert [r["status"] for r in response.json["requests"]] == ["Rejected", "Rejected"]
    assert [r["rejectionReason"] for r in response.json["requests"]] == ["No technician available."] * 2
    assert ("review_event_requests", TARGET, "Rejected") in world.calls
    assert not any(call[0] == "overlapping" for call in world.calls)



def test_bulk_approve_when_nothing_pending_returns_existing_conflict(world, client):
    """Summary: With only decided rows, a bulk approval reports no Pending requests.
AC2: System allows the Technical Support Staff to change the request status (eg: to "Approved", "Rejected").
Double: Fake (world: only an already-decided line)
"""
    world.requests = [line("decided", TARGET, MIC, 1, "Approved")]
    response = client.patch(f"/equipment-reservations/events/{TARGET}", headers=TS, json={"status": "Approved"})
    assert response.status_code == 409 and response.json["message"] == "This event has no Pending equipment requests."



def test_reject_line_when_insufficient_rejects_without_stock_check(world, client):
    """Summary: Rejecting a line needs no stock check.
AC2: System allows the Technical Support Staff to change the request status (eg: to "Approved", "Rejected").
Double: Fake (world: the line exceeds the remaining stock)
"""
    rid = "00000000-0000-4000-8000-0000000000d3"
    world.requests = [line(rid, TARGET, LAPTOP, 5)]

    response = client.patch(f"/equipment-reservations/requests/{rid}", headers=TS, json={"status": "Rejected", "rejectionReason": "  Equipment unavailable.  "})

    assert response.status_code == 200
    assert world.calls == [("review_request", rid, "Rejected")]
    assert response.json["request"]["rejectionReason"] == "Equipment unavailable."



def test_approve_line_when_already_decided_skips_stock_check(world, client):
    """Summary: An already-decided line is refused without gathering stock or sending a mutation.
AC2: System allows the Technical Support Staff to change the request status (eg: to "Approved", "Rejected").
Double: Fake (world: the line is Approved)
"""
    rid = "00000000-0000-4000-8000-0000000000d4"
    world.requests = [line(rid, TARGET, LAPTOP, 5, "Approved")]

    response = client.patch(f"/equipment-reservations/requests/{rid}", headers=TS, json={"status": "Approved"})
    assert response.status_code == 409
    assert response.json["message"] == "Only Pending equipment requests can be reviewed."
    assert world.calls == []



@pytest.mark.parametrize("path", ["/equipment-reservations/requests/nope", "/equipment-reservations/events/nope"], ids=["single_request", "whole_event"])
def test_review_with_malformed_id_returns_400(world, client, path):
    """Summary: A decision must name a valid request or event.
AC2: System allows the Technical Support Staff to change the request status (eg: to "Approved", "Rejected").
Double: Fake (world)
"""
    # Review AC2 / Reservation AC2 (validation): decisions require valid request/event references.
    assert client.patch(path, headers=TS, json={"status": "Approved"}).status_code == 400



@pytest.mark.parametrize("payload", [None, {}, {"status": "Pending"}, {"status": "Maybe"}, ["Approved"]], ids=["no_body", "empty_object", "back_to_pending", "unknown_status", "list_body"])
def test_review_with_status_other_than_approved_or_rejected_returns_400(world, client, payload):
    """Summary: A decision must be Approved or Rejected.
AC2: System allows the Technical Support Staff to change the request status (eg: to "Approved", "Rejected").
Double: Fake (world)
"""
    # Review AC2 (validation): only Approved and Rejected are supported decisions.
    for path in (f"/equipment-reservations/events/{TARGET}", f"/equipment-reservations/requests/{TARGET}"):
        assert client.patch(path, headers=TS, json=payload).status_code == 400
    assert world.calls == []



def test_review_list_when_downstream_fails_returns_its_status(world, client, monkeypatch):
    """Summary: A downstream failure is passed on with its status rather than shown as an empty list.
AC1: Technical Support Staff can view the requested equipment, equipment type, quantity, and technical requirements for a given event.
Double: Fake (world), Stub (list_requests raises DownstreamError)
"""
    def down(*args, **kwargs):
        raise DownstreamError(503, "Unable to reach a service this request depends on.")

    monkeypatch.setattr("app.clients.list_requests", down)
    response = client.get("/equipment-reservations", headers=TS)
    assert response.status_code == 503 and "Unable to reach" in response.json["message"]



def test_list_requests_client_with_no_events_makes_no_call(sent):
    """Summary: Asking for the requests of no events makes no downstream call.
AC1: Technical Support Staff can view the requested equipment, equipment type, quantity, and technical requirements for a given event.
Double: Stub (canned downstream HTTP responses), Mock (recorded outbound method, URL, headers or no-call contract).
"""
    calls, _ = sent
    assert clients.list_requests("Approved", []) == []
    assert calls == []



def test_list_requests_client_without_filters_sends_no_parameters(sent):
    """Summary: A lookup without filters asks for every request.
AC1: Technical Support Staff can view the requested equipment, equipment type, quantity, and technical requirements for a given event.
Double: Stub (canned downstream HTTP responses), Mock (recorded outbound method, URL, headers or no-call contract).
"""
    calls, fake = sent
    fake.response = FakeResponse(body={"requests": []})
    clients.list_requests()
    assert calls[0][2]["params"] == {}



def test_get_and_review_clients_call_request_service_endpoints(sent):
    """Summary: Reading and deciding requests call Equipment Request Service's matching endpoints.
AC2: System allows the Technical Support Staff to change the request status (eg: to "Approved", "Rejected").
Double: Stub (canned downstream HTTP responses), Mock (recorded outbound method, URL, headers or no-call contract).
"""
    calls, fake = sent
    fake.response = FakeResponse(body={"request": {"id": "r", "eventId": "ev"}, "requests": [{"id": "r"}]})

    assert clients.get_request("r") == {"id": "r", "eventId": "ev"}
    assert clients.review_request("r", "Approved") == {"id": "r", "eventId": "ev"}
    assert clients.review_event_requests("ev", "Rejected", "No technician available.") == [{"id": "r"}]

    assert [(c[0], c[1]) for c in calls] == [
        ("GET", "http://localhost:5011/equipment-requests/r"),
        ("GET", "http://localhost:5011/equipment-requests/r"),
        ("PATCH", "http://localhost:5011/equipment-requests/r"),
        ("PATCH", "http://localhost:5011/events/ev/equipment-requests"),
    ]
    assert calls[2][2]["json"] == {"status": "Approved", "notificationContext": {"eventId": "ev"}, "approvalContext": None}
    assert calls[3][2]["json"] == {"status": "Rejected", "rejectionReason": "No technician available.", "notificationContext": {"eventId": "ev"}}



def test_event_summaries_client_fetches_in_chunks_of_100(sent):
    """Summary: Event details for many requests are fetched 100 events at a time.
AC1: Technical Support Staff can view the requested equipment, equipment type, quantity, and technical requirements for a given event.
Double: Stub (canned downstream HTTP responses), Mock (recorded outbound method, URL, headers or no-call contract).
"""
    calls, fake = sent
    fake.response = FakeResponse(body={"events": [{"id": "x"}]})

    assert clients.get_event_summaries([str(i) for i in range(150)]) == [{"id": "x"}, {"id": "x"}]
    assert len(calls) == 2 and calls[0][1] == "http://localhost:5003/events/summaries"
    assert calls[0][2]["params"]["ids"] == ",".join(str(i) for i in range(100))
    assert calls[1][2]["params"]["ids"] == ",".join(str(i) for i in range(100, 150))



@pytest.mark.parametrize("status", [401, 403, 404, 409], ids=["unauthorised", "forbidden", "not_found", "conflict"])
def test_downstream_client_when_refused_raises_with_status_and_message(sent, status):
    """Summary: A downstream refusal keeps its status and message.
AC2: System allows the Technical Support Staff to change the request status (eg: to "Approved", "Rejected").
Double: Stub (canned downstream HTTP responses), Mock (recorded outbound method, URL, headers or no-call contract).
"""
    # Review AC1/AC2 (failure transport): preserve expected downstream authorization and decision errors.
    _, fake = sent
    fake.response = FakeResponse(status, {"message": "nope"})
    with pytest.raises(DownstreamError) as error:
        clients.get_request("r")
    assert (error.value.status, error.value.message) == (status, "nope")



@pytest.mark.parametrize("response", [FakeResponse(500, {"message": "synthetic-private-detail"}), FakeResponse(400, json_error=True), FakeResponse(500, ["x"])], ids=["server_error", "unreadable_400", "non_object_500"])
def test_downstream_client_when_failing_raises_502_without_details(sent, response):
    """Summary: Other downstream failures become a generic 502 that leaks nothing.
AC2: System allows the Technical Support Staff to change the request status (eg: to "Approved", "Rejected").
Double: Stub (canned downstream HTTP responses), Mock (recorded outbound method, URL, headers or no-call contract).
"""
    # Review AC1/AC2 (failure transport): handle malformed or unexpected downstream errors safely.
    _, fake = sent
    fake.response = response
    with pytest.raises(DownstreamError) as error:
        clients.get_request("r")
    assert (error.value.status, error.value.message) == (
        502, "A service this request depends on failed.",
    )



def test_downstream_client_when_unreachable_raises_503(monkeypatch):
    """Summary: An unreachable downstream service is reported as unavailable.
AC2: System allows the Technical Support Staff to change the request status (eg: to "Approved", "Rejected").
Double: Stub (httpx.request raises ConnectError)
"""
    def boom(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr("app.clients.httpx.request", boom)
    with pytest.raises(DownstreamError) as error:
        clients.list_equipment()
    assert error.value.status == 503



@pytest.mark.parametrize(
    "length, expected_status",
    [(499, 200), (500, 200), (501, 400)],
    ids=["below_limit", "at_limit", "above_limit"],
)
def test_reject_line_when_reason_near_limit_accepts_up_to_500_characters(world, client, length, expected_status):
    """Summary: A rejection reason can be up to 500 characters.
AC2: System allows the Technical Support Staff to change the request status (eg: to "Approved", "Rejected").
Double: Fake (world: one Pending line)
"""
    rid = "00000000-0000-4000-8000-0000000000d3"
    world.requests = [line(rid, TARGET, MIC, 1)]

    response = client.patch(
        f"/equipment-reservations/requests/{rid}", headers=TS, json={"status": "Rejected", "rejectionReason": "x" * length}
    )

    assert response.status_code == expected_status



def test_approve_event_without_requests_preserves_not_found_response(boundary):
    """Summary: No requests gives the existing 404, not a misleading stock/context conflict.
AC2: System allows the Technical Support Staff to change the request status (eg: to "Approved", "Rejected").
Double: Stub (downstream HTTP); Mock (no mutation is sent)
"""
    boundary.rows = []
    response = boundary.client.patch(f"/equipment-reservations/events/{EVENT}",
        headers=identity(A, "Technical Support"), json={"status": "Approved"})
    assert response.status_code == 404
    assert response.json["message"] == "No equipment requests found for this event."
    assert mutations(boundary) == []

from unittest.mock import MagicMock
from tests.unit.factories import TSS1


@pytest.mark.parametrize("route", ["single", "bulk"], ids=["single", "bulk"])
@pytest.mark.parametrize("reason", [None, " ", 12, "x" * 501], ids=["missing", "blank", "non_text", "too_long"])
def test_reject_with_invalid_reason_returns_400_before_any_call(monkeypatch, route, reason):
    """Summary: A rejection with a missing or bad reason is refused before any downstream call or alert.
AC2: System allows the Technical Support Staff to change the request status (eg: to "Approved", "Rejected").
Double: Stub (httpx.request fails the test if called)
"""
    # Arrange (Given)
    http = MagicMock(side_effect=AssertionError("must reject before HTTP"))
    monkeypatch.setattr(clients.httpx, "request", http)
    url = f"/equipment-reservations/requests/{R1}" if route == "single" else f"/equipment-reservations/events/{EVENT}"

    # Act (When)
    response = create_app({"TESTING": True}).test_client().patch(url,
        headers=identity(TSS1, "Technical Support"), json={"status": "Rejected", "rejectionReason": reason})

    # Assert (Then)
    assert response.status_code == 400
    assert response.json == {"message": "A rejection reason between 1 and 500 characters is required."}
    http.assert_not_called()



def test_review_list_preserves_nonempty_equipment_details_for_each_request(world, client):
    """Summary: Technical Support sees each requested item's name, type, quantity and instructions without mixing two lines.
    AC1: Technical Support Staff can view the requested equipment, equipment type, quantity, and technical requirements for a given event.
    Double: Fake (Event, catalogue and request replies with two distinct lines; real review projection).
    """
    world.requests = [
        {**line("r1", TARGET, MIC, 3), "technicalRequirements": "Use channel 4."},
        {**line("r2", TARGET, TABLE, 7), "technicalRequirements": "Keep the exit clear."},
    ]
    world.catalogue[1]["type"] = "Table"

    event = rows(client)[0]

    assert event["eventId"] == TARGET
    assert [
        (item["id"], item["equipment"]["description"], item["equipment"]["type"],
         item["quantityRequested"], item["technicalRequirements"])
        for item in event["requests"]
    ] == [
        ("r1", "Wireless mic", "Microphone", 3, "Use channel 4."),
        ("r2", "Table", "Table", 7, "Keep the exit clear."),
    ]
