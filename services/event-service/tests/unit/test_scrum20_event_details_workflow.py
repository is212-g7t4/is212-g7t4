"""
SCRUM-20: Event Information Management & Impact Validation

User Story
----------
As the Event Coordinator assigned to an event, I want to update event
information during the planning process, so that event details remain up to
date without introducing conflicts with arrangements already made for the
event.

Acceptance Criteria
-------------------
AC1: Given a field being updated is one of the low-impact fields (Event Name,
     Description, Purpose, Registration Needs), when the assigned Event
     Coordinator saves the change, then the update is applied and the system
     records the new information.
AC2: Given a field being updated is one of the high-impact fields (Date/Time,
     Expected Attendance, Venue Requirements, Equipment Requirements,
     Accessibility Needs), when the assigned Event Coordinator attempts to save
     the change, then the system checks the update against other arrangements
     already made for the event (e.g. confirmed venue bookings, equipment
     reservations) for contradictions before the change is applied.
AC3: Given a high-impact update contradicts an existing arrangement, the update
     is blocked and the Coordinator is shown the reason.
AC4: Given a high-impact update passes validation with no contradiction found,
     then the update is applied and saved.

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
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
LEAD_ID = "22222222-2222-4222-8222-222222222222"
INTERNAL_TOKEN = "test-internal-token"
INTERNAL_HEADERS = {"X-Internal-Token": INTERNAL_TOKEN}


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app(
        {"TESTING": True, "DATABASE_URL": "unused", "INTERNAL_SERVICE_TOKEN": INTERNAL_TOKEN}
    )
    return signed_in(app.test_client()), cursor


def event_row(status="Approved", coordinator_id=COORDINATOR_ID):
    row = {column: "" for column in FIELDS.values()}
    row.update(
        event_id=EVENT_ID,
        event_name="Community Workshop",
        status=status,
        coordinator_id=coordinator_id,
        organiser_id=None,
        submission_date=datetime(2026, 10, 1, 8, tzinfo=UTC),
        preferred_start_date=datetime(2026, 11, 10, 9),
        preferred_end_date=datetime(2026, 11, 10, 12),
        expected_attendance=120,
        venue_requirements="Hall A",
        equipment_requirements="Two microphones",
        accessibility_needs="Step-free access",
        registration_needs="Name and email",
        description=json.dumps(
            {
                "_connectsphere": "event-submission-v1",
                "description": "A workshop for the community.",
                "purpose": "Skills sharing.",
            }
        ),
    )
    return row


def patch_details(client, changes, headers=None, **extra):
    body = {"coordinatorId": COORDINATOR_ID, "changes": changes, **extra}
    return client.patch(f"/events/{EVENT_ID}/details", json=body, headers=headers or {})


def test_ac2_a_dry_run_classifies_the_change_as_high_impact_without_writing(setup):
    """
    Summary: PATCH /events/<id>/details with dryRun true, changing expectedAttendance and eventName, answers 200 listing changedFields [eventName, expectedAttendance], highImpactFields [expectedAttendance], the two labels and the unchanged event (attendance "120"); only the lookup read ran.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (cursor.fetchone returns the 'Approved' event),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row()

    # Act (When)
    response = patch_details(
        client, {"expectedAttendance": "400", "eventName": "Renamed"}, dryRun=True
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["changedFields"] == ["eventName", "expectedAttendance"]
    assert response.json["highImpactFields"] == ["expectedAttendance"]
    assert response.json["labels"] == ["Event name", "Expected attendance"]
    assert response.json["event"]["expectedAttendance"] == "120"
    assert cursor.execute.call_count == 1


def test_ac2_a_dry_run_on_a_confirmed_event_reports_the_high_impact_field_instead_of_blocking(setup):
    """
    Summary: PATCH /events/<id>/details with dryRun true, changing expectedAttendance on a 'Confirmed' event, answers 200 with highImpactFields [expectedAttendance].
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (cursor.fetchone returns a 'Confirmed' event); the 200 status and highImpactFields are the only assertions
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(status="Confirmed")

    # Act (When)
    response = patch_details(client, {"expectedAttendance": "400"}, dryRun=True)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["highImpactFields"] == ["expectedAttendance"]


def test_ac2_a_dry_run_of_a_high_impact_change_is_refused_while_the_event_is_under_safety_review(setup):
    """
    Summary: PATCH /events/<id>/details with dryRun true, changing expectedAttendance on a 'Pending Safety Check' event, answers 409 EVENT_UNDER_SAFETY_REVIEW.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (cursor.fetchone returns a 'Pending Safety Check' event); the 409 status and code are the only assertions
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(status="Pending Safety Check")

    # Act (When)
    response = patch_details(client, {"expectedAttendance": "400"}, dryRun=True)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "EVENT_UNDER_SAFETY_REVIEW"


def test_ac2_a_dry_run_is_refused_for_a_coordinator_the_event_is_not_assigned_to(setup):
    """
    Summary: PATCH /events/<id>/details with dryRun true by the coordinator when the event is assigned to a different coordinator answers 403.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (cursor.fetchone returns an event assigned to another coordinator); the 403 status is the only assertion
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=LEAD_ID)

    # Act (When)
    response = patch_details(client, {"eventName": "Renamed"}, dryRun=True)

    # Assert (Then)
    assert response.status_code == 403


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_a_dry_run_flag_that_is_not_a_boolean_is_refused_before_any_query(setup):
    """
    Summary: PATCH /events/<id>/details with dryRun "yes" answers 400 and no query is sent.
    Supporting design check: the dryRun flag must be a real boolean
    Double: Mock (cursor.execute asserted never called)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = patch_details(client, {"eventName": "Renamed"}, dryRun="yes")

    # Assert (Then)
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_a_lead_acting_through_the_workflow_service_can_edit_an_event_with_no_assigned_coordinator(setup):
    """
    Summary: PATCH /events/<id>/details (a real edit, not a dry run) with the internal token and actorRole "Event Coordinator Lead" on an event with no coordinator answers 200.
    Supporting design check: when nobody is assigned, the Lead may edit on the
        workflow service's behalf
    Double: Stub (cursor.fetchone returns an event with no coordinator, then the updated event); the 200 status is the only assertion
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [event_row(coordinator_id=None), event_row()]

    # Act (When)
    response = patch_details(
        client,
        {"eventName": "Renamed"},
        headers=INTERNAL_HEADERS,
        coordinatorId=LEAD_ID,
        actorRole="Event Coordinator Lead",
    )

    # Assert (Then)
    assert response.status_code == 200


def test_a_lead_cannot_edit_an_event_assigned_to_another_coordinator_through_the_workflow_service(setup):
    """
    Summary: PATCH /events/<id>/details (a real edit) with the internal token and actorRole "Event Coordinator Lead" on an event assigned to a different coordinator answers 403.
    Supporting design check: the Lead's edit right applies only while no
        coordinator is assigned
    Double: Stub (cursor.fetchone returns an event assigned to another coordinator); the 403 status is the only assertion
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=COORDINATOR_ID)

    # Act (When)
    response = patch_details(
        client,
        {"eventName": "Renamed"},
        headers=INTERNAL_HEADERS,
        coordinatorId=LEAD_ID,
        actorRole="Event Coordinator Lead",
    )

    # Assert (Then)
    assert response.status_code == 403


def test_a_claimed_lead_role_is_ignored_when_the_internal_token_is_missing(setup):
    """
    Summary: PATCH /events/<id>/details with actorRole "Event Coordinator Lead" but no X-Internal-Token, on an event with no coordinator, answers 403, so the claimed role grants nothing.
    Supporting design check: only the workflow service (holding the internal
        token) may say the caller is the Lead
    Double: Stub (cursor.fetchone returns an event with no coordinator); the 403 status is the only assertion
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=None)

    # Act (When)
    response = patch_details(
        client, {"eventName": "Renamed"}, actorRole="Event Coordinator Lead"
    )

    # Assert (Then)
    assert response.status_code == 403


def test_an_actor_role_other_than_lead_does_not_bypass_the_assignment_check(setup):
    """
    Summary: PATCH /events/<id>/details with the internal token and actorRole "Event Coordinator" (not the Lead) on an event with no coordinator answers 403.
    Supporting design check: only the Lead role may edit an unassigned event
    Double: Stub (cursor.fetchone returns an event with no coordinator); the 403 status is the only assertion
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=None)

    # Act (When)
    response = patch_details(
        client,
        {"eventName": "Renamed"},
        headers=INTERNAL_HEADERS,
        actorRole="Event Coordinator",
    )

    # Assert (Then)
    assert response.status_code == 403
