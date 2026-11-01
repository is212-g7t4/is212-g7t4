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


# --- AC1: requesting changes needs areas and a description --------------------


def test_ac1_requesting_changes_without_remarks_is_refused_before_any_query(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Safety Changes Requested" with remarks null answers 400 "remarks is required." and no query is sent.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Mock (cursor.execute asserted never called)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = request_changes(client, remarks=None)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "remarks is required."
    cursor.execute.assert_not_called()


def test_ac1_requesting_changes_with_blank_remarks_is_refused_before_any_query(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Safety Changes Requested" with whitespace-only remarks answers 400 and no query is sent.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Mock (cursor.execute asserted never called)
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
def test_ac1_requesting_changes_without_a_valid_list_of_areas_is_refused_before_any_query(areas, setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Safety Changes Requested" with areas null, empty, a plain string, an unknown area or a repeated area answers 400 and no query is sent.
    AC1: Given an event is 'Pending Safety Check', when I request changes, then
        I must select at least one affected area (venue arrangement,
        technical/equipment arrangement, event details) and describe the change
        needed; otherwise the decision is not saved.
    Double: Mock (cursor.execute asserted never called)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = request_changes(client, areas=areas)

    # Assert (Then)
    assert response.status_code == 400
    cursor.execute.assert_not_called()


# --- AC2/AC6: request changes -------------------------------------------------


def test_ac2_requesting_changes_moves_a_pending_safety_check_event_to_safety_changes_requested(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Safety Changes Requested" with remarks and two areas on a 'Pending Safety Check' event answers 200 with status "Safety Changes Requested", and the UPDATE's first parameter is that status.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: Stub (cursor.fetchone returns the 'Pending Safety Check' event, then the updated event),
        Mock (the UPDATE's status parameter asserted)
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


def test_ac2_requesting_changes_keeps_the_existing_decision_and_action_details(setup):
    """
    Summary: After requesting changes, the metadata written by the UPDATE still holds the earlier decision status "Approved" and the earlier actionDetails "Venue booked.", so only the status and history change.
    AC2: Given changes are requested, then the event status changes to 'Safety
        Changes Requested', the event returns to the planning stage for each
        selected area, and its existing arrangements are preserved. For
        equipment requests affected by the requested changes, only requests
        with status 'Approved' return to 'Pending' for review. Requests already
        'Pending' or 'Rejected' remain unchanged, including any recorded
        reviewer and rejection reason.
    Double: Stub (cursor.fetchone returns the 'Pending Safety Check' event, then the updated event),
        Mock (the UPDATE's metadata parameter asserted)
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


def test_ac6_requesting_changes_records_the_officer_round_remarks_areas_and_time_in_the_history(setup):
    """
    Summary: After requesting changes, the stored action history ends with an entry whose status is "Safety Changes Requested", with the officer's id, the safety check id, the remarks, both areas, a UTC timestamp and details naming the areas; the earlier "Pending Safety Check" entry is still first.
    AC6: Given either decision, then the safety check is recorded with the
        status 'Changes Requested' or 'Safety Rejected' respectively, together
        with my identity, the timestamp and the reason (plus the selected areas
        for a change request), and the original event information is retained.
    Double: Stub (cursor.fetchone returns the 'Pending Safety Check' event, then the updated event),
        Mock (the UPDATE's metadata parameter asserted)
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


# --- AC3/AC4/AC6: reject ------------------------------------------------------


def test_ac3_rejecting_without_remarks_is_refused_before_any_query(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Cancelled" with remarks null answers 400 "remarks is required." and no query is sent.
    AC3: Given an event is 'Pending Safety Check', when I reject it, then a
        reason is required and I must confirm the rejection before it is saved.
    Double: Mock (cursor.execute asserted never called)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = reject(client, remarks=None)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "remarks is required."
    cursor.execute.assert_not_called()


def test_ac4_rejecting_moves_a_pending_safety_check_event_to_cancelled(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Cancelled" with remarks on a 'Pending Safety Check' event answers 200 with status "Cancelled", and the UPDATE's first parameter is that status.
    AC4: Given I confirm a rejection, then the event status changes to
        'Cancelled', and the event cannot be resubmitted for a safety check or
        moved to any further stage.
    Double: Stub (cursor.fetchone returns the 'Pending Safety Check' event, then the 'Cancelled' event),
        Mock (the UPDATE's status parameter asserted)
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


@pytest.mark.parametrize("target", ["Pending Safety Check", "Confirmed"])
def test_ac4_a_cancelled_event_cannot_be_moved_on_through_the_safety_status_route(target, setup):
    """
    Summary: PATCH /events/<id>/safety-status asking a 'Cancelled' event to go to "Pending Safety Check" (a resubmission) or "Confirmed" answers 409 INVALID_SAFETY_TRANSITION and only the lookup read ran.
    AC4: Given I confirm a rejection, then the event status changes to
        'Cancelled', and the event cannot be resubmitted for a safety check or
        moved to any further stage.
    Double: Stub (cursor.fetchone returns a 'Cancelled' event),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
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


def test_ac6_rejecting_records_the_officer_remarks_and_time_with_no_areas_in_the_history(setup):
    """
    Summary: After rejecting, the stored action history ends with an entry whose status is "Cancelled", with the officer's id and the remarks, no areas, and details that mention the cancellation.
    AC6: Given either decision, then the safety check is recorded with the
        status 'Changes Requested' or 'Safety Rejected' respectively, together
        with my identity, the timestamp and the reason (plus the selected areas
        for a change request), and the original event information is retained.
    Double: Stub (cursor.fetchone returns the 'Pending Safety Check' event, then the 'Cancelled' event),
        Mock (the UPDATE's metadata parameter asserted)
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


# --- AC7: only 'Pending Safety Check' may move --------------------------------


@pytest.mark.parametrize("current_status", NON_PENDING_STATUSES)
def test_ac7_changes_can_only_be_requested_while_the_event_is_pending_safety_check(current_status, setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Safety Changes Requested" on an event in any status other than 'Pending Safety Check' answers 409 INVALID_SAFETY_TRANSITION with the event's currentStatus, and only the lookup read ran.
    AC7: Given an event is not 'Pending Safety Check', then these actions are
        not available and an API call is rejected without changing the event.
    Double: Stub (cursor.fetchone returns the event in the parametrised status),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
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
def test_ac7_an_event_can_only_be_rejected_while_it_is_pending_safety_check(current_status, setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Cancelled" on an event in any status other than 'Pending Safety Check' answers 409 INVALID_SAFETY_TRANSITION with the event's currentStatus, and only the lookup read ran.
    AC7: Given an event is not 'Pending Safety Check', then these actions are
        not available and an API call is rejected without changing the event.
    Double: Stub (cursor.fetchone returns the event in the parametrised status),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
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


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_requesting_changes_reads_the_event_under_a_row_lock(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Safety Changes Requested" runs a first query containing FOR UPDATE.
    Supporting design check: the decision reads the status under a row lock so
        a concurrent decision cannot leave it stale
    Double: Stub (cursor.fetchone returns the 'Pending Safety Check' event, then the updated event),
        Mock (the first cursor.execute query asserted to contain FOR UPDATE)
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


def test_requesting_changes_does_not_require_the_decider_to_be_the_assigned_coordinator(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Safety Changes Requested" decided by the Safety Officer, who is not the event's assigned coordinator, answers 200.
    Supporting design check: the Safety Officer deciding need not be the
        assigned coordinator
    Double: Stub (cursor.fetchone returns a 'Pending Safety Check' event assigned to a coordinator, then the updated event); the 200 status is the only assertion
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


def test_rejecting_does_not_require_the_decider_to_be_the_assigned_coordinator(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Cancelled" decided by the Safety Officer, who is not the event's assigned coordinator, answers 200.
    Supporting design check: the Safety Officer deciding need not be the
        assigned coordinator
    Double: Stub (cursor.fetchone returns a 'Pending Safety Check' event assigned to a coordinator, then the 'Cancelled' event); the 200 status is the only assertion
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


def test_a_stale_safety_check_id_is_refused_when_requesting_changes(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Safety Changes Requested" naming a safetyCheckId that is not the open round's answers 409 STALE_SAFETY_CHECK and only the lookup read ran.
    Supporting design check: a decision on an old round cannot change the event
    Double: Stub (cursor.fetchone returns a 'Pending Safety Check' event whose open round has a different id),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
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


def test_a_stale_safety_check_id_is_refused_when_rejecting(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Cancelled" naming a safetyCheckId that is not the open round's answers 409 STALE_SAFETY_CHECK and only the lookup read ran.
    Supporting design check: a decision on an old round cannot change the event
    Double: Stub (cursor.fetchone returns a 'Pending Safety Check' event whose open round has a different id),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
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


def test_a_safety_decision_on_an_event_that_does_not_exist_answers_404(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Cancelled" answers 404 "Event request not found." when the database finds no such event.
    Supporting design check: deciding on an event that does not exist is a 404
    Double: Stub (cursor.fetchone returns None)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    # Act (When)
    response = reject(client)

    # Assert (Then)
    assert response.status_code == 404
    assert response.json["message"] == "Event request not found."


def test_a_cancelled_event_can_still_save_progress_notes_through_the_progress_route(setup):
    """
    Summary: PATCH /events/<id>/progress keeping a 'Cancelled' event at "Cancelled" with action details answers 200 with status "Cancelled".
    Supporting design check: the progress route's Cancelled to Cancelled notes
        save is untouched by the safety rejection
    Double: Stub (cursor.fetchone returns the 'Cancelled' event, then the updated 'Cancelled' event); the 200 status and status are the only assertions
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
