"""
SCRUM-43: Review Event Change Requests

User Story
----------
As an Event Coordinator, I want to review and process change requests for
events I manage, so that I can assess the impact of changes and approve or
reject them appropriately.

Acceptance Criteria
-------------------
AC1: The Event Coordinator can view a list of pending change requests for
     events they manage.
AC2: For each change request, the Event Coordinator can see the event details
     and proposed changes (original vs proposed values), reason for change,
     attachments, request timestamp.
AC3: The Event Coordinator can approve the change request, where the system
     ppdates the event with the proposed changes, Changes the request status to
     'Approved', Records the Event Coordinator's identity, approval timestamp,
     and decision
AC4: The Event Coordinator can reject the change request with a reason
     (required), where the system Changes the request status to 'Rejected',
     Stores the rejection reason, Records the Event Coordinator's identity,
     rejection timestamp, and reason

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
- Submitting a change request (-> test_scrum42_change_requests.py).
- That only the Event Workflow Service may call the review routes (->
  test_scrum10_event_modification_access.py).
"""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from app import create_app
from app.models import FIELDS
from tests.unit.factories import signed_in

EVENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ORGANISER_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "22222222-2222-4222-8222-222222222222"
COORDINATOR_ID = "33333333-3333-4333-8333-333333333333"
CHANGE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def event_row(status="Submitted", organiser_id=ORGANISER_ID):
    row = {column: "" for column in FIELDS.values()}
    row.update(
        event_id=EVENT_ID,
        event_name="Community Workshop",
        description=json.dumps({
            "_connectsphere": "event-submission-v1",
            "description": "Original description",
            "purpose": "Learning",
        }),
        preferred_start_date=datetime(2026, 11, 1, 9),
        preferred_end_date=datetime(2026, 11, 1, 12),
        expected_attendance=30,
        status=status,
        submission_date=datetime(2026, 10, 1, tzinfo=UTC),
        coordinator_id=None,
        organiser_id=organiser_id,
        assigned_by=None,
        assigned_at=None,
        previous_coordinator_id=None,
    )
    return row


def review_row(change_status="Pending Review", coordinator_id=COORDINATOR_ID):
    return {
        **event_row("Approved"),
        "coordinator_id": coordinator_id,
        "change_id": CHANGE_ID,
        "requested_changes": {"expectedAttendance": "40"},
        "change_request_status": change_status,
        "request_date": datetime(2026, 10, 23, 4, 5, tzinfo=UTC),
        "requested_by": ORGANISER_ID,
        "reason": "More guests accepted the invitation.",
        "rejection_reason": None,
        "review_date": None,
        "reviewed_by": None,
    }


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url", "INTERNAL_SERVICE_TOKEN": "workflow-token"})
    client = signed_in(app.test_client(), role="Event Organiser")
    # The review routes are only for Event Workflow Service, which always sends this header.
    client.environ_base["HTTP_X_INTERNAL_TOKEN"] = "workflow-token"
    return client, connection, cursor


def test_ac1_ac2_coordinator_lists_pending_change_requests_for_their_events_with_the_event_and_proposal(setup):
    """
    Summary: GET /change-requests?coordinatorId=C answers 200 with the pending request carrying its id, the event's name and current attendance 30, the proposed changes {"expectedAttendance": "40"} and the reason; the SQL selects only status 'Pending Review' for events where event.coordinator_id = %s, with the coordinator id as its only parameter.
    AC1: The Event Coordinator can view a list of pending change requests for
        events they manage.
    AC2: For each change request, the Event Coordinator can see the event
        details and proposed changes (original vs proposed values), reason for
        change, attachments, request timestamp.
    Double: Stub (cursor.fetchall returns one pending request joined with its event),
        Mock (cursor.execute SQL contains the Pending Review and coordinator clauses; parameters are [coordinator id])
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = [review_row()]

    response = client.get(f"/change-requests?coordinatorId={COORDINATOR_ID}")

    assert response.status_code == 200
    change = response.json["changeRequests"][0]
    assert change["id"] == CHANGE_ID
    assert change["event"]["eventName"] == "Community Workshop"
    assert change["event"]["expectedAttendance"] == "30"
    assert change["proposedChanges"] == {"expectedAttendance": "40"}
    assert change["reason"] == "More guests accepted the invitation."
    query, params = cursor.execute.call_args.args
    assert "request.status = 'Pending Review'" in query
    assert "event.coordinator_id = %s" in query
    assert params == [COORDINATOR_ID]


def test_ac1_only_the_assigned_coordinator_can_read_or_decide_a_change_request(setup):
    """
    Summary: GET /change-requests/<id> and PATCH /change-requests/<id>/decision by a coordinator when the event is assigned to a different one each answer 403.
    AC1: The Event Coordinator can view a list of pending change requests for
        events they manage.
    Double: Stub (cursor.fetchone returns a request whose event is assigned to another coordinator); only the two status codes are asserted
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = review_row(coordinator_id=OTHER_ID)

    assert client.get(
        f"/change-requests/{CHANGE_ID}?coordinatorId={COORDINATOR_ID}"
    ).status_code == 403
    assert client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
    ).status_code == 403


def test_ac2_assigned_coordinator_opens_one_change_request_and_sees_its_event_details(setup):
    """
    Summary: GET /change-requests/<id> by the assigned coordinator answers 200 with the request id and the event's current expectedAttendance "30".
    AC2: For each change request, the Event Coordinator can see the event
        details and proposed changes (original vs proposed values), reason for
        change, attachments, request timestamp.
    Double: Stub (cursor.fetchone returns a pending request joined with its event); the response body is the only assertion
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = review_row()
    response = client.get(
        f"/change-requests/{CHANGE_ID}?coordinatorId={COORDINATOR_ID}"
    )
    assert response.status_code == 200
    assert response.json["id"] == CHANGE_ID
    assert response.json["event"]["expectedAttendance"] == "30"


def test_ac3_approving_updates_the_event_and_records_the_decision_in_one_transaction(setup):
    """
    Summary: PATCH /change-requests/<id>/decision with decision "Approved" answers 200 with status 'Approved', the reviewer's id and the event's attendance now "40"; the second statement UPDATEs public."Event", the third UPDATEs public."EventChangeReq" with parameters starting ["Approved", coordinator id, None].
    AC3: The Event Coordinator can approve the change request, where the system
        ppdates the event with the proposed changes, Changes the request status
        to 'Approved', Records the Event Coordinator's identity, approval
        timestamp, and decision
    Double: Stub (cursor.fetchone returns the pending request, the updated event, then the decided request row),
        Mock (the order and parameters of the cursor.execute statements asserted)
    """
    client, _, cursor = setup
    updated_event = event_row("Approved")
    updated_event.update(coordinator_id=COORDINATOR_ID, expected_attendance=40)
    cursor.fetchone.side_effect = [
        review_row(),
        updated_event,
        {
            "status": "Approved",
            "review_date": datetime(2026, 10, 24, 2, 0, tzinfo=UTC),
            "reviewed_by": COORDINATOR_ID,
            "rejection_reason": None,
        },
    ]

    response = client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
    )

    assert response.status_code == 200
    assert response.json["status"] == "Approved"
    assert response.json["reviewedBy"] == COORDINATOR_ID
    assert response.json["event"]["expectedAttendance"] == "40"
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert 'UPDATE public."Event"' in statements[1]
    assert 'UPDATE public."EventChangeReq"' in statements[2]
    assert cursor.execute.call_args_list[2].args[1][:3] == [
        "Approved", COORDINATOR_ID, None,
    ]


def test_ac3_a_change_request_that_is_already_decided_cannot_be_approved_again(setup):
    """
    Summary: PATCH /change-requests/<id>/decision with "Approved" on a request whose status is already 'Approved' answers 409 CHANGE_REQUEST_ALREADY_DECIDED.
    AC3: The Event Coordinator can approve the change request, where the system
        ppdates the event with the proposed changes, Changes the request status
        to 'Approved', Records the Event Coordinator's identity, approval
        timestamp, and decision
    Double: Stub (cursor.fetchone returns an already 'Approved' request); the 409 status and code are asserted
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = review_row(change_status="Approved")
    response = client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
    )
    assert response.status_code == 409
    assert response.json["code"] == "CHANGE_REQUEST_ALREADY_DECIDED"


def test_ac3_approval_is_refused_once_the_event_has_moved_past_the_stage_the_request_was_made_in(setup):
    """
    Summary: PATCH /change-requests/<id>/decision with "Approved" when the event's status is now 'Confirmed' answers 409 CHANGE_REQUEST_NOT_APPLICABLE.
    AC3: The Event Coordinator can approve the change request, where the system
        ppdates the event with the proposed changes, Changes the request status
        to 'Approved', Records the Event Coordinator's identity, approval
        timestamp, and decision
    Double: Stub (cursor.fetchone returns a pending request whose event is 'Confirmed'); the 409 status and code are asserted
    """
    client, _, cursor = setup
    row = review_row()
    row["status"] = "Confirmed"
    cursor.fetchone.return_value = row
    response = client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
    )
    assert response.status_code == 409
    assert response.json["code"] == "CHANGE_REQUEST_NOT_APPLICABLE"


def test_ac3_a_stored_proposal_for_a_field_that_cannot_be_changed_is_not_applied(setup):
    """
    Summary: PATCH /change-requests/<id>/decision with "Approved" when the stored proposal changes status to "Cancelled" answers 409 INVALID_STORED_PROPOSAL.
    AC3: The Event Coordinator can approve the change request, where the system
        ppdates the event with the proposed changes, Changes the request status
        to 'Approved', Records the Event Coordinator's identity, approval
        timestamp, and decision
    Double: Stub (cursor.fetchone returns a pending request whose stored proposal is {"status": "Cancelled"}); the 409 status and code are asserted
    """
    client, _, cursor = setup
    row = review_row()
    row["requested_changes"] = {"status": "Cancelled"}
    cursor.fetchone.return_value = row
    response = client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
    )
    assert response.status_code == 409
    assert response.json["code"] == "INVALID_STORED_PROPOSAL"


def test_ac3_a_stored_proposal_that_would_now_make_the_event_invalid_is_not_applied(setup):
    """
    Summary: PATCH /change-requests/<id>/decision with "Approved" when the stored proposal sets an end time before the start answers 409 INVALID_STORED_PROPOSAL with "Preferred End Date & Time must be after the start."
    AC3: The Event Coordinator can approve the change request, where the system
        ppdates the event with the proposed changes, Changes the request status
        to 'Approved', Records the Event Coordinator's identity, approval
        timestamp, and decision
    Double: Stub (cursor.fetchone returns a pending request whose stored proposal has an end before the start); the 409 status, code and errors are asserted
    """
    client, _, cursor = setup
    row = review_row()
    row["requested_changes"] = {"preferredEndDate": "2026-11-01T08:00"}
    cursor.fetchone.return_value = row
    response = client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
    )
    assert response.status_code == 409
    assert response.json["code"] == "INVALID_STORED_PROPOSAL"
    assert response.json["errors"] == ["Preferred End Date & Time must be after the start."]


def test_ac3_a_proposal_whose_values_already_match_the_event_can_still_be_approved_to_close_it(setup):
    """
    Summary: PATCH /change-requests/<id>/decision with "Approved" when the stored proposal equals the event's current attendance (30) answers 200 and no UPDATE of public."Event" is sent.
    AC3: The Event Coordinator can approve the change request, where the system
        ppdates the event with the proposed changes, Changes the request status
        to 'Approved', Records the Event Coordinator's identity, approval
        timestamp, and decision
    Double: Stub (cursor.fetchone returns a pending request with attendance "30", then the decided request row),
        Mock (no cursor.execute call contains an UPDATE of public."Event")
    """
    client, _, cursor = setup
    row = review_row()
    row["requested_changes"] = {"expectedAttendance": "30"}
    cursor.fetchone.side_effect = [
        row,
        {
            "status": "Approved",
            "review_date": datetime(2026, 10, 24, 2, 0, tzinfo=UTC),
            "reviewed_by": COORDINATOR_ID,
            "rejection_reason": None,
        },
    ]
    response = client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
    )
    assert response.status_code == 200
    assert all(
        'UPDATE public."Event"' not in call.args[0]
        for call in cursor.execute.call_args_list
    )


def test_ac4_rejecting_records_the_reason_and_leaves_the_event_unchanged(setup):
    """
    Summary: PATCH /change-requests/<id>/decision with "Rejected" and a reason answers 200 with that rejectionReason; no UPDATE of public."Event" is sent and the second statement UPDATEs public."EventChangeReq".
    AC4: The Event Coordinator can reject the change request with a reason
        (required), where the system Changes the request status to 'Rejected',
        Stores the rejection reason, Records the Event Coordinator's identity,
        rejection timestamp, and reason
    Double: Stub (cursor.fetchone returns the pending request, then the 'Rejected' request row),
        Mock (the statements of cursor.execute asserted to update only public."EventChangeReq")
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        review_row(),
        {
            "status": "Rejected",
            "review_date": datetime(2026, 10, 24, 2, 0, tzinfo=UTC),
            "reviewed_by": COORDINATOR_ID,
            "rejection_reason": "The revised capacity cannot be supported.",
        },
    ]

    response = client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={
            "coordinatorId": COORDINATOR_ID,
            "decision": "Rejected",
            "reason": "The revised capacity cannot be supported.",
        },
    )

    assert response.status_code == 200
    assert response.json["rejectionReason"] == "The revised capacity cannot be supported."
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert all('UPDATE public."Event"' not in statement for statement in statements)
    assert 'UPDATE public."EventChangeReq"' in statements[1]


def test_ac4_a_rejection_without_a_reason_is_refused_before_any_query(setup):
    """
    Summary: PATCH /change-requests/<id>/decision with "Rejected" and a whitespace-only reason answers 400 and no query is sent.
    AC4: The Event Coordinator can reject the change request with a reason
        (required), where the system Changes the request status to 'Rejected',
        Stores the rejection reason, Records the Event Coordinator's identity,
        rejection timestamp, and reason
    Double: Mock (cursor.execute asserted never called)
    """
    client, _, cursor = setup
    response = client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Rejected", "reason": "  "},
    )
    assert response.status_code == 400
    cursor.execute.assert_not_called()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_a_change_request_that_does_not_exist_answers_404_for_read_and_decision(setup):
    """
    Summary: GET /change-requests/<id> and PATCH /change-requests/<id>/decision each answer 404 when the database finds no such request.
    Supporting design check: reading or deciding a change request that does not
        exist is a 404
    Double: Stub (cursor.fetchone returns None)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = None
    assert client.get(
        f"/change-requests/{CHANGE_ID}?coordinatorId={COORDINATOR_ID}"
    ).status_code == 404
    assert client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
    ).status_code == 404


@pytest.mark.parametrize(
    "path,method,body",
    [
        (f"/change-requests/{CHANGE_ID}/decision", "patch", None),
        (f"/change-requests/{CHANGE_ID}/decision", "patch", {"coordinatorId": COORDINATOR_ID, "decision": "Maybe"}),
        (f"/change-requests/{CHANGE_ID}/decision", "patch", {"coordinatorId": COORDINATOR_ID, "decision": "Rejected", "reason": "x" * 2001}),
    ],
    ids=["f_change_requests_change_id_decision_patch_none", "f_change_requests_change_id_decision_patch_coord", "f_change_requests_change_id_decision_patch_coord_2"],
)
def test_malformed_decisions_are_refused_before_any_query(setup, path, method, body):
    """
    Summary: PATCH /change-requests/<id>/decision with a non-JSON body, the decision "Maybe", or a 2001-character rejection reason answers 400 and no query is sent.
    Supporting design check: a decision must be well formed before the database
        is touched
    Double: Mock (cursor.execute asserted never called)
    """
    client, _, cursor = setup
    signed_in(client, role="Event Coordinator")  # decisions are a coordinator's
    if method == "get":
        response = client.get(path)
    else:
        response = client.patch(path, json=body) if body is not None else client.patch(path, data="x")
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_change_request_review_routes_answer_503_when_no_database_is_configured():
    """
    Summary: With no DATABASE_URL set, GET /change-requests, GET /change-requests/<id> and PATCH /change-requests/<id>/decision each answer 503.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None for the database, since the app has none configured; only the Supabase JWKS Stub, which verifies the signed token
    """
    # Arrange (Given)
    client = signed_in(create_app({
        "TESTING": True, "DATABASE_URL": None, "INTERNAL_SERVICE_TOKEN": "workflow-token",
    }).test_client())
    client.environ_base["HTTP_X_INTERNAL_TOKEN"] = "workflow-token"

    # Act + Assert (When / Then)
    assert client.get(f"/change-requests?coordinatorId={COORDINATOR_ID}").status_code == 503
    assert client.get(f"/change-requests/{CHANGE_ID}?coordinatorId={COORDINATOR_ID}").status_code == 503
    assert client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
    ).status_code == 503
