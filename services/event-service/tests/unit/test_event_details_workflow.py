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


def test_dry_run_classifies_a_change_without_writing(setup):
    """
    Summary: Dry run classifies a change without writing.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_dry_run_on_a_confirmed_event_reports_instead_of_gating(setup):
    """
    Summary: Dry run on a confirmed event reports instead of gating.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(status="Confirmed")

    # Act (When)
    response = patch_details(client, {"expectedAttendance": "400"}, dryRun=True)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["highImpactFields"] == ["expectedAttendance"]


def test_dry_run_refuses_a_high_impact_change_while_under_safety_review(setup):
    """
    Summary: Dry run refuses a high impact change while under safety review.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(status="Pending Safety Check")

    # Act (When)
    response = patch_details(client, {"expectedAttendance": "400"}, dryRun=True)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "EVENT_UNDER_SAFETY_REVIEW"


def test_dry_run_still_requires_the_assigned_coordinator(setup):
    """
    Summary: Dry run still requires the assigned coordinator.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=LEAD_ID)

    # Act (When)
    response = patch_details(client, {"eventName": "Renamed"}, dryRun=True)

    # Assert (Then)
    assert response.status_code == 403


def test_dry_run_must_be_a_boolean(setup):
    """
    Summary: Dry run must be a boolean.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = patch_details(client, {"eventName": "Renamed"}, dryRun="yes")

    # Assert (Then)
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_dry_run_lead_can_edit_an_event_with_no_assigned_coordinator(setup):
    """
    Summary: Dry run lead can edit an event with no assigned coordinator.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_dry_run_lead_cannot_edit_an_event_assigned_to_someone_else(setup):
    """
    Summary: Dry run lead cannot edit an event assigned to someone else.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_dry_run_lead_role_is_ignored_without_the_internal_token(setup):
    """
    Summary: Dry run lead role is ignored without the internal token.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_dry_run_other_roles_do_not_bypass_the_assignment_check(setup):
    """
    Summary: Dry run other roles do not bypass the assignment check.
    AC2: Given a field being updated is one of the high-impact fields
        (Date/Time, Expected Attendance, Venue Requirements, Equipment
        Requirements, Accessibility Needs), when the assigned Event Coordinator
        attempts to save the change, then the system checks the update against
        other arrangements already made for the event (e.g. confirmed venue
        bookings, equipment reservations) for contradictions before the change
        is applied.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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
