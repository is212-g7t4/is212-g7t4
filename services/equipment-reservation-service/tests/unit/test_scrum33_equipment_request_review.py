"""
SCRUM-33: Equipment Request Review

User Story
----------
As a Technical Support Staff, I want to review and update the status of an
equipment request so that the Event Coordinator knows the technical
arrangements are approved.

Acceptance Criteria
-------------------
AC1: Technical Support Staff can view the requested equipment, equipment type,
     quantity, and technical requirements for a given event.
AC2: System allows the Technical Support Staff to change the request status
     (eg: to "Approved", "Rejected").
AC3: Ensure the newly updated status is visible to the assigned Event
     Coordinator.

SCRUM-8: User Authentication and Authorization

User Story
----------
As a system user, I want to securely access the system, so that I can use the
information and functionality available to me.

Acceptance Criteria
-------------------
AC1: Given a system user has not been successfully authenticated, when they
     attempt to access protected information or functionality, then access is
     denied.
AC2: Given a system user successfully authenticates, when they access protected
     information or functionality, then their access is evaluated according to
     their role and relationship to the relevant event.
AC3: Given a system user's authentication attempt is unsuccessful, when the
     authentication attempt is completed, then they remain unable to access
     protected information or functionality.

SCRUM-9: Role-Based Access Control for Events

User Story
----------
As a registered user, I want to view only information appropriate to my role
and relationship to an event, so that I can access the information relevant to
my responsibilities without viewing restricted information.

Acceptance Criteria
-------------------
AC1: Given an authenticated user is permitted to view information based on
     their role and relationship to the event, when they access that
     information, then the information is made available to them.
AC2: Given an authenticated user's role does not permit them to view particular
     information, when they attempt to access that information, then access is
     denied.
AC3: Given an authenticated user's relationship to an event does not permit
     them to view that event's information, when they attempt to access the
     information, then access is denied.
AC4: Given a user is permitted to view information for one event but does not
     have the required relationship to another event, when they attempt to view
     information for both events, then they can only view the information for
     which they have the required access.
AC5: Given two authenticated users have different roles or relationships to the
     same event, when they access information relating to that event, then each
     user can only view the information permitted by their own role and
     relationship to the event.

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
  catalogue and request lines that read back what earlier calls wrote;
  world.calls records which calls were made.
- httpx.request (client tests): Stub (`sent` fixture) - canned FakeResponse;
  the recorded method, URL and headers are inspected.

Not proven
----------
- That Equipment Request Service applies only Pending-to-decision changes and
  records the reviewer (-> equipment-request-service
  test_scrum33_equipment_request_review.py).
- That the coordinator's event page shows the new status (AC3, UI half) (->
  frontend EquipmentRequestsPage.test.tsx).
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


def test_review_list_when_event_unknown_labels_it_without_dates(world, client):
    """
    Summary: Requests whose event cannot be found are still listed, clearly labelled.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    Double: Fake (world: request for an event Event Service does not return)
    """
    world.requests = [line("r1", OTHER, MIC, 1)]
    event = rows(client)[0]
    assert event["eventName"] == "Unknown event" and event["startTime"] is None


def test_review_list_includes_each_events_coordinator(world, client):
    """
    Summary: Each event in the review list says who its coordinator is.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    AC3: Ensure the newly updated status is visible to the assigned Event
        Coordinator.
    Double: Fake (world: TARGET with a coordinator)
    """
    coordinator_id = "00000000-0000-4000-8000-00000000c001"
    world.events[TARGET]["coordinatorId"] = coordinator_id
    world.requests = [line("r1", TARGET, MIC, 1)]

    assert rows(client)[0]["coordinatorId"] == coordinator_id


def test_review_list_when_no_requests_returns_no_events(world, client):
    """
    Summary: With no equipment requests, the review list is empty.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    Double: Fake (world: no requests)
    """
    assert rows(client) == []


def test_review_list_with_status_filter_asks_for_that_status(world, client):
    """
    Summary: Technical Support can narrow the review list to one status.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    Double: Fake (world records the status asked for)
    """
    rows(client, status="Approved")
    assert world.calls[0] == ("list_requests", "Approved", None)


def test_review_when_caller_is_coordinator_can_view_but_not_decide(world, client):
    """
    Summary: A coordinator can see their event's requests and decisions but cannot make a decision.
    AC3: Ensure the newly updated status is visible to the assigned Event
        Coordinator.
    AC2: only Technical Support Staff change the status
    Double: Fake (world: TARGET assigned to the coordinator)
    """
    assert client.get("/equipment-reservations", headers=COORDINATOR).status_code == 200
    assert client.patch(f"/equipment-reservations/events/{TARGET}", headers=COORDINATOR, json={"status": "Rejected"}).status_code == 403
    assert client.patch("/equipment-reservations/requests/r1", headers=COORDINATOR, json={"status": "Rejected"}).status_code == 403


def test_review_list_when_coordinator_shows_only_their_assigned_events(world, client):
    """
    Summary: A coordinator sees equipment requests only for events currently assigned to them.
    AC3: Ensure the newly updated status is visible to the assigned Event
        Coordinator.
    SCRUM-9 AC3: Given an authenticated user's relationship to an event does
        not permit them to view that event's information, when they attempt to
        access the information, then access is denied.
    Double: Fake (world: two events, one assigned to the coordinator)
    """
    # Arrange (Given)
    assigned_event = "00000000-0000-4000-8000-0000000000e1"
    other_event = "00000000-0000-4000-8000-0000000000e2"
    world.coordinator_assignments = {assigned_event: USER, other_event: THIRD}
    world.requests = [line("assigned", assigned_event, MIC, 2), line("other", other_event, MIC, 2)]

    # Act (When)
    response = client.get("/equipment-reservations", headers=COORDINATOR)

    # Assert (Then)
    assert response.status_code == 200
    assert [event["eventId"] for event in response.json["events"]] == [assigned_event]
    assert ("assigned_events", USER) in world.calls
    assert ("list_requests", None, [assigned_event]) in world.calls


def test_review_list_when_coordinator_has_no_events_shows_nothing(world, client):
    """
    Summary: A coordinator with no assigned events sees no requests and nothing else is fetched.
    SCRUM-9 AC3: Given an authenticated user's relationship to an event does
        not permit them to view that event's information, when they attempt to
        access the information, then access is denied.
    Double: Fake (world: no assignments)
    """
    # Arrange (Given)
    world.requests = [line("unassigned", TARGET, MIC, 2)]

    # Act (When)
    response = client.get("/equipment-reservations", headers=COORDINATOR)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["events"] == []
    assert ("list_requests", None, []) in world.calls


def test_review_list_after_reassignment_moves_access_to_new_coordinator(world, client):
    """
    Summary: After reassignment, only the new coordinator sees the event's equipment requests.
    SCRUM-9 AC5: Given two authenticated users have different roles or
        relationships to the same event, when they access information relating
        to that event, then each user can only view the information permitted
        by their own role and relationship to the event.
    Double: Fake (world: assignment changed between calls)
    """
    # Arrange (Given)
    event_id = "00000000-0000-4000-8000-0000000000e1"
    world.requests = [line("assigned", event_id, MIC, 2)]
    world.coordinator_assignments = {event_id: THIRD}

    old_coordinator = client.get("/equipment-reservations", headers=COORDINATOR)

    # Act (When)
    new_coordinator = client.get("/equipment-reservations", headers=bearer(THIRD, "Event Coordinator"))

    # Assert (Then)
    assert old_coordinator.json["events"] == []
    assert [event["eventId"] for event in new_coordinator.json["events"]] == [event_id]


@pytest.mark.parametrize("headers,code", [({}, 401), ({"X-Dev-User-Id": USER, "X-Dev-Role": "Technical Support"}, 401), (bearer(USER, "Attendee"), 403)], ids=["no_token", "dev_headers", "attendee"])
def test_review_list_without_permitted_role_is_refused(world, client, headers, code):
    """
    Summary: The review list is not shown to anonymous callers, retired developer headers or attendees.
    SCRUM-8 AC1: Given a system user has not been successfully authenticated,
        when they attempt to access protected information or functionality,
        then access is denied.
    SCRUM-9 AC2: Given an authenticated user's role does not permit them to
        view particular information, when they attempt to access that
        information, then access is denied.
    Double: Fake (world)
    """
    # Arrange (Given): world, client, headers, code, from fixtures

    # Act + Assert (When / Then)
    # Review AC1/AC3 (access): deny anonymous (SCRUM-8: DEV headers are not a sign-in) and unrelated-role readers.
    assert client.get("/equipment-reservations", headers=headers).status_code == code
    assert world.calls == []


def test_review_list_with_unknown_status_returns_400(world, client):
    """
    Summary: An unknown status filter is refused.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    Double: Fake (world)
    """
    assert client.get("/equipment-reservations?status=Broken", headers=TS).status_code == 400


def test_bulk_approve_when_any_line_insufficient_returns_409_without_deciding(world, client):
    """
    Summary: An event's equipment cannot be approved in one go while any line lacks stock.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Fake (world: one line exceeds the remaining stock)
    """
    world.overlapping = [{"id": OTHER}]
    world.requests = [line("r1", TARGET, MIC, 7), line("r2", TARGET, TABLE, 2), line("held", OTHER, MIC, 4, "Approved")]

    response = client.patch(f"/equipment-reservations/events/{TARGET}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 409
    assert "Wireless mic (requested 7, available 6)" in response.json["message"]
    assert "Table" not in response.json["message"]
    assert not any(call[0] == "review_event_requests" for call in world.calls)


def test_bulk_reject_when_a_line_insufficient_rejects_all(world, client):
    """
    Summary: An event's equipment can be rejected in one go whatever the stock.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Fake (world: one line exceeds the remaining stock)
    """
    world.requests = [line("r1", TARGET, LAPTOP, 1), line("r2", TARGET, TABLE, 2)]

    response = client.patch(f"/equipment-reservations/events/{TARGET}", headers=TS, json={"status": "Rejected", "rejectionReason": "No technician available."})

    assert response.status_code == 200
    assert [r["status"] for r in response.json["requests"]] == ["Rejected", "Rejected"]
    assert [r["rejectionReason"] for r in response.json["requests"]] == ["No technician available."] * 2
    assert ("review_event_requests", TARGET, "Rejected") in world.calls
    assert not any(call[0] == "overlapping" for call in world.calls)


def test_bulk_approve_when_every_line_fits_approves_all(world, client):
    """
    Summary: When every pending line fits the stock, the whole event can be approved at once.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Fake (world: enough stock for every line)
    """
    world.requests = [line("r1", TARGET, MIC, 10), line("r2", TARGET, TABLE, 2)]

    response = client.patch(f"/equipment-reservations/events/{TARGET}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 200
    assert ("review_event_requests", TARGET, "Approved") in world.calls


def test_bulk_approve_when_nothing_pending_returns_request_service_answer(world, client, monkeypatch):
    """
    Summary: With nothing pending, a bulk approval gets Equipment Request Service's own answer.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Fake (world: no Pending lines), Stub (review_event_requests raises
        DownstreamError 409)
    """
    def conflict(event_id, status, rejection_reason=None):
        raise DownstreamError(409, "This event has no Pending equipment requests.")

    monkeypatch.setattr("app.clients.review_event_requests", conflict)
    response = client.patch(f"/equipment-reservations/events/{TARGET}", headers=TS, json={"status": "Approved"})
    assert response.status_code == 409 and response.json["message"] == "This event has no Pending equipment requests."


def test_approve_line_when_insufficient_returns_409_without_deciding(world, client):
    """
    Summary: A single line cannot be approved when there is not enough stock for it.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Fake (world: the line exceeds the remaining stock)
    """
    rid = "00000000-0000-4000-8000-0000000000d1"
    world.requests = [line(rid, TARGET, MIC, 11)]

    response = client.patch(f"/equipment-reservations/requests/{rid}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 409
    assert "requested 11, available 10" in response.json["message"]
    assert not any(call[0] == "review_request" for call in world.calls)


def test_approve_line_when_it_fits_is_approved(world, client):
    """
    Summary: A single line that fits the stock can be approved.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Fake (world: enough stock)
    """
    rid = "00000000-0000-4000-8000-0000000000d2"
    world.requests = [line(rid, TARGET, MIC, 10)]

    response = client.patch(f"/equipment-reservations/requests/{rid}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 200 and response.json["request"]["status"] == "Approved"


def test_reject_line_when_insufficient_rejects_without_stock_check(world, client):
    """
    Summary: Rejecting a line needs no stock check.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Fake (world: the line exceeds the remaining stock)
    """
    rid = "00000000-0000-4000-8000-0000000000d3"
    world.requests = [line(rid, TARGET, LAPTOP, 5)]

    response = client.patch(f"/equipment-reservations/requests/{rid}", headers=TS, json={"status": "Rejected", "rejectionReason": "  Equipment unavailable.  "})

    assert response.status_code == 200
    assert world.calls == [("review_request", rid, "Rejected")]
    assert response.json["request"]["rejectionReason"] == "Equipment unavailable."


def test_approve_line_when_already_decided_skips_stock_check(world, client):
    """
    Summary: Approving a line that was already decided is left to Equipment Request Service to refuse.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Fake (world: the line is Approved)
    """
    rid = "00000000-0000-4000-8000-0000000000d4"
    world.requests = [line(rid, TARGET, LAPTOP, 5, "Approved")]

    assert client.patch(f"/equipment-reservations/requests/{rid}", headers=TS, json={"status": "Approved"}).status_code == 200
    assert ("review_request", rid, "Approved") in world.calls


@pytest.mark.parametrize("path", ["/equipment-reservations/requests/nope", "/equipment-reservations/events/nope"], ids=["single_request", "whole_event"])
def test_review_with_malformed_id_returns_400(world, client, path):
    """
    Summary: A decision must name a valid request or event.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Fake (world)
    """
    # Review AC2 / Reservation AC2 (validation): decisions require valid request/event references.
    assert client.patch(path, headers=TS, json={"status": "Approved"}).status_code == 400


@pytest.mark.parametrize("payload", [None, {}, {"status": "Pending"}, {"status": "Maybe"}, ["Approved"]], ids=["no_body", "empty_object", "back_to_pending", "unknown_status", "list_body"])
def test_review_with_status_other_than_approved_or_rejected_returns_400(world, client, payload):
    """
    Summary: A decision must be Approved or Rejected.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Fake (world)
    """
    # Review AC2 (validation): only Approved and Rejected are supported decisions.
    for path in (f"/equipment-reservations/events/{TARGET}", f"/equipment-reservations/requests/{TARGET}"):
        assert client.patch(path, headers=TS, json=payload).status_code == 400
    assert world.calls == []


def test_review_list_when_downstream_fails_returns_its_status(world, client, monkeypatch):
    """
    Summary: A downstream failure is passed on with its status rather than shown as an empty list.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    Double: Fake (world), Stub (list_requests raises DownstreamError)
    """
    def down(*args, **kwargs):
        raise DownstreamError(503, "Unable to reach a service this request depends on.")

    monkeypatch.setattr("app.clients.list_requests", down)
    response = client.get("/equipment-reservations", headers=TS)
    assert response.status_code == 503 and "Unable to reach" in response.json["message"]


def test_review_list_when_lead_shows_only_their_assigned_events(world, client):
    """
    Summary: The Lead, like any coordinator, sees requests only for events assigned to them.
    SCRUM-9 AC3: Given an authenticated user's relationship to an event does
        not permit them to view that event's information, when they attempt to
        access the information, then access is denied.
    Double: Fake (world: one event assigned to the Lead)
    """
    # Arrange (Given)
    event_id = "00000000-0000-4000-8000-0000000000e1"
    world.requests = [line("assigned", event_id, MIC, 2), line("other", OTHER, MIC, 1)]
    world.coordinator_assignments = {event_id: USER, OTHER: THIRD}

    # Act (When)
    response = client.get("/equipment-reservations", headers=LEAD)

    # Assert (Then)
    assert response.status_code == 200
    assert [event["eventId"] for event in response.json["events"]] == [event_id]


def test_list_requests_client_forwards_only_token_and_filters(sent):
    """
    Summary: Request lookups carry the caller's token and filters, never their cookies.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    SCRUM-8 AC2: Given a system user successfully authenticates, when they
        access protected information or functionality, then their access is
        evaluated according to their role and relationship to the relevant
        event.
    Double: Stub (httpx.request returns one request)
    """
    calls, fake = sent
    fake.response = FakeResponse(body={"requests": [1]})

    with create_app().test_request_context(headers=HEADERS):
        assert clients.list_requests("Approved", ["a", "b"]) == [1]

    method, url, kwargs = calls[0]
    assert (method, url) == ("GET", "http://localhost:5011/equipment-requests")
    assert kwargs["params"] == {"status": "Approved", "eventIds": "a,b"}
    assert kwargs["headers"] == {"Authorization": "Bearer user-token"}


def test_list_requests_client_with_no_events_makes_no_call(sent):
    """
    Summary: Asking for the requests of no events makes no downstream call.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    Double: Stub (httpx.request records nothing)
    """
    calls, _ = sent
    assert clients.list_requests("Approved", []) == []
    assert calls == []


def test_list_requests_client_without_filters_sends_no_parameters(sent):
    """
    Summary: A lookup without filters asks for every request.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    Double: Stub (httpx.request returns no requests)
    """
    calls, fake = sent
    fake.response = FakeResponse(body={"requests": []})
    clients.list_requests()
    assert calls[0][2]["params"] == {}


def test_get_and_review_clients_call_request_service_endpoints(sent):
    """
    Summary: Reading and deciding requests call Equipment Request Service's matching endpoints.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Stub (httpx.request returns a request)
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
    assert calls[2][2]["json"] == {"status": "Approved", "notificationContext": {"eventId": "ev"}}
    assert calls[3][2]["json"] == {"status": "Rejected", "rejectionReason": "No technician available.", "notificationContext": {"eventId": "ev"}}


def test_event_summaries_client_fetches_in_chunks_of_100(sent):
    """
    Summary: Event details for many requests are fetched 100 events at a time.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    Double: Stub (httpx.request returns one event per call)
    """
    calls, fake = sent
    fake.response = FakeResponse(body={"events": [{"id": "x"}]})

    assert len(clients.get_event_summaries([str(i) for i in range(150)])) == 2
    assert len(calls) == 2 and calls[0][1] == "http://localhost:5003/events/summaries"
    assert len(calls[1][2]["params"]["ids"].split(",")) == 50


def test_assigned_events_client_uses_coordinator_scoped_endpoint(sent):
    """
    Summary: A coordinator's events come from Event Service's own scoped list for the token's user.
    AC3: Ensure the newly updated status is visible to the assigned Event
        Coordinator.
    SCRUM-9 AC3: Given an authenticated user's relationship to an event does
        not permit them to view that event's information, when they attempt to
        access the information, then access is denied.
    Double: Stub (httpx.request returns two events)
    """
    calls, fake = sent
    fake.response = FakeResponse(body={"events": [{"id": "event-1"}, {"id": "event-2"}]})

    with create_app().test_request_context(headers=HEADERS):
        assert clients.list_assigned_event_ids() == ["event-1", "event-2"]
    assert calls[0][0:2] == ("GET", "http://localhost:5003/events")
    assert calls[0][2] == {"timeout": 10, "headers": {"Authorization": "Bearer user-token"}}


@pytest.mark.parametrize("status", [401, 403, 404, 409], ids=["unauthorised", "forbidden", "not_found", "conflict"])
def test_downstream_client_when_refused_raises_with_status_and_message(sent, status):
    """
    Summary: A downstream refusal keeps its status and message.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Stub (httpx.request answers the refusal)
    """
    # Review AC1/AC2 (failure transport): preserve expected downstream authorization and decision errors.
    _, fake = sent
    fake.response = FakeResponse(status, {"message": "nope"})
    with pytest.raises(DownstreamError) as error:
        clients.get_request("r")
    assert (error.value.status, error.value.message) == (status, "nope")


@pytest.mark.parametrize("response", [FakeResponse(500, {"message": "db password"}), FakeResponse(400, json_error=True), FakeResponse(500, ["x"])], ids=["server_error", "unreadable_400", "non_object_500"])
def test_downstream_client_when_failing_raises_502_without_details(sent, response):
    """
    Summary: Other downstream failures become a generic 502 that leaks nothing.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Stub (httpx.request answers 500 or unreadable bodies)
    """
    # Review AC1/AC2 (failure transport): handle malformed or unexpected downstream errors safely.
    _, fake = sent
    fake.response = response
    with pytest.raises(DownstreamError) as error:
        clients.get_request("r")
    assert error.value.status == 502


def test_downstream_client_when_unreachable_raises_503(monkeypatch):
    """
    Summary: An unreachable downstream service is reported as unavailable.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
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
    """
    Summary: A rejection reason can be up to 500 characters.
    AC2: (boundary: reason length = 499, 500, 501)
    Double: Fake (world: one Pending line)
    """
    rid = "00000000-0000-4000-8000-0000000000d3"
    world.requests = [line(rid, TARGET, MIC, 1)]

    response = client.patch(
        f"/equipment-reservations/requests/{rid}", headers=TS, json={"status": "Rejected", "rejectionReason": "x" * length}
    )

    assert response.status_code == expected_status
