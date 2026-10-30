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

Real
----
- POST /events/<id>/assign-coordinator/<coordinator>: the signed-in check, the
  Lead check against User Service's role, pool membership and the error mapping
  run for real, as do the User/Event Service client functions.
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
    Summary: The Lead can list the coordinators an event can be given to.
    AC1: the Lead selects a coordinator from the assignable pool
    Double: Stub (pool of Lead and one coordinator)
    """
    # Arrange (Given)
    downstream.coordinators.return_value = [LEAD, COORDINATOR]
    client = signed_in(create_app().test_client(), role="Event Coordinator Lead")

    # Act (When)
    response = client.get("/coordinators")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json == {"coordinators": [LEAD, COORDINATOR]}


def test_assign_when_lead_picks_available_coordinator_saves_assignment(downstream):
    """
    Summary: The Lead can assign an unassigned event to an available coordinator.
    AC1: Given an unassigned submitted event, when the Lead assigns a
        coordinator to the event, then the system:
        - assigns the selected coordinator to the event
        - removes the event from the unassigned queue
        - the current coordinator, who assigned them, and when the assignment
          was done are recorded in the event's detail page
    Double: Stub (acting user is the Lead; pool), Mock
        (assign_event_coordinator)
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
    Summary: The Lead can take an event on themselves.
    AC1: Given an unassigned submitted event, when the Lead assigns a
        coordinator to the event, then the system:
        - assigns the selected coordinator to the event
        - removes the event from the unassigned queue
        - the current coordinator, who assigned them, and when the assignment
          was done are recorded in the event's detail page
    Double: Stub (acting user is the Lead; pool includes the Lead), Mock
        (assign_event_coordinator)
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
    Summary: An event cannot be given to someone who is not an assignable coordinator.
    AC1: only a coordinator from the assignable pool can be selected
    Double: Stub (pool without the chosen user), Mock (assign_event_coordinator
        not called)
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
    Summary: If the coordinator pool cannot be read, nothing is assigned and the Lead sees an error.
    AC1: Given an unassigned submitted event, when the Lead assigns a
        coordinator to the event, then the system:
        - assigns the selected coordinator to the event
        - removes the event from the unassigned queue
        - the current coordinator, who assigned them, and when the assignment
          was done are recorded in the event's detail page
    Double: Stub (pool lookup raises), Mock (assign_event_coordinator not
        called)
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


def test_assign_without_token_returns_401(downstream):
    """
    Summary: Nobody can assign a coordinator without signing in.
    SCRUM-8 AC1: Given a system user has not been successfully authenticated,
        when they attempt to access protected information or functionality,
        then access is denied.
    Double: Mock (assign_event_coordinator not called)
    """
    # Arrange (Given): downstream, from fixtures

    # Act (When)
    response = create_app().test_client().post(
        "/events/EVT-001/assign-coordinator/user-coordinator", json={"actingUserId": "user-lead"}
    )

    # Assert (Then)
    assert response.status_code == 401
    downstream.assign.assert_not_called()


def test_assign_when_user_service_says_not_lead_returns_403(downstream):
    """
    Summary: A coordinator who is not the Lead cannot assign, even with a token that claims the Lead role.
    AC2: only the Lead may assign (API half of "not able to see any Reassign
        option")
    Double: Stub (User Service profile says Event Coordinator), Mock
        (assign_event_coordinator not called)
    """
    # Arrange (Given)
    downstream.get_user.return_value = COORDINATOR

    # Act (When)
    response = assign(headers=bearer("user-coordinator", "Event Coordinator Lead"))

    # Assert (Then)
    assert response.status_code == 403
    assert "Lead" in response.json["error"]
    downstream.assign.assert_not_called()


def test_assign_when_acting_user_unknown_returns_403(downstream):
    """
    Summary: A signed-in user with no profile cannot assign.
    AC2: only the Lead may assign
    Double: Stub (User Service has no profile), Mock (assign_event_coordinator
        not called)
    """
    # Arrange (Given)
    downstream.get_user.return_value = None

    # Act (When)
    response = assign(headers=bearer("does-not-exist", "Event Coordinator Lead"))

    # Assert (Then)
    assert response.status_code == 403
    downstream.assign.assert_not_called()


def test_assign_when_acting_user_lookup_fails_returns_500_before_pool_lookup(downstream):
    """
    Summary: If the Lead's own profile cannot be checked, the assignment stops before anything else is read.
    AC2: Given an Event Coordinator who is not the Lead, they should not be
        able to see any 'Reassign' option or button
    Double: Stub (User Service raises), Mock (pool lookup not called)
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
    Summary: If Event Service cannot save the assignment, the Lead gets an error rather than a false success.
    AC1: Given an unassigned submitted event, when the Lead assigns a
        coordinator to the event, then the system:
        - assigns the selected coordinator to the event
        - removes the event from the unassigned queue
        - the current coordinator, who assigned them, and when the assignment
          was done are recorded in the event's detail page
    Double: Stub (acting user, pool, assign_event_coordinator raises)
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


def test_assign_with_acting_user_in_body_checks_token_identity_instead(downstream):
    """
    Summary: The person assigning is the signed-in user; an id in the request body is ignored.
    SCRUM-8 AC2: Given a system user successfully authenticates, when they
        access protected information or functionality, then their access is
        evaluated according to their role and relationship to the relevant
        event.
    Double: Mock (get_user records which user is looked up)
    """
    # Arrange (Given)
    downstream.get_user.return_value = None

    # Act (When)
    create_app().test_client().post(
        "/events/EVT-1/assign-coordinator/user-1",
        json={"actingUserId": "someone-else"},
        headers=bearer("e7334aa9-eb3a-4c45-84b5-280501b6c109", "Event Coordinator"),
    )

    # Assert (Then)
    downstream.get_user.assert_called_once_with("e7334aa9-eb3a-4c45-84b5-280501b6c109")


def test_available_coordinators_when_queried_include_lead_first(monkeypatch):
    """
    Summary: The assignable pool is the Lead followed by every Event Coordinator.
    AC1: the Lead selects a coordinator from the assignable pool
    Double: Stub (httpx.get returns users per role)
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


def test_available_coordinators_when_user_service_fails_raises_http_error(monkeypatch):
    """
    Summary: A User Service failure while reading the pool is raised, not hidden as an empty pool.
    AC1: Given an unassigned submitted event, when the Lead assigns a
        coordinator to the event, then the system:
        - assigns the selected coordinator to the event
        - removes the event from the unassigned queue
        - the current coordinator, who assigned them, and when the assignment
          was done are recorded in the event's detail page
    Double: Stub (httpx.get answers 503)
    """
    # Arrange (Given)
    monkeypatch.setattr(clients.httpx, "get", Mock(return_value=user_service_reply(503, {})))

    # Act + Assert (When / Then)
    with pytest.raises(httpx.HTTPStatusError):
        clients.get_available_coordinators()


def test_get_user_when_found_returns_profile(monkeypatch):
    """
    Summary: The acting user's profile, with their role, is read from User Service.
    AC2: only the Lead may assign
    Double: Stub (httpx.get returns the Lead's profile)
    """
    get = Mock(return_value=user_service_reply(200, LEAD))
    monkeypatch.setattr(clients.httpx, "get", get)

    assert clients.get_user("user-lead") == LEAD
    assert get.call_args.args[0] == f"{clients.USER_SERVICE_URL}/users/user-lead"


def test_get_user_when_unknown_returns_none(monkeypatch):
    """
    Summary: A user User Service does not know is reported as missing rather than as an error.
    AC2: Given an Event Coordinator who is not the Lead, they should not be
        able to see any 'Reassign' option or button
    Double: Stub (httpx.get answers 404)
    """
    # Arrange (Given)
    monkeypatch.setattr(clients.httpx, "get", Mock(return_value=user_service_reply(404, {})))

    # Act + Assert (When / Then)
    assert clients.get_user("nobody") is None


def test_get_user_when_user_service_fails_raises_http_error(monkeypatch):
    """
    Summary: A User Service failure while checking the acting user is raised.
    AC2: Given an Event Coordinator who is not the Lead, they should not be
        able to see any 'Reassign' option or button
    Double: Stub (httpx.get answers 500)
    """
    # Arrange (Given)
    monkeypatch.setattr(clients.httpx, "get", Mock(return_value=user_service_reply(500, {})))

    # Act + Assert (When / Then)
    with pytest.raises(httpx.HTTPStatusError):
        clients.get_user("user-lead")


def test_assign_event_coordinator_when_called_sends_only_new_coordinator(monkeypatch):
    """
    Summary: Event Service is told only the new coordinator; it records the signed-in Lead as assigner itself.
    AC1: Given an unassigned submitted event, when the Lead assigns a
        coordinator to the event, then the system:
        - assigns the selected coordinator to the event
        - removes the event from the unassigned queue
        - the current coordinator, who assigned them, and when the assignment
          was done are recorded in the event's detail page
    Double: Stub (httpx.patch returns the saved event)
    """
    # Arrange (Given)
    saved = {"id": "evt-1", "coordinatorId": "coord", "assignedBy": "lead"}
    patch = Mock(return_value=httpx.Response(200, json=saved, request=httpx.Request("PATCH", "http://event.test")))

    monkeypatch.setattr(clients.httpx, "patch", patch)

    # Act + Assert (When / Then)
    assert clients.assign_event_coordinator("evt-1", "coord") == saved
    assert patch.call_args.args[0] == f"{clients.EVENT_SERVICE_URL}/events/evt-1"
    assert patch.call_args.kwargs["json"] == {"assignedCoordinatorId": "coord"}


def test_assign_event_coordinator_when_event_service_refuses_raises_http_error(monkeypatch):
    """
    Summary: An Event Service refusal of the assignment is raised to the route.
    AC1: Given an unassigned submitted event, when the Lead assigns a
        coordinator to the event, then the system:
        - assigns the selected coordinator to the event
        - removes the event from the unassigned queue
        - the current coordinator, who assigned them, and when the assignment
          was done are recorded in the event's detail page
    Double: Stub (httpx.patch answers 404)
    """
    # Arrange (Given)
    monkeypatch.setattr(clients.httpx, "patch", Mock(return_value=httpx.Response(
        404, json={}, request=httpx.Request("PATCH", "http://event.test"))))

    # Act + Assert (When / Then)
    with pytest.raises(httpx.HTTPStatusError):
        clients.assign_event_coordinator("evt-1", "coord")
