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
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.models import FIELDS
from tests.unit.factories import signed_in

EVENT_ID = "00000000-0000-0000-0000-000000000001"
OTHER_EVENT_ID = "00000000-0000-0000-0000-000000000002"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OTHER_COORDINATOR_ID = "22222222-2222-4222-8222-222222222222"
ORGANISER_ID = "33333333-3333-4333-8333-333333333333"
OTHER_ORGANISER_ID = "44444444-4444-4444-8444-444444444444"
LEAD = "Event Coordinator Lead"


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), cursor


def event_row(event_id=EVENT_ID, coordinator_id=COORDINATOR_ID, **changes):
    row = {column: "" for column in FIELDS.values()}
    row.update(
        event_id=event_id, status="Under Review", coordinator_id=coordinator_id,
        organiser_id=ORGANISER_ID, expected_attendance=25,
        submission_date=datetime(2026, 9, 15, tzinfo=UTC),
        preferred_start_date=datetime(2030, 10, 1, 9), preferred_end_date=datetime(2030, 10, 1, 17),
        description=json.dumps({
            "_connectsphere": "event-submission-v1", "description": "d", "purpose": "p",
            "actionHistory": [{"note": "internal"}],
        }),
    )
    row.update(changes)
    return row


# AC1 ----

def test_ac1_coordinator_assigned_to_an_event_can_open_it(setup):
    """
    Summary: GET /events/<id> as the Event Coordinator the event is assigned to answers 200 with that event.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: Stub (cursor.fetchone returns an 'Under Review' event whose coordinator_id is this coordinator)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row()

    # Act (When)
    response = signed_in(client, COORDINATOR_ID, "Event Coordinator").get(f"/events/{EVENT_ID}")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["id"] == EVENT_ID


def test_ac1_lead_role_can_open_the_unassigned_queue(setup):
    """
    Summary: GET /events/unassigned as an Event Coordinator Lead answers 200 with the one unassigned event.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: Stub (cursor.fetchall returns one event with no coordinator)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = [event_row(coordinator_id=None)]

    # Act (When)
    response = signed_in(client, role=LEAD).get("/events/unassigned")

    # Assert (Then)
    assert response.status_code == 200
    assert len(response.json["events"]) == 1


def test_ac1_lead_can_open_an_event_assigned_to_a_different_coordinator(setup):
    """
    Summary: GET /events/<id> as an Event Coordinator Lead answers 200 for an event assigned to another coordinator.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: Stub (cursor.fetchone returns an event assigned to OTHER_COORDINATOR_ID)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=OTHER_COORDINATOR_ID)

    # Act (When)
    response = signed_in(client).get(f"/events/{EVENT_ID}?coordinatorId={COORDINATOR_ID}&viewerRole=Event+Coordinator+Lead")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["coordinatorId"] == OTHER_COORDINATOR_ID


def test_ac1_lead_can_open_an_event_nobody_is_assigned_to(setup):
    """
    Summary: GET /events/<id> as an Event Coordinator Lead answers 200 for an event with no coordinator. Overlaps the previous test: both only show the Lead's role opens any event.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: Stub (cursor.fetchone returns an event with no coordinator)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=None)

    # Act (When)
    response = signed_in(client).get(f"/events/{EVENT_ID}?coordinatorId={COORDINATOR_ID}&viewerRole=Event+Coordinator+Lead")

    # Assert (Then)
    assert response.status_code == 200


@pytest.mark.parametrize("role", ["Venue Staff", "Technical Support", "Safety Officer"])
def test_ac1_venue_staff_technical_support_and_safety_officer_can_open_any_event(role, setup):
    """
    Summary: GET /events/<id> as Venue Staff, Technical Support or a Safety Officer answers 200 with the event, whoever it is assigned to.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: Stub (cursor.fetchone returns an event assigned to another coordinator)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=None)

    # Act (When)
    response = signed_in(client).get(
        f"/events/{EVENT_ID}",
        query_string={"coordinatorId": COORDINATOR_ID, "viewerRole": role},
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["id"] == EVENT_ID


def test_ac1_organiser_can_open_an_event_they_created(setup):
    """
    Summary: GET /events/<id> as the Event Organiser who created the event answers 200 with that organiser's id on it.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: Stub (cursor.fetchone returns an 'Approved' event created by this organiser)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(status="Approved")

    # Act (When)
    response = signed_in(client).get(f"/events/{EVENT_ID}?organiserId={ORGANISER_ID}")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["organiserId"] == ORGANISER_ID


def test_ac1_organiser_lists_only_the_events_they_created_in_every_status(setup):
    """
    Summary: GET /events?organiserId=<id> returns that organiser's Approved and Rejected events, and the SQL filters on organiser_id = %s with no status condition other than excluding drafts.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: Stub (cursor.fetchall returns two events created by this organiser),
        Mock (cursor.execute SQL and parameters asserted: organiser_id = %s, [ORGANISER_ID])
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = [
        event_row(status="Approved"),
        event_row(OTHER_EVENT_ID, status="Rejected"),
    ]

    # Act (When)
    response = signed_in(client).get(f"/events?organiserId={ORGANISER_ID}")

    # Assert (Then)
    assert response.status_code == 200
    assert [e["status"] for e in response.json["events"]] == ["Approved", "Rejected"]
    assert response.json["events"][0]["organiserId"] == ORGANISER_ID
    query, params = cursor.execute.call_args.args
    # Every status except their drafts, which have their own list (drafts AC2).
    where = query.split("WHERE")[1]
    assert "organiser_id = %s" in where
    assert where.replace("status IS DISTINCT FROM 'Draft'", "").count("status") == 0
    assert params == [ORGANISER_ID]


def test_ac1_lead_lists_every_event_whatever_its_coordinator(setup):
    """
    Summary: GET /events as the Lead returns every non-draft event (assigned or not): the SQL has no coordinator_id filter and no parameters.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: Stub (cursor.fetchall returns one assigned and one unassigned event),
        Mock (cursor.execute SQL asserted: only the draft exclusion in WHERE; parameters [])
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = [event_row(), event_row(OTHER_EVENT_ID, coordinator_id=None)]

    # Act (When)
    response = signed_in(client).get(f"/events?coordinatorId={COORDINATOR_ID}&viewerRole=Event+Coordinator+Lead")

    # Assert (Then)
    assert response.status_code == 200
    assert len(response.json["events"]) == 2
    query, params = cursor.execute.call_args.args
    assert "coordinator_id = %s" not in query
    # The only condition is the draft exclusion (drafts AC1).
    assert "WHERE status IS DISTINCT FROM 'Draft'\n" in query
    assert params == []


def test_ac1_lead_listing_every_event_can_still_filter_by_status(setup):
    """
    Summary: GET /events as the Lead with status=Approved filters on status = %s with only 'Approved' as a parameter and no coordinator_id filter. Overlaps the staff test below, which makes the same assertions for other roles.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: Stub (cursor.fetchall returns no rows),
        Mock (cursor.execute SQL and parameters asserted: status = %s, ["Approved"])
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = []

    # Act (When)
    response = signed_in(client).get(f"/events?coordinatorId={COORDINATOR_ID}&viewerRole=Event+Coordinator+Lead&status=Approved")

    # Assert (Then)
    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert "coordinator_id = %s" not in query
    assert "status = %s" in query
    assert params == ["Approved"]


@pytest.mark.parametrize("role", ["Venue Staff", "Technical Support", "Safety Officer"])
def test_ac1_venue_staff_technical_support_and_safety_officer_list_every_event_with_the_status_filter(role, setup):
    """
    Summary: GET /events as Venue Staff, Technical Support or a Safety Officer with status=Approved filters on status = %s with only 'Approved' as a parameter and no coordinator_id filter.
    AC1: Given an authenticated user is permitted to view information based on
        their role and relationship to the event, when they access that
        information, then the information is made available to them.
    Double: Stub (cursor.fetchall returns one event),
        Mock (cursor.execute SQL and parameters asserted: status = %s, ["Approved"])
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = [event_row()]

    # Act (When)
    response = signed_in(client).get(
        "/events",
        query_string={"coordinatorId": COORDINATOR_ID, "viewerRole": role, "status": "Approved"},
    )

    # Assert (Then)
    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert "coordinator_id = %s" not in query
    assert "status = %s" in query
    assert params == ["Approved"]


# AC2 ----

@pytest.mark.parametrize(
    "path, role",
    [
        ("/events/unassigned", "Event Coordinator"),
        ("/events/active", "Attendee"),
        ("/events/registration", "Event Organiser"),
        ("/events/summaries", "Attendee"),
        ("/events/attendee-summaries", "Event Organiser"),
        ("/events/overlapping", "Attendee"),
    ],
)
def test_ac2_role_outside_the_allowed_roles_is_denied_on_each_role_gated_read(setup, path, role):
    """
    Summary: A role not allowed on the route (Coordinator on /events/unassigned, Attendee on /events/active, /events/summaries and /events/overlapping, Organiser on /events/registration and /events/attendee-summaries) gets 403 and no query is sent.
    AC2: Given an authenticated user's role does not permit them to view
        particular information, when they attempt to access that information,
        then access is denied.
    Double: Mock (cursor.execute asserted never called); no rows are stubbed because the role check refuses first
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = signed_in(client, role=role).get(path)

    # Assert (Then)
    assert response.status_code == 403
    cursor.execute.assert_not_called()


def test_ac2_attendee_cannot_ask_to_view_an_internal_event(setup):
    """
    Summary: GET /events/<id> asking for the Attendee view answers 403 and no query is sent.
    AC2: Given an authenticated user's role does not permit them to view
        particular information, when they attempt to access that information,
        then access is denied.
    Double: Mock (cursor.execute asserted never called); no rows are stubbed because the role check refuses first
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = signed_in(client).get(
        f"/events/{EVENT_ID}",
        query_string={"coordinatorId": COORDINATOR_ID, "viewerRole": "Attendee"},
    )

    # Assert (Then)
    assert response.status_code == 403
    cursor.execute.assert_not_called()


def test_ac2_attendee_cannot_list_every_internal_event(setup):
    """
    Summary: GET /events asking for the Attendee view answers 403 and no query is sent.
    AC2: Given an authenticated user's role does not permit them to view
        particular information, when they attempt to access that information,
        then access is denied.
    Double: Mock (cursor.execute asserted never called); no rows are stubbed because the role check refuses first
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = signed_in(client).get(
        "/events",
        query_string={"coordinatorId": COORDINATOR_ID, "viewerRole": "Attendee"},
    )

    # Assert (Then)
    assert response.status_code == 403
    cursor.execute.assert_not_called()


# AC3 ----

def test_ac3_coordinator_not_assigned_to_the_event_is_denied(setup):
    """
    Summary: GET /events/<id> as a coordinator whom the event is not assigned to answers 403.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to view that event's information, when they attempt to access the
        information, then access is denied.
    Double: Stub (cursor.fetchone returns an event assigned to OTHER_COORDINATOR_ID)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=OTHER_COORDINATOR_ID)

    # Act (When)
    response = signed_in(client, COORDINATOR_ID, "Event Coordinator").get(f"/events/{EVENT_ID}")

    # Assert (Then)
    assert response.status_code == 403


def test_ac3_organiser_cannot_open_an_event_created_by_someone_else(setup):
    """
    Summary: GET /events/<id> as an Event Organiser who did not create the event answers 403, even though the organiserId in the query names that organiser.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to view that event's information, when they attempt to access the
        information, then access is denied.
    Double: Stub (cursor.fetchone returns an event whose organiser_id is a different organiser)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row()

    # Act (When)
    response = signed_in(client, OTHER_ORGANISER_ID, "Event Organiser").get(
        f"/events/{EVENT_ID}?organiserId={OTHER_ORGANISER_ID}"
    )

    # Assert (Then)
    assert response.status_code == 403


def test_ac3_coordinator_cannot_open_an_event_nobody_is_assigned_to(setup):
    """
    Summary: GET /events/<id> as an Event Coordinator answers 403 for an event that has no coordinator.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to view that event's information, when they attempt to access the
        information, then access is denied.
    Double: Stub (cursor.fetchone returns an event with no coordinator)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=None)

    # Act (When)
    response = signed_in(client).get(f"/events/{EVENT_ID}?coordinatorId={COORDINATOR_ID}")

    # Assert (Then)
    assert response.status_code == 403


def test_ac3_organiser_cannot_open_an_event_with_no_recorded_organiser(setup):
    """
    Summary: GET /events/<id> as an Event Organiser answers 403 for an event whose organiser_id is empty.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to view that event's information, when they attempt to access the
        information, then access is denied.
    Double: Stub (cursor.fetchone returns an event with organiser_id None)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(organiser_id=None)

    # Act (When)
    response = signed_in(client).get(f"/events/{EVENT_ID}?organiserId={ORGANISER_ID}")

    # Assert (Then)
    assert response.status_code == 403


def test_ac3_retired_ismanager_flag_does_not_open_another_coordinators_event(setup):
    """
    Summary: GET /events/<id>?isManager=true as a coordinator still answers 403 for an event assigned to someone else, so the old flag grants nothing.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to view that event's information, when they attempt to access the
        information, then access is denied.
    Double: Stub (cursor.fetchone returns an event assigned to OTHER_COORDINATOR_ID)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=OTHER_COORDINATOR_ID)

    # Act (When)
    response = signed_in(client).get(f"/events/{EVENT_ID}?coordinatorId={COORDINATOR_ID}&isManager=true")

    # Assert (Then)
    assert response.status_code == 403


def test_ac3_retired_ismanager_flag_does_not_widen_a_coordinators_list(setup):
    """
    Summary: GET /events?isManager=true as a coordinator still filters on coordinator_id = %s with only that coordinator as a parameter.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to view that event's information, when they attempt to access the
        information, then access is denied.
    Double: Stub (cursor.fetchall returns no rows),
        Mock (cursor.execute SQL and parameters asserted: coordinator_id = %s, [COORDINATOR_ID])
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchall.return_value = []

    # Act (When)
    response = signed_in(client).get(f"/events?coordinatorId={COORDINATOR_ID}&isManager=true")

    # Assert (Then)
    assert response.status_code == 200
    query, params = cursor.execute.call_args.args
    assert "coordinator_id = %s" in query
    assert params == [COORDINATOR_ID]


# AC4 ----

def test_ac4_coordinator_gets_the_event_assigned_to_them_and_is_refused_the_other(setup):
    """
    Summary: The same coordinator asking for two events gets 200 for the one assigned to them and 403 for the one assigned to someone else.
    AC4: Given a user is permitted to view information for one event but does
        not have the required relationship to another event, when they attempt
        to view information for both events, then they can only view the
        information for which they have the required access.
    Double: Stub (cursor.fetchone returns, in turn, an event assigned to this coordinator and one assigned to another)
    """
    # Arrange (Given)
    client, cursor = setup
    coordinator = signed_in(client, COORDINATOR_ID, "Event Coordinator")
    cursor.fetchone.side_effect = [event_row(), event_row(OTHER_EVENT_ID, OTHER_COORDINATOR_ID)]

    allowed = coordinator.get(f"/events/{EVENT_ID}")

    # Act (When)
    refused = coordinator.get(f"/events/{OTHER_EVENT_ID}")

    # Assert (Then)
    assert (allowed.status_code, refused.status_code) == (200, 403)


# AC5 ----

def test_ac5_lead_sees_organiser_and_action_history_that_venue_staff_do_not(setup):
    """
    Summary: For the same event, the Lead's body includes organiserId and actionHistory, while Venue Staff's body has the event id but none of organiserId, actionHistory, decision or decisionHistory.
    AC5: Given two authenticated users have different roles or relationships to
        the same event, when they access information relating to that event,
        then each user can only view the information permitted by their own
        role and relationship to the event.
    Double: Stub (cursor.fetchone returns one event with an organiser and an action history; the Lead's and Venue Staff's response bodies are compared)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row()
    url = f"/events/{EVENT_ID}?viewerRole=1"

    lead = signed_in(client, role=LEAD).get(url).json

    # Act (When)
    staff = signed_in(client, role="Venue Staff").get(url).json

    # Assert (Then)
    assert lead["organiserId"] == ORGANISER_ID and lead["actionHistory"]
    assert staff["id"] == EVENT_ID
    for hidden in ("organiserId", "actionHistory", "decision", "decisionHistory"):
        assert hidden not in staff
