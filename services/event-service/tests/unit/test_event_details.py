"""
SCRUM-18: View Event Status

User Story
----------
As an Event Coordinator, I would like to be able to view the status (submitted,
approved, rejected) of an Event, so that I can understand the progress of an
Event and take subsequent actions if necessary.

Acceptance Criteria
-------------------
AC1: Event Coordinator should be able to view and filter his/her events and its
     status
AC2: Event Coordinator should be able to view the details of an Event and its
     status.

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
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.models import FIELDS
from tests.unit.factories import signed_in

VALID = {
    "eventName": "Community Workshop", "description": "A workshop", "purpose": "Learning",
    "preferredStartDate": "2026-10-01T09:00", "preferredEndDate": "2026-10-01T17:00",
    "expectedAttendance": "25",
}

EVENT_ID = "00000000-0000-0000-0000-000000000001"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OTHER_COORDINATOR_ID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client()), connection, cursor


def saved_row():
    row = {column: VALID.get(key, "") for key, column in FIELDS.items()}
    row.update(event_id=EVENT_ID, status="Submitted",
               submission_date=datetime(2026, 9, 15, 1, 30, tzinfo=UTC),
               preferred_start_date=datetime(2026, 10, 1, 9),
               preferred_end_date=datetime(2026, 10, 1, 17), expected_attendance=25,
               coordinator_id=None)
    row["description"] = json.dumps({"_connectsphere": "event-submission-v1",
                                     "description": VALID["description"], "purpose": VALID["purpose"]})
    return row


def test_event_details_returns_full_event_details_for_assigned_coordinator(setup):
    """
    Summary: Event details returns full event details for assigned coordinator.
    AC2: Event Coordinator should be able to view the details of an Event and
        its status.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    assigned = saved_row()
    assigned["coordinator_id"] = COORDINATOR_ID
    cursor.fetchone.return_value = assigned

    response = client.get(f"/events/{EVENT_ID}?coordinatorId={COORDINATOR_ID}")

    assert response.status_code == 200
    body = response.json
    for key in FIELDS:
        assert key in body
    assert body["id"] == EVENT_ID
    assert body["status"] == "Submitted"
    assert body["purpose"] == "Learning"
    assert body["description"] == "A workshop"
    assert body["submittedAt"] == "2026-09-15T01:30:00+00:00"
    assert body["coordinatorId"] == COORDINATOR_ID
    query, parameters = cursor.execute.call_args.args
    assert "SELECT event_id" in query
    assert 'FROM public."Event"' in query
    assert "FOR UPDATE" not in query
    assert parameters == [EVENT_ID]


def test_event_details_not_found_for_unknown_event(setup):
    """
    Summary: Event details not found for unknown event.
    AC2: Event Coordinator should be able to view the details of an Event and
        its status.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = None
    response = client.get(f"/events/{EVENT_ID}?coordinatorId={COORDINATOR_ID}")
    assert response.status_code == 404


def test_event_details_forbidden_when_not_assigned_to_caller(setup):
    """
    Summary: Event details forbidden when not assigned to caller.
    AC2: Event Coordinator should be able to view the details of an Event and
        its status.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    assigned = saved_row()
    assigned["coordinator_id"] = OTHER_COORDINATOR_ID
    cursor.fetchone.return_value = assigned

    response = client.get(f"/events/{EVENT_ID}?coordinatorId={COORDINATOR_ID}")

    assert response.status_code == 403


def test_event_details_forbidden_when_event_has_no_coordinator_assigned(setup):
    """
    Summary: Event details forbidden when event has no coordinator assigned.
    AC2: Event Coordinator should be able to view the details of an Event and
        its status.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = saved_row()

    response = client.get(f"/events/{EVENT_ID}?coordinatorId={COORDINATOR_ID}")

    assert response.status_code == 403


@pytest.mark.parametrize("query_string", ["", f"?coordinatorId={COORDINATOR_ID}"], ids=["empty", "f_coordinatorid_coordinator_id"])
def test_event_details_requires_a_signed_in_user(query_string, setup):
    """
    Summary: The viewer is the signed-in user; a query id alone grants nothing.
    SCRUM-8 AC1: Given a system user has not been successfully authenticated,
        when they attempt to access protected information or functionality,
        then access is denied.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    _, _, cursor = setup
    client = setup[0].application.test_client()

    # Act (When)
    response = client.get(f"/events/{EVENT_ID}{query_string}")

    # Assert (Then)
    assert response.status_code == 401
    cursor.execute.assert_not_called()


def test_event_details_lead_can_view_event_assigned_to_a_different_coordinator(setup):
    """
    Summary: Event details lead can view event assigned to a different coordinator.
    AC2: Event Coordinator should be able to view the details of an Event and
        its status.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    assigned = saved_row()
    assigned["coordinator_id"] = OTHER_COORDINATOR_ID
    cursor.fetchone.return_value = assigned

    response = client.get(f"/events/{EVENT_ID}?coordinatorId={COORDINATOR_ID}&viewerRole=Event+Coordinator+Lead")

    assert response.status_code == 200
    assert response.json["coordinatorId"] == OTHER_COORDINATOR_ID


def test_event_details_lead_can_view_unassigned_event(setup):
    """
    Summary: Event details lead can view unassigned event.
    AC2: Event Coordinator should be able to view the details of an Event and
        its status.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = saved_row()

    response = client.get(f"/events/{EVENT_ID}?coordinatorId={COORDINATOR_ID}&viewerRole=Event+Coordinator+Lead")

    assert response.status_code == 200


@pytest.mark.parametrize("role", ["Venue Staff", "Technical Support", "Safety Officer"])
def test_event_details_internal_operational_staff_can_view_any_event_read_only(role, setup):
    """
    Summary: Event details internal operational staff can view any event read only.
    AC2: Event Coordinator should be able to view the details of an Event and
        its status.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = saved_row()

    response = client.get(
        f"/events/{EVENT_ID}",
        query_string={"coordinatorId": COORDINATOR_ID, "viewerRole": role},
    )

    assert response.status_code == 200
    assert response.json["id"] == EVENT_ID


def test_event_details_unrecognised_role_cannot_request_internal_event_details(setup):
    """
    Summary: Event details unrecognised role cannot request internal event details.
    AC2: Event Coordinator should be able to view the details of an Event and
        its status.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    response = client.get(
        f"/events/{EVENT_ID}",
        query_string={"coordinatorId": COORDINATOR_ID, "viewerRole": "Attendee"},
    )
    assert response.status_code == 403
    cursor.execute.assert_not_called()


ORGANISER_ID = "33333333-3333-4333-8333-333333333333"
OTHER_ORGANISER_ID = "44444444-4444-4444-8444-444444444444"


def test_event_details_organiser_can_view_event_they_created(setup):
    """
    Summary: Organiser registration view: creator may open their event.
    AC2: Event Coordinator should be able to view the details of an Event and
        its status.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    row = saved_row()
    row.update(status="Approved", organiser_id=ORGANISER_ID)
    cursor.fetchone.return_value = row

    response = client.get(f"/events/{EVENT_ID}?organiserId={ORGANISER_ID}")

    assert response.status_code == 200
    assert response.json["organiserId"] == ORGANISER_ID


def test_event_details_organiser_cannot_view_event_they_did_not_create(setup):
    """
    Summary: Organiser registration view: non-creators are refused.
    AC2: Event Coordinator should be able to view the details of an Event and
        its status.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    row = saved_row()
    row.update(status="Approved", organiser_id=ORGANISER_ID)
    cursor.fetchone.return_value = row

    response = client.get(f"/events/{EVENT_ID}?organiserId={OTHER_ORGANISER_ID}")

    assert response.status_code == 403


def test_event_details_organiser_cannot_view_event_with_no_recorded_organiser(setup):
    """
    Summary: Event details organiser cannot view event with no recorded organiser.
    AC2: Event Coordinator should be able to view the details of an Event and
        its status.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    row = saved_row()
    row["organiser_id"] = None
    cursor.fetchone.return_value = row
    assert client.get(f"/events/{EVENT_ID}?organiserId={ORGANISER_ID}").status_code == 403


def test_event_details_organiser_event_not_found(setup):
    """
    Summary: Event details organiser event not found.
    AC2: Event Coordinator should be able to view the details of an Event and
        its status.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = None
    assert client.get(f"/events/{EVENT_ID}?organiserId={ORGANISER_ID}").status_code == 404


def test_event_details_retired_is_manager_flag_no_longer_opens_other_coordinators_events(setup):
    """
    Summary: Event details retired is manager flag no longer opens other coordinators events.
    AC2: Event Coordinator should be able to view the details of an Event and
        its status.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    assigned = saved_row()
    assigned["coordinator_id"] = OTHER_COORDINATOR_ID
    cursor.fetchone.return_value = assigned

    response = client.get(f"/events/{EVENT_ID}?coordinatorId={COORDINATOR_ID}&isManager=true")

    assert response.status_code == 403


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_event_details_missing_database_configuration():
    """
    Summary: Event details missing database configuration.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client())
    response = client.get(f"/events/{EVENT_ID}?coordinatorId={COORDINATOR_ID}")
    assert response.status_code == 503


def test_event_details_organiser_event_reports_missing_database_url(setup):
    """
    Summary: Event details organiser event reports missing database url.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None
    """
    client, _, _ = setup
    client.application.config["DATABASE_URL"] = None
    assert client.get(f"/events/{EVENT_ID}?organiserId={ORGANISER_ID}").status_code == 503
