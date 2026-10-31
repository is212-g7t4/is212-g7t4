"""SCRUM-9: Role-Based Access Control for Events

User Story
----------
As a registered user, I want to view only information appropriate to my role and relationship to an event, so that I can access the information relevant to my responsibilities without viewing restricted information.

Acceptance Criteria
-------------------
AC1: Given an authenticated user is permitted to view information based on their role and relationship to the event, when they access that information, then the information is made available to them.
AC2: Given an authenticated user's role does not permit them to view particular information, when they attempt to access that information, then access is denied.
AC3: Given an authenticated user's relationship to an event does not permit them to view that event's information, when they attempt to access the information, then access is denied.
AC4: Given a user is permitted to view information for one event but does not have the required relationship to another event, when they attempt to view information for both events, then they can only view the information for which they have the required access.
AC5: Given two authenticated users have different roles or relationships to the same event, when they access information relating to that event, then each user can only view the information permitted by their own role and relationship to the event.

Real
----
- Real composite request-list filtering and client request construction; current coordinator assignment controls the visible event IDs.

Doubled
-------
- Fake (Event and Equipment Request services with assignment changes); Stub (HTTP event responses); Mock (outbound method/URL/headers inspected). JWKS key lookup is a Stub.

Not proven
----------
- AC1: Permitted local assignment-scoped list access is checked.
- AC2: Role refusal is covered by the authentication module, not these assignment-focused cases.
- AC3: Unauthorized events are filtered from local list responses.
- AC4: Mixed permitted and other event lists are checked.
- AC5: Old/new coordinator views after reassignment are checked; Event assignment persistence is doubled.
- Supporting validation, transport, retry, authentication configuration and defensive checks retain useful regressions, but their exact limits/failure contracts are not separate Jira ACs; Product Owner clarification remains pending.
- Real Supabase issuance, other services, browser rendering and actual broker durability are NOT COVERED ANYWHERE in this module.
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



def test_review_list_when_coordinator_shows_only_their_assigned_events(world, client):
    """Summary: A coordinator sees equipment requests only for events currently assigned to them.
AC1: Given an authenticated user is permitted to view information based on their role and relationship to the event, when they access that information, then the information is made available to them.
AC3: Given an authenticated user's relationship to an event does not permit them to view that event's information, when they attempt to access the information, then access is denied.
AC4: Given a user is permitted to view information for one event but does not have the required relationship to another event, when they attempt to view information for both events, then they can only view the information for which they have the required access.
Double: Fake (downstream service assignments); Stub (event lookup HTTP responses)
"""
    # Arrange (Given)
    # Arrange (Given): test data and external adapters from fixtures.
    assigned_event = "00000000-0000-4000-8000-0000000000e1"
    other_event = "00000000-0000-4000-8000-0000000000e2"
    world.coordinator_assignments = {assigned_event: USER, other_event: THIRD}
    world.requests = [line("assigned", assigned_event, MIC, 2), line("other", other_event, MIC, 2)]

    # Act (When)
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    response = client.get("/equipment-reservations", headers=COORDINATOR)

    # Assert (Then)
    assert response.status_code == 200
    assert [event["eventId"] for event in response.json["events"]] == [assigned_event]
    assert ("assigned_events", USER) in world.calls
    assert ("list_requests", None, [assigned_event]) in world.calls


def test_review_list_when_coordinator_has_no_events_shows_nothing(world, client):
    """Summary: A coordinator with no assigned events sees no requests and nothing else is fetched.
AC3: Given an authenticated user's relationship to an event does not permit them to view that event's information, when they attempt to access the information, then access is denied.
Double: Fake (downstream service assignments); Stub (event lookup HTTP responses)
"""
    # Arrange (Given)
    # Arrange (Given): test data and external adapters from fixtures.
    world.requests = [line("unassigned", TARGET, MIC, 2)]

    # Act (When)
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    response = client.get("/equipment-reservations", headers=COORDINATOR)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["events"] == []
    assert ("list_requests", None, []) in world.calls


def test_review_list_after_reassignment_moves_access_to_new_coordinator(world, client):
    """Summary: After reassignment, only the new coordinator sees the event's equipment requests.
AC5: Given two authenticated users have different roles or relationships to the same event, when they access information relating to that event, then each user can only view the information permitted by their own role and relationship to the event.
Double: Fake (downstream service assignments); Stub (event lookup HTTP responses)
"""
    # Arrange (Given)
    # Arrange (Given): test data and external adapters from fixtures.
    event_id = "00000000-0000-4000-8000-0000000000e1"
    world.requests = [line("assigned", event_id, MIC, 2)]
    world.coordinator_assignments = {event_id: THIRD}

    old_coordinator = client.get("/equipment-reservations", headers=COORDINATOR)

    # Act (When)
    new_coordinator = client.get("/equipment-reservations", headers=bearer(THIRD, "Event Coordinator"))

    # Assert (Then)
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    assert old_coordinator.json["events"] == []
    assert [event["eventId"] for event in new_coordinator.json["events"]] == [event_id]


def test_review_list_when_lead_shows_only_their_assigned_events(world, client):
    """Summary: The Lead, like any coordinator, sees requests only for events assigned to them.
AC1: Given an authenticated user is permitted to view information based on their role and relationship to the event, when they access that information, then the information is made available to them.
AC3: Given an authenticated user's relationship to an event does not permit them to view that event's information, when they attempt to access the information, then access is denied.
AC4: Given a user is permitted to view information for one event but does not have the required relationship to another event, when they attempt to view information for both events, then they can only view the information for which they have the required access.
Double: Fake (downstream service assignments); Stub (event lookup HTTP responses)
"""
    # Arrange (Given)
    # Arrange (Given): test data and external adapters from fixtures.
    event_id = "00000000-0000-4000-8000-0000000000e1"
    world.requests = [line("assigned", event_id, MIC, 2), line("other", OTHER, MIC, 1)]
    world.coordinator_assignments = {event_id: USER, OTHER: THIRD}

    # Act (When)
    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    response = client.get("/equipment-reservations", headers=LEAD)

    # Assert (Then)
    assert response.status_code == 200
    assert [event["eventId"] for event in response.json["events"]] == [event_id]


def test_assigned_events_client_uses_coordinator_scoped_endpoint(sent):
    """Summary: A coordinator's events come from Event Service's own scoped list for the token's user.
AC3: Given an authenticated user's relationship to an event does not permit them to view that event's information, when they attempt to access the information, then access is denied.
Double: Stub (canned downstream HTTP responses), Mock (recorded outbound method, URL, headers or no-call contract).
"""
    # Arrange (Given): test data and external adapters from fixtures.
    calls, fake = sent
    fake.response = FakeResponse(body={"events": [{"id": "event-1"}, {"id": "event-2"}]})

    # Act + Assert (When / Then): exercise the request/calculation and inspect outcomes.
    with create_app().test_request_context(headers=HEADERS):
        assert clients.list_assigned_event_ids() == ["event-1", "event-2"]
    assert calls[0][0:2] == ("GET", "http://localhost:5003/events")
    assert calls[0][2] == {"timeout": 10, "headers": {"Authorization": "Bearer user-token"}}
