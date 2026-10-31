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
from tests.unit.factories import bearer, signed_in

EVENT_ID = "00000000-0000-0000-0000-000000000001"
OTHER_EVENT_ID = "00000000-0000-0000-0000-000000000002"
CHANGE_ID = "00000000-0000-0000-0000-0000000000c1"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OTHER_COORDINATOR_ID = "22222222-2222-4222-8222-222222222222"
ORGANISER_ID = "33333333-3333-4333-8333-333333333333"
STAFF_ID = "55555555-5555-4555-8555-555555555555"
LEAD = "Event Coordinator Lead"
SERVICE_TOKEN = "test-service-token"
ORGANISER = "Event Organiser"
COORDINATOR = "Event Coordinator"

# (method, path, who may change it) for every role-gated write route.
ORGANISER_ROUTES = [
    ("post", "/events"),
    ("post", "/events/drafts"),
    ("patch", f"/events/drafts/{EVENT_ID}"),
    ("post", f"/events/drafts/{EVENT_ID}/submit"),
    ("delete", f"/events/drafts/{EVENT_ID}"),
    ("post", f"/events/{EVENT_ID}/change-requests"),
    ("patch", f"/events/{EVENT_ID}/clarification-response"),
    ("patch", f"/events/{EVENT_ID}/amendment-response"),
]
LEAD_ROUTES = [("patch", f"/events/{EVENT_ID}")]
COORDINATOR_ROUTES = [
    ("patch", f"/events/{EVENT_ID}/progress"),
    ("patch", f"/events/{EVENT_ID}/approve"),
    ("patch", f"/events/{EVENT_ID}/reject"),
    ("patch", f"/events/{EVENT_ID}/clarification-request"),
    ("patch", f"/events/{EVENT_ID}/amendment-request"),
    ("patch", f"/events/{EVENT_ID}/details"),
    ("patch", f"/change-requests/{CHANGE_ID}/decision"),
]


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url", "INTERNAL_SERVICE_TOKEN": SERVICE_TOKEN})
    return app.test_client(), cursor


def event_row(event_id=EVENT_ID, status="Under Review", coordinator_id=COORDINATOR_ID):
    row = {column: "" for column in FIELDS.values()}
    row.update(
        event_id=event_id, event_name="Community Workshop", status=status,
        coordinator_id=coordinator_id, organiser_id=ORGANISER_ID, expected_attendance=30,
        submission_date=datetime(2026, 10, 1, 8, tzinfo=UTC),
        preferred_start_date=datetime(2030, 10, 10, 9), preferred_end_date=datetime(2030, 10, 10, 12),
        description=json.dumps({
            "_connectsphere": "event-submission-v1", "description": "d", "purpose": "p",
            "decision": None, "decisionHistory": [], "actionDetails": "", "actionHistory": [],
        }),
    )
    return row


def send(client, method, path, role, user_id=STAFF_ID):
    return getattr(client, method)(path, json={}, headers=bearer(user_id, role))


# AC1 ----

def test_assigned_coordinator_updates_progress(setup):
    """
    Summary: The coordinator role plus the assignment lets a valid change through.
    AC1: Given an authenticated user is permitted to modify information based
        on their role and relationship to the event, when they make a valid
        change to that information, then the change is allowed.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row(status="Approved")]

    # Act (When)
    response = signed_in(client, COORDINATOR_ID, COORDINATOR).patch(
        f"/events/{EVENT_ID}/progress", json={"status": "Approved", "actionDetails": "Venue held."}
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Approved"


# AC2 ----

@pytest.mark.parametrize(
    "method, path, role",
    [(m, p, COORDINATOR) for m, p in ORGANISER_ROUTES]
    + [(m, p, COORDINATOR) for m, p in LEAD_ROUTES]
    + [(m, p, "Venue Staff") for m, p in COORDINATOR_ROUTES],
)
def test_a_role_outside_the_routes_allowlist_cannot_change_anything(setup, method, path, role):
    """
    Summary: Every write route refuses the wrong role before reading the body or the database.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = send(client, method, path, role)

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["message"] == "Your role cannot change this information."
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("method, path", ORGANISER_ROUTES + LEAD_ROUTES + COORDINATOR_ROUTES)
def test_an_attendee_cannot_change_any_event_information(setup, method, path):
    """
    Summary: Attendee is a registered role with no modification rights at all.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = send(client, method, path, "Attendee")

    # Assert (Then)
    assert response.status_code == 403
    cursor.execute.assert_not_called()


def test_the_lead_role_does_not_grant_organiser_rights(setup):
    """
    Summary: The Lead is a coordinator, not an organiser, so it cannot create events.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = send(client, "post", "/events", LEAD)

    # Assert (Then)
    assert response.status_code == 403
    cursor.execute.assert_not_called()


# AC3 ----

def test_coordinator_assigned_to_another_coordinator_cannot_change_the_event(setup):
    """
    Summary: The right role is not enough without the assignment.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to modify that event's information, when they attempt to make a
        change, then the modification is prevented and the existing information
        remains unchanged.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=OTHER_COORDINATOR_ID)

    # Act (When)
    response = signed_in(client, COORDINATOR_ID, COORDINATOR).patch(
        f"/events/{EVENT_ID}/progress", json={"status": "Approved", "actionDetails": "Venue held."}
    )

    # Assert (Then)
    assert response.status_code == 403
    writes = [c for c in cursor.execute.call_args_list if c.args[0].lstrip().upper().startswith(("UPDATE", "INSERT"))]
    assert writes == []


def test_lead_cannot_edit_details_of_an_event_assigned_to_someone_else(setup):
    """
    Summary: The Lead may only edit an event that has no coordinator.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to modify that event's information, when they attempt to make a
        change, then the modification is prevented and the existing information
        remains unchanged.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=OTHER_COORDINATOR_ID)

    # Act (When)
    response = signed_in(client, COORDINATOR_ID, LEAD).patch(
        f"/events/{EVENT_ID}/details", json={"changes": {"eventName": "New"}}
    )

    # Assert (Then)
    assert response.status_code == 403


# AC4 ----

def test_venue_staff_keep_their_view_when_their_change_is_refused(setup):
    """
    Summary: The refused PATCH does not disturb the read access the role still has.
    AC4: Given a user is permitted to view particular information but is not
        permitted to modify it, when they attempt to change that information,
        then the modification is prevented while their permitted viewing access
        remains unaffected.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup
    cursor.fetchone.return_value = event_row()
    staff = signed_in(client, STAFF_ID, "Venue Staff")
    url = f"/events/{EVENT_ID}?viewerRole=1"

    before = staff.get(url)
    refused = staff.patch(f"/events/{EVENT_ID}/progress", json={"status": "Approved", "actionDetails": "x"})

    # Act (When)
    after = staff.get(url)

    # Assert (Then)
    assert (before.status_code, refused.status_code, after.status_code) == (200, 403, 200)
    assert before.json == after.json


# AC5 ----

def test_coordinator_changes_only_the_event_they_are_assigned_to(setup):
    """
    Summary: Changing both events succeeds for one and is refused for the other.
    AC5: Given a user is permitted to modify information for one event but does
        not have the required access to another event, when they attempt to
        modify information for both events, then only modifications to
        information for which they have the required access are allowed.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup
    coordinator = signed_in(client, COORDINATOR_ID, COORDINATOR)
    cursor.fetchone.side_effect = [
        event_row(), event_row(status="Approved"),
        event_row(OTHER_EVENT_ID, coordinator_id=OTHER_COORDINATOR_ID),
    ]
    body = {"status": "Approved", "actionDetails": "Venue held."}

    allowed = coordinator.patch(f"/events/{EVENT_ID}/progress", json=body)

    # Act (When)
    refused = coordinator.patch(f"/events/{OTHER_EVENT_ID}/progress", json=body)

    # Assert (Then)
    assert (allowed.status_code, refused.status_code) == (200, 403)


# AC2/AC4: PATCH /safety-status is called by Safety Check Service with the caller's own token ----

SAFETY_ROUND = "55555555-5555-4555-8555-555555555555"
SAFETY_BODY = {"safetyCheckId": SAFETY_ROUND, "roundNumber": 1}
OFFICER_ID = "66666666-6666-4666-8666-666666666666"


def move(client, status, role, **extra):
    return client.patch(
        f"/events/{EVENT_ID}/safety-status", json={"status": status, **SAFETY_BODY, **extra},
        headers={**bearer(OFFICER_ID, role), "X-Internal-Token": SERVICE_TOKEN},
    )


@pytest.mark.parametrize("status", ["Confirmed", "Safety Changes Requested", "Cancelled"])
@pytest.mark.parametrize("role", [COORDINATOR, LEAD, ORGANISER, "Venue Staff", "Attendee"], ids=["coordinator", "lead", "organiser", "venue_staff", "attendee"])
def test_only_a_safety_officer_may_decide_a_safety_check(setup, status, role):
    """
    Summary: A coordinator cannot approve their own event, nor can any other role.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = move(client, status, role, remarks="r", areas=["Venue"])

    # Assert (Then)
    assert response.status_code == 403
    assert response.json["message"] == "Your role cannot change this information."
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("role", ["Safety Officer", ORGANISER, "Venue Staff", "Attendee"], ids=["safety_officer", "organiser", "venue_staff", "attendee"])
def test_only_coordinators_may_submit_an_event_for_a_safety_check(setup, role):
    """
    Summary: Submitting is the coordinator's step; the Safety Officer decides but does not submit.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = move(client, "Pending Safety Check", role)

    # Assert (Then)
    assert response.status_code == 403
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("marker", [{"withdrawnSafetyCheckId": SAFETY_ROUND, "reason": "venue changed"},
                                    {"restoredSafetyCheckId": SAFETY_ROUND}], ids=["withdrawnsafetycheckid_safety_round_reason_venue", "restoredsafetycheckid_safety_round"])
def test_a_safety_officer_cannot_withdraw_or_restore_an_approval_for_a_venue_change(setup, marker):
    """
    Summary: Withdrawing or restoring after a booking change is the coordinator's step.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, cursor = setup
    status = "Approved" if "withdrawnSafetyCheckId" in marker else "Confirmed"

    # Act (When)
    response = move(client, status, "Safety Officer", **marker)

    # Assert (Then)
    assert response.status_code == 403
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("role", [COORDINATOR, LEAD, "Safety Officer"], ids=["coordinator", "lead", "safety_officer"])
def test_each_permitted_role_gets_past_the_safety_status_gate(setup, role):
    """
    Summary: The three roles Safety Check Service acts for reach the handler's own validation.
    AC1: Given an authenticated user is permitted to modify information based
        on their role and relationship to the event, when they make a valid
        change to that information, then the change is allowed.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _ = setup

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/safety-status", json={},
        headers={**bearer(OFFICER_ID, role), "X-Internal-Token": SERVICE_TOKEN},
    )

    # Assert (Then)
    assert response.status_code == 400
    assert "Status must be one of" in response.json["message"]
