"""
SCRUM-11: Event Submission Form

User Story
----------
As an Event Organiser, I want to enter my event's details into a structured
form and submit it for review, so that the Event Coordinator can evaluate it.

Acceptance Criteria
-------------------
AC1: The form contains: Event Name (required), Description (required), Purpose
     (required), Preferred Date(s) and Time (required), Expected Attendance
     (required), Venue Requirements (optional), Accessibility Needs (optional),
     Equipment Requirements (optional), Registration Needs (optional).
AC2: Given all required fields (Event Name, Description, Purpose, Preferred
     Date(s) and Time, Expected Attendance) are filled in, when the Event
     Organiser submits, then the status changes to 'Submitted', the submission
     date is recorded, and it appears in the queue of submitted requests
     visible to Event Coordinators.
AC3: Given the submission succeeds, the Event Organiser receives a confirmation
     popup in ConnectSphere referencing the event name and submission date.
AC4: Given one or more required fields are missing, when the Event Organiser
     attempts to submit, then submission is blocked and a pop-up is shown,
     listing exactly which fields are missing.

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
from uuid import UUID

import psycopg2
import pytest

from app import create_app
from app.models import FIELDS, SINGAPORE, serialize, unpack_description
from tests.unit.factories import (
    COORDINATOR_ID,
    ORGANISER_ID,
    VALID,
    saved_row,
    signed_in,
)


def test_ac1_ac2_ac3_complete_submission_is_stored_as_submitted_and_returns_name_and_submission_date(setup):
    """
    Summary: POST /events with all required fields (and a forged status "Approved" and submission_date "fake" in the body) answers 201 with status 'Submitted', submittedAt, purpose and description; the INSERT hard-codes 'Submitted' and now(), binds the dates as Singapore time, the attendance as 25, the purpose inside the stored description metadata and the signed-in organiser's id, and the connection commits and closes.
    AC1: The form contains: Event Name (required), Description (required),
        Purpose (required), Preferred Date(s) and Time (required), Expected
        Attendance (required), Venue Requirements (optional), Accessibility
        Needs (optional), Equipment Requirements (optional), Registration Needs
        (optional).
    AC2: Given all required fields (Event Name, Description, Purpose, Preferred
        Date(s) and Time, Expected Attendance) are filled in, when the Event
        Organiser submits, then the status changes to 'Submitted', the
        submission date is recorded, and it appears in the queue of submitted
        requests visible to Event Coordinators.
    AC3: Given the submission succeeds, the Event Organiser receives a
        confirmation popup in ConnectSphere referencing the event name and
        submission date.
    Double: Stub (cursor.fetchone returns the saved 'Submitted' row),
        Mock (the INSERT query and parameters asserted; connection.__exit__ and connection.close each called once)
    """
    # Arrange (Given)
    client, connection, cursor = setup
    cursor.fetchone.return_value = saved_row()

    # Act (When)
    response = client.post(
        "/events", json={**VALID, "status": "Approved", "submission_date": "fake"}
    )

    # Assert (Then)
    assert response.status_code == 201
    assert response.json["status"] == "Submitted"
    assert response.json["submittedAt"] == "2026-09-15T01:30:00+00:00"
    assert response.json["purpose"] == "Learning"
    assert response.json["description"] == "A workshop"
    query, parameters = cursor.execute.call_args.args
    assert 'INSERT INTO public."Event"' in query
    assert "'Submitted', now()" in query
    assert "purpose" not in query
    assert "'Submitted'" in query
    assert UUID(parameters[0])
    # Naive local input is bound as an aware Singapore time for TIMESTAMPTZ.
    assert parameters[3] == datetime(2026, 10, 1, 9, tzinfo=SINGAPORE)
    assert parameters[4] == datetime(2026, 10, 1, 17, tzinfo=SINGAPORE)
    assert parameters[5] == 25
    assert json.loads(parameters[2])["purpose"] == "Learning"
    # No deadline; the organiser is the signed-in caller (SCRUM-8), not a body field.
    assert parameters[6:] == ["", "", "", "", None, "00000000-0000-4000-8000-000000000001"]
    connection.__exit__.assert_called_once()
    connection.close.assert_called_once()


def test_ac1_optional_equipment_requirements_are_stored_and_returned_as_entered(setup):
    """
    Summary: POST /events with equipmentRequirements "Projector" answers with equipmentRequirements "Projector", and "Projector" is the ninth INSERT parameter.
    AC1: The form contains: Event Name (required), Description (required),
        Purpose (required), Preferred Date(s) and Time (required), Expected
        Attendance (required), Venue Requirements (optional), Accessibility
        Needs (optional), Equipment Requirements (optional), Registration Needs
        (optional).
    Double: Stub (cursor.fetchone returns a saved row whose equipment_requirements is "Projector"),
        Mock (the INSERT's ninth parameter asserted)
    """
    client, _, cursor = setup
    row = saved_row()
    row["equipment_requirements"] = "Projector"
    cursor.fetchone.return_value = row
    response = client.post(
        "/events", json={**VALID, "equipmentRequirements": "Projector"}
    )
    assert response.json["equipmentRequirements"] == "Projector"
    assert cursor.execute.call_args.args[1][8] == "Projector"


def test_ac1_optional_withdrawal_deadline_is_bound_and_returned_as_singapore_local_time(setup):
    """
    Summary: POST /events with withdrawalDeadline 2026-10-01T02:00 answers 201 returning "2026-10-01T02:00:00", and the INSERT binds that deadline as 02:00 Singapore time.
    AC1: The form contains: Event Name (required), Description (required),
        Purpose (required), Preferred Date(s) and Time (required), Expected
        Attendance (required), Venue Requirements (optional), Accessibility
        Needs (optional), Equipment Requirements (optional), Registration Needs
        (optional).
    Double: Stub (cursor.fetchone returns a saved row whose withdrawal_deadline is 2026-09-30 18:00 UTC),
        Mock (the INSERT's eleventh parameter asserted)
    """
    client, _, cursor = setup
    row = saved_row()
    row["withdrawal_deadline"] = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)
    cursor.fetchone.return_value = row

    response = client.post(
        "/events", json={**VALID, "withdrawalDeadline": "2026-10-01T02:00"}
    )

    assert response.status_code == 201
    assert response.json["withdrawalDeadline"] == "2026-10-01T02:00:00"
    assert cursor.execute.call_args.args[1][10] == datetime(
        2026, 10, 1, 2, tzinfo=SINGAPORE
    )


@pytest.mark.parametrize(
    "deadline",
    ["invalid", "2026-10-01T09:01"],
)
def test_ac1_withdrawal_deadline_that_is_invalid_or_after_the_start_is_refused(setup, deadline):
    """
    Summary: POST /events with withdrawalDeadline "invalid" or 2026-10-01T09:01 (after the 09:00 start) answers 400 with a Withdrawal Deadline error, and no query is sent.
    AC1: The form contains: Event Name (required), Description (required),
        Purpose (required), Preferred Date(s) and Time (required), Expected
        Attendance (required), Venue Requirements (optional), Accessibility
        Needs (optional), Equipment Requirements (optional), Registration Needs
        (optional).
    Double: Mock (cursor.execute asserted never called; the first error message checked for "Withdrawal Deadline")
    """
    response = setup[0].post(
        "/events", json={**VALID, "withdrawalDeadline": deadline}
    )
    assert response.status_code == 400
    assert "Withdrawal Deadline" in response.json["errors"][0]
    setup[2].execute.assert_not_called()


def test_ac1_withdrawal_deadline_that_is_not_text_is_refused(setup):
    """
    Summary: POST /events with withdrawalDeadline set to the number 123 answers 400 with "withdrawalDeadline must be text".
    AC1: The form contains: Event Name (required), Description (required),
        Purpose (required), Preferred Date(s) and Time (required), Expected
        Attendance (required), Venue Requirements (optional), Accessibility
        Needs (optional), Equipment Requirements (optional), Registration Needs
        (optional).
    Double: None for the database: the request is refused before any query; only the 400 message is asserted
    """
    response = setup[0].post(
        "/events", json={**VALID, "withdrawalDeadline": 123}
    )
    assert response.status_code == 400
    assert "withdrawalDeadline must be text" in response.json["errors"][0]


@pytest.mark.parametrize(
    "field,label",
    [
        ("eventName", "Event Name"),
        ("description", "Description"),
        ("purpose", "Purpose"),
        ("preferredStartDate", "Preferred Start Date & Time"),
        ("preferredEndDate", "Preferred End Date & Time"),
        ("expectedAttendance", "Expected Attendance"),
    ],
)
@pytest.mark.parametrize("value", [None, "", "  "])
def test_ac4_a_blank_required_field_blocks_submission_and_is_the_only_field_listed(setup, field, label, value):
    """
    Summary: For each of the six required fields set to null, "" or whitespace, POST /events answers 400 whose missingFields is exactly that field's label, and no query is sent.
    AC4: Given one or more required fields are missing, when the Event
        Organiser attempts to submit, then submission is blocked and a pop-up
        is shown, listing exactly which fields are missing.
    Double: Mock (cursor.execute asserted never called; missingFields compared with the one label)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = client.post("/events", json={**VALID, field: value})

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["missingFields"] == [label]
    cursor.execute.assert_not_called()


def test_ac4_an_empty_submission_lists_every_required_field_in_form_order(setup):
    """
    Summary: POST /events with an empty object answers with missingFields listing all six required fields (name, description, purpose, start, end, attendance) in form order.
    AC4: Given one or more required fields are missing, when the Event
        Organiser attempts to submit, then submission is blocked and a pop-up
        is shown, listing exactly which fields are missing.
    Double: None for the database: the request is refused before any query; only the missingFields list is asserted
    """
    # Arrange (Given): setup, from fixtures

    # Act (When)
    response = setup[0].post("/events", json={})

    # Assert (Then)
    assert response.json["missingFields"] == [
        "Event Name",
        "Description",
        "Purpose",
        "Preferred Start Date & Time",
        "Preferred End Date & Time",
        "Expected Attendance",
    ]


@pytest.mark.parametrize(
    "value", ["0", "-1", "2.5", "abc", "2147483648", "9" * 5000, "²"],
    ids=["0", "1", "2_5", "abc", "2147483648", "9_5000", "empty"],
)
def test_ac1_expected_attendance_that_is_not_a_whole_number_in_range_is_refused(setup, value):
    """
    Summary: POST /events with expectedAttendance 0, -1, 2.5, "abc", 2147483648, a 5000-digit number or "²" answers 400 with at least one error.
    AC1: The form contains: Event Name (required), Description (required),
        Purpose (required), Preferred Date(s) and Time (required), Expected
        Attendance (required), Venue Requirements (optional), Accessibility
        Needs (optional), Equipment Requirements (optional), Registration Needs
        (optional).
    Double: None for the database: the request is refused before any query; only the 400 status and the presence of errors are asserted
    """
    response = setup[0].post("/events", json={**VALID, "expectedAttendance": value})
    assert response.status_code == 400
    assert response.json["errors"]


@pytest.mark.parametrize(
    "value",
    [
        "invalid",
        "2026-10-01",
        "2026-10-01T09:00",
        "2026-09-30T09:00",
        "2026-10-01T17:00+08:00",
    ],
)
def test_ac1_preferred_end_that_is_unparseable_date_only_offset_or_not_after_the_start_is_refused(setup, value):
    """
    Summary: POST /events with preferredEndDate "invalid", a date without a time, 09:00 (equal to the start), the day before, or a time carrying a +08:00 offset answers 400.
    AC1: The form contains: Event Name (required), Description (required),
        Purpose (required), Preferred Date(s) and Time (required), Expected
        Attendance (required), Venue Requirements (optional), Accessibility
        Needs (optional), Equipment Requirements (optional), Registration Needs
        (optional).
    Double: None for the database: the request is refused before any query; only the 400 status is asserted
    """
    assert (
        setup[0].post("/events", json={**VALID, "preferredEndDate": value}).status_code
        == 400
    )


def test_ac1_optional_field_that_is_not_text_is_refused(setup):
    """
    Summary: POST /events with venueRequirements set to a list instead of text answers 400.
    AC1: The form contains: Event Name (required), Description (required),
        Purpose (required), Preferred Date(s) and Time (required), Expected
        Attendance (required), Venue Requirements (optional), Accessibility
        Needs (optional), Equipment Requirements (optional), Registration Needs
        (optional).
    Double: None for the database: the request is refused before any query; only the 400 status is asserted
    """
    assert (
        setup[0].post("/events", json={**VALID, "venueRequirements": []}).status_code
        == 400
    )


@pytest.mark.parametrize("operation", ["execute", "commit"])
def test_ac2_a_database_failure_is_never_reported_as_a_successful_submission(setup, operation):
    """
    Summary: When the INSERT raises an OperationalError, or the commit does, POST /events answers 503 without echoing the database error text, and the connection is still closed.
    AC2: Given all required fields (Event Name, Description, Purpose, Preferred
        Date(s) and Time, Expected Attendance) are filled in, when the Event
        Organiser submits, then the status changes to 'Submitted', the
        submission date is recorded, and it appears in the queue of submitted
        requests visible to Event Coordinators.
    Double: Stub (cursor.execute, or connection.__exit__ on commit, raises psycopg2.OperationalError),
        Mock (connection.close asserted called once)
    """
    # Arrange (Given)
    client, connection, cursor = setup
    cursor.fetchone.return_value = saved_row()
    if operation == "execute":
        cursor.execute.side_effect = psycopg2.OperationalError(
            "secret connection information"
        )
    else:
        connection.__exit__.side_effect = psycopg2.OperationalError("commit failed")

    # Act (When)
    response = client.post("/events", json=VALID)

    # Assert (Then)
    assert response.status_code == 503
    assert "secret" not in response.text
    connection.close.assert_called_once()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


@pytest.mark.parametrize("body", [None, [], "text"], ids=["none", "empty", "text"])
def test_a_body_that_is_not_a_json_object_is_refused_with_400(setup, body):
    """
    Summary: POST /events with no body, an empty list or a plain string answers 400.
    Supporting design check: a submission body must be a JSON object of event
        details
    Double: None for the database: the request is refused before any query; only the 400 status is asserted
    """
    # Arrange (Given): setup, body, from fixtures

    # Act + Assert (When / Then)
    assert setup[0].post("/events", json=body).status_code == 400


def test_submission_records_the_signed_in_organiser_as_the_owner(setup):
    """
    Summary: POST /events answers 201 returning organiserId, and the last INSERT parameter is the signed-in organiser's id, so ownership can be checked later.
    Supporting design check: the submitting organiser is stored as the event's
        owner
    Double: Stub (cursor.fetchone returns a saved row owned by the organiser),
        Mock (the INSERT parameters found in cursor.execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    row = saved_row()
    row["organiser_id"] = ORGANISER_ID
    cursor.fetchone.return_value = row

    # Act (When)
    response = client.post("/events", json={**VALID, "organiserId": ORGANISER_ID})

    # Assert (Then)
    assert response.status_code == 201
    assert response.json["organiserId"] == ORGANISER_ID
    event_insert = next(call for call in cursor.execute.call_args_list if 'INSERT INTO public."Event"' in call.args[0])
    assert event_insert.args[1][-1] == ORGANISER_ID


@pytest.mark.parametrize(
    "value,description,purpose",
    [
        ("Legacy plain text", "Legacy plain text", ""),
        (None, "", ""),
        ('{"other":"value"}', '{"other":"value"}', ""),
        ("[]", "[]", ""),
    ],
)
def test_descriptions_stored_before_the_metadata_format_are_returned_unchanged(value, description, purpose):
    """
    Summary: unpack_description returns plain text, None, a JSON object without the metadata marker and a JSON list unchanged as (description, "", None).
    Supporting design check: descriptions saved before the metadata format
        still read back as they were written
    Double: None; unpack_description is a pure function called directly
    """
    assert unpack_description(value) == (description, purpose, None)


def test_rows_with_empty_optional_columns_still_serialize():
    """
    Summary: serialize on a row whose form columns and submission date are all None returns an empty preferredStartDate, a None submittedAt and an empty purpose.
    Supporting design check: older rows with empty columns still read back
    Double: None; serialize is a pure function called directly on a row dict
    """
    row = saved_row()
    for column in FIELDS.values():
        row[column] = None
    row["submission_date"] = None
    serialized = serialize(row)
    assert serialized["preferredStartDate"] == ""
    assert serialized["submittedAt"] is None
    assert serialized["purpose"] == ""


def test_stored_timestamps_are_returned_as_singapore_local_time():
    """
    Summary: serialize turns the UTC times 01:00 and 09:00 into "2026-10-01T09:00:00" and "2026-10-01T17:00:00".
    Supporting design check: stored timestamps are shown to users in Singapore
        local time
    Double: None; serialize is a pure function called directly on a row dict
    """
    row = saved_row()
    row["preferred_start_date"] = datetime(2026, 10, 1, 1, tzinfo=UTC)
    row["preferred_end_date"] = datetime(2026, 10, 1, 9, tzinfo=UTC)

    serialized = serialize(row)

    assert serialized["preferredStartDate"] == "2026-10-01T09:00:00"
    assert serialized["preferredEndDate"] == "2026-10-01T17:00:00"


def test_submission_and_submitted_queue_answer_503_when_no_database_is_configured():
    """
    Summary: With no DATABASE_URL set, POST /events and GET /events/submitted each answer 503.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None for the database, since the app has none configured; only the Supabase JWKS Stub, which verifies the signed token
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client(), role="Event Organiser")
    assert client.post("/events", json=VALID).status_code == 503
    assert (
        client.get(f"/events/submitted?coordinatorId={COORDINATOR_ID}").status_code
        == 503
    )
