"""Request Amendment on Event Submission acceptance criteria.

AC1  An assigned coordinator moves a 'Submitted' request to 'Amendment
     Requested' and must flag the field(s) that need changes.
AC2  The reason for the amendment is stored with the request.
AC3  The organiser can edit only the flagged fields; all others stay locked.
AC4  Resubmitting returns the request to 'Submitted', records the amendment
     timestamp and keeps the same coordinator.
AC5  The requesting coordinator's identity and timestamp are recorded.
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


# AC1 ---------------------------------------------------------------------


def test_ac1_assigned_coordinator_requests_amendment_and_status_changes(setup):
    """An 'Under Review' request assigned to the caller moves to 'Amendment Requested'."""
    client, connection, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row("Amendment Requested")]

    response = request_amendment(client)

    assert response.status_code == 200
    assert response.json["status"] == "Amendment Requested"
    query, parameters = written(cursor)
    assert "SET status = 'Amendment Requested', description = %s" in query
    assert "coordinator_id" not in query.split("RETURNING")[0]
    assert "submission_date" not in query.split("RETURNING")[0]
    assert parameters[1] == EVENT_ID
    connection.__exit__.assert_called_once()


def test_ac1_submitted_status_also_accepts_an_amendment_request(setup):
    """The literal AC status, 'Submitted', is accepted as well."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row("Submitted"), event_row("Amendment Requested")]
    assert request_amendment(client).status_code == 200


@pytest.mark.parametrize("fields", [[], None, "expectedAttendance", ["expectedAttendance", 3]])
def test_ac1_at_least_one_field_must_be_flagged(fields, setup):
    """No list, an empty list, or a non-string entry is refused before any database work."""
    client, _, cursor = setup
    body = {"coordinatorId": COORDINATOR_ID, "reason": REASON}
    if fields is not None:
        body["fields"] = fields
    response = client.patch(f"/events/{EVENT_ID}/amendment-request", json=body)
    assert response.status_code == 400
    assert response.json["message"] == "Flag at least one field that needs amending."
    cursor.execute.assert_not_called()


def test_ac1_unknown_field_is_refused_with_invalid_fields(setup):
    """The withdrawal deadline and unknown names can't be flagged; both are named, sorted."""
    client, _, cursor = setup
    response = request_amendment(client, fields=["withdrawalDeadline", "nope", "eventName"])
    assert response.status_code == 400
    assert response.json["message"] == "One or more flagged fields cannot be amended."
    assert response.json["invalidFields"] == ["nope", "withdrawalDeadline"]
    cursor.execute.assert_not_called()


def test_ac1_flagging_one_date_flags_both(setup):
    """Flagging the end date stores both dates, deduplicated, in EDITABLE_FIELDS order."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row("Amendment Requested")]

    request_amendment(
        client, fields=["expectedAttendance", "preferredEndDate", "eventName", "eventName"]
    )

    stored = written_metadata(cursor)["amendmentHistory"][-1]["fields"]
    assert stored == ["eventName", "preferredStartDate", "preferredEndDate", "expectedAttendance"]
    assert stored == [field for field in EDITABLE_FIELDS if field in stored]


def test_ac1_flagging_no_date_adds_no_date(setup):
    """The pairing only applies to the dates: other fields are stored as flagged."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row("Amendment Requested")]
    request_amendment(client, fields=["venueRequirements"])
    stored = written_metadata(cursor)
    assert stored["amendmentHistory"][-1]["fields"] == ["venueRequirements"]
    assert stored["actionHistory"][-1]["details"] == (
        "Amendment requested from the Event Organiser: Venue requirements."
    )


@pytest.mark.parametrize("coordinator_id", [OTHER_COORDINATOR_ID, None])
def test_ac1_only_the_assigned_coordinator_may_request(coordinator_id, setup):
    """Another coordinator's event, or an unassigned one, is 403 and is not written."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=coordinator_id)
    response = request_amendment(client)
    assert response.status_code == 403
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("status", [
    "Approved", "Rejected", "Clarification Requested", "Amendment Requested",
    "Pending Safety Check", "Confirmed",
])
def test_ac1_wrong_status_is_refused_with_current_status(status, setup):
    """Only 'Submitted'/'Under Review' can be sent back; one open amendment at a time."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(status)
    response = request_amendment(client)
    assert response.status_code == 409
    assert response.json["code"] == "AMENDMENT_NOT_ALLOWED"
    assert response.json["currentStatus"] == status
    assert_nothing_written(cursor)


@pytest.mark.parametrize("row", [None, event_row("Draft")])
def test_ac1_missing_or_draft_event_is_not_found(row, setup):
    """A draft is invisible to coordinators, so it reads as missing."""
    client, _, cursor = setup
    cursor.fetchone.return_value = row
    assert request_amendment(client).status_code == 404


@pytest.mark.parametrize("endpoint, body", [
    ("amendment-request", {"coordinatorId": COORDINATOR_ID, "fields": ["eventName"], "reason": REASON}),
    ("amendment-response", {"organiserId": ORGANISER_ID, "changes": {"eventName": "New"}}),
])
def test_amendment_endpoints_require_database_configuration(endpoint, body):
    """Without DATABASE_URL both endpoints answer 503."""
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client())
    assert client.patch(f"/events/{EVENT_ID}/{endpoint}", json=body).status_code == 503


@pytest.mark.parametrize("endpoint, body, message", [
    ("amendment-request", ["not", "an", "object"],
     "Flag at least one field that needs amending."),
    ("amendment-response", "not an object",
     "Send the amended values for the flagged fields."),
])
def test_amendment_endpoints_refuse_a_non_object_body(endpoint, body, message, setup):
    """A body that isn't an object is refused before any database work (the caller is the token's, SCRUM-8)."""
    response = setup[0].patch(f"/events/{EVENT_ID}/{endpoint}", json=body)
    assert response.status_code == 400
    assert response.json["message"] == message
    setup[2].execute.assert_not_called()


# AC2 ---------------------------------------------------------------------


@pytest.mark.parametrize("reason", [None, "", "   ", ["a list"]])
def test_ac2_reason_is_required(reason, setup):
    """A missing, blank or non-text reason is refused."""
    client, _, cursor = setup
    body = {"coordinatorId": COORDINATOR_ID, "fields": ["eventName"]}
    if reason is not None:
        body["reason"] = reason
    response = client.patch(f"/events/{EVENT_ID}/amendment-request", json=body)
    assert response.status_code == 400
    assert response.json["message"] == "A reason for the amendment is required."
    cursor.execute.assert_not_called()


def test_ac2_reason_of_exactly_1000_characters_is_accepted(setup):
    """1000 characters after trimming is the limit, as for clarification."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row("Amendment Requested")]
    response = request_amendment(client, reason=f"  {'x' * 1000}  ")
    assert response.status_code == 200
    assert written_metadata(cursor)["amendmentHistory"][-1]["reason"] == "x" * 1000


def test_ac2_reason_of_1001_characters_is_refused(setup):
    """One character over the limit is refused."""
    client, _, cursor = setup
    response = request_amendment(client, reason="x" * 1001)
    assert response.status_code == 400
    assert response.json["message"] == "An amendment reason must be 1000 characters or fewer."
    cursor.execute.assert_not_called()


def test_ac2_reason_and_fields_are_stored_in_amendment_history(setup):
    """The new round carries the trimmed reason and the flagged fields, still open."""
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
    """A second round is appended; the closed first round is untouched."""
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


# AC5 ---------------------------------------------------------------------


def test_ac5_requesting_coordinator_and_timestamp_are_recorded(setup):
    """requestedBy/requestedAt and an actionHistory entry name the coordinator and time."""
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


# AC4 ---------------------------------------------------------------------


def test_ac4_resubmission_returns_status_to_submitted(setup):
    """The UPDATE sets 'Submitted' and writes the changed column."""
    client, connection, cursor = setup
    cursor.fetchone.side_effect = [amending_row(), event_row("Submitted")]

    response = respond(client)

    assert response.status_code == 200
    assert response.json["status"] == "Submitted"
    query, parameters = written(cursor)
    assert "SET expected_attendance = %s, description = %s, status = 'Submitted'" in query
    assert parameters[0] == 120
    assert parameters[-1] == EVENT_ID
    connection.__exit__.assert_called_once()


def test_ac4_resubmission_keeps_the_same_coordinator(setup):
    """Neither the coordinator nor the assignment is written, and the response keeps them."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [amending_row(), event_row("Submitted")]

    response = respond(client)

    query, _ = written(cursor)
    set_clause = query.split("RETURNING")[0]
    for column in ("coordinator_id", "assigned_by", "assigned_at"):
        assert column not in set_clause
    assert response.json["coordinatorId"] == COORDINATOR_ID


def test_ac4_amendment_timestamp_is_recorded(setup):
    """The open round is closed with who, when, what moved and the note."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [amending_row(), event_row("Submitted")]
    before = datetime.now(UTC)

    respond(
        client,
        changes={"expectedAttendance": "120", "preferredStartDate": "2030-10-10T10:00"},
        note="  Moved an hour later.  ",
    )

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


@pytest.mark.parametrize("note", [None, "", "   "])
def test_ac4_note_is_optional(note, setup):
    """No note, or a blank one, is stored as null."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [amending_row(), event_row("Submitted")]
    response = respond(client, note=note)
    assert response.status_code == 200
    assert written_metadata(cursor)["amendmentHistory"][-1]["note"] is None


# AC3 ---------------------------------------------------------------------


def test_ac3_changing_an_unflagged_field_is_refused_and_nothing_is_written(setup):
    """A flagged + an unflagged change is refused whole, naming the locked field."""
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
    """Even resending a locked field's own value is refused: the lock is on the key."""
    client, _, cursor = setup
    cursor.fetchone.return_value = amending_row()
    response = respond(
        client, changes={"expectedAttendance": "120", "venueRequirements": "Main hall"}
    )
    assert response.status_code == 400
    assert response.json["lockedFields"] == ["venueRequirements"]
    assert_nothing_written(cursor)


@pytest.mark.parametrize("changes", [
    {"expectedAttendance": "300"},
    {"expectedAttendance": " 300 "},
    {"preferredStartDate": "2030-10-10T09:00"},
])
def test_ac3_unchanged_flagged_values_are_refused(changes, setup):
    """The same value, however it is spelled, is not an amendment."""
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
])
def test_ac3_amended_values_are_validated(changes, missing, error, setup):
    """The merged event must still pass submission validation; nothing is written otherwise."""
    client, _, cursor = setup
    cursor.fetchone.return_value = amending_row()
    response = respond(client, changes=changes)
    assert response.status_code == 400
    assert response.json["message"] == "Please correct the event details."
    assert response.json["missingFields"] == missing
    if error:
        assert any(message.startswith(error) for message in response.json["errors"])
    assert_nothing_written(cursor)


def test_ac3_description_and_purpose_amendments_are_written_to_metadata(setup):
    """Description and purpose live in the metadata JSON, so no column is written."""
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
    """An untouched flagged description keeps its stored value."""
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
    """A text column is written as the trimmed value."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row("Amendment Requested", amendments=[open_amendment(["venueRequirements"])]),
        event_row("Submitted"),
    ]
    respond(client, changes={"venueRequirements": "  Hall B  "})
    query, parameters = written(cursor)
    assert "SET venue_requirements = %s, description = %s" in query
    assert parameters[0] == "Hall B"


def test_ac3_amended_dates_are_written_as_singapore_time(setup):
    """Both dates are written as aware Singapore-local datetimes."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [amending_row(), event_row("Submitted")]
    respond(
        client,
        # Sent end-first: the columns are still written in field order.
        changes={"preferredEndDate": "2030-10-11T12:00", "preferredStartDate": "2030-10-11T09:00"},
    )
    query, parameters = written(cursor)
    assert "SET preferred_start_date = %s, preferred_end_date = %s, description = %s" in query
    assert parameters[0].isoformat() == "2030-10-11T09:00:00+08:00"
    assert parameters[1].isoformat() == "2030-10-11T12:00:00+08:00"


@pytest.mark.parametrize("organiser_id", [OTHER_ORGANISER_ID, None])
def test_ac3_only_the_owning_organiser_may_resubmit(organiser_id, setup):
    """Another organiser (or an event with none) is 403 and nothing is written."""
    client, _, cursor = setup
    cursor.fetchone.return_value = amending_row(organiser_id=organiser_id)
    response = respond(client)
    assert response.status_code == 403
    assert response.json["message"] == "You can only amend event requests you created."
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("row", [None, event_row("Draft")])
def test_resubmitting_a_missing_or_draft_event_is_not_found(row, setup):
    """Missing and draft events are 404."""
    client, _, cursor = setup
    cursor.fetchone.return_value = row
    assert respond(client).status_code == 404


@pytest.mark.parametrize("status", ["Submitted", "Under Review", "Clarification Requested", "Approved"])
def test_resubmitting_without_an_open_amendment_status_is_refused(status, setup):
    """Only an event in 'Amendment Requested' can be resubmitted."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(status, amendments=[open_amendment()])
    response = respond(client)
    assert response.status_code == 409
    assert response.json["code"] == "AMENDMENT_NOT_OPEN"
    assert_nothing_written(cursor)


@pytest.mark.parametrize("amendments", [
    [],
    [{**open_amendment(), "resubmittedAt": "2026-10-21T01:00:00+00:00"}],
    ["not an entry"],
])
def test_resubmitting_with_no_open_round_is_refused_even_if_status_is_stale(amendments, setup):
    """The status alone isn't enough; the history must hold an open round."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row("Amendment Requested", amendments=amendments)
    response = respond(client)
    assert response.status_code == 409
    assert response.json["code"] == "AMENDMENT_NOT_OPEN"


def test_an_open_round_with_corrupt_fields_locks_everything(setup):
    """If the stored flagged list is unreadable, no field is editable."""
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(
        "Amendment Requested", amendments=[{**open_amendment(), "fields": "expectedAttendance"}]
    )
    response = respond(client)
    assert response.status_code == 400
    assert response.json["code"] == "AMENDMENT_FIELD_LOCKED"


@pytest.mark.parametrize("body, message", [
    ({"changes": {}}, "Send the amended values for the flagged fields."),
    ({"changes": None}, "Send the amended values for the flagged fields."),
    ({"changes": ["expectedAttendance"]}, "Send the amended values for the flagged fields."),
    ({"changes": {"expectedAttendance": 120}}, "Every amended value must be text."),
    ({"note": 5}, "A resubmission note must be 1000 characters or fewer."),
    ({"note": "x" * 1001}, "A resubmission note must be 1000 characters or fewer."),
])
def test_resubmission_body_is_validated(body, message, setup):
    """Bad bodies are refused before any database work."""
    client, _, cursor = setup
    response = respond(client, **body)
    assert response.status_code == 400
    assert response.json["message"] == message
    cursor.execute.assert_not_called()


def test_resubmission_note_of_exactly_1000_characters_is_accepted(setup):
    """1000 characters after trimming is the note's limit."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [amending_row(), event_row("Submitted")]
    assert respond(client, note=f" {'n' * 1000} ").status_code == 200


# Interactions with existing flows -----------------------------------------


@pytest.mark.parametrize("status", ["Approved", "Rejected"])
def test_coordinator_cannot_approve_or_reject_while_amendment_is_open(status, setup):
    """decide_event only accepts 'Submitted'/'Under Review'."""
    _, _, cursor = setup
    cursor.fetchone.return_value = amending_row()
    with pytest.raises(EventNotSubmittedError):
        decide_event(URL, EVENT_ID, COORDINATOR_ID, status, "A reason")


def test_change_request_cannot_be_opened_while_amendment_is_open(setup):
    """An organiser can't open a SCRUM-42 proposal mid-amendment."""
    client, _, cursor = setup
    cursor.fetchone.return_value = amending_row()
    response = client.post(
        f"/events/{EVENT_ID}/change-requests",
        json={"organiserId": ORGANISER_ID, "changes": {"eventName": "New"}, "reason": "Why"},
    )
    assert response.status_code == 409
    assert response.json["code"] == "CHANGE_REQUEST_NOT_ALLOWED"


def test_pending_change_request_cannot_be_approved_while_amendment_is_open(setup):
    """A proposal made earlier can't be applied until the event is back in review."""
    _, _, cursor = setup
    cursor.fetchone.return_value = {**amending_row(), **change_request_columns()}
    with pytest.raises(ChangeRequestNotAllowedError):
        decide_change_request(URL, CHANGE_ID, COORDINATOR_ID, "Approved")


def test_progress_endpoint_cannot_leave_amendment_requested(setup):
    """PATCH /progress lists no transition out of 'Amendment Requested'."""
    client, _, cursor = setup
    cursor.fetchone.return_value = amending_row()
    response = client.patch(
        f"/events/{EVENT_ID}/progress",
        json={"coordinatorId": COORDINATOR_ID, "status": "Amendment Requested", "actionDetails": "x"},
    )
    assert response.status_code == 409
    assert_nothing_written(cursor)


def test_progress_status_filter_accepts_amendment_requested(setup):
    """The new status is a known status, so lists can filter by it."""
    client, _, cursor = setup
    cursor.fetchall.return_value = [amending_row()]
    response = client.get(
        "/events", query_string={"coordinatorId": COORDINATOR_ID, "status": "Amendment Requested"}
    )
    assert response.status_code == 200
    assert response.json["events"][0]["status"] == "Amendment Requested"


def test_coordinator_detail_edit_is_refused_while_amendment_is_open(setup):
    """The organiser holds the pen, so the coordinator's own edit is refused."""
    client, _, cursor = setup
    cursor.fetchone.return_value = amending_row()
    response = client.patch(
        f"/events/{EVENT_ID}/details",
        json={"coordinatorId": COORDINATOR_ID, "changes": {"eventName": "New"}},
    )
    assert response.status_code == 409
    assert_nothing_written(cursor)


def test_amendment_requested_event_cannot_be_reassigned(setup):
    """AC4's 'same coordinator': a Lead can't reassign while the amendment is open."""
    client, _, cursor = setup
    cursor.fetchone.return_value = {"coordinator_id": COORDINATOR_ID, "status": "Amendment Requested"}
    with pytest.raises(EventClosedError):
        update_event_coordinator(URL, EVENT_ID, OTHER_COORDINATOR_ID, LEAD_ID)
    response = client.patch(
        f"/events/{EVENT_ID}",
        json={"assignedCoordinatorId": OTHER_COORDINATOR_ID, "assignedBy": LEAD_ID},
    )
    assert response.status_code == 409
    assert response.json["message"] == "A Amendment Requested event can't be reassigned."


def test_serialize_returns_empty_amendment_history_for_old_events():
    """Events from before this story serialize with an empty list."""
    row = event_row()
    metadata = json.loads(row["description"])
    del metadata["amendmentHistory"]
    row["description"] = json.dumps(metadata)
    assert serialize(row)["amendmentHistory"] == []
    assert serialize(amending_row())["amendmentHistory"] == [open_amendment()]


@pytest.mark.parametrize("value", [
    None,
    "",
    "plain text description",
    json.dumps(["a", "list"]),
    json.dumps({"description": "no marker", "amendmentHistory": [1]}),
    json.dumps({"_connectsphere": "event-submission-v1", "amendmentHistory": "not a list"}),
])
def test_unpack_amendments_ignores_anything_that_is_not_a_history(value):
    """Non-JSON, non-metadata and non-list values all read as no history."""
    assert unpack_amendments(value) == []


# The carry-through guard: every writer that rebuilds the metadata ----------


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
])
def test_amendment_history_survives_every_metadata_writer(writer, setup):
    """Each writer that rebuilds the metadata JSON keeps amendmentHistory as it was."""
    _, _, cursor = setup
    writer(cursor)
    updates = [
        call.args[1]
        for call in cursor.execute.call_args_list
        if call.args[0].lstrip().startswith('UPDATE public."Event"')
    ]
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
