"""
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
- GET /safety-checks/feedback: the role check and the per-role question to
  Event Service about the caller's relationship to the event.
- Assertions are on the status and what is returned.

Doubled
-------
- Event, Safety Check Record, Venue Availability, Venue, Equipment Request,
  Equipment and User Services: Stub (monkeypatched app.clients functions) -
  canned answers or raised client errors; calls recorded so tests assert the
  order and what was (or was not) called.

Not proven
----------
- Event Service's own relationship rules (-> event-service unit tests for
  SCRUM-9).
"""
import pytest

from app import clients, create_app
from tests.unit.factories import EVENT_ID, OFFICER_ID, bearer, event

OTHER_EVENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ROUNDS = [{"roundNumber": 1, "status": "Changes Requested"}]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(clients, "list_safety_check_records", lambda *a, **k: ROUNDS)
    return create_app().test_client()


def feedback(client, role, event_id=EVENT_ID):
    return client.get(f"/safety-checks/feedback?eventId={event_id}", headers=bearer(OFFICER_ID, role))


# AC1 ----

@pytest.mark.parametrize("role", ["Event Coordinator", "Event Coordinator Lead", "Safety Officer"])
def test_feedback_when_safety_role_reads_it(client, monkeypatch, role):
    """
    Summary: Coordinators, the Lead and Safety Officers can read safety feedback.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: Stub (Event Service and rounds)
    """
    # Arrange (Given)
    monkeypatch.setattr(clients, "get_event", lambda *a, **k: event("Safety Changes Requested"))

    # Act (When)
    response = feedback(client, role)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["safetyChecks"] == ROUNDS


# AC2 ----

@pytest.mark.parametrize("role", ["Attendee", "Venue Staff", "Technical Support", "Event Organiser"])
def test_feedback_when_other_role_returns_403(client, monkeypatch, role):
    """
    Summary: Other roles are refused without asking Event Service.
    AC2: Given an authenticated user's role does not permit them to view
        particular information, when they attempt to access that information,
        then access is denied.
    Double: Mock (Event Service not asked)
    """
    # Arrange (Given)
    def fail(*args, **kwargs):
        raise AssertionError("Event Service must not be asked")
    monkeypatch.setattr(clients, "get_event", fail)

    # Act + Assert (When / Then)
    assert feedback(client, role).status_code == 403


# AC3 ----

def test_feedback_when_coordinator_not_assigned_returns_403(client, monkeypatch):
    """
    Summary: A coordinator not assigned to the event is refused.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to view that event's information, when they attempt to access the
        information, then access is denied.
    Double: Stub (Event Service and rounds)
    """
    # Arrange (Given)
    def refuse(*args, **kwargs):
        raise clients.EventNotAssignedError
    monkeypatch.setattr(clients, "get_event", refuse)

    # Act + Assert (When / Then)
    assert feedback(client, "Event Coordinator").status_code == 403


# AC4 ----

def test_feedback_for_two_events_returns_only_assigned_one(client, monkeypatch):
    """
    Summary: Asking for two events gives feedback for the assigned one only.
    AC4: Given a user is permitted to view information for one event but does
        not have the required relationship to another event, when they attempt
        to view information for both events, then they can only view the
        information for which they have the required access.
    Double: Stub (Event Service and rounds)
    """
    # Arrange (Given)
    def get_event(event_id, viewer_role=None):
        if event_id != EVENT_ID:
            raise clients.EventNotAssignedError
        return event("Safety Changes Requested")
    monkeypatch.setattr(clients, "get_event", get_event)

    # Act + Assert (When / Then)
    assert feedback(client, "Event Coordinator").status_code == 200
    assert feedback(client, "Event Coordinator", OTHER_EVENT_ID).status_code == 403


# AC5 ----

def test_feedback_same_event_lead_can_read_coordinator_cannot(client, monkeypatch):
    """
    Summary: For the same event, the Lead can read what an unassigned coordinator cannot.
    AC5: Given two authenticated users have different roles or relationships to
        the same event, when they access information relating to that event,
        then each user can only view the information permitted by their own
        role and relationship to the event.
    Double: Stub (Event Service and rounds)
    """
    # Arrange (Given)
    def get_event(event_id, viewer_role=None):
        if viewer_role is None:
            raise clients.EventNotAssignedError
        return event("Safety Changes Requested")
    monkeypatch.setattr(clients, "get_event", get_event)

    # Act + Assert (When / Then)
    assert feedback(client, "Event Coordinator Lead").status_code == 200
    assert feedback(client, "Event Coordinator").status_code == 403


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (clients.EventNotFoundError(), 404),
        (clients.EventNotAssignedError(), 403),
        (clients.DownstreamTimeout(), 504),
        (clients.DownstreamError(), 502),
    ],
    ids=["clients_eventnotfounderror_404", "clients_eventnotassignederror_403", "clients_downstreamtimeout_504", "clients_downstreamerror_502"],
)
def test_feedback_when_lead_lookup_fails_discloses_nothing(client, monkeypatch, error, status):
    """
    Summary: If Event Service cannot answer, no feedback is disclosed.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to view that event's information, when they attempt to access the
        information, then access is denied.
    Double: Stub (Event Service and rounds)
    """
    # Arrange (Given)
    def broken(*args, **kwargs):
        raise error
    monkeypatch.setattr(clients, "get_event", broken)

    # Act + Assert (When / Then)
    assert feedback(client, "Safety Officer").status_code == status
