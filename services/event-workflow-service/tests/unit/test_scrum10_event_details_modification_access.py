"""
SCRUM-10: Role-Based Modification Control for Events

User Story
----------
As a registered user, I want to modify only information appropriate to my role
and relationship to an event, so that I can perform my responsibilities without
changing information outside my permissions.

Acceptance Criteria
-------------------
AC1: Given an authenticated user is permitted to modify information based on
     their role and relationship to the event, when they make a valid change to
     that information, then the change is allowed.
AC2: Given an authenticated user's role does not permit them to modify
     particular information, when they attempt to change that information, then
     the modification is prevented and the existing information remains
     unchanged.
AC3: Given an authenticated user's relationship to an event does not permit
     them to modify that event's information, when they attempt to make a
     change, then the modification is prevented and the existing information
     remains unchanged.
AC4: Given a user is permitted to view particular information but is not
     permitted to modify it, when they attempt to change that information, then
     the modification is prevented while their permitted viewing access remains
     unaffected.
AC5: Given a user is permitted to modify information for one event but does not
     have the required access to another event, when they attempt to modify
     information for both events, then only modifications to information for
     which they have the required access are allowed.

Real
----
- PATCH /events/<id>/details: token verification and the coordinator-role gate
  (read from the token's role claim) run for real.
- PATCH /change-requests/<id>: the coordinator check (role read from User
  Service) runs for real.
- Assertions are on the status, error code and which downstream calls are made.

Doubled
-------
- Supabase signing key: Stub (autouse fixture in conftest.py) so bearer tokens
  can be minted locally.
- User Service `get_user`: Stub where the test says so.
- Event Service change-request calls: Stub that records calls, to prove none
  is made for a refused user.

Not proven
----------
- That the coordinator is the event's assigned one (AC3, AC5): Event Service
  decides; the tests here prove its refusal is passed on and nothing is saved
  (-> event-service test_scrum10_event_modification_access.py).
- That a valid change by a permitted role is saved (AC1 in full): the happy
  path is covered by the SCRUM-20 update tests.
- AC4 (view allowed, modify refused): this service serves no read-only route
  to the roles concerned (viewing is Event Service's /events routes), so there
  is nothing to test here (-> event-service test_scrum9_event_view_access.py).
"""
import pytest

from app import clients, create_app
from tests.unit.factories import bearer, signed_in

EVENT_ID = "00000000-0000-0000-0000-000000000001"
OTHER_EVENT_ID = "00000000-0000-0000-0000-000000000002"
CHANGE_ID = "22222222-2222-4222-8222-222222222222"
USER = "00000000-0000-4000-8000-000000000001"


# AC1 ----

@pytest.mark.parametrize("role", ["Event Coordinator", "Event Coordinator Lead"], ids=["event_coordinator", "event_coordinator_lead"])
def test_ac1_update_details_when_coordinator_role_passes_role_gate(role):
    """
    Summary: PATCH /events/<id>/details with an empty body and a token whose
        role is Event Coordinator or Event Coordinator Lead is not refused
        with 403; it is stopped later by body validation (400, message
        mentions "changes"), so the role gate let the caller through.
    AC1: Given an authenticated user is permitted to modify information based
        on their role and relationship to the event, when they make a valid
        change to that information, then the change is allowed.
    Double: Stub (Supabase signing key only, via conftest); no downstream
        client is stubbed or reached because the empty body is rejected first
    """
    # Arrange (Given)
    client = signed_in(create_app().test_client(), role=role)

    # Act (When)
    response = client.patch(f"/events/{EVENT_ID}/details", json={})

    # Assert (Then)
    assert response.status_code == 400
    assert "changes" in response.json["message"]


# AC2 ----

@pytest.mark.parametrize(
    "role", ["Event Organiser", "Venue Staff", "Technical Support", "Safety Officer", "Attendee"],
    ids=["event_organiser", "venue_staff", "technical_support", "safety_officer", "attendee"],
)
def test_ac2_update_details_when_not_coordinator_returns_403(role):
    """
    Summary: PATCH /events/<id>/details with a valid body and a token whose
        role is Event Organiser, Venue Staff, Technical Support, Safety
        Officer or Attendee is answered 403 NOT_ASSIGNED_COORDINATOR "Your
        role cannot change this information." before any downstream call.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Stub (Supabase signing key only, via conftest); no downstream
        client is stubbed, so any call to Event or User Service would fail
        the request instead of returning 403
    """
    # Arrange (Given)
    client = create_app().test_client()

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/details", json={"changes": {"eventName": "X"}}, headers=bearer(USER, role)
    )

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["code"] == "NOT_ASSIGNED_COORDINATOR"
    assert response.json["message"] == "Your role cannot change this information."


def test_ac2_review_change_request_when_not_coordinator_returns_403(monkeypatch):
    """
    Summary: PATCH /change-requests/<id> approving a request is answered 403
        COORDINATOR_REQUIRED when User Service says the signed-in user is an
        Event Organiser, and no change request is read or decided.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Stub (get_user returns role Event Organiser), Mock (get_change_request
        and decide_change_request record calls; none are made)
    """
    # Arrange (Given)
    calls = []
    monkeypatch.setattr(clients, "get_user", lambda _id: {"role": "Event Organiser"})
    monkeypatch.setattr(clients, "get_change_request", lambda *args: calls.append(("read", args)))
    monkeypatch.setattr(clients, "decide_change_request", lambda *args: calls.append(("decide", args)))
    client = signed_in(create_app().test_client())

    # Act (When)
    response = client.patch(f"/change-requests/{CHANGE_ID}", json={"decision": "Approved"})

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["code"] == "COORDINATOR_REQUIRED"
    assert calls == []


# AC3 ----

def test_ac3_update_details_when_event_service_refuses_unassigned_coordinator_saves_nothing(monkeypatch):
    """
    Summary: PATCH /events/<id>/details by a coordinator whom Event Service
        says is not assigned to the event is answered 403
        NOT_ASSIGNED_COORDINATOR with Event Service's message unchanged, and
        save_event_details is never called, so the event stays as it was.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to modify that event's information, when they attempt to make a
        change, then the modification is prevented and the existing information
        remains unchanged.
    Double: Stub (get_user returns role Event Coordinator;
        preview_event_details raises EventRejectedError 403
        NOT_ASSIGNED_COORDINATOR), Mock (save_event_details records calls;
        none are made)
    """
    # Arrange (Given)
    saved = []
    refusal = {"code": "NOT_ASSIGNED_COORDINATOR", "message": "You are not assigned to this event."}

    def refuse(*args, **kwargs):
        raise clients.EventRejectedError(403, refusal)

    monkeypatch.setattr(clients, "get_user", lambda _id: {"role": "Event Coordinator"})
    monkeypatch.setattr(clients, "preview_event_details", refuse)
    monkeypatch.setattr(clients, "save_event_details", lambda *args: saved.append(args))
    client = signed_in(create_app().test_client())

    # Act (When)
    response = client.patch(f"/events/{EVENT_ID}/details", json={"changes": {"eventName": "New"}})

    # Assert (Then)
    assert response.status_code == 403
    assert response.json == refusal
    assert saved == []


def test_ac3_review_change_request_when_event_service_refuses_unassigned_coordinator_decides_nothing(monkeypatch):
    """
    Summary: PATCH /change-requests/<id> approving a request for an event the
        coordinator is not assigned to is answered 403 with Event Service's
        refusal unchanged when Event Service refuses to return the request, and
        no decision is sent.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to modify that event's information, when they attempt to make a
        change, then the modification is prevented and the existing information
        remains unchanged.
    Double: Stub (get_user returns role Event Coordinator;
        get_change_request raises EventRejectedError 403
        NOT_ASSIGNED_COORDINATOR), Mock (decide_change_request records calls;
        none are made)
    """
    # Arrange (Given)
    decided = []
    refusal = {"code": "NOT_ASSIGNED_COORDINATOR", "message": "You are not assigned to this event."}

    def refuse(*args, **kwargs):
        raise clients.EventRejectedError(403, refusal)

    monkeypatch.setattr(clients, "get_user", lambda _id: {"role": "Event Coordinator"})
    monkeypatch.setattr(clients, "get_change_request", refuse)
    monkeypatch.setattr(clients, "decide_change_request", lambda *args: decided.append(args))
    client = signed_in(create_app().test_client())

    # Act (When)
    response = client.patch(f"/change-requests/{CHANGE_ID}", json={"decision": "Approved"})

    # Assert (Then)
    assert response.status_code == 403
    assert response.json == refusal
    assert decided == []


# AC5 ----

def test_ac5_update_details_for_two_events_only_the_permitted_one_is_saved(monkeypatch):
    """
    Summary: One coordinator sends the same edit for two events: the event they
        are assigned to is saved and answered 200, the event Event Service
        refuses (403 NOT_ASSIGNED_COORDINATOR) is answered 403, and only the
        permitted event id is ever saved.
    AC5: Given a user is permitted to modify information for one event but does
        not have the required access to another event, when they attempt to
        modify information for both events, then only modifications to
        information for which they have the required access are allowed.
    Double: Stub (get_user returns role Event Coordinator;
        preview_event_details returns a low-impact preview for the permitted
        event and raises EventRejectedError 403 for the other one), Mock
        (save_event_details records the event id of each save)
    """
    # Arrange (Given)
    saved = []

    def preview(event_id, changes, actor_role=None):
        if event_id == OTHER_EVENT_ID:
            raise clients.EventRejectedError(403, {"code": "NOT_ASSIGNED_COORDINATOR"})
        return {"event": {"id": event_id}, "changedFields": ["eventName"], "highImpactFields": [], "labels": []}

    def save(event_id, changes, actor_role=None):
        saved.append(event_id)
        return {"id": event_id}

    monkeypatch.setattr(clients, "get_user", lambda _id: {"role": "Event Coordinator"})
    monkeypatch.setattr(clients, "preview_event_details", preview)
    monkeypatch.setattr(clients, "save_event_details", save)
    client = signed_in(create_app().test_client())
    body = {"changes": {"eventName": "New"}}

    # Act (When)
    permitted = client.patch(f"/events/{EVENT_ID}/details", json=body)
    refused = client.patch(f"/events/{OTHER_EVENT_ID}/details", json=body)

    # Assert (Then)
    assert permitted.status_code == 200
    assert refused.status_code == 403
    assert refused.json["code"] == "NOT_ASSIGNED_COORDINATOR"
    assert saved == [EVENT_ID]


# Supporting design checks ----
# No SCRUM-10 AC describes a signed-in user whose User Service profile is
# missing; this checks the refusal rather than an error.

def test_update_details_when_user_has_no_profile_returns_403(monkeypatch):
    """
    Summary: PATCH /events/<id>/details with a coordinator token and a valid
        body is answered 403 NOT_ASSIGNED_COORDINATOR when User Service has no
        profile for the signed-in user.
    Supporting design check: a user whose profile cannot be found is refused,
        not treated as a server error
    Double: Stub (get_user raises UserNotFoundError; Supabase signing key via
        conftest); no other downstream client is reached
    """
    # Arrange (Given)
    def missing(user_id):
        raise clients.UserNotFoundError

    monkeypatch.setattr(clients, "get_user", missing)
    client = signed_in(create_app().test_client())

    # Act (When)
    response = client.patch(f"/events/{EVENT_ID}/details", json={"changes": {"eventName": "New"}})

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["code"] == "NOT_ASSIGNED_COORDINATOR"
