"""SCRUM-151: Reject or Request Changes to Safety Arrangements

Agreed revision from this conversation; pending confirmation that Jira has been updated

User Story
----------
As a Safety Officer, I want to reject an event's safety arrangement or request
changes, stating which planning area must be revisited, so that the Event
Coordinator knows exactly what to fix before the event can proceed.

Acceptance Criteria
-------------------
AC1: Given an event is 'Pending Safety Check', when I request changes, then I
     must select at least one affected area (venue arrangement,
     technical/equipment arrangement, event details) and describe the change
     needed; otherwise the decision is not saved.
AC2: Given changes are requested, then the event status changes to 'Safety Changes Requested', the event returns to the planning stage for each selected area, and its existing arrangements are preserved. For equipment requests affected by the requested changes, only requests with status 'Approved' return to 'Pending' for review. Requests already 'Pending' or 'Rejected' remain unchanged, including any recorded reviewer and rejection reason.
AC3: Given an event is 'Pending Safety Check', when I reject it, then a reason
     is required and I must confirm the rejection before it is saved.
AC4: Given I confirm a rejection, then the event status changes to 'Cancelled',
     and the event cannot be resubmitted for a safety check or moved to any
     further stage.
AC5: Given an event is cancelled by a safety rejection, then its venue bookings
     and equipment reservations are released so they no longer block other
     events, while their records remain in the event's history.
AC6: Given either decision, then the safety check is recorded with the status
     'Changes Requested' or 'Safety Rejected' respectively, together with my
     identity, the timestamp and the reason (plus the selected areas for a
     change request), and the original event information is retained.
AC7: Given an event is not 'Pending Safety Check', then these actions are not
     available and an API call is rejected without changing the event.

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
OFFICER_ID = "33333333-3333-4333-8333-333333333333"
SAFETY_CHECK_ID = "55555555-5555-4555-8555-555555555555"
OTHER_SAFETY_CHECK_ID = "66666666-6666-4666-8666-666666666666"
INTERNAL_TOKEN = "test-internal-token"
INTERNAL_HEADERS = {"X-Internal-Token": INTERNAL_TOKEN}

# Every status an event can hold that isn't 'Pending Safety Check'; none of
# them may move to 'Safety Changes Requested' or 'Cancelled' through this
# endpoint (AC7).
NON_PENDING_STATUSES = [
    "Submitted",
    "Under Review",
    "Approved",
    "Rejected",
    "Confirmed",
    "Safety Changes Requested",
    "Cancelled",
]


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": "unused-test-url",
            "INTERNAL_SERVICE_TOKEN": INTERNAL_TOKEN,
        }
    )
    return signed_in(app.test_client()), connection, cursor


def event_row(
    status="Pending Safety Check",
    coordinator_id=COORDINATOR_ID,
    action_history=None,
):
    row = {column: "" for column in FIELDS.values()}
    row.update(
        event_id=EVENT_ID,
        event_name="Community Workshop",
        status=status,
        coordinator_id=coordinator_id,
        organiser_id=None,
        submission_date=datetime(2026, 10, 1, 8, tzinfo=UTC),
        preferred_start_date=datetime(2026, 11, 12, 9),
        preferred_end_date=datetime(2026, 11, 12, 17),
        expected_attendance=120,
    )
    if action_history is None:
        action_history = [
            {
                "status": "Pending Safety Check",
                "details": "Submitted for Operational Safety Check (round 1).",
                "coordinatorId": COORDINATOR_ID,
                "safetyCheckId": SAFETY_CHECK_ID,
                "recordedAt": "2026-11-01T02:30:00+00:00",
            }
        ]
    row["description"] = json.dumps(
        {
            "_connectsphere": "event-submission-v1",
            "description": "A practical workshop",
            "purpose": "Learning",
            "decision": {
                "status": "Approved",
                "coordinatorId": COORDINATOR_ID,
                "decidedAt": "2026-10-02T01:00:00+00:00",
                "reason": None,
            },
            "decisionHistory": [],
            "actionDetails": "Venue booked.",
            "actionHistory": action_history,
        }
    )
    return row


def request_changes(client, headers=INTERNAL_HEADERS, **overrides):
    body = {
        "status": "Safety Changes Requested",
        "decidedBy": OFFICER_ID,
        "safetyCheckId": SAFETY_CHECK_ID,
        "roundNumber": 1,
        "remarks": "Needs another look.",
        "areas": ["venue arrangement", "event details"],
        **overrides,
    }
    return client.patch(f"/events/{EVENT_ID}/safety-status", json=body, headers=headers)


def reject(client, headers=INTERNAL_HEADERS, **overrides):
    body = {
        "status": "Cancelled",
        "decidedBy": OFFICER_ID,
        "safetyCheckId": SAFETY_CHECK_ID,
        "roundNumber": 1,
        "remarks": "Unsafe egress plan.",
        **overrides,
    }
    return client.patch(f"/events/{EVENT_ID}/safety-status", json=body, headers=headers)


# --- AC2/AC6: request changes -------------------------------------------------


def test_pending_safety_check_moves_to_safety_changes_requested(setup):
    """
    Summary: Pending safety check moves to safety changes requested.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Safety Changes Requested"),
    ]

    # Act (When)
    response = request_changes(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Safety Changes Requested"
    assert cursor.execute.call_args_list[1].args[1][0] == "Safety Changes Requested"


def test_changes_requested_history_entry_has_areas_and_remarks(setup):
    """
    Summary: Changes requested history entry has areas and remarks.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Safety Changes Requested"),
    ]

    request_changes(client)

    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    action = stored["actionHistory"][-1]

    # Act + Assert (When / Then)
    assert action["status"] == "Safety Changes Requested"
    assert action["decidedBy"] == OFFICER_ID
    assert action["safetyCheckId"] == SAFETY_CHECK_ID
    assert action["remarks"] == "Needs another look."
    assert action["areas"] == ["venue arrangement", "event details"]
    assert action["recordedAt"].endswith("+00:00")
    assert "venue arrangement, event details" in action["details"]
    # The earlier submit entry is kept, not replaced.
    assert stored["actionHistory"][0]["status"] == "Pending Safety Check"


def test_changes_requested_preserves_everything_else(setup):
    """
    Summary: "existing arrangements are preserved" — only status/history change.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Safety Changes Requested"),
    ]

    request_changes(client)

    # Act (When)
    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])

    # Assert (Then)
    assert stored["decision"]["status"] == "Approved"
    assert stored["actionDetails"] == "Venue booked."


def test_changes_requested_requires_remarks(setup):
    """
    Summary: Changes requested requires remarks.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = request_changes(client, remarks=None)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "remarks is required."
    cursor.execute.assert_not_called()


def test_changes_requested_rejects_blank_remarks(setup):
    """
    Summary: Changes requested rejects blank remarks.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = request_changes(client, remarks="   ")

    # Assert (Then)
    assert response.status_code == 400
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    "areas",
    [
        None,
        [],
        "venue arrangement",
        ["not a real area"],
        ["venue arrangement", "venue arrangement"],
    ],
    ids=["none", "empty", "venue_arrangement", "not_a_real_area", "venue_arrangement_venue_arrangement"],
)
def test_changes_requested_rejects_bad_areas(areas, setup):
    """
    Summary: Changes requested rejects bad areas.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = request_changes(client, areas=areas)

    # Assert (Then)
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_changes_requested_runs_under_a_row_lock(setup):
    """
    Summary: Changes requested runs under a row lock.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Safety Changes Requested"),
    ]

    # Act (When)
    request_changes(client)

    # Assert (Then)
    assert "FOR UPDATE" in cursor.execute.call_args_list[0].args[0]


def test_no_coordinator_check_on_request_changes(setup):
    """
    Summary: The Safety Officer deciding need not be the assigned coordinator.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check", coordinator_id=COORDINATOR_ID),
        event_row("Safety Changes Requested"),
    ]

    # Act (When)
    response = request_changes(client, decidedBy=OFFICER_ID)

    # Assert (Then)
    assert response.status_code == 200


# --- AC4/AC6: reject -----------------------------------------------------------


def test_pending_safety_check_moves_to_cancelled(setup):
    """
    Summary: Pending safety check moves to cancelled.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Cancelled"),
    ]

    # Act (When)
    response = reject(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Cancelled"
    assert cursor.execute.call_args_list[1].args[1][0] == "Cancelled"


def test_rejected_history_entry_has_remarks_and_no_areas(setup):
    """
    Summary: Rejected history entry has remarks and no areas.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check"),
        event_row("Cancelled"),
    ]

    reject(client)

    stored = json.loads(cursor.execute.call_args_list[1].args[1][1])
    action = stored["actionHistory"][-1]

    # Act + Assert (When / Then)
    assert action["status"] == "Cancelled"
    assert action["decidedBy"] == OFFICER_ID
    assert action["remarks"] == "Unsafe egress plan."
    assert "areas" not in action
    assert "cancelled" in action["details"].lower()


def test_rejected_requires_remarks(setup):
    """
    Summary: Rejected requires remarks.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = reject(client, remarks=None)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "remarks is required."
    cursor.execute.assert_not_called()


def test_no_coordinator_check_on_reject(setup):
    """
    Summary: No coordinator check on reject.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Pending Safety Check", coordinator_id=COORDINATOR_ID),
        event_row("Cancelled"),
    ]

    # Act (When)
    response = reject(client, decidedBy=OFFICER_ID)

    # Assert (Then)
    assert response.status_code == 200


# --- AC7: only 'Pending Safety Check' may move, and only with its own round --


@pytest.mark.parametrize("current_status", NON_PENDING_STATUSES)
def test_only_pending_safety_check_can_move_to_changes_requested(current_status, setup):
    """
    Summary: Only pending safety check can move to changes requested.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(current_status)

    # Act (When)
    response = request_changes(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "INVALID_SAFETY_TRANSITION"
    assert response.json["currentStatus"] == current_status
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("current_status", NON_PENDING_STATUSES)
def test_only_pending_safety_check_can_be_rejected(current_status, setup):
    """
    Summary: Only pending safety check can be rejected.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(current_status)

    # Act (When)
    response = reject(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "INVALID_SAFETY_TRANSITION"
    assert response.json["currentStatus"] == current_status
    assert cursor.execute.call_count == 1


def test_stale_safety_check_id_is_refused_for_changes_requested(setup):
    """
    Summary: Stale safety check id is refused for changes requested.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Pending Safety Check")

    # Act (When)
    response = request_changes(client, safetyCheckId=OTHER_SAFETY_CHECK_ID)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "STALE_SAFETY_CHECK"
    assert cursor.execute.call_count == 1


def test_stale_safety_check_id_is_refused_for_reject(setup):
    """
    Summary: Stale safety check id is refused for reject.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Pending Safety Check")

    # Act (When)
    response = reject(client, safetyCheckId=OTHER_SAFETY_CHECK_ID)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "STALE_SAFETY_CHECK"
    assert cursor.execute.call_count == 1


def test_missing_event_is_404(setup):
    """
    Summary: Missing event is 404.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    # Act (When)
    response = reject(client)

    # Assert (Then)
    assert response.status_code == 404
    assert response.json["message"] == "Event request not found."


# --- AC4: nothing leaves 'Cancelled' -------------------------------------------


@pytest.mark.parametrize("target", ["Pending Safety Check", "Confirmed"])
def test_cancelled_event_cannot_move_through_safety_status(target, setup):
    """
    Summary: Cancelled event cannot move through safety status.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Cancelled")

    # Act (When)
    if target == "Pending Safety Check":
        response = client.patch(
            f"/events/{EVENT_ID}/safety-status",
            json={
                "status": "Pending Safety Check",
                "coordinatorId": COORDINATOR_ID,
                "safetyCheckId": SAFETY_CHECK_ID,
                "roundNumber": 1,
            },
            headers=INTERNAL_HEADERS,
        )
    else:
        response = client.patch(
            f"/events/{EVENT_ID}/safety-status",
            json={
                "status": "Confirmed",
                "decidedBy": OFFICER_ID,
                "safetyCheckId": SAFETY_CHECK_ID,
                "roundNumber": 1,
            },
            headers=INTERNAL_HEADERS,
        )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "INVALID_SAFETY_TRANSITION"
    assert cursor.execute.call_count == 1


def test_cancelled_event_progress_self_save_still_works(setup):
    """
    Summary: `/progress`'s Cancelled -> Cancelled notes save is untouched by this story.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Cancelled"),
        event_row("Cancelled", action_history=[]),
    ]

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/progress",
        json={"coordinatorId": COORDINATOR_ID, "status": "Cancelled", "actionDetails": "Noted."},
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Cancelled"
