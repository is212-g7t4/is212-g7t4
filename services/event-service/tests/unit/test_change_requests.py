"""
SCRUM-42: Request Change for Submitted Event

User Story
----------
As an Event Organiser, I want to request changes to my submitted event, so that
I can update event details when circumstances change.

Acceptance Criteria
-------------------
AC1: The Event Organiser can access a "Request Changes" option for events they
     have submitted with status: Submitted, Under Review, or Approved.
AC2: The Event Organiser cannot request changes for events with any other
     status, including: Draft, Clarification Requested, Rejected, Pending
     Safety Check, Confirmed, Safety Changes Requested, Completed, or
     Cancelled.
AC3: The Event Organiser can propose changes to the following fields: Event
     name, Event date and/or time, Expected attendance, Venue requirements,
     Accessibility needs, Equipment requirements, Event description/purpose,
     Registration requirements, or any other editable event details.
AC4: The Event Organiser must propose at least one value that differs from the
     event's current details.
AC5: The Event Organiser must provide a reason/justification for the requested
     change (required field).
AC6: Only the Event Organiser who submitted the event can submit a change
     request for it.
AC7: An event can have only one change request with status 'Pending Review' at
     a time.
AC8: Given the Event Organiser submits a valid change request, the system
     creates a change request record linked to the event, sets the change
     request status to 'Pending Review', and records the Event Organiser's
     identity, request timestamp, proposed changes, and reason.
AC9: Submitting a change request does not immediately alter the event's
     existing details or lifecycle status.

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


def change_row():
    return {
        "change_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "event_id": EVENT_ID,
        "requested_changes": {"expectedAttendance": "40"},
        "status": "Pending Review",
        "request_date": datetime(2026, 10, 23, 4, 5, tzinfo=UTC),
        "requested_by": ORGANISER_ID,
        "reason": "More guests accepted the invitation.",
    }


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
    # The review routes are only for Event Workflow Service, which always sends this header (SCRUM-10: fails closed).
    client.environ_base["HTTP_X_INTERNAL_TOKEN"] = "workflow-token"
    return client, connection, cursor


def post(client, **overrides):
    body = {
        "organiserId": ORGANISER_ID,
        "changes": {"expectedAttendance": "40"},
        "reason": "More guests accepted the invitation.",
        **overrides,
    }
    return client.post(f"/events/{EVENT_ID}/change-requests", json=body)


@pytest.mark.parametrize("status", ["Submitted", "Under Review", "Approved"])
def test_eligible_owner_creates_a_pending_audit_record(setup, status):
    """
    Summary: The owner of a Submitted, Under Review or Approved event records a pending change request.
    AC1: The Event Organiser can access a "Request Changes" option for events
        they have submitted with status: Submitted, Under Review, or Approved.
    AC8: Given the Event Organiser submits a valid change request, the system
        creates a change request record linked to the event, sets the change
        request status to 'Pending Review', and records the Event Organiser's
        identity, request timestamp, proposed changes, and reason.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(status), change_row()]

    # Act (When)
    response = post(client)

    # Assert (Then)
    assert response.status_code == 201
    assert response.json == {
        "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "eventId": EVENT_ID,
        "proposedChanges": {"expectedAttendance": "40"},
        "status": "Pending Review",
        "requestedAt": "2026-10-23T04:05:00+00:00",
        "requestedBy": ORGANISER_ID,
        "reason": "More guests accepted the invitation.",
    }
    insert, parameters = cursor.execute.call_args_list[1].args
    assert 'INSERT INTO public."EventChangeReq"' in insert
    assert "ON CONFLICT (event_id) WHERE status = 'Pending Review'" in insert
    assert json.loads(parameters[1]) == {"expectedAttendance": "40"}
    assert all("UPDATE public.\"Event\"" not in call.args[0] for call in cursor.execute.call_args_list)


@pytest.mark.parametrize("status", [
    "Draft", "Clarification Requested", "Rejected", "Pending Safety Check",
    "Confirmed", "Safety Changes Requested", "Completed", "Cancelled",
])
def test_every_other_status_is_refused_without_creating_a_request(setup, status):
    """
    Summary: Any other status refuses the change request and records nothing.
    AC2: The Event Organiser cannot request changes for events with any other
        status, including: Draft, Clarification Requested, Rejected, Pending
        Safety Check, Confirmed, Safety Changes Requested, Completed, or
        Cancelled.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(status)
    response = post(client)
    assert response.status_code == 409
    assert response.json["code"] == "CHANGE_REQUEST_NOT_ALLOWED"
    assert len(cursor.execute.call_args_list) == 1


def test_reason_is_required_before_database_access(setup):
    """
    Summary: A change request without a reason is refused before the database is touched.
    AC5: The Event Organiser must provide a reason/justification for the
        requested change (required field).
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    response = post(client, reason="   ")
    assert response.status_code == 400
    assert response.json["message"] == "A reason or justification is required."
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("body", [None, [], "not an object"], ids=["none", "empty", "not_an_object"])
def test_request_body_must_be_a_json_object(setup, body):
    """
    Summary: A body that is not a JSON object is refused.
    AC3: The Event Organiser can propose changes to the following fields: Event
        name, Event date and/or time, Expected attendance, Venue requirements,
        Accessibility needs, Equipment requirements, Event description/purpose,
        Registration requirements, or any other editable event details.
    Double: None
    """
    client, _, cursor = setup
    response = client.post(
        f"/events/{EVENT_ID}/change-requests",
        json=body,
    )
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_nonempty_changes_are_required_before_database_access(setup):
    """
    Summary: A change request must propose at least one field.
    AC4: The Event Organiser must propose at least one value that differs from
        the event's current details.
    Double: None
    """
    client, _, cursor = setup
    assert post(client, changes={}).status_code == 400
    assert post(client, changes="expected attendance").status_code == 400
    cursor.execute.assert_not_called()


def test_unconfigured_database_returns_service_unavailable():
    """
    Summary: Unconfigured database returns service unavailable.
    AC8: Given the Event Organiser submits a valid change request, the system
        creates a change request record linked to the event, sets the change
        request status to 'Pending Review', and records the Event Organiser's
        identity, request timestamp, proposed changes, and reason.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    app = create_app({"TESTING": True, "DATABASE_URL": None})

    # Act (When)
    response = post(signed_in(app.test_client()))

    # Assert (Then)
    assert response.status_code == 503


def test_reason_must_be_text(setup):
    """
    Summary: A reason that is not text is refused.
    AC5: The Event Organiser must provide a reason/justification for the
        requested change (required field).
    Double: None
    """
    client, _, cursor = setup
    assert post(client, reason=123).status_code == 400
    cursor.execute.assert_not_called()


def test_only_the_event_owner_can_submit(setup):
    """
    Summary: Only the organiser who submitted the event can request a change.
    AC6: Only the Event Organiser who submitted the event can submit a change
        request for it.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(organiser_id=OTHER_ID)
    response = post(client)
    assert response.status_code == 403
    assert len(cursor.execute.call_args_list) == 1


def test_at_least_one_value_must_actually_change(setup):
    """
    Summary: Proposing only current values is refused.
    AC4: The Event Organiser must propose at least one value that differs from
        the event's current details.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()
    response = post(client, changes={"expectedAttendance": "30"})
    assert response.status_code == 400
    assert "must differ" in response.json["message"]
    assert len(cursor.execute.call_args_list) == 1


def test_unknown_fields_and_non_text_values_are_refused_before_database_access(setup):
    """
    Summary: Fields outside the allowed list, or non-text values, are refused.
    AC3: The Event Organiser can propose changes to the following fields: Event
        name, Event date and/or time, Expected attendance, Venue requirements,
        Accessibility needs, Equipment requirements, Event description/purpose,
        Registration requirements, or any other editable event details.
    Double: None
    """
    client, _, cursor = setup
    assert post(client, changes={"status": "Cancelled"}).status_code == 400
    assert post(client, changes={"expectedAttendance": 40}).status_code == 400
    cursor.execute.assert_not_called()


def test_invalid_combined_details_are_not_recorded(setup):
    """
    Summary: A proposal that would leave the event invalid is not recorded.
    AC3: The Event Organiser can propose changes to the following fields: Event
        name, Event date and/or time, Expected attendance, Venue requirements,
        Accessibility needs, Equipment requirements, Event description/purpose,
        Registration requirements, or any other editable event details.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()
    response = post(client, changes={"preferredEndDate": "2026-11-01T08:00"})
    assert response.status_code == 400
    assert response.json["errors"] == ["Preferred End Date & Time must be after the start."]
    assert len(cursor.execute.call_args_list) == 1


def test_required_event_details_cannot_be_proposed_as_blank(setup):
    """
    Summary: Required details cannot be proposed as blank.
    AC3: The Event Organiser can propose changes to the following fields: Event
        name, Event date and/or time, Expected attendance, Venue requirements,
        Accessibility needs, Equipment requirements, Event description/purpose,
        Registration requirements, or any other editable event details.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()
    response = post(client, changes={"eventName": "  "})
    assert response.status_code == 400
    assert response.json["missingFields"] == ["Event Name"]
    assert len(cursor.execute.call_args_list) == 1


def test_one_pending_request_per_event(setup):
    """
    Summary: A second pending change request for the same event is refused.
    AC7: An event can have only one change request with status 'Pending Review'
        at a time.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), None]
    response = post(client)
    assert response.status_code == 409
    assert response.json["code"] == "CHANGE_REQUEST_ALREADY_PENDING"


def test_missing_event_returns_not_found(setup):
    """
    Summary: A change request for an event that does not exist returns 404.
    AC6: Only the Event Organiser who submitted the event can submit a change
        request for it.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = None
    assert post(client).status_code == 404


def test_review_lists_pending_requests_for_events_managed_by_the_coordinator(setup):
    """
    Summary: The coordinator sees pending change requests for their events, original against proposed.
    SCRUM-43 AC1: The Event Coordinator can view a list of pending change
        requests for events they manage.
    SCRUM-43 AC2: For each change request, the Event Coordinator can see the
        event details and proposed changes (original vs proposed values),
        reason for change, attachments, request timestamp.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_review_approval_updates_event_and_decision_in_one_transaction(setup):
    """
    Summary: Approving applies the changes and records the decision in one transaction.
    SCRUM-43 AC3: The Event Coordinator can approve the change request, where
        the system ppdates the event with the proposed changes, Changes the
        request status to 'Approved', Records the Event Coordinator's identity,
        approval timestamp, and decision
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_review_rejection_records_required_reason_without_updating_event(setup):
    """
    Summary: Rejecting records the reason and leaves the event unchanged.
    SCRUM-43 AC4: The Event Coordinator can reject the change request with a
        reason (required), where the system Changes the request status to
        'Rejected', Stores the rejection reason, Records the Event
        Coordinator's identity, rejection timestamp, and reason
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_review_rejection_reason_is_required_before_database_access(setup):
    """
    Summary: A rejection without a reason is refused before the database is touched.
    SCRUM-43 AC4: The Event Coordinator can reject the change request with a
        reason (required), where the system Changes the request status to
        'Rejected', Stores the rejection reason, Records the Event
        Coordinator's identity, rejection timestamp, and reason
    Double: None
    """
    client, _, cursor = setup
    response = client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Rejected", "reason": "  "},
    )
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_review_only_the_assigned_coordinator_can_read_or_decide(setup):
    """
    Summary: Only the event's assigned coordinator can read or decide its change requests.
    SCRUM-43 AC1: The Event Coordinator can view a list of pending change
        requests for events they manage.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_review_assigned_coordinator_can_open_request_details(setup):
    """
    Summary: The assigned coordinator can open one change request's details.
    SCRUM-43 AC2: For each change request, the Event Coordinator can see the
        event details and proposed changes (original vs proposed values),
        reason for change, attachments, request timestamp.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = review_row()
    response = client.get(
        f"/change-requests/{CHANGE_ID}?coordinatorId={COORDINATOR_ID}"
    )
    assert response.status_code == 200
    assert response.json["id"] == CHANGE_ID
    assert response.json["event"]["expectedAttendance"] == "30"


def test_review_a_decided_request_cannot_be_processed_again(setup):
    """
    Summary: A change request already decided cannot be decided again.
    SCRUM-43 AC3: The Event Coordinator can approve the change request, where
        the system ppdates the event with the proposed changes, Changes the
        request status to 'Approved', Records the Event Coordinator's identity,
        approval timestamp, and decision
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = review_row(change_status="Approved")
    response = client.patch(
        f"/change-requests/{CHANGE_ID}/decision",
        json={"coordinatorId": COORDINATOR_ID, "decision": "Approved"},
    )
    assert response.status_code == 409
    assert response.json["code"] == "CHANGE_REQUEST_ALREADY_DECIDED"


def test_review_missing_request_returns_not_found_for_read_and_decision(setup):
    """
    Summary: A change request that does not exist returns 404 for read and decision.
    SCRUM-43 AC2: For each change request, the Event Coordinator can see the
        event details and proposed changes (original vs proposed values),
        reason for change, attachments, request timestamp.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_review_approval_is_refused_if_event_stage_has_moved_on(setup):
    """
    Summary: Approval is refused once the event has moved past the stage the request was made in.
    SCRUM-43 AC3: The Event Coordinator can approve the change request, where
        the system ppdates the event with the proposed changes, Changes the
        request status to 'Approved', Records the Event Coordinator's identity,
        approval timestamp, and decision
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_review_invalid_stored_proposal_is_refused(setup):
    """
    Summary: A stored proposal that can no longer be read is not applied.
    SCRUM-43 AC3: The Event Coordinator can approve the change request, where
        the system ppdates the event with the proposed changes, Changes the
        request status to 'Approved', Records the Event Coordinator's identity,
        approval timestamp, and decision
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_review_stored_proposal_must_still_form_a_valid_event(setup):
    """
    Summary: A stored proposal that would now make the event invalid is not applied.
    SCRUM-43 AC3: The Event Coordinator can approve the change request, where
        the system ppdates the event with the proposed changes, Changes the
        request status to 'Approved', Records the Event Coordinator's identity,
        approval timestamp, and decision
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_review_already_applied_values_can_still_close_the_request(setup):
    """
    Summary: A proposal whose values already match the event can still be approved to close it.
    SCRUM-43 AC3: The Event Coordinator can approve the change request, where
        the system ppdates the event with the proposed changes, Changes the
        request status to 'Approved', Records the Event Coordinator's identity,
        approval timestamp, and decision
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


@pytest.mark.parametrize(
    "path,method,body",
    [
        (f"/change-requests/{CHANGE_ID}/decision", "patch", None),
        (f"/change-requests/{CHANGE_ID}/decision", "patch", {"coordinatorId": COORDINATOR_ID, "decision": "Maybe"}),
        (f"/change-requests/{CHANGE_ID}/decision", "patch", {"coordinatorId": COORDINATOR_ID, "decision": "Rejected", "reason": "x" * 2001}),
    ],
    ids=["f_change_requests_change_id_decision_patch_none", "f_change_requests_change_id_decision_patch_coord", "f_change_requests_change_id_decision_patch_coord_2"],
)
def test_review_malformed_requests_are_rejected_before_database_access(setup, path, method, body):
    """
    Summary: Malformed review requests are refused before the database is touched.
    SCRUM-43 AC4: The Event Coordinator can reject the change request with a
        reason (required), where the system Changes the request status to
        'Rejected', Stores the rejection reason, Records the Event
        Coordinator's identity, rejection timestamp, and reason
    Double: None
    """
    client, _, cursor = setup
    signed_in(client, role="Event Coordinator")  # decisions are a coordinator's (SCRUM-10)
    if method == "get":
        response = client.get(path)
    else:
        response = client.patch(path, json=body) if body is not None else client.patch(path, data="x")
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_review_unconfigured_database_returns_service_unavailable():
    """
    Summary: Review unconfigured database returns service unavailable.
    AC8: Given the Event Organiser submits a valid change request, the system
        creates a change request record linked to the event, sets the change
        request status to 'Pending Review', and records the Event Organiser's
        identity, request timestamp, proposed changes, and reason.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_review_internal_endpoints_honor_the_configured_service_token(monkeypatch):
    """
    Summary: The internal review routes accept only the configured service token.
    SCRUM-10 AC2: Given an authenticated user's role does not permit them to
        modify particular information, when they attempt to change that
        information, then the modification is prevented and the existing
        information remains unchanged.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_review_routes_fail_closed_when_the_service_token_is_not_configured(monkeypatch):
    """
    Summary: Without a configured service token the internal routes answer 503 and touch nothing.
    SCRUM-10 AC2: Given an authenticated user's role does not permit them to
        modify particular information, when they attempt to change that
        information, then the modification is prevented and the existing
        information remains unchanged.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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
