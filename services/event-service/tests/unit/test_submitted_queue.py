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

This file covers AC1 only, the list. AC2 and AC3 (assigning and reassigning) are
in test_coordinator_assignment.py and test_coordinator_reassignment.py.

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


def test_submitted_queue_for_a_coordinator_is_limited_to_the_events_assigned_to_them(setup):
    """
    Summary: GET /events/submitted?coordinatorId=<id> as a coordinator answers 200 with an empty list when none of their events are submitted, and the SQL filters on coordinator_id = %s with that id as the only parameter.
    Supporting design check: a coordinator's own submitted queue is the
        narrower case of AC1's list; only the Lead's unfiltered view is
        described by the story
    Double: Stub (cursor.fetchall returns no rows),
        Mock (cursor.execute SQL and parameters asserted: coordinator_id = %s, [OTHER_COORDINATOR_ID])
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


def test_ac1_lead_sees_every_submitted_request_even_when_a_coordinator_id_is_sent(setup):
    """
    Summary: GET /events/submitted with viewerRole=Event Coordinator Lead and a coordinatorId answers 200 with the submitted event, and the SQL has no coordinator_id filter and no parameters.
    AC1: Given an event request has status 'Submitted', when the Event
        Coordinator Manager views the list of submitted events, then the system
        displays each event with its name, Event Organiser name, proposed date,
        and current assignment status (Unassigned/Assigned).
    Double: Stub (cursor.fetchall returns one saved_row() in status 'Submitted'),
        Mock (cursor.execute SQL asserted to lack coordinator_id = %s; parameters asserted to be [])
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


def test_submitted_queue_returns_an_empty_list_when_no_submitted_events_match(setup):
    """
    Summary: GET /events/submitted?coordinatorId=<id> returns {"events": []} when the database has no rows. REDUNDANT: the coordinator-limited test above stubs no rows and asserts the same body for the same request.
    Supporting design check: an empty queue is an empty list, not an error
    Double: Stub (cursor.fetchall returns no rows)
    """
    # Arrange (Given)
    setup[2].fetchall.return_value = []

    # Act (When)
    response = setup[0].get(f"/events/submitted?coordinatorId={OTHER_COORDINATOR_ID}")

    # Assert (Then)
    assert response.json == {"events": []}


def test_submitted_queue_ignores_the_retired_ismanager_flag(setup):
    """
    Summary: GET /events/submitted?coordinatorId=<id>&isManager=true still answers 200 with the coordinator filter in the SQL (coordinator_id = %s with that id), so the old flag cannot widen the queue.
    Supporting design check: a retired query flag must not widen who sees the
        submitted queue
    Double: Stub (cursor.fetchall returns no rows),
        Mock (cursor.execute SQL and parameters asserted: coordinator_id = %s, [OTHER_COORDINATOR_ID])
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
def test_ac1_only_the_lead_can_view_every_submitted_request(role, setup):
    """
    Summary: GET /events/submitted asking to view every request (viewerRole) as Venue Staff, an Event Coordinator or an Attendee answers 403 and no query is sent.
    AC1: Given an event request has status 'Submitted', when the Event
        Coordinator Manager views the list of submitted events, then the system
        displays each event with its name, Event Organiser name, proposed date,
        and current assignment status (Unassigned/Assigned).
    Double: Mock (cursor.execute asserted never called); no rows are stubbed because the role check refuses first
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
