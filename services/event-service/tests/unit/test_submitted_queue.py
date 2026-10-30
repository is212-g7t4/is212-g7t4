"""
SCRUM-112: Assign Event Coordinator to Submitted Event

User Story
----------
As an Event Coordinator Manager, I want to assign an Event Coordinator to a
submitted event, so that the event has a main internal point of contact
responsible for coordinating it.

Acceptance Criteria
-------------------
AC1: Given an event request has status 'Submitted', when the Event Coordinator
     Manager views the list of submitted events, then the system displays each
     event with its name, Event Organiser name, proposed date, and current
     assignment status (Unassigned/Assigned).
AC2: Given an event request has status 'Submitted' and is unassigned, when the
     Event Coordinator Manager selects an Event Coordinator from the list of
     available coordinators and confirms the assignment, then the system:
     - Assigns the selected Event Coordinator to the event
     - Changes the event's assignment status to 'Assigned'
     - Records the Event Coordinator Manager's identity, the assigned Event
       Coordinator, and the assignment timestamp
AC3: Given an event request already has an assigned Event Coordinator, when the
     Event Coordinator Manager selects a different Event Coordinator and
     confirms the reassignment, then the system:
     - Replaces the existing Event Coordinator with the newly selected one
     - Updates the event's assignment to reflect the new Event Coordinator

SCRUM-11: Event Submission Form

User Story
----------
As an Event Organiser, I want to enter my event's details into a structured
form and submit it for review, so that the Event Coordinator can evaluate it.

Acceptance Criteria
-------------------
AC1: The form contains: Event Name (required), Description (required), Purpose
     (required), Preferred Date(s) and Time (required), Expected Attendance
     (required), Venue Requirements (optional), Accessibility Needs (optional),
     Equipment Requirements (optional), Registration Needs (optional).
AC2: Given all required fields (Event Name, Description, Purpose, Preferred
     Date(s) and Time, Expected Attendance) are filled in, when the Event
     Organiser submits, then the status changes to 'Submitted', the submission
     date is recorded, and it appears in the queue of submitted requests
     visible to Event Coordinators.
AC3: Given the submission succeeds, the Event Organiser receives a confirmation
     popup in ConnectSphere referencing the event name and submission date.
AC4: Given one or more required fields are missing, when the Event Organiser
     attempts to submit, then submission is blocked and a pop-up is shown,
     listing exactly which fields are missing.

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
- The Event Service routes in app/__init__.py and the rules in app/models.py,
  run through a real create_app(): request validation, the caller's role and
  ownership checks from the signed token, the status rules, and the SQL and
  parameters sent to the database (including notification outbox rows).
- Assertions are on the HTTP status, the response body and the queries and
  parameters the cursor received.

Doubled
-------
- psycopg2.connect: Stub (fixture) - a MagicMock connection whose cursor
  returns canned rows; Mock - its execute calls are asserted to prove what was
  (or was not) written.
- Supabase JWKS: Stub (tests/conftest.py) - tokens are signed with a throwaway
  ES256 key.

Not proven
----------
- That the SQL runs against the real Postgres schema, constraints and row locks
  (-> tests/integration/ against a throwaway postgres:17.6).
- That the notification outbox rows are delivered (-> Notification Service
  tests and the E2E journeys).
"""

import pytest

from tests.unit.factories import OTHER_COORDINATOR_ID, saved_row


def test_submitted_queue_requires_a_signed_in_coordinator(setup):
    """
    Summary: The submitted queue is only shown to a signed-in caller.
    SCRUM-8 AC1: Given a system user has not been successfully authenticated,
        when they attempt to access protected information or functionality,
        then access is denied.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    _, _, cursor = setup
    client = setup[0].application.test_client()

    # Act (When)
    response = client.get("/events/submitted")

    # Assert (Then)
    assert response.status_code == 401
    cursor.execute.assert_not_called()


def test_submitted_queue_filters_to_the_coordinator(setup):
    """
    Summary: A coordinator's submitted queue lists only their events.
    SCRUM-11 AC2: Given all required fields (Event Name, Description, Purpose,
        Preferred Date(s) and Time, Expected Attendance) are filled in, when
        the Event Organiser submits, then the status changes to 'Submitted',
        the submission date is recorded, and it appears in the queue of
        submitted requests visible to Event Coordinators.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchall.return_value = []

    # Act (When)
    response = client.get(f"/events/submitted?coordinatorId={OTHER_COORDINATOR_ID}")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json == {"events": []}
    query, params = cursor.execute.call_args.args
    assert "coordinator_id = %s" in query
    assert params == [OTHER_COORDINATOR_ID]


def test_submitted_queue_manager_sees_all_even_with_coordinator_id(setup):
    """
    Summary: The Lead sees every submitted request.
    AC1: Given an event request has status 'Submitted', when the Event
        Coordinator Manager views the list of submitted events, then the system
        displays each event with its name, Event Organiser name, proposed date,
        and current assignment status (Unassigned/Assigned).
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchall.return_value = [saved_row()]

    # Act (When)
    response = client.get(
        f"/events/submitted?coordinatorId={OTHER_COORDINATOR_ID}&viewerRole=Event+Coordinator+Lead"
    )

    # Assert (Then)
    assert response.status_code == 200
    assert len(response.json["events"]) == 1
    query, params = cursor.execute.call_args.args
    assert "coordinator_id = %s" not in query
    assert params == []


def test_empty_queue(setup):
    """
    Summary: An empty submitted queue returns an empty list.
    SCRUM-11 AC2: Given all required fields (Event Name, Description, Purpose,
        Preferred Date(s) and Time, Expected Attendance) are filled in, when
        the Event Organiser submits, then the status changes to 'Submitted',
        the submission date is recorded, and it appears in the queue of
        submitted requests visible to Event Coordinators.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    setup[2].fetchall.return_value = []

    # Act (When)
    response = setup[0].get(f"/events/submitted?coordinatorId={OTHER_COORDINATOR_ID}")

    # Assert (Then)
    assert response.json == {"events": []}


def test_submitted_queue_ignores_the_retired_is_manager_flag(setup):
    """
    Summary: A retired manager flag no longer widens the submitted queue.
    AC1: Given an event request has status 'Submitted', when the Event
        Coordinator Manager views the list of submitted events, then the system
        displays each event with its name, Event Organiser name, proposed date,
        and current assignment status (Unassigned/Assigned).
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchall.return_value = []

    # Act (When)
    response = client.get(
        f"/events/submitted?coordinatorId={OTHER_COORDINATOR_ID}&isManager=true"
    )

    # Assert (Then)
    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert "coordinator_id = %s" in query
    assert params == [OTHER_COORDINATOR_ID]


@pytest.mark.parametrize("role", ["Venue Staff", "Event Coordinator", "Attendee"])
def test_only_the_lead_can_view_every_submitted_request(role, setup):
    """
    Summary: Only the Lead sees every submitted request.
    AC1: Given an event request has status 'Submitted', when the Event
        Coordinator Manager views the list of submitted events, then the system
        displays each event with its name, Event Organiser name, proposed date,
        and current assignment status (Unassigned/Assigned).
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = client.get(
        "/events/submitted",
        query_string={"coordinatorId": OTHER_COORDINATOR_ID, "viewerRole": role},
    )

    # Assert (Then)
    assert response.status_code == 403
    cursor.execute.assert_not_called()
