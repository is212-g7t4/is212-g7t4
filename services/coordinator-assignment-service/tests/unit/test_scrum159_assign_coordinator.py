"""
SCRUM-159: Assign Coordinator to an Event

User Story
----------
As an Event Coordinator Lead, I want to assign an Event Coordinator to an
unassigned event, so that the event has a main point of contact.

Acceptance Criteria
-------------------
AC1: Given an unassigned submitted event, when the Lead assigns a coordinator
     to the event, then the system:
     - assigns the selected coordinator to the event
     - removes the event from the unassigned queue
     - the current coordinator, who assigned them, and when the assignment was
       done are recorded in the event's detail page
AC2: Given an Event Coordinator who is not the Lead, they should not be able to
     see any 'Reassign' option or button

Real
----
- POST /events/<id>/assign-coordinator/<coordinator>: the Lead check against
  User Service's role, pool membership and the error mapping run for real, as
  do the User/Event Service client functions.
- Assertions are on the status and message the Lead sees, and on which
  coordinator is sent to Event Service.

Doubled
-------
- get_user, get_available_coordinators: Stub - return the acting user's profile
  and the assignable pool (or raise) without User Service.
- assign_event_coordinator: Mock - the call to Event Service is the assignment
  itself, so tests assert it is (or is not) made.
- httpx.get / httpx.patch (client tests): Stub - canned User/Event Service
  replies; call arguments are inspected to prove the URL and payload.

Not proven
----------
- That Event Service records the assigner and timestamp and removes the event
  from the unassigned queue (AC1, bullets 2-3) (-> event-service unit tests for
  SCRUM-159 and coordinator-assignment integration test
  test_coordinator_assignment.py).
- That a non-Lead sees no Reassign button (AC2, UI half) (-> frontend
  ReassignCoordinatorPanel.test.tsx).
"""

from unittest.mock import Mock

import httpx
import pytest

from app import clients, create_app
from tests.unit.factories import COORDINATOR, LEAD, as_lead, bearer, signed_in


def assign(coordinator_id="user-coordinator", headers=None):
    return create_app().test_client().post(
        f"/events/EVT-001/assign-coordinator/{coordinator_id}",
        headers=as_lead() if headers is None else headers,
    )


def user_service_reply(status, body):
    return httpx.Response(status, json=body, request=httpx.Request("GET", "http://user.test"))


def test_get_coordinators_when_lead_returns_available_pool(downstream):
    """
    Summary: GET /coordinators as the Lead returns {"coordinators": [...]} with
        the pool get_available_coordinators gave it, in the same order.
    AC1: the Lead selects a coordinator from the assignable pool
    Double: Stub (get_available_coordinators returns [LEAD, COORDINATOR])
    """
    # Arrange (Given)
    downstream.coordinators.return_value = [LEAD, COORDINATOR]
    client = signed_in(create_app().test_client(), role="Event Coordinator Lead")

    # Act (When)
    response = client.get("/coordinators")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json == {"coordinators": [LEAD, COORDINATOR]}


def test_get_coordinators_when_pool_lookup_fails_returns_500(downstream):
    """
    Summary: GET /coordinators as the Lead is answered 500 when
        get_available_coordinators raises, instead of an empty list.
    AC1: the Lead selects a coordinator from the assignable pool (error path: a
        failed read must not look like an empty pool)
    Double: Stub (get_available_coordinators raises Exception("User Service
        down"))
    """
    # Arrange (Given)
    downstream.coordinators.side_effect = Exception("User Service down")
    client = signed_in(create_app().test_client(), role="Event Coordinator Lead")

    # Act (When)
    response = client.get("/coordinators")

    # Assert (Then)
    assert response.status_code == 500
    assert "Failed to fetch coordinators" in response.json["error"]


def test_assign_when_lead_picks_available_coordinator_saves_assignment(downstream):
    """
    Summary: POST assign-coordinator as the Lead for a coordinator in the pool
        calls assign_event_coordinator("EVT-001", "user-coordinator") once and
        returns its result with 200.
    AC1 (bullet 1 only): assigns the selected coordinator to the event. Queue
        removal and the recorded assigner/time are Event Service's and not
        proven here.
    Double: Stub (get_user returns LEAD; get_available_coordinators returns
        [COORDINATOR]), Mock (assign_event_coordinator returns the saved
        assignment and is asserted called once)
    """
    # Arrange (Given)
    downstream.get_user.return_value = LEAD
    downstream.coordinators.return_value = [COORDINATOR]
    downstream.assign.return_value = {"eventId": "EVT-001", "assignedCoordinatorId": "user-coordinator"}

    # Act (When)
    response = assign("user-coordinator")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json == {"eventId": "EVT-001", "assignedCoordinatorId": "user-coordinator"}
    downstream.assign.assert_called_once_with("EVT-001", "user-coordinator")


def test_assign_when_lead_picks_themselves_saves_self_assignment(downstream):
    """
    Summary: POST assign-coordinator as the Lead with the Lead's own user id
        (which is in the pool) is answered 200 and calls
        assign_event_coordinator("EVT-001", "user-lead") once.
    AC1 (bullet 1 only): assigns the selected coordinator to the event; the
        Lead counts as selectable.
    Double: Stub (get_user returns LEAD; get_available_coordinators returns
        [LEAD, COORDINATOR]), Mock (assign_event_coordinator returns a canned
        assignment and is asserted called once)
    """
    # Arrange (Given)
    downstream.get_user.return_value = LEAD
    downstream.coordinators.return_value = [LEAD, COORDINATOR]
    downstream.assign.return_value = {"eventId": "EVT-001", "assignedCoordinatorId": "user-lead"}

    # Act (When)
    response = assign("user-lead")

    # Assert (Then)
    assert response.status_code == 200
    downstream.assign.assert_called_once_with("EVT-001", "user-lead")


def test_assign_when_coordinator_not_in_pool_returns_404_without_saving(downstream):
    """
    Summary: POST assign-coordinator as the Lead for "user-999", who is not in
        the pool, is answered 404 "... is not available or does not exist" and
        assign_event_coordinator is never called.
    AC1: only a coordinator from the assignable pool can be selected
    Double: Stub (get_user returns LEAD; get_available_coordinators returns
        [COORDINATOR]), Mock (assign_event_coordinator asserted not called)
    """
    # Arrange (Given)
    downstream.get_user.return_value = LEAD
    downstream.coordinators.return_value = [COORDINATOR]

    # Act (When)
    response = assign("user-999")

    # Assert (Then)
    assert response.status_code == 404
    assert "not available" in response.json["error"]
    downstream.assign.assert_not_called()


def test_assign_when_pool_lookup_fails_returns_500_without_saving(downstream):
    """
    Summary: POST assign-coordinator as the Lead is answered 500 "Failed to
        validate coordinator..." when get_available_coordinators raises, and
        assign_event_coordinator is never called.
    AC1: only a coordinator from the assignable pool can be selected (error
        path: an unreadable pool must not let an unchecked assignment through)
    Double: Stub (get_user returns LEAD; get_available_coordinators raises
        Exception("User Service error")), Mock (assign_event_coordinator
        asserted not called)
    """
    # Arrange (Given)
    downstream.get_user.return_value = LEAD
    downstream.coordinators.side_effect = Exception("User Service error")

    # Act (When)
    response = assign()

    # Assert (Then)
    assert response.status_code == 500
    assert "Failed to validate coordinator" in response.json["error"]
    downstream.assign.assert_not_called()


def test_assign_when_user_service_says_not_lead_returns_403(downstream):
    """
    Summary: POST assign-coordinator with a token claiming the Lead role is
        answered 403 {"error": "Only the Event Coordinator Lead can assign or
        reassign coordinators"} when User Service's profile for
        that user says Event Coordinator, and assign_event_coordinator is never
        called. The token's role claim is not what decides.
    AC2: only the Lead may assign (API half of "not able to see any Reassign
        option")
    Double: Stub (get_user returns the COORDINATOR profile), Mock
        (assign_event_coordinator asserted not called)
    """
    # Arrange (Given)
    downstream.get_user.return_value = COORDINATOR

    # Act (When)
    response = assign(headers=bearer("user-coordinator", "Event Coordinator Lead"))

    # Assert (Then)
    assert response.status_code == 403
    assert response.json == {"error": "Only the Event Coordinator Lead can assign or reassign coordinators"}
    downstream.assign.assert_not_called()


def test_assign_when_acting_user_unknown_returns_403(downstream):
    """
    Summary: POST assign-coordinator with a Lead-role token whose user id
        User Service does not know (get_user returns None) is answered 403 {"error":
        "Only the Event Coordinator Lead can assign or reassign coordinators"} and
        assign_event_coordinator is never called.
    AC2: only the Lead may assign
    Double: Stub (get_user returns None), Mock (assign_event_coordinator
        asserted not called)
    """
    # Arrange (Given)
    downstream.get_user.return_value = None

    # Act (When)
    response = assign(headers=bearer("does-not-exist", "Event Coordinator Lead"))

    # Assert (Then)
    assert response.status_code == 403
    assert response.json == {"error": "Only the Event Coordinator Lead can assign or reassign coordinators"}
    downstream.assign.assert_not_called()


def test_assign_when_acting_user_lookup_fails_returns_500_before_pool_lookup(downstream):
    """
    Summary: POST assign-coordinator as the Lead is answered 500 "Failed to
        validate acting user..." when get_user raises, and
        get_available_coordinators is never called.
    AC2: only the Lead may assign (error path: if the role cannot be checked,
        nothing further is read or done)
    Double: Stub (get_user raises Exception("User Service unreachable")), Mock
        (get_available_coordinators asserted not called)
    """
    # Arrange (Given)
    downstream.get_user.side_effect = Exception("User Service unreachable")

    # Act (When)
    response = assign()

    # Assert (Then)
    assert response.status_code == 500
    assert "Failed to validate acting user" in response.json["error"]
    downstream.coordinators.assert_not_called()


def test_assign_when_event_service_fails_returns_500_not_success(downstream):
    """
    Summary: POST assign-coordinator as the Lead is answered 500 "Failed to
        assign coordinator to event..." (not 200) when
        assign_event_coordinator raises a plain Exception.
    AC1 (bullet 1 only; error path): the assignment is not reported as done when
        Event Service could not save it.
    Double: Stub (get_user returns LEAD; get_available_coordinators returns
        [COORDINATOR]; assign_event_coordinator raises Exception("Event Service
        down"))
    """
    # Arrange (Given)
    downstream.get_user.return_value = LEAD
    downstream.coordinators.return_value = [COORDINATOR]
    downstream.assign.side_effect = Exception("Event Service down")

    # Act (When)
    response = assign()

    # Assert (Then)
    assert response.status_code == 500
    assert "Failed to assign coordinator to event" in response.json["error"]


def test_available_coordinators_when_queried_include_lead_first(monkeypatch):
    """
    Summary: clients.get_available_coordinators() asks User Service for the
        Event Coordinator Lead users, then the Event Coordinator users, and
        returns them in that order (Lead first).
    AC1: the Lead selects a coordinator from the assignable pool
    Double: Stub (httpx.get is replaced and answers 200 with one user per
        requested role; the role params of each call are inspected)
    """
    by_role = {
        "Event Coordinator Lead": [{"user_id": "lead", "role": "Event Coordinator Lead"}],
        "Event Coordinator": [{"user_id": "coord", "role": "Event Coordinator"}],
    }
    get = Mock(side_effect=lambda url, params, headers: user_service_reply(200, {"users": by_role[params["role"]]}))
    monkeypatch.setattr(clients.httpx, "get", get)

    coordinators = clients.get_available_coordinators()

    assert [c["user_id"] for c in coordinators] == ["lead", "coord"]
    assert [call.kwargs["params"]["role"] for call in get.call_args_list] == list(clients.ASSIGNABLE_ROLES)


def test_get_user_when_found_returns_profile(monkeypatch):
    """
    Summary: clients.get_user("user-lead") requests {USER_SERVICE_URL}/users/user-lead
        and returns the profile (including role) from a 200 reply.
    AC2: only the Lead may assign (the role check needs the user's profile)
    Double: Stub (httpx.get is replaced and answers 200 with the LEAD profile;
        the URL it was called with is inspected)
    """
    get = Mock(return_value=user_service_reply(200, LEAD))
    monkeypatch.setattr(clients.httpx, "get", get)

    assert clients.get_user("user-lead") == LEAD
    assert get.call_args.args[0] == f"{clients.USER_SERVICE_URL}/users/user-lead"


def test_get_user_when_unknown_returns_none(monkeypatch):
    """
    Summary: clients.get_user("nobody") returns None, not an exception, when
        User Service answers 404.
    AC2: only the Lead may assign (an unknown user is later refused by the route
        as not the Lead, see test_assign_when_acting_user_unknown_returns_403)
    Double: Stub (httpx.get is replaced and answers 404)
    """
    # Arrange (Given)
    monkeypatch.setattr(clients.httpx, "get", Mock(return_value=user_service_reply(404, {})))

    # Act + Assert (When / Then)
    assert clients.get_user("nobody") is None


def test_assign_event_coordinator_when_called_sends_only_new_coordinator(monkeypatch):
    """
    Summary: clients.assign_event_coordinator("evt-1", "coord") PATCHes
        {EVENT_SERVICE_URL}/events/evt-1 with a JSON body of exactly
        {"assignedCoordinatorId": "coord"} (no assigner is sent) and returns
        Event Service's reply.
    AC1 (bullet 1 only): assigns the selected coordinator to the event. That
        Event Service records the assigner and time from the forwarded token
        is not proven here.
    Double: Stub (httpx.patch is replaced and answers 200 with the saved event;
        the URL and JSON it was called with are inspected)
    """
    # Arrange (Given)
    saved = {"id": "evt-1", "coordinatorId": "coord", "assignedBy": "lead"}
    patch = Mock(return_value=httpx.Response(200, json=saved, request=httpx.Request("PATCH", "http://event.test")))

    monkeypatch.setattr(clients.httpx, "patch", patch)

    # Act + Assert (When / Then)
    assert clients.assign_event_coordinator("evt-1", "coord") == saved
    assert patch.call_args.args[0] == f"{clients.EVENT_SERVICE_URL}/events/evt-1"
    assert patch.call_args.kwargs["json"] == {"assignedCoordinatorId": "coord"}


@pytest.mark.parametrize(
    "http_method,status,call",
    [
        pytest.param("get", 503, lambda: clients.get_available_coordinators(), id="pool_503"),
        pytest.param("get", 500, lambda: clients.get_user("user-lead"), id="acting_user_500"),
        pytest.param("patch", 404, lambda: clients.assign_event_coordinator("evt-1", "coord"), id="assign_404"),
    ],
)
def test_client_when_downstream_service_refuses_raises_http_error(monkeypatch, http_method, status, call):
    """
    Summary: get_available_coordinators (User Service 503), get_user (User
        Service 500) and assign_event_coordinator (Event Service 404) each raise
        httpx.HTTPStatusError instead of returning an empty pool, None or a
        saved event, so the route can map the failure.
    AC1: the Lead selects a coordinator from the assignable pool (case
        "pool_503"), and AC1 bullet 1 (case "assign_404"): a failed read or
        refused save is not returned as success.
    AC2: only the Lead may assign (case "acting_user_500": a failed lookup must
        not be read as "unknown user")
    Double: Stub (httpx.get or httpx.patch is replaced and answers the
        parametrised status with an empty JSON body)
    """
    # Arrange (Given)
    reply = httpx.Response(status, json={}, request=httpx.Request(http_method.upper(), "http://downstream.test"))
    monkeypatch.setattr(clients.httpx, http_method, Mock(return_value=reply))

    # Act + Assert (When / Then)
    with pytest.raises(httpx.HTTPStatusError):
        call()


def test_assign_when_token_says_coordinator_but_user_service_says_lead_saves_assignment(downstream):
    """
    Summary: POST assign-coordinator with an Event Coordinator-role token is
        answered 200 and calls assign_event_coordinator when User Service's
        profile for that user says Event Coordinator Lead. The role is read
        fresh from User Service, not from the token (unlike /queue, /workload
        and /coordinators).
    AC2: only the Lead may assign (the live User Service role decides, so a
        promotion or demotion takes effect before the token is reissued)
    Double: Stub (get_user returns LEAD; get_available_coordinators returns
        [COORDINATOR]), Mock (assign_event_coordinator returns a canned
        assignment and is asserted called once)
    """
    # Arrange (Given)
    downstream.get_user.return_value = LEAD
    downstream.coordinators.return_value = [COORDINATOR]
    downstream.assign.return_value = {"eventId": "EVT-001", "assignedCoordinatorId": "user-coordinator"}

    # Act (When)
    response = assign(headers=bearer("user-lead", "Event Coordinator"))

    # Assert (Then)
    assert response.status_code == 200
    downstream.assign.assert_called_once_with("EVT-001", "user-coordinator")


def test_assign_when_pool_entry_has_only_id_returns_404_without_saving(downstream):
    """
    Summary: POST assign-coordinator as the Lead for "user-coordinator" is
        answered 404 and assign_event_coordinator is never called when the pool
        entry carries the id under "id" instead of "user_id", because only
        "user_id" (User Service's key) is read.
    AC1: only a coordinator from the assignable pool can be selected
    Double: Stub (get_user returns LEAD; get_available_coordinators returns one
        entry {"id": "user-coordinator", "role": "Event Coordinator"}), Mock
        (assign_event_coordinator asserted not called)
    """
    # Arrange (Given)
    downstream.get_user.return_value = LEAD
    downstream.coordinators.return_value = [{"id": "user-coordinator", "role": "Event Coordinator"}]

    # Act (When)
    response = assign("user-coordinator")

    # Assert (Then)
    assert response.status_code == 404
    downstream.assign.assert_not_called()
