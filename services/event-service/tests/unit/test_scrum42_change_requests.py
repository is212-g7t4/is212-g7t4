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
- Reviewing a change request (-> test_scrum43_review_change_requests.py).
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


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client(), role="Event Organiser"), connection, cursor


def post(client, **overrides):
    body = {
        "organiserId": ORGANISER_ID,
        "changes": {"expectedAttendance": "40"},
        "reason": "More guests accepted the invitation.",
        **overrides,
    }
    return client.post(f"/events/{EVENT_ID}/change-requests", json=body)


@pytest.mark.parametrize("status", ["Submitted", "Under Review", "Approved"])
def test_ac1_ac8_ac9_owner_of_a_submitted_under_review_or_approved_event_records_a_pending_review_request_and_leaves_the_event_alone(setup, status):
    """
    Summary: POST /events/<id>/change-requests by the owner of a 'Submitted', 'Under Review' or 'Approved' event with an attendance change and a reason answers 201 with the new record (id, event id, proposed changes, status 'Pending Review', request time, requester, reason); the INSERT into public."EventChangeReq" uses ON CONFLICT ... WHERE status = 'Pending Review', carries the proposed changes as JSON, and no UPDATE of public."Event" is sent.
    AC1: The Event Organiser can access a "Request Changes" option for events
        they have submitted with status: Submitted, Under Review, or Approved.
    AC8: Given the Event Organiser submits a valid change request, the system
        creates a change request record linked to the event, sets the change
        request status to 'Pending Review', and records the Event Organiser's
        identity, request timestamp, proposed changes, and reason.
    AC9: Submitting a change request does not immediately alter the event's
        existing details or lifecycle status.
    Double: Stub (cursor.fetchone returns the event in the parametrised status, then the saved change-request row),
        Mock (the INSERT query and parameters asserted; no execute call contains an UPDATE of public."Event")
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
def test_ac2_an_event_in_any_other_status_refuses_the_change_request_and_records_nothing(setup, status):
    """
    Summary: POST /events/<id>/change-requests for an event in Draft, Clarification Requested, Rejected, Pending Safety Check, Confirmed, Safety Changes Requested, Completed or Cancelled answers 409 CHANGE_REQUEST_NOT_ALLOWED and only the lookup read ran.
    AC2: The Event Organiser cannot request changes for events with any other
        status, including: Draft, Clarification Requested, Rejected, Pending
        Safety Check, Confirmed, Safety Changes Requested, Completed, or
        Cancelled.
    Double: Stub (cursor.fetchone returns the event in the parametrised status),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(status)
    response = post(client)
    assert response.status_code == 409
    assert response.json["code"] == "CHANGE_REQUEST_NOT_ALLOWED"
    assert len(cursor.execute.call_args_list) == 1


def test_ac4_a_change_request_with_empty_or_non_object_changes_is_refused_before_any_query(setup):
    """
    Summary: POST /events/<id>/change-requests with changes {} or the text "expected attendance" answers 400 and no query is sent.
    AC4: The Event Organiser must propose at least one value that differs from
        the event's current details.
    Double: Mock (cursor.execute asserted never called)
    """
    client, _, cursor = setup
    assert post(client, changes={}).status_code == 400
    assert post(client, changes="expected attendance").status_code == 400
    cursor.execute.assert_not_called()


def test_ac3_a_field_outside_the_editable_list_or_a_non_text_value_is_refused_before_any_query(setup):
    """
    Summary: POST /events/<id>/change-requests proposing a change to status ("Cancelled") or a numeric expectedAttendance (40) answers 400 each time and no query is sent.
    AC3: The Event Organiser can propose changes to the following fields: Event
        name, Event date and/or time, Expected attendance, Venue requirements,
        Accessibility needs, Equipment requirements, Event description/purpose,
        Registration requirements, or any other editable event details.
    Double: Mock (cursor.execute asserted never called)
    """
    client, _, cursor = setup
    assert post(client, changes={"status": "Cancelled"}).status_code == 400
    assert post(client, changes={"expectedAttendance": 40}).status_code == 400
    cursor.execute.assert_not_called()


def test_ac3_a_proposal_that_would_leave_the_event_invalid_is_not_recorded(setup):
    """
    Summary: POST /events/<id>/change-requests proposing an end time before the start answers 400 with "Preferred End Date & Time must be after the start." and only the lookup read ran.
    AC3: The Event Organiser can propose changes to the following fields: Event
        name, Event date and/or time, Expected attendance, Venue requirements,
        Accessibility needs, Equipment requirements, Event description/purpose,
        Registration requirements, or any other editable event details.
    Double: Stub (cursor.fetchone returns the current event),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()
    response = post(client, changes={"preferredEndDate": "2026-11-01T08:00"})
    assert response.status_code == 400
    assert response.json["errors"] == ["Preferred End Date & Time must be after the start."]
    assert len(cursor.execute.call_args_list) == 1


def test_ac3_a_required_event_detail_cannot_be_proposed_as_blank(setup):
    """
    Summary: POST /events/<id>/change-requests proposing a blank eventName answers 400 with missingFields ["Event Name"] and only the lookup read ran.
    AC3: The Event Organiser can propose changes to the following fields: Event
        name, Event date and/or time, Expected attendance, Venue requirements,
        Accessibility needs, Equipment requirements, Event description/purpose,
        Registration requirements, or any other editable event details.
    Double: Stub (cursor.fetchone returns the current event),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()
    response = post(client, changes={"eventName": "  "})
    assert response.status_code == 400
    assert response.json["missingFields"] == ["Event Name"]
    assert len(cursor.execute.call_args_list) == 1


def test_ac4_a_proposal_that_only_repeats_the_current_values_is_refused(setup):
    """
    Summary: POST /events/<id>/change-requests proposing expectedAttendance "30" when the event already has 30 answers 400 with a message saying the value "must differ", and only the lookup read ran.
    AC4: The Event Organiser must propose at least one value that differs from
        the event's current details.
    Double: Stub (cursor.fetchone returns the current event with attendance 30),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()
    response = post(client, changes={"expectedAttendance": "30"})
    assert response.status_code == 400
    assert "must differ" in response.json["message"]
    assert len(cursor.execute.call_args_list) == 1


def test_ac5_a_blank_reason_is_refused_before_any_query(setup):
    """
    Summary: POST /events/<id>/change-requests with a whitespace-only reason answers 400 "A reason or justification is required." and no query is sent.
    AC5: The Event Organiser must provide a reason/justification for the
        requested change (required field).
    Double: Mock (cursor.execute asserted never called)
    """
    client, _, cursor = setup
    response = post(client, reason="   ")
    assert response.status_code == 400
    assert response.json["message"] == "A reason or justification is required."
    cursor.execute.assert_not_called()


def test_ac5_a_reason_that_is_not_text_is_refused_before_any_query(setup):
    """
    Summary: POST /events/<id>/change-requests with the number 123 as the reason answers 400 and no query is sent.
    AC5: The Event Organiser must provide a reason/justification for the
        requested change (required field).
    Double: Mock (cursor.execute asserted never called)
    """
    client, _, cursor = setup
    assert post(client, reason=123).status_code == 400
    cursor.execute.assert_not_called()


def test_ac6_an_organiser_who_did_not_submit_the_event_cannot_request_a_change(setup):
    """
    Summary: POST /events/<id>/change-requests when the event was submitted by a different organiser answers 403 and only the lookup read ran.
    AC6: Only the Event Organiser who submitted the event can submit a change
        request for it.
    Double: Stub (cursor.fetchone returns an event owned by another organiser),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(organiser_id=OTHER_ID)
    response = post(client)
    assert response.status_code == 403
    assert len(cursor.execute.call_args_list) == 1


def test_ac7_a_second_pending_review_request_for_the_same_event_is_refused(setup):
    """
    Summary: POST /events/<id>/change-requests when the INSERT finds a pending request already present (it returns no row) answers 409 CHANGE_REQUEST_ALREADY_PENDING.
    AC7: An event can have only one change request with status 'Pending Review'
        at a time.
    Double: Stub (cursor.fetchone returns the event, then None for the conflicting INSERT)
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), None]
    response = post(client)
    assert response.status_code == 409
    assert response.json["code"] == "CHANGE_REQUEST_ALREADY_PENDING"


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


@pytest.mark.parametrize("body", [None, [], "not an object"], ids=["none", "empty", "not_an_object"])
def test_a_change_request_body_that_is_not_a_json_object_is_refused(setup, body):
    """
    Summary: POST /events/<id>/change-requests with no body, an empty list or a plain string answers 400 and no query is sent.
    Supporting design check: the request body must be a JSON object
    Double: Mock (cursor.execute asserted never called)
    """
    client, _, cursor = setup
    response = client.post(
        f"/events/{EVENT_ID}/change-requests",
        json=body,
    )
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_a_change_request_for_an_event_that_does_not_exist_answers_404(setup):
    """
    Summary: POST /events/<id>/change-requests answers 404 when the database finds no such event.
    Supporting design check: asking to change an event that does not exist is a
        404
    Double: Stub (cursor.fetchone returns None)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = None
    assert post(client).status_code == 404


def test_change_requests_answer_503_when_no_database_is_configured():
    """
    Summary: With no DATABASE_URL set, POST /events/<id>/change-requests answers 503.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None for the database, since the app has none configured; only the Supabase JWKS Stub, which verifies the signed token
    """
    # Arrange (Given)
    app = create_app({"TESTING": True, "DATABASE_URL": None})

    # Act (When)
    response = post(signed_in(app.test_client()))

    # Assert (Then)
    assert response.status_code == 503
