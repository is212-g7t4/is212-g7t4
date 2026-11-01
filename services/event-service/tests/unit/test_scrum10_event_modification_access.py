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

def test_ac1_assigned_coordinator_changes_event_progress_and_the_change_is_allowed(setup):
    """
    Summary: PATCH /events/<id>/progress to "Approved" with action details, signed in as the Event Coordinator the event is assigned to, answers 200 with status "Approved".
    AC1: Given an authenticated user is permitted to modify information based
        on their role and relationship to the event, when they make a valid
        change to that information, then the change is allowed.
    Double: Stub (cursor.fetchone returns the 'Under Review' event assigned to that coordinator, then the 'Approved' event); the status code and body are the only assertions
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
def test_ac2_a_role_outside_the_routes_allowlist_cannot_change_anything(setup, method, path, role):
    """
    Summary: Each organiser-only route and the Lead-only route called as an Event Coordinator, and each coordinator route called as Venue Staff, answers 403 "Your role cannot change this information." and no query is sent.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Mock (cursor.execute asserted never called); no rows are stubbed because the role gate refuses first
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
def test_ac2_an_attendee_cannot_change_any_event_information(setup, method, path):
    """
    Summary: Each organiser, Lead and coordinator write route called as an Attendee answers 403 and no query is sent.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Mock (cursor.execute asserted never called); no rows are stubbed because the role gate refuses first
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = send(client, method, path, "Attendee")

    # Assert (Then)
    assert response.status_code == 403
    cursor.execute.assert_not_called()


def test_ac2_the_lead_role_does_not_grant_organiser_rights(setup):
    """
    Summary: POST /events as an Event Coordinator Lead answers 403 and no query is sent, because the Lead is a coordinator role, not an organiser.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Mock (cursor.execute asserted never called); no rows are stubbed because the role gate refuses first
    """
    # Arrange (Given)
    client, cursor = setup

    # Act (When)
    response = send(client, "post", "/events", LEAD)

    # Assert (Then)
    assert response.status_code == 403
    cursor.execute.assert_not_called()


# AC3 ----

def test_ac3_a_coordinator_cannot_change_an_event_assigned_to_another_coordinator(setup):
    """
    Summary: PATCH /events/<id>/progress as a coordinator when the event is assigned to a different coordinator answers 403 and no UPDATE or INSERT is sent.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to modify that event's information, when they attempt to make a
        change, then the modification is prevented and the existing information
        remains unchanged.
    Double: Stub (cursor.fetchone returns an event assigned to another coordinator),
        Mock (no cursor.execute call starts with UPDATE or INSERT)
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


def test_ac3_the_lead_cannot_edit_details_of_an_event_assigned_to_another_coordinator(setup):
    """
    Summary: PATCH /events/<id>/details as an Event Coordinator Lead when the event is assigned to another coordinator answers 403.
    AC3: Given an authenticated user's relationship to an event does not permit
        them to modify that event's information, when they attempt to make a
        change, then the modification is prevented and the existing information
        remains unchanged.
    Double: Stub (cursor.fetchone returns an event assigned to another coordinator); the 403 status is the only assertion
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

def test_ac4_venue_staff_keep_their_view_when_their_change_is_refused(setup):
    """
    Summary: As Venue Staff, GET /events/<id> answers 200, PATCH /events/<id>/progress answers 403, and a second GET answers 200 with the same body as the first.
    AC4: Given a user is permitted to view particular information but is not
        permitted to modify it, when they attempt to change that information,
        then the modification is prevented while their permitted viewing access
        remains unaffected.
    Double: Stub (cursor.fetchone returns the same event for every read); the three status codes and the equality of the two GET bodies are asserted
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

def test_ac5_a_coordinator_can_change_the_event_assigned_to_them_but_not_another_coordinators(setup):
    """
    Summary: PATCH /events/<id>/progress for the coordinator's own event answers 200, and the same change for an event assigned to a different coordinator answers 403.
    AC5: Given a user is permitted to modify information for one event but does
        not have the required access to another event, when they attempt to
        modify information for both events, then only modifications to
        information for which they have the required access are allowed.
    Double: Stub (cursor.fetchone returns the coordinator's event, its updated copy, then another coordinator's event); the two status codes are the only assertions
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
def test_ac2_only_a_safety_officer_may_decide_a_safety_check(setup, status, role):
    """
    Summary: PATCH /events/<id>/safety-status to Confirmed, Safety Changes Requested or Cancelled, sent with the service token as a coordinator, Lead, organiser, Venue Staff or Attendee, answers 403 "Your role cannot change this information." and no query is sent.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Mock (cursor.execute asserted never called); no rows are stubbed because the role gate refuses first
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
def test_ac2_only_coordinators_may_submit_an_event_for_a_safety_check(setup, role):
    """
    Summary: PATCH /events/<id>/safety-status to "Pending Safety Check", sent with the service token as a Safety Officer, organiser, Venue Staff or Attendee, answers 403 and no query is sent.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Mock (cursor.execute asserted never called); no rows are stubbed because the role gate refuses first
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
def test_ac2_a_safety_officer_cannot_withdraw_or_restore_an_approval_for_a_venue_change(setup, marker):
    """
    Summary: PATCH /events/<id>/safety-status carrying a withdrawnSafetyCheckId (status "Approved") or a restoredSafetyCheckId (status "Confirmed"), sent with the service token as a Safety Officer, answers 403 and no query is sent.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Mock (cursor.execute asserted never called); no rows are stubbed because the role gate refuses first
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
def test_ac1_each_permitted_role_gets_past_the_safety_status_gate(setup, role):
    """
    Summary: PATCH /events/<id>/safety-status with an empty body, sent with the service token as a coordinator, Lead or Safety Officer, answers 400 "Status must be one of ...", which shows the role gate let the request through to the handler's own validation.
    AC1: Given an authenticated user is permitted to modify information based
        on their role and relationship to the event, when they make a valid
        change to that information, then the change is allowed.
    Double: None for the database: the request is refused by body validation before any query; only the 400 status and message are asserted
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


# AC2: the change-request review routes are for Event Workflow Service only ----


def test_ac2_review_routes_refuse_a_caller_that_does_not_present_the_configured_service_token(monkeypatch):
    """
    Summary: GET /change-requests, GET /change-requests/<id> and PATCH /change-requests/<id>/decision from a signed-in user without the matching X-Internal-Token each answer 403, and no database cursor is opened.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Mock (psycopg2.connect returns a MagicMock connection; connection.cursor asserted never called)
    """
    # Arrange (Given)
    connection = MagicMock()
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    client = signed_in(create_app({
        "TESTING": True,
        "DATABASE_URL": "unused-test-url",
        "INTERNAL_SERVICE_TOKEN": "secret",
    }).test_client())

    # Act (When)
    responses = [
        client.get(f"/change-requests?coordinatorId={COORDINATOR_ID}"),
        client.get(f"/change-requests/{CHANGE_ID}?coordinatorId={COORDINATOR_ID}"),
        client.patch(
            f"/change-requests/{CHANGE_ID}/decision",
            json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
        ),
    ]

    # Assert (Then)
    assert [response.status_code for response in responses] == [403, 403, 403]
    connection.cursor.assert_not_called()


def test_ac2_review_routes_stay_closed_with_503_when_no_service_token_is_configured(monkeypatch):
    """
    Summary: With INTERNAL_SERVICE_TOKEN unset, GET /change-requests, GET /change-requests/<id> and PATCH /change-requests/<id>/decision each answer 503 with code INTERNAL_AUTH_NOT_CONFIGURED, and no database cursor is opened.
    AC2: Given an authenticated user's role does not permit them to modify
        particular information, when they attempt to change that information,
        then the modification is prevented and the existing information remains
        unchanged.
    Double: Mock (psycopg2.connect returns a MagicMock connection; connection.cursor asserted never called)
    """
    # Arrange (Given)
    connection = MagicMock()
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    client = signed_in(create_app({
        "TESTING": True, "DATABASE_URL": "unused-test-url", "INTERNAL_SERVICE_TOKEN": None,
    }).test_client())

    # Act (When)
    responses = [
        client.get(f"/change-requests?coordinatorId={COORDINATOR_ID}"),
        client.get(f"/change-requests/{CHANGE_ID}?coordinatorId={COORDINATOR_ID}"),
        client.patch(
            f"/change-requests/{CHANGE_ID}/decision",
            json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
        ),
    ]

    # Assert (Then)
    assert [response.status_code for response in responses] == [503, 503, 503]
    assert {response.json["code"] for response in responses} == {"INTERNAL_AUTH_NOT_CONFIGURED"}
    connection.cursor.assert_not_called()
