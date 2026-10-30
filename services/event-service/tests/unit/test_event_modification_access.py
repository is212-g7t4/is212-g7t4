"""SCRUM-10 Role-Based Modification Control for Events: Event Service unit tests.

Story:      As a registered user, I want to modify only information appropriate to my
            role and relationship to an event, so that I can perform my responsibilities
            without changing information outside my permissions.
Real:       Flask app, routes, token verification and role checks, relationship checks.
Doubled:    psycopg2 (mocked cursor).
Not proven: that a refused change leaves the stored row untouched in a real database (see
            tests/integration/test_event_modification_access.py); Supabase issuing the token.

AC1  Given an authenticated user is permitted to modify information based on their role and
     relationship to the event, when they make a valid change to that information, then the
     change is allowed.
AC2  Given an authenticated user's role does not permit them to modify particular information,
     when they attempt to change that information, then the modification is prevented and the
     existing information remains unchanged.
AC3  Given an authenticated user's relationship to an event does not permit them to modify that
     event's information, when they attempt to make a change, then the modification is prevented
     and the existing information remains unchanged.
AC4  Given a user is permitted to view particular information but is not permitted to modify it,
     when they attempt to change that information, then the modification is prevented while their
     permitted viewing access remains unaffected.
AC5  Given a user is permitted to modify information for one event but does not have the required
     access to another event, when they attempt to modify information for both events, then only
     modifications to information for which they have the required access are allowed.
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
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
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

def test_ac1_assigned_coordinator_updates_progress(setup):
    """Normal: the coordinator role plus the assignment lets a valid change through."""
    client, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row(status="Approved")]

    response = signed_in(client, COORDINATOR_ID, COORDINATOR).patch(
        f"/events/{EVENT_ID}/progress", json={"status": "Approved", "actionDetails": "Venue held."}
    )

    assert response.status_code == 200
    assert response.json["status"] == "Approved"


# AC2 ----

@pytest.mark.parametrize(
    "method, path, role",
    [(m, p, COORDINATOR) for m, p in ORGANISER_ROUTES]
    + [(m, p, COORDINATOR) for m, p in LEAD_ROUTES]
    + [(m, p, "Venue Staff") for m, p in COORDINATOR_ROUTES],
)
def test_ac2_a_role_outside_the_routes_allowlist_cannot_change_anything(setup, method, path, role):
    """Failure: every write route refuses the wrong role before reading the body or the database."""
    client, cursor = setup

    response = send(client, method, path, role)

    assert response.status_code == 403
    assert response.json["message"] == "Your role cannot change this information."
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("method, path", ORGANISER_ROUTES + LEAD_ROUTES + COORDINATOR_ROUTES)
def test_ac2_an_attendee_cannot_change_any_event_information(setup, method, path):
    """Failure: Attendee is a registered role with no modification rights at all."""
    client, cursor = setup

    response = send(client, method, path, "Attendee")

    assert response.status_code == 403
    cursor.execute.assert_not_called()


def test_ac2_the_lead_role_does_not_grant_organiser_rights(setup):
    """Boundary: the Lead is a coordinator, not an organiser, so it cannot create events."""
    client, cursor = setup

    response = send(client, "post", "/events", LEAD)

    assert response.status_code == 403
    cursor.execute.assert_not_called()


# AC3 ----

def test_ac3_coordinator_assigned_to_another_coordinator_cannot_change_the_event(setup):
    """Failure: the right role is not enough without the assignment."""
    client, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=OTHER_COORDINATOR_ID)

    response = signed_in(client, COORDINATOR_ID, COORDINATOR).patch(
        f"/events/{EVENT_ID}/progress", json={"status": "Approved", "actionDetails": "Venue held."}
    )

    assert response.status_code == 403
    writes = [c for c in cursor.execute.call_args_list if c.args[0].lstrip().upper().startswith(("UPDATE", "INSERT"))]
    assert writes == []


def test_ac3_lead_cannot_edit_details_of_an_event_assigned_to_someone_else(setup):
    """Boundary: the Lead may only edit an event that has no coordinator."""
    client, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=OTHER_COORDINATOR_ID)

    response = signed_in(client, COORDINATOR_ID, LEAD).patch(
        f"/events/{EVENT_ID}/details", json={"changes": {"eventName": "New"}}
    )

    assert response.status_code == 403


# AC4 ----

def test_ac4_venue_staff_keep_their_view_when_their_change_is_refused(setup):
    """Conflict: the refused PATCH does not disturb the read access the role still has."""
    client, cursor = setup
    cursor.fetchone.return_value = event_row()
    staff = signed_in(client, STAFF_ID, "Venue Staff")
    url = f"/events/{EVENT_ID}?viewerRole=1"

    before = staff.get(url)
    refused = staff.patch(f"/events/{EVENT_ID}/progress", json={"status": "Approved", "actionDetails": "x"})
    after = staff.get(url)

    assert (before.status_code, refused.status_code, after.status_code) == (200, 403, 200)
    assert before.json == after.json


# AC5 ----

def test_ac5_coordinator_changes_only_the_event_they_are_assigned_to(setup):
    """Conflict: changing both events succeeds for one and is refused for the other."""
    client, cursor = setup
    coordinator = signed_in(client, COORDINATOR_ID, COORDINATOR)
    cursor.fetchone.side_effect = [
        event_row(), event_row(status="Approved"),
        event_row(OTHER_EVENT_ID, coordinator_id=OTHER_COORDINATOR_ID),
    ]
    body = {"status": "Approved", "actionDetails": "Venue held."}

    allowed = coordinator.patch(f"/events/{EVENT_ID}/progress", json=body)
    refused = coordinator.patch(f"/events/{OTHER_EVENT_ID}/progress", json=body)

    assert (allowed.status_code, refused.status_code) == (200, 403)
