"""
SCRUM-16: Request Amendment on Event Submission

User Story
----------
As an Event Coordinator, I want to request an amendment on a submitted event
request assigned to me, so that the Event Organiser can update specific details
before I decide.

Acceptance Criteria
-------------------
AC1: Given an Event Request has status 'Submitted' and is assigned to the
     current Event Coordinator, when they request an amendment, then the status
     changes to 'Amendment Requested', and the Coordinator must specify which
     field(s) require changes.
AC2: The reason/details for the amendment are stored with the request.
AC3: The Event Organiser can edit only the fields flagged by the Event
     Coordinator; all other submitted fields remain locked.
AC4: Given the Event Organiser resubmits after amending, the status changes
     back to 'Submitted', the amendment timestamp is recorded, and the request
     remains assigned to the same Event Coordinator.
AC5: The requesting Event Coordinator's identity and timestamp are recorded for
     auditability.

Real
----
- The Event Service routes in app/__init__.py and the rules in app/models.py,
  run through a real create_app(): request validation, the caller's role and
  ownership checks from the signed token, the status rules, the amendment-field
  lock, and the SQL and parameters sent to the database. A few tests call the
  model functions directly (decide_event, update_event_coordinator, ...).
- Assertions are on the HTTP status, the response body and the queries and
  parameters the cursor received.

Doubled
-------
- psycopg2.connect: Stub (fixture) - a MagicMock connection whose cursor
  returns canned rows; Mock - its execute calls are asserted to prove what was
  (or was not) written.
- Supabase JWKS: Stub (tests/conftest.py) - tokens are signed with a
  throwaway ES256 key.
- ActingClient (tests/unit/factories.py): Stub - lifts coordinatorId /
  organiserId out of the request and sends them as that user's signed bearer
  token, so the identity the app sees is always the token's, never the body's.

Not proven
----------
- That the SQL runs against the real Postgres schema, constraints and row locks
  (-> tests/integration/ against a throwaway postgres:17.6).
"""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.models import (
    EDITABLE_FIELDS,
    FIELDS,
    VENUE_CHANGE_WITHDRAW,
    ChangeRequestNotAllowedError,
    EventClosedError,
    EventNotSubmittedError,
    decide_change_request,
    decide_event,
    request_event_clarification,
    respond_to_event_clarification,
    serialize,
    unpack_amendments,
    update_event_coordinator,
    update_event_details,
    update_event_progress,
    update_event_safety_status,
)
from tests.unit.factories import signed_in

EVENT_ID = "00000000-0000-4000-8000-000000000016"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OTHER_COORDINATOR_ID = "22222222-2222-4222-8222-222222222222"
ORGANISER_ID = "33333333-3333-4333-8333-333333333333"
OTHER_ORGANISER_ID = "44444444-4444-4444-8444-444444444444"
LEAD_ID = "55555555-5555-4555-8555-555555555555"
CHANGE_ID = "66666666-6666-4666-8666-666666666666"
ROUND_ID = "77777777-7777-4777-8777-777777777777"
NEXT_ROUND_ID = "88888888-8888-4888-8888-888888888888"
URL = "unused-test-url"

REASON = "The hall is booked that week and 300 exceeds every room."


def open_amendment(fields=("preferredStartDate", "preferredEndDate", "expectedAttendance")):
    return {
        "id": "amendment-1",
        "fields": list(fields),
        "reason": REASON,
        "requestedBy": COORDINATOR_ID,
        "requestedAt": "2026-10-20T01:00:00+00:00",
        "resubmittedBy": None,
        "resubmittedAt": None,
        "changes": None,
        "note": None,
    }


def event_row(
    status="Under Review",
    coordinator_id=COORDINATOR_ID,
    organiser_id=ORGANISER_ID,
    amendments=None,
    action_history=None,
    clarifications=None,
):
    row = {column: "" for column in FIELDS.values()}
    row.update(
        event_id=EVENT_ID,
        event_name="Community Workshop",
        status=status,
        coordinator_id=coordinator_id,
        organiser_id=organiser_id,
        assigned_by=LEAD_ID,
        assigned_at=datetime(2026, 10, 2, 8, tzinfo=UTC),
        previous_coordinator_id=None,
        submission_date=datetime(2026, 10, 1, 8, tzinfo=UTC),
        preferred_start_date=datetime(2030, 10, 10, 9),
        preferred_end_date=datetime(2030, 10, 10, 12),
        expected_attendance=300,
        venue_requirements="Main hall",
        withdrawal_deadline=None,
    )
    row["description"] = json.dumps({
        "_connectsphere": "event-submission-v1",
        "description": "A practical workshop",
        "purpose": "Learning",
        "decision": None,
        "decisionHistory": [],
        "actionDetails": "Review started.",
        "actionHistory": action_history or [],
        "clarificationHistory": clarifications or [],
        "amendmentHistory": [] if amendments is None else amendments,
    })
    return row


def amending_row(**overrides):
    return event_row("Amendment Requested", amendments=[open_amendment()], **overrides)


def change_request_columns():
    return {
        "change_id": CHANGE_ID,
        "requested_changes": {"eventName": "Renamed Workshop"},
        "change_request_status": "Pending Review",
        "request_date": datetime(2026, 10, 23, tzinfo=UTC),
        "requested_by": ORGANISER_ID,
        "reason": "Rename",
        "rejection_reason": None,
        "review_date": None,
        "reviewed_by": None,
    }


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": URL})
    return signed_in(app.test_client()), connection, cursor


def request_amendment(client, **overrides):
    body = {
        "coordinatorId": COORDINATOR_ID,
        "fields": ["preferredStartDate", "expectedAttendance"],
        "reason": REASON,
        **overrides,
    }
    return client.patch(f"/events/{EVENT_ID}/amendment-request", json=body)


def respond(client, **overrides):
    body = {
        "organiserId": ORGANISER_ID,
        "changes": {"expectedAttendance": "120"},
        **overrides,
    }
    return client.patch(f"/events/{EVENT_ID}/amendment-response", json=body)


def written(cursor):
    """The (query, parameters) of the UPDATE the call made."""
    query, parameters = cursor.execute.call_args_list[1].args
    assert query.lstrip().startswith('UPDATE public."Event"')
    return query, parameters


def written_metadata(cursor):
    _, parameters = written(cursor)
    return json.loads(parameters[-2])


def assert_nothing_written(cursor):
    assert all(
        not call.args[0].lstrip().startswith("UPDATE")
        for call in cursor.execute.call_args_list
    )


# AC1: request an amendment --------------------------------------------------


def test_ac1_assigned_coordinator_request_moves_event_to_amendment_requested(setup):
    """
    Summary: An 'Under Review' request assigned to the caller moves to 'Amendment Requested'.
    AC1: Given an Event Request has status 'Submitted' and is assigned to the
        current Event Coordinator, when they request an amendment, then the
        status changes to 'Amendment Requested', and the Coordinator must
        specify which field(s) require changes.
    Double: Stub (cursor.fetchone returns the 'Under Review' event, then the updated
        'Amendment Requested' row); Mock (the UPDATE's SQL and parameters; connection.__exit__
        asserted once = the transaction committed)
    """
    # Arrange (Given)
    client, connection, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row("Amendment Requested")]

    # Act (When)
    response = request_amendment(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Amendment Requested"
    query, parameters = written(cursor)
    assert "SET status = 'Amendment Requested', description = %s" in query
    assert "coordinator_id" not in query.split("RETURNING")[0]
    assert "submission_date" not in query.split("RETURNING")[0]
    assert parameters[1] == EVENT_ID
    connection.__exit__.assert_called_once()


def test_ac1_submitted_status_also_accepts_an_amendment_request(setup):
    """
    Summary: The literal AC status, 'Submitted', is accepted as well.
    AC1: Given an Event Request has status 'Submitted' and is assigned to the
        current Event Coordinator, when they request an amendment, then the
        status changes to 'Amendment Requested', and the Coordinator must
        specify which field(s) require changes.
    Double: Stub (cursor.fetchone returns the 'Submitted' event, then the updated row)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row("Submitted"), event_row("Amendment Requested")]

    # Act + Assert (When / Then)
    assert request_amendment(client).status_code == 200


@pytest.mark.parametrize("fields", [[], None, "expectedAttendance", ["expectedAttendance", 3]], ids=["empty", "none", "expectedattendance", "expectedattendance_3"])
def test_ac1_at_least_one_field_must_be_flagged(fields, setup):
    """
    Summary: No list, an empty list, or a non-string entry is refused before any database work.
    AC1: Given an Event Request has status 'Submitted' and is assigned to the
        current Event Coordinator, when they request an amendment, then the
        status changes to 'Amendment Requested', and the Coordinator must
        specify which field(s) require changes.
    Double: Mock (cursor.execute, asserted never called)
    """
    # Arrange (Given)
    client, _, cursor = setup
    body = {"coordinatorId": COORDINATOR_ID, "reason": REASON}
    if fields is not None:
        body["fields"] = fields

    # Act (When)
    response = client.patch(f"/events/{EVENT_ID}/amendment-request", json=body)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "Flag at least one field that needs amending."
    cursor.execute.assert_not_called()


def test_ac1_unknown_field_is_refused_with_invalid_fields(setup):
    """
    Summary: The withdrawal deadline and unknown names can't be flagged; both are named, sorted.
    AC1: Given an Event Request has status 'Submitted' and is assigned to the
        current Event Coordinator, when they request an amendment, then the
        status changes to 'Amendment Requested', and the Coordinator must
        specify which field(s) require changes.
    Double: Mock (cursor.execute, asserted never called)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = request_amendment(client, fields=["withdrawalDeadline", "nope", "eventName"])

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "One or more flagged fields cannot be amended."
    assert response.json["invalidFields"] == ["nope", "withdrawalDeadline"]
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("coordinator_id", [OTHER_COORDINATOR_ID, None], ids=["other_coordinator_id", "none"])
def test_ac1_only_the_assigned_coordinator_may_request(coordinator_id, setup):
    """
    Summary: Another coordinator's event, or an unassigned one, is 403 and is not written.
    AC1: Given an Event Request has status 'Submitted' and is assigned to the
        current Event Coordinator, when they request an amendment, then the
        status changes to 'Amendment Requested', and the Coordinator must
        specify which field(s) require changes.
    Double: Stub (cursor.fetchone returns an 'Under Review' event assigned to another
        coordinator, or to nobody); Mock (cursor.execute call_count == 1: the SELECT ran, no
        UPDATE followed)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=coordinator_id)

    # Act (When)
    response = request_amendment(client)

    # Assert (Then)
    assert response.status_code == 403
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("status", [
    "Approved", "Rejected", "Clarification Requested", "Amendment Requested",
    "Pending Safety Check", "Confirmed",
])
def test_ac1_wrong_status_is_refused_with_current_status(status, setup):
    """
    Summary: Only 'Submitted'/'Under Review' can be sent back; one open amendment at a time.
    AC1: Given an Event Request has status 'Submitted' and is assigned to the
        current Event Coordinator, when they request an amendment, then the
        status changes to 'Amendment Requested', and the Coordinator must
        specify which field(s) require changes.
    Double: Stub (cursor.fetchone returns the assigned event at each non-amendable status);
        Mock (cursor.execute calls scanned: no UPDATE was issued)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(status)

    # Act (When)
    response = request_amendment(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "AMENDMENT_NOT_ALLOWED"
    assert response.json["currentStatus"] == status
    assert_nothing_written(cursor)


# AC2: the reason is stored with the request ---------------------------------


@pytest.mark.parametrize("reason", [None, "", "   ", ["a list"]], ids=["none", "empty", "empty_2", "a_list"])
def test_ac2_reason_is_required(reason, setup):
    """
    Summary: A missing, blank or non-text reason is refused.
    AC2: The reason/details for the amendment are stored with the request.
    Double: Mock (cursor.execute, asserted never called); no rows stubbed because validation
        refuses the request first
    """
    client, _, cursor = setup
    body = {"coordinatorId": COORDINATOR_ID, "fields": ["eventName"]}
    if reason is not None:
        body["reason"] = reason
    response = client.patch(f"/events/{EVENT_ID}/amendment-request", json=body)
    assert response.status_code == 400
    assert response.json["message"] == "A reason for the amendment is required."
    cursor.execute.assert_not_called()


def test_ac2_reason_and_fields_are_stored_in_amendment_history(setup):
    """
    Summary: The new round carries the trimmed reason and the flagged fields, still open.
    AC2: The reason/details for the amendment are stored with the request.
    Double: Stub (cursor.fetchone returns the 'Under Review' event, then the updated row);
        Mock (the UPDATE's metadata JSON parameter, parsed to read the new round and the
        untouched description and actionDetails)
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row("Amendment Requested")]

    request_amendment(client, reason=f"  {REASON}  ")

    stored = written_metadata(cursor)
    amendment = stored["amendmentHistory"][-1]
    assert amendment["reason"] == REASON
    assert amendment["fields"] == ["preferredStartDate", "preferredEndDate", "expectedAttendance"]
    assert amendment["id"]
    assert amendment["resubmittedAt"] is None
    assert amendment["changes"] is None
    # Everything else in the metadata survives.
    assert stored["description"] == "A practical workshop"
    assert stored["actionDetails"] == "Review started."


def test_ac2_existing_history_is_kept_when_a_second_round_opens(setup):
    """
    Summary: A second round is appended; the closed first round is untouched.
    AC2: The reason/details for the amendment are stored with the request.
    Double: Stub (cursor.fetchone returns a 'Submitted' event holding one closed round, then
        the updated row); Mock (the UPDATE's metadata JSON parameter, parsed to compare the
        history)
    """
    client, _, cursor = setup
    closed = {**open_amendment(), "resubmittedAt": "2026-10-21T01:00:00+00:00"}
    cursor.fetchone.side_effect = [
        event_row("Submitted", amendments=[closed]),
        event_row("Amendment Requested"),
    ]
    request_amendment(client)
    history = written_metadata(cursor)["amendmentHistory"]
    assert len(history) == 2
    assert history[0] == closed
    assert history[1]["resubmittedAt"] is None


# AC3: only the flagged fields can change ------------------------------------


def test_ac3_changing_an_unflagged_field_is_refused_and_nothing_is_written(setup):
    """
    Summary: A flagged + an unflagged change is refused whole, naming the locked field.
    AC3: The Event Organiser can edit only the fields flagged by the Event
        Coordinator; all other submitted fields remain locked.
    Double: Stub (cursor.fetchone.return_value: the event with one open round flagging dates
        and attendance); Mock (cursor.execute calls scanned: no UPDATE was issued)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = amending_row()
    response = respond(
        client,
        changes={"expectedAttendance": "120", "venueRequirements": "Hall B", "eventName": "X"},
    )
    assert response.status_code == 400
    assert response.json["code"] == "AMENDMENT_FIELD_LOCKED"
    assert response.json["lockedFields"] == ["eventName", "venueRequirements"]
    assert_nothing_written(cursor)


def test_ac3_sending_an_unflagged_field_with_its_current_value_is_still_refused(setup):
    """
    Summary: Even resending a locked field's own value is refused: the lock is on the key.
    AC3: The Event Organiser can edit only the fields flagged by the Event
        Coordinator; all other submitted fields remain locked.
    Double: Stub (cursor.fetchone.return_value: the event with one open round flagging dates
        and attendance); Mock (cursor.execute calls scanned: no UPDATE was issued)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = amending_row()
    response = respond(
        client, changes={"expectedAttendance": "120", "venueRequirements": "Main hall"}
    )
    assert response.status_code == 400
    assert response.json["lockedFields"] == ["venueRequirements"]
    assert_nothing_written(cursor)


def test_ac3_description_and_purpose_amendments_are_written_to_metadata(setup):
    """
    Summary: Description and purpose live in the metadata JSON, so no column is written.
    AC3: The Event Organiser can edit only the fields flagged by the Event
        Coordinator; all other submitted fields remain locked.
    Double: Stub (cursor.fetchone returns the event with an open round flagging description
        and purpose, then the 'Submitted' row); Mock (the UPDATE's SQL, parameter count, and
        metadata JSON parsed to read the stored values and the from/to changes)
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row(
            "Amendment Requested",
            amendments=[open_amendment(["description", "purpose"])],
        ),
        event_row("Submitted"),
    ]

    response = respond(client, changes={"description": " Hands-on session ", "purpose": "Skills"})

    assert response.status_code == 200
    query, parameters = written(cursor)
    assert "SET description = %s, status = 'Submitted'" in query
    assert len(parameters) == 2
    stored = written_metadata(cursor)
    assert stored["description"] == "Hands-on session"
    assert stored["purpose"] == "Skills"
    assert stored["amendmentHistory"][-1]["changes"] == {
        "description": {"from": "A practical workshop", "to": "Hands-on session"},
        "purpose": {"from": "Learning", "to": "Skills"},
    }


def test_ac3_only_the_purpose_changes_when_only_it_is_amended(setup):
    """
    Summary: A flagged field sent back unchanged is not recorded as a change.
    AC3: The Event Organiser can edit only the fields flagged by the Event
        Coordinator; all other submitted fields remain locked.
    Double: Stub (cursor.fetchone returns the event with an open round flagging description
        and purpose, then the 'Submitted' row); Mock (the UPDATE's metadata JSON parameter,
        parsed to read the stored values and which fields the round recorded as changed)
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row(
            "Amendment Requested",
            amendments=[open_amendment(["description", "purpose"])],
        ),
        event_row("Submitted"),
    ]
    respond(client, changes={"description": "A practical workshop", "purpose": "Skills"})
    stored = written_metadata(cursor)
    assert stored["description"] == "A practical workshop"
    assert stored["purpose"] == "Skills"
    assert list(stored["amendmentHistory"][-1]["changes"]) == ["purpose"]


def test_ac3_text_column_amendment_is_written_trimmed(setup):
    """
    Summary: A text column is written as the trimmed value.
    AC3: The Event Organiser can edit only the fields flagged by the Event
        Coordinator; all other submitted fields remain locked.
    Double: Stub (cursor.fetchone returns the event with an open round flagging
        venueRequirements, then the 'Submitted' row); Mock (the UPDATE's SQL and first
        parameter)
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Amendment Requested", amendments=[open_amendment(["venueRequirements"])]),
        event_row("Submitted"),
    ]
    respond(client, changes={"venueRequirements": "  Hall B  "})
    query, parameters = written(cursor)
    assert "SET venue_requirements = %s, description = %s" in query
    assert parameters[0] == "Hall B"


def test_ac3_an_open_round_with_corrupt_fields_locks_everything(setup):
    """
    Summary: If the stored flagged list is unreadable, no field is editable.
    AC3: The Event Organiser can edit only the fields flagged by the Event
        Coordinator; all other submitted fields remain locked.
    Double: Stub (cursor.fetchone.return_value: an 'Amendment Requested' event whose open
        round stores "fields" as a string, not a list); no execute assertions - only the
        400 and its code are checked
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(
        "Amendment Requested", amendments=[{**open_amendment(), "fields": "expectedAttendance"}]
    )

    # Act (When)
    response = respond(client)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["code"] == "AMENDMENT_FIELD_LOCKED"


# AC4: the organiser resubmits -----------------------------------------------


def test_ac4_resubmission_returns_status_to_submitted(setup):
    """
    Summary: The UPDATE sets 'Submitted' and writes the changed column.
    AC4: Given the Event Organiser resubmits after amending, the status changes
        back to 'Submitted', the amendment timestamp is recorded, and the
        request remains assigned to the same Event Coordinator.
    Double: Stub (cursor.fetchone returns the 'Amendment Requested' event, then the
        'Submitted' row); Mock (the UPDATE's SQL and parameters; connection.__exit__ asserted
        once = the transaction committed)
    """
    # Arrange (Given)
    client, connection, cursor = setup
    cursor.fetchone.side_effect = [amending_row(), event_row("Submitted")]

    # Act (When)
    response = respond(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Submitted"
    query, parameters = written(cursor)
    assert "SET expected_attendance = %s, description = %s, status = 'Submitted'" in query
    assert parameters[0] == 120
    assert parameters[-1] == EVENT_ID
    connection.__exit__.assert_called_once()


def test_ac4_resubmission_keeps_the_same_coordinator(setup):
    """
    Summary: Neither the coordinator nor the assignment is written, and the response keeps them.
    AC4: Given the Event Organiser resubmits after amending, the status changes
        back to 'Submitted', the amendment timestamp is recorded, and the
        request remains assigned to the same Event Coordinator.
    Double: Stub (cursor.fetchone returns the 'Amendment Requested' event, then the
        'Submitted' row); Mock (the UPDATE's SET clause, checked for the absence of
        coordinator_id, assigned_by and assigned_at)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [amending_row(), event_row("Submitted")]

    # Act (When)
    response = respond(client)

    # Assert (Then)
    query, _ = written(cursor)
    set_clause = query.split("RETURNING")[0]
    for column in ("coordinator_id", "assigned_by", "assigned_at"):
        assert column not in set_clause
    assert response.json["coordinatorId"] == COORDINATOR_ID


def test_ac4_amendment_timestamp_is_recorded(setup):
    """
    Summary: The open round is closed with who, when, the from/to changes and the note; the
        actionHistory entry names the organiser and changed fields; the submission date is
        not rewritten.
    AC4: Given the Event Organiser resubmits after amending, the status changes
        back to 'Submitted', the amendment timestamp is recorded, and the
        request remains assigned to the same Event Coordinator.
    Double: Stub (cursor.fetchone returns the 'Amendment Requested' event, then the
        'Submitted' row); Mock (the UPDATE's SQL, and its metadata JSON parameter parsed to
        read the closed round and the actionHistory entry)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [amending_row(), event_row("Submitted")]
    before = datetime.now(UTC)

    # Act (When)
    respond(
        client,
        changes={"expectedAttendance": "120", "preferredStartDate": "2030-10-10T10:00"},
        note="  Moved an hour later.  ",
    )

    # Assert (Then)
    query, _ = written(cursor)
    assert "submission_date" not in query.split("RETURNING")[0]
    stored = written_metadata(cursor)
    amendment = stored["amendmentHistory"][-1]
    assert amendment["resubmittedBy"] == ORGANISER_ID
    assert before <= datetime.fromisoformat(amendment["resubmittedAt"]) <= datetime.now(UTC)
    assert amendment["note"] == "Moved an hour later."
    assert amendment["changes"] == {
        "preferredStartDate": {"from": "2030-10-10T09:00:00", "to": "2030-10-10T10:00:00"},
        "expectedAttendance": {"from": "300", "to": "120"},
    }
    # The request side of the round is unchanged.
    assert amendment["reason"] == REASON
    assert amendment["requestedBy"] == COORDINATOR_ID
    action = stored["actionHistory"][-1]
    assert action["status"] == "Submitted"
    assert action["organiserId"] == ORGANISER_ID
    assert action["changedFields"] == ["preferredStartDate", "expectedAttendance"]
    assert action["details"] == (
        "Event Organiser resubmitted the amended request: Date/time and Expected attendance."
    )


@pytest.mark.parametrize("organiser_id", [OTHER_ORGANISER_ID, None], ids=["other_organiser_id", "none"])
def test_ac4_only_the_owning_organiser_may_resubmit(organiser_id, setup):
    """
    Summary: Another organiser (or an event with none) is 403 and nothing is written.
    AC4: Given the Event Organiser resubmits after amending, the status changes
        back to 'Submitted', the amendment timestamp is recorded, and the
        request remains assigned to the same Event Coordinator.
    Double: Stub (cursor.fetchone.return_value: an 'Amendment Requested' event owned by
        another organiser, or by nobody); Mock (cursor.execute call_count == 1: the SELECT
        ran, no UPDATE followed)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = amending_row(organiser_id=organiser_id)
    response = respond(client)
    assert response.status_code == 403
    assert response.json["message"] == "You can only amend event requests you created."
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("row", [None, event_row("Draft")], ids=["none", "event_row_draft"])
def test_ac4_resubmitting_a_missing_or_draft_event_is_not_found(row, setup):
    """
    Summary: Missing and draft events are 404.
    AC4: Given the Event Organiser resubmits after amending, the status changes
        back to 'Submitted', the amendment timestamp is recorded, and the
        request remains assigned to the same Event Coordinator.
    Double: Stub (cursor.fetchone returns None, or a 'Draft' row); no execute assertions -
        only the 404 is checked
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = row

    # Act + Assert (When / Then)
    assert respond(client).status_code == 404


@pytest.mark.parametrize("status", ["Submitted", "Under Review", "Clarification Requested", "Approved"])
def test_ac4_resubmitting_without_an_open_amendment_status_is_refused(status, setup):
    """
    Summary: Only an event in 'Amendment Requested' can be resubmitted.
    AC4: Given the Event Organiser resubmits after amending, the status changes
        back to 'Submitted', the amendment timestamp is recorded, and the
        request remains assigned to the same Event Coordinator.
    Double: Stub (cursor.fetchone.return_value: the owned event at each non-amending status,
        still holding an open round); Mock (cursor.execute calls scanned: no UPDATE was issued)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(status, amendments=[open_amendment()])

    # Act (When)
    response = respond(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "AMENDMENT_NOT_OPEN"
    assert_nothing_written(cursor)


@pytest.mark.parametrize("amendments", [
    [],
    [{**open_amendment(), "resubmittedAt": "2026-10-21T01:00:00+00:00"}],
    ["not an entry"],
], ids=["empty", "open_amendment_resubmittedat_2026_10_21t01_00_00", "not_an_entry"])
def test_ac4_resubmitting_with_no_open_round_is_refused_even_if_status_is_stale(amendments, setup):
    """
    Summary: The status alone isn't enough; the history must hold an open round.
    AC4: Given the Event Organiser resubmits after amending, the status changes
        back to 'Submitted', the amendment timestamp is recorded, and the
        request remains assigned to the same Event Coordinator.
    Double: Stub (cursor.fetchone.return_value: an 'Amendment Requested' event whose history
        is empty, already closed, or not a dict); no execute assertions - only the 409 and
        its code are checked
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Amendment Requested", amendments=amendments)

    # Act (When)
    response = respond(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "AMENDMENT_NOT_OPEN"


def test_ac4_reassigning_an_amendment_requested_event_is_refused_by_the_model(setup):
    """
    Summary: update_event_coordinator raises EventClosedError for an event under amendment.
    AC4: Given the Event Organiser resubmits after amending, the status changes
        back to 'Submitted', the amendment timestamp is recorded, and the
        request remains assigned to the same Event Coordinator.
    Double: Stub (cursor.fetchone.return_value: the event's coordinator_id and status
        'Amendment Requested'); the EventClosedError is the assertion, no execute calls are
        checked
    """
    # Arrange (Given)
    _, _, cursor = setup
    cursor.fetchone.return_value = {"coordinator_id": COORDINATOR_ID, "status": "Amendment Requested"}

    # Act + Assert (When / Then)
    with pytest.raises(EventClosedError):
        update_event_coordinator(URL, EVENT_ID, OTHER_COORDINATOR_ID, LEAD_ID)


def test_ac4_reassigning_an_amendment_requested_event_returns_409_over_http(setup):
    """
    Summary: A Lead can't reassign while the amendment is open; the route answers 409.
    AC4: Given the Event Organiser resubmits after amending, the status changes
        back to 'Submitted', the amendment timestamp is recorded, and the
        request remains assigned to the same Event Coordinator.
    Double: Stub (cursor.fetchone.return_value: the event's coordinator_id and status
        'Amendment Requested'); no execute assertions - only the 409 and its message are
        checked
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = {"coordinator_id": COORDINATOR_ID, "status": "Amendment Requested"}

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}",
        json={"assignedCoordinatorId": OTHER_COORDINATOR_ID, "assignedBy": LEAD_ID},
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["message"] == "A Amendment Requested event can't be reassigned."


# AC5: the requester and the history are recorded ----------------------------
# Every writer that rebuilds the metadata JSON must carry amendmentHistory
# through, or the auditable record would be erased by the next status change.


def test_ac5_requesting_coordinator_and_timestamp_are_recorded(setup):
    """
    Summary: RequestedBy/requestedAt and an actionHistory entry name the coordinator and time.
    AC5: The requesting Event Coordinator's identity and timestamp are recorded
        for auditability.
    Double: Stub (cursor.fetchone returns the 'Under Review' event, then the updated row);
        Mock (the UPDATE's metadata JSON parameter, parsed to read requestedBy, requestedAt
        and the actionHistory entry)
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row("Amendment Requested")]
    before = datetime.now(UTC)

    request_amendment(client)

    stored = written_metadata(cursor)
    amendment = stored["amendmentHistory"][-1]
    assert amendment["requestedBy"] == COORDINATOR_ID
    requested_at = datetime.fromisoformat(amendment["requestedAt"])
    assert requested_at.utcoffset().total_seconds() == 0
    assert before <= requested_at <= datetime.now(UTC)
    action = stored["actionHistory"][-1]
    assert action == {
        "status": "Amendment Requested",
        "details": "Amendment requested from the Event Organiser: Date/time and Expected attendance.",
        "coordinatorId": COORDINATOR_ID,
        "recordedAt": amendment["requestedAt"],
    }


def _decide_change_request(cursor):
    cursor.fetchone.side_effect = [
        {**event_row(amendments=[open_amendment()]), **change_request_columns()},
        event_row(),
        {"status": "Approved", "review_date": datetime.now(UTC), "reviewed_by": COORDINATOR_ID,
         "rejection_reason": None},
    ]
    decide_change_request(URL, CHANGE_ID, COORDINATOR_ID, "Approved")


def _update_event_progress(cursor):
    cursor.fetchone.side_effect = [event_row(amendments=[open_amendment()]), event_row()]
    update_event_progress(URL, EVENT_ID, COORDINATOR_ID, "Under Review", "Checked.")


def _update_event_safety_status(cursor):
    cursor.fetchone.side_effect = [event_row("Approved", amendments=[open_amendment()]), event_row()]
    update_event_safety_status(
        URL, EVENT_ID, "Pending Safety Check", ROUND_ID, 1, coordinator_id=COORDINATOR_ID
    )


def _venue_change_safety_status(cursor):
    approval = {"status": "Confirmed", "safetyCheckId": ROUND_ID}
    cursor.fetchone.side_effect = [
        event_row("Confirmed", amendments=[open_amendment()], action_history=[approval]),
        event_row(),
    ]
    update_event_safety_status(
        URL, EVENT_ID, "Approved", ROUND_ID, 1, coordinator_id=COORDINATOR_ID,
        # SCRUM-46: this successful withdrawal supplies original venue facts;
        # SQL remains doubled and the inherited amendment assertions stay scoped.
        venue_change={"move": VENUE_CHANGE_WITHDRAW, "reason": "Venue changed.", "venueBefore": "Grand Hall"},
    )


def _update_event_details(cursor):
    cursor.fetchone.side_effect = [event_row(amendments=[open_amendment()]), event_row()]
    update_event_details(URL, EVENT_ID, COORDINATOR_ID, {"eventName": "Renamed Workshop"})


def _request_event_clarification(cursor):
    cursor.fetchone.side_effect = [event_row(amendments=[open_amendment()]), event_row()]
    request_event_clarification(URL, EVENT_ID, COORDINATOR_ID, "Which audience?")


def _respond_to_event_clarification(cursor):
    question = {"id": "c-1", "question": "Which audience?", "response": None}
    cursor.fetchone.side_effect = [
        event_row(
            "Clarification Requested", amendments=[open_amendment()], clarifications=[question]
        ),
        event_row(),
    ]
    respond_to_event_clarification(URL, EVENT_ID, ORGANISER_ID, "Students.")


def _decide_event(cursor):
    cursor.fetchone.side_effect = [event_row(amendments=[open_amendment()]), event_row()]
    decide_event(URL, EVENT_ID, COORDINATOR_ID, "Approved")


@pytest.mark.parametrize("writer", [
    _decide_change_request,
    _update_event_progress,
    _update_event_safety_status,
    _venue_change_safety_status,
    _update_event_details,
    _request_event_clarification,
    _respond_to_event_clarification,
    _decide_event,
], ids=["decide_change_request", "update_event_progress", "update_event_safety_status", "venue_change_safety_status", "update_event_details", "request_event_clarification", "respond_to_event_clarification", "decide_event"])
def test_ac5_amendment_history_survives_every_metadata_writer(writer, setup):
    """
    Summary: Each writer that rebuilds the metadata JSON keeps amendmentHistory as it was.
    AC5: The requesting Event Coordinator's identity and timestamp are recorded
        for auditability.
    Double: Stub (cursor.fetchone rows set by each writer helper: an event holding one open
        round, plus the change-request columns or follow-up row that writer reads); Mock (the
        single UPDATE's parameters, parsed from JSON to find the amendment history)
    """
    # Arrange (Given)
    _, _, cursor = setup
    writer(cursor)

    # Act (When)
    updates = [
        call.args[1]
        for call in cursor.execute.call_args_list
        if call.args[0].lstrip().startswith('UPDATE public."Event"')
    ]

    # Assert (Then)
    assert len(updates) == 1
    expected = [open_amendment()]
    histories = []
    for parameter in updates[0]:
        if not isinstance(parameter, str):
            continue
        try:
            value = json.loads(parameter)
        except ValueError:
            continue
        if isinstance(value, dict) and "amendmentHistory" in value:
            histories.append(value["amendmentHistory"])
        elif value == expected:  # decide_event passes the list on its own
            histories.append(value)
    assert histories == [expected]


# Supporting design checks ---------------------------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# story relies on (validation limits, effects on other flows, configuration).


def test_supporting_flagging_one_date_flags_both(setup):
    """
    Summary: Flagging the end date stores both dates, deduplicated, in EDITABLE_FIELDS order.
    Supporting design check: the two dates are flagged as one "Date/time" pair, stored
        deduplicated and in a fixed order (no acceptance criterion states it)
    Double: Stub (cursor.fetchone returns the 'Under Review' event, then the updated row);
        Mock (the UPDATE's metadata JSON parameter, parsed to read the stored flagged fields)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row("Amendment Requested")]

    # Act (When)
    request_amendment(
        client, fields=["expectedAttendance", "preferredEndDate", "eventName", "eventName"]
    )

    # Assert (Then)
    stored = written_metadata(cursor)["amendmentHistory"][-1]["fields"]
    assert stored == ["eventName", "preferredStartDate", "preferredEndDate", "expectedAttendance"]
    assert stored == [field for field in EDITABLE_FIELDS if field in stored]


def test_supporting_non_date_field_is_stored_without_adding_dates(setup):
    """
    Summary: The pairing only applies to the dates: another field is stored as flagged, and
        the actionHistory line names only that field.
    Supporting design check: flagging a non-date field does not pull in the date pair
        (no acceptance criterion states it)
    Double: Stub (cursor.fetchone returns the 'Under Review' event, then the updated row);
        Mock (the UPDATE's metadata JSON parameter, parsed to read the flagged fields and the
        actionHistory details)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row("Amendment Requested")]

    # Act (When)
    request_amendment(client, fields=["venueRequirements"])

    # Assert (Then)
    stored = written_metadata(cursor)
    assert stored["amendmentHistory"][-1]["fields"] == ["venueRequirements"]
    assert stored["actionHistory"][-1]["details"] == (
        "Amendment requested from the Event Organiser: Venue requirements."
    )


@pytest.mark.parametrize("row", [None, event_row("Draft")], ids=["none", "event_row_draft"])
def test_supporting_missing_or_draft_event_is_not_found(row, setup):
    """
    Summary: A draft is invisible to coordinators, so it reads as missing.
    Supporting design check: an amendment request for a missing or draft event answers 404
        (no acceptance criterion states it)
    Double: Stub (cursor.fetchone returns None, or a 'Draft' row); no execute assertions -
        only the 404 is checked
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = row

    # Act + Assert (When / Then)
    assert request_amendment(client).status_code == 404


def test_supporting_reason_of_1001_characters_is_refused(setup):
    """
    Summary: One character over the limit is refused.
    Supporting design check: an amendment reason may be at most 1000 characters
        (no acceptance criterion states a length)
    Double: Mock (cursor.execute, asserted never called); no rows stubbed because validation
        refuses the request first
    """
    client, _, cursor = setup
    response = request_amendment(client, reason="x" * 1001)
    assert response.status_code == 400
    assert response.json["message"] == "An amendment reason must be 1000 characters or fewer."
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"expectedAttendance": "300"},
    {"expectedAttendance": " 300 "},
    {"preferredStartDate": "2030-10-10T09:00"},
], ids=["expectedattendance_300", "expectedattendance_300_2", "preferredstartdate_2030_10_10t09_00"])
def test_supporting_unchanged_flagged_values_are_refused(changes, setup):
    """
    Summary: The same value, however it is spelled, is not an amendment.
    Supporting design check: resubmitting with no real change is refused
        (NO_AMENDMENT_CHANGES); no acceptance criterion states it
    Double: Stub (cursor.fetchone.return_value: the event with one open round whose flagged
        fields already hold these values); Mock (cursor.execute calls scanned: no UPDATE was
        issued)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = amending_row()
    response = respond(client, changes=changes)
    assert response.status_code == 400
    assert response.json["code"] == "NO_AMENDMENT_CHANGES"
    assert_nothing_written(cursor)


@pytest.mark.parametrize("changes, missing, error", [
    ({"preferredEndDate": "2030-10-10T08:00"}, [], "Preferred End Date & Time must be after the start."),
    ({"expectedAttendance": "0"}, [], "Expected Attendance must be a positive whole number"),
    ({"expectedAttendance": "  "}, ["Expected Attendance"], None),
], ids=["preferredenddate_2030_10_10t08_00_preferred_end", "expectedattendance_0_expected_attendance_must_be", "expectedattendance_expected_attendance_none"])
def test_supporting_amended_values_are_validated(changes, missing, error, setup):
    """
    Summary: The merged event must still pass submission validation; nothing is written otherwise.
    Supporting design check: amended values go through the same validation as a
        submission; no acceptance criterion states it
    Double: Stub (cursor.fetchone.return_value: the event with one open round); Mock
        (cursor.execute calls scanned: no UPDATE was issued)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = amending_row()
    response = respond(client, changes=changes)
    assert response.status_code == 400
    assert response.json["message"] == "Please correct the event details."
    assert response.json["missingFields"] == missing
    if error:
        assert any(message.startswith(error) for message in response.json["errors"])
    assert_nothing_written(cursor)


@pytest.mark.parametrize("body, message", [
    ({"changes": {}}, "Send the amended values for the flagged fields."),
    ({"changes": None}, "Send the amended values for the flagged fields."),
    ({"changes": ["expectedAttendance"]}, "Send the amended values for the flagged fields."),
    ({"changes": {"expectedAttendance": 120}}, "Every amended value must be text."),
    ({"note": 5}, "A resubmission note must be 1000 characters or fewer."),
    ({"note": "x" * 1001}, "A resubmission note must be 1000 characters or fewer."),
], ids=["changes_send_the_amended_values_for_the_flagged", "changes_none_send_the_amended_values_for_the_fla", "changes_expectedattendance_send_the_amended_valu", "changes_expectedattendance_120_every_amended_val", "note_5_a_resubmission_note_must_be_1000_characte", "note_x_1001_a_resubmission_note_must_be_1000_cha"])
def test_supporting_resubmission_body_is_validated(body, message, setup):
    """
    Summary: Bad bodies are refused before any database work.
    Supporting design check: a malformed resubmission body (missing or non-text changes, bad
        note) is refused with 400; no acceptance criterion states it
    Double: Mock (cursor.execute, asserted never called); no rows stubbed because validation
        refuses the request first
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = respond(client, **body)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == message
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("status", ["Approved", "Rejected"])
def test_supporting_coordinator_cannot_approve_or_reject_while_amendment_is_open(status, setup):
    """
    Summary: Once the status is 'Amendment Requested', decide_event refuses to approve or
        reject; it only accepts 'Submitted'/'Under Review'.
    Supporting design check: an event waiting for the organiser's amendment can't be decided
        (SCRUM-13); no acceptance criterion lists this side effect
    Double: Stub (cursor.fetchone.return_value: the event in 'Amendment Requested'); the
        EventNotSubmittedError is the assertion, no execute calls are checked
    """
    # Arrange (Given)
    _, _, cursor = setup
    cursor.fetchone.return_value = amending_row()

    # Act + Assert (When / Then)
    with pytest.raises(EventNotSubmittedError):
        decide_event(URL, EVENT_ID, COORDINATOR_ID, status, "A reason")


def test_supporting_change_request_cannot_be_opened_while_amendment_is_open(setup):
    """
    Summary: An organiser can't open a SCRUM-42 proposal mid-amendment.
    Supporting design check: a change proposal can't be opened while an amendment is open
        (SCRUM-42); no acceptance criterion lists this side effect
    Double: Stub (cursor.fetchone.return_value: the event in 'Amendment Requested'); no
        execute assertions - only the 409 and its code are checked
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = amending_row()

    # Act (When)
    response = client.post(
        f"/events/{EVENT_ID}/change-requests",
        json={"organiserId": ORGANISER_ID, "changes": {"eventName": "New"}, "reason": "Why"},
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "CHANGE_REQUEST_NOT_ALLOWED"


def test_supporting_pending_change_request_cannot_be_approved_while_amendment_is_open(setup):
    """
    Summary: A proposal made earlier can't be applied until the event is back in review.
    Supporting design check: a pending change proposal can't be approved while an amendment
        is open (SCRUM-42); no acceptance criterion lists this side effect
    Double: Stub (cursor.fetchone.return_value: the event in 'Amendment Requested' merged with
        a pending change request's columns); the ChangeRequestNotAllowedError is the
        assertion, no execute calls are checked
    """
    # Arrange (Given)
    _, _, cursor = setup
    cursor.fetchone.return_value = {**amending_row(), **change_request_columns()}

    # Act + Assert (When / Then)
    with pytest.raises(ChangeRequestNotAllowedError):
        decide_change_request(URL, CHANGE_ID, COORDINATOR_ID, "Approved")


def test_supporting_progress_endpoint_cannot_leave_amendment_requested(setup):
    """
    Summary: PATCH /progress lists no transition out of 'Amendment Requested'.
    Supporting design check: only the organiser's resubmission can leave 'Amendment Requested'
        (SCRUM-19's status endpoint offers no way out); no acceptance criterion lists this
    Double: Stub (cursor.fetchone.return_value: the event in 'Amendment Requested'); Mock
        (cursor.execute calls scanned: no UPDATE was issued)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = amending_row()

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/progress",
        json={"coordinatorId": COORDINATOR_ID, "status": "Amendment Requested", "actionDetails": "x"},
    )

    # Assert (Then)
    assert response.status_code == 409
    assert_nothing_written(cursor)


def test_supporting_status_filter_accepts_amendment_requested(setup):
    """
    Summary: The new status is a known status, so lists can filter by it.
    Supporting design check: 'Amendment Requested' is a known status that event lists can
        filter by; no acceptance criterion lists this
    Double: Stub (cursor.fetchall returns the event in 'Amendment Requested'); no execute
        assertions - only the 200 and the listed status are checked
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchall.return_value = [amending_row()]

    # Act (When)
    response = client.get(
        "/events", query_string={"coordinatorId": COORDINATOR_ID, "status": "Amendment Requested"}
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["events"][0]["status"] == "Amendment Requested"


def test_supporting_coordinator_detail_edit_is_refused_while_amendment_is_open(setup):
    """
    Summary: The organiser holds the pen, so the coordinator's own edit is refused.
    Supporting design check: the coordinator can't edit details while the organiser is
        amending them (SCRUM-153); no acceptance criterion lists this side effect
    Double: Stub (cursor.fetchone.return_value: the event in 'Amendment Requested'); Mock
        (cursor.execute calls scanned: no UPDATE was issued)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = amending_row()

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/details",
        json={"coordinatorId": COORDINATOR_ID, "changes": {"eventName": "New"}},
    )

    # Assert (Then)
    assert response.status_code == 409
    assert_nothing_written(cursor)


def test_supporting_serialize_returns_empty_amendment_history_for_old_events():
    """
    Summary: Events from before this story serialize with an empty list.
    Supporting design check: events stored before SCRUM-16 have no amendmentHistory and read
        as an empty list, not an error
    Double: None (serialize is a pure function over a row dict)
    """
    # Arrange (Given)
    row = event_row()
    metadata = json.loads(row["description"])
    del metadata["amendmentHistory"]
    row["description"] = json.dumps(metadata)

    # Act + Assert (When / Then)
    assert serialize(row)["amendmentHistory"] == []
    assert serialize(amending_row())["amendmentHistory"] == [open_amendment()]


@pytest.mark.parametrize("value", [
    None,
    "",
    "plain text description",
    json.dumps(["a", "list"]),
    json.dumps({"description": "no marker", "amendmentHistory": [1]}),
    json.dumps({"_connectsphere": "event-submission-v1", "amendmentHistory": "not a list"}),
], ids=["none", "empty", "plain_text_description", "json_dumps_a_list", "json_dumps_description_no_marker_amendmenthistor", "json_dumps_connectsphere_event_submission_v1_ame"])
def test_supporting_unpack_amendments_ignores_anything_that_is_not_a_history(value):
    """
    Summary: Non-JSON, non-metadata and non-list values all read as no history.
    Supporting design check: unreadable stored metadata reads as no amendment history,
        not an error
    Double: None (unpack_amendments is a pure function over a string)
    """
    # Arrange (Given): value, from fixtures

    # Act + Assert (When / Then)
    assert unpack_amendments(value) == []


@pytest.mark.parametrize("endpoint, body", [
    ("amendment-request", {"coordinatorId": COORDINATOR_ID, "fields": ["eventName"], "reason": REASON}),
    ("amendment-response", {"organiserId": ORGANISER_ID, "changes": {"eventName": "New"}}),
], ids=["amendment_request_coordinatorid_coordinator_id_f", "amendment_response_organiserid_organiser_id_chan"])
def test_supporting_amendment_endpoints_require_database_configuration(endpoint, body):
    """
    Summary: Without DATABASE_URL both endpoints answer 503.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: Stub (JWKS signing key, via the autouse fixture in tests/conftest.py); no database
        is stubbed because DATABASE_URL is None and the route answers before connecting
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client())
    assert client.patch(f"/events/{EVENT_ID}/{endpoint}", json=body).status_code == 503
