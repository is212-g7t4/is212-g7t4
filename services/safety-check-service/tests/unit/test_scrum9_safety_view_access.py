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
- Who may see safety information: the safety feedback is for the event's
  assigned coordinator, the Lead and Safety Officers; the safety check queue
  and an event's safety review are for Safety Officers only.
- We check who gets the information, who is refused, and that refusals disclose
  nothing.

Doubled
-------
- Event, Safety Check Record, Venue Availability, Venue, Equipment Request and
  User Services: answer as each test needs, fail, or do not answer in time
  [Stub]; we check which were asked, in what order, and what they were sent
  [Mock].
- Sign-in: a test key signs the caller's token (tests/conftest.py) [Stub].

Not proven
----------
- That Event Service judges each coordinator's assignment correctly (->
  event-service SCRUM-9 tests).
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
    Double: Event Service holds the event, and Safety Check Record its rounds
        [Stub].
    """
    monkeypatch.setattr(clients, "get_event", lambda *a, **k: event("Safety Changes Requested"))

    response = feedback(client, role)

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
    Double: We check Event Service is not asked [Mock].
    """
    def fail(*args, **kwargs):
        raise AssertionError("Event Service must not be asked")
    monkeypatch.setattr(clients, "get_event", fail)

    assert feedback(client, role).status_code == 403


# AC3 ----

def test_feedback_when_coordinator_not_assigned_returns_403(client, monkeypatch):
    """
    Summary: A coordinator not assigned to the event is refused.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to view that event's information, when they attempt to access the
        information, then access is denied.
    Double: Event Service holds the event, and Safety Check Record its rounds
        [Stub].
    """
    def refuse(*args, **kwargs):
        raise clients.EventNotAssignedError
    monkeypatch.setattr(clients, "get_event", refuse)

    assert feedback(client, "Event Coordinator").status_code == 403


# AC4 ----

def test_feedback_for_two_events_returns_only_assigned_one(client, monkeypatch):
    """
    Summary: Asking for two events gives feedback for the assigned one only.
    AC4: Given a user is permitted to view information for one event but does
        not have the required relationship to another event, when they attempt
        to view information for both events, then they can only view the
        information for which they have the required access.
    Double: Event Service holds the event, and Safety Check Record its rounds
        [Stub].
    """
    def get_event(event_id, viewer_role=None):
        if event_id != EVENT_ID:
            raise clients.EventNotAssignedError
        return event("Safety Changes Requested")
    monkeypatch.setattr(clients, "get_event", get_event)

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
    Double: Event Service holds the event, and Safety Check Record its rounds
        [Stub].
    """
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
    ids=["clients_eventnotfounderror_404", "clients_eventnotassignederror_403", "clients_downstreamtimeout_504", "clients_downstreamerror_502"],
)
def test_feedback_when_lead_lookup_fails_discloses_nothing(client, monkeypatch, error, status):
    """
    Summary: If Event Service cannot answer, no feedback is disclosed.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to view that event's information, when they attempt to access the
        information, then access is denied.
    Double: Event Service holds the event, and Safety Check Record its rounds
        [Stub].
    """
    def broken(*args, **kwargs):
        raise error
    monkeypatch.setattr(clients, "get_event", broken)

    assert feedback(client, "Safety Officer").status_code == status


@pytest.mark.parametrize("path", ["/safety-checks/queue", f"/safety-checks/{EVENT_ID}/review"], ids=["queue", "review"])
@pytest.mark.parametrize("role", ["Event Coordinator", "Venue Staff", "Event Organiser"])
def test_safety_officer_pages_when_other_role_return_403(path, role, sent):
    """
    Summary: Only a Safety Officer can open the safety check queue or an event's safety review; nothing is looked up for anyone else.
    AC2: Given an authenticated user's role does not permit them to view
        particular information, when they attempt to access that information,
        then access is denied.
    Double: We check no other service is contacted [Mock].
    """
    calls, _ = sent
    client = create_app().test_client()

    response = client.get(path, headers=bearer(OFFICER_ID, role))

    assert response.status_code == 403
    assert response.get_json()["code"] == "NOT_SAFETY_OFFICER"
    assert calls == []
