"""SCRUM-9 Role-based viewing control for events: Safety Check unit tests.

Story:      As a registered user, I want to view only information appropriate to my
            role and relationship to an event, so that I can access the information
            relevant to my responsibilities without viewing restricted information.
Real:       Flask app, GET /safety-checks/feedback and /safety-checks/queue routes,
            token verification and role checks.
Doubled:    clients.get_event (Event Service answer) and the safety record lookups.
Not proven: Event Service's own coordinator rule (event-service tests).
            Modification of safety checks is not covered here (SCRUM-10).

AC1  Given an authenticated user is permitted to view information based on their role and
     relationship to the event, when they access that information, then the information
     is made available to them.
AC2  Given an authenticated user's role does not permit them to view particular information,
     when they attempt to access that information, then access is denied.
AC3  Given an authenticated user's relationship to an event does not permit them to view that
     event's information, when they attempt to access the information, then access is denied.
AC4  Given a user is permitted to view information for one event but does not have the
     required relationship to another event, when they attempt to view information for both
     events, then they can only view the information for which they have the required access.
AC5  Given two authenticated users have different roles or relationships to the same event,
     when they access information relating to that event, then each user can only view the
     information permitted by their own role and relationship to the event.
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
def test_ac1_coordinator_lead_and_safety_officer_can_read_feedback(client, monkeypatch, role):
    """Normal: the roles that handle safety feedback get it once Event Service allows them."""
    monkeypatch.setattr(clients, "get_event", lambda *a, **k: event("Safety Changes Requested"))

    response = feedback(client, role)

    assert response.status_code == 200
    assert response.json["safetyChecks"] == ROUNDS


# AC2 ----

@pytest.mark.parametrize("role", ["Attendee", "Venue Staff", "Technical Support", "Event Organiser"])
def test_ac2_other_roles_are_denied_without_asking_event_service(client, monkeypatch, role):
    """Failure: remarks and flags are not for these roles."""
    def fail(*args, **kwargs):
        raise AssertionError("Event Service must not be asked")
    monkeypatch.setattr(clients, "get_event", fail)

    assert feedback(client, role).status_code == 403


# AC3 ----

def test_ac3_coordinator_not_assigned_to_the_event_is_denied(client, monkeypatch):
    """Failure: Event Service refuses a coordinator who is not assigned."""
    def refuse(*args, **kwargs):
        raise clients.EventNotAssignedError
    monkeypatch.setattr(clients, "get_event", refuse)

    assert feedback(client, "Event Coordinator").status_code == 403


# AC4 ----

def test_ac4_coordinator_reads_only_the_event_they_are_assigned_to(client, monkeypatch):
    """Conflict: asking for two events returns one list and one refusal."""
    def get_event(event_id, viewer_role=None):
        if event_id != EVENT_ID:
            raise clients.EventNotAssignedError
        return event("Safety Changes Requested")
    monkeypatch.setattr(clients, "get_event", get_event)

    assert feedback(client, "Event Coordinator").status_code == 200
    assert feedback(client, "Event Coordinator", OTHER_EVENT_ID).status_code == 403


# AC5 ----

def test_ac5_lead_reads_an_event_a_coordinator_is_not_assigned_to(client, monkeypatch):
    """Conflict: same event, the Lead asks as 'any event' and is allowed; the coordinator is not."""
    def get_event(event_id, viewer_role=None):
        if viewer_role is None:
            raise clients.EventNotAssignedError
        return event("Safety Changes Requested")
    monkeypatch.setattr(clients, "get_event", get_event)

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
)
def test_lead_lookup_failures_are_reported_without_disclosing_feedback(client, monkeypatch, error, status):
    """Failure: nothing is returned if Event Service cannot confirm access."""
    def broken(*args, **kwargs):
        raise error
    monkeypatch.setattr(clients, "get_event", broken)

    assert feedback(client, "Safety Officer").status_code == status
