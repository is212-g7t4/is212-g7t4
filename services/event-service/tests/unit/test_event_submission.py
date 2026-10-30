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

SCRUM-8: User Authentication and Authorization

User Story
----------
As a system user, I want to securely access the system, so that I can use the
information and functionality available to me.

Acceptance Criteria
-------------------
AC1: Given a system user has not been successfully authenticated, when they
     attempt to access protected information or functionality, then access is
     denied.
AC2: Given a system user successfully authenticates, when they access protected
     information or functionality, then their access is evaluated according to
     their role and relationship to the relevant event.
AC3: Given a system user's authentication attempt is unsuccessful, when the
     authentication attempt is completed, then they remain unable to access
     protected information or functionality.

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


def test_submit_existing_columns_and_return_confirmation_data(setup):
    """
    Summary: A complete submission is stored as 'Submitted' and returns the name and submission date for the confirmation.
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
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_optional_details_roundtrip(setup):
    """
    Summary: Optional details are stored and returned as entered.
    AC1: The form contains: Event Name (required), Description (required),
        Purpose (required), Preferred Date(s) and Time (required), Expected
        Attendance (required), Venue Requirements (optional), Accessibility
        Needs (optional), Equipment Requirements (optional), Registration Needs
        (optional).
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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


def test_optional_withdrawal_deadline_roundtrips_as_singapore_local_time(setup):
    """
    Summary: An optional withdrawal deadline is stored and returned in Singapore time.
    AC1: The form contains: Event Name (required), Description (required),
        Purpose (required), Preferred Date(s) and Time (required), Expected
        Attendance (required), Venue Requirements (optional), Accessibility
        Needs (optional), Equipment Requirements (optional), Registration Needs
        (optional).
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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
def test_withdrawal_deadline_must_be_valid_and_no_later_than_start(setup, deadline):
    """
    Summary: A withdrawal deadline must be a valid time no later than the event start.
    AC1: The form contains: Event Name (required), Description (required),
        Purpose (required), Preferred Date(s) and Time (required), Expected
        Attendance (required), Venue Requirements (optional), Accessibility
        Needs (optional), Equipment Requirements (optional), Registration Needs
        (optional).
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    response = setup[0].post(
        "/events", json={**VALID, "withdrawalDeadline": deadline}
    )
    assert response.status_code == 400
    assert "Withdrawal Deadline" in response.json["errors"][0]
    setup[2].execute.assert_not_called()


def test_withdrawal_deadline_must_be_text(setup):
    """
    Summary: A withdrawal deadline that is not text is refused.
    AC1: The form contains: Event Name (required), Description (required),
        Purpose (required), Preferred Date(s) and Time (required), Expected
        Attendance (required), Venue Requirements (optional), Accessibility
        Needs (optional), Equipment Requirements (optional), Registration Needs
        (optional).
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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
def test_exact_missing_fields_prevent_database_call(setup, field, label, value):
    """
    Summary: Submission is blocked and lists exactly the missing required fields.
    AC4: Given one or more required fields are missing, when the Event
        Organiser attempts to submit, then submission is blocked and a pop-up
        is shown, listing exactly which fields are missing.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = client.post("/events", json={**VALID, field: value})

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["missingFields"] == [label]
    cursor.execute.assert_not_called()


def test_all_required_missing(setup):
    """
    Summary: With every required field missing, all of them are listed.
    AC4: Given one or more required fields are missing, when the Event
        Organiser attempts to submit, then submission is blocked and a pop-up
        is shown, listing exactly which fields are missing.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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
def test_attendance_boundary_validation(setup, value):
    """
    Summary: Expected attendance must be a whole number in range.
    AC1: The form contains: Event Name (required), Description (required),
        Purpose (required), Preferred Date(s) and Time (required), Expected
        Attendance (required), Venue Requirements (optional), Accessibility
        Needs (optional), Equipment Requirements (optional), Registration Needs
        (optional).
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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
def test_invalid_period_validation(setup, value):
    """
    Summary: An end time before the start time is refused.
    AC1: The form contains: Event Name (required), Description (required),
        Purpose (required), Preferred Date(s) and Time (required), Expected
        Attendance (required), Venue Requirements (optional), Accessibility
        Needs (optional), Equipment Requirements (optional), Registration Needs
        (optional).
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    assert (
        setup[0].post("/events", json={**VALID, "preferredEndDate": value}).status_code
        == 400
    )


@pytest.mark.parametrize("body", [None, [], "text"], ids=["none", "empty", "text"])
def test_invalid_json_body(setup, body):
    """
    Summary: A body that is not a JSON object is refused.
    AC2: Given all required fields (Event Name, Description, Purpose, Preferred
        Date(s) and Time, Expected Attendance) are filled in, when the Event
        Organiser submits, then the status changes to 'Submitted', the
        submission date is recorded, and it appears in the queue of submitted
        requests visible to Event Coordinators.
    Double: None
    """
    # Arrange (Given): setup, body, from fixtures

    # Act + Assert (When / Then)
    assert setup[0].post("/events", json=body).status_code == 400


def test_optional_field_wrong_type(setup):
    """
    Summary: An optional field that is not text is refused.
    AC1: The form contains: Event Name (required), Description (required),
        Purpose (required), Preferred Date(s) and Time (required), Expected
        Attendance (required), Venue Requirements (optional), Accessibility
        Needs (optional), Equipment Requirements (optional), Registration Needs
        (optional).
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    assert (
        setup[0].post("/events", json={**VALID, "venueRequirements": []}).status_code
        == 400
    )


def test_submit_persists_organiser_id(setup):
    """
    Summary: The submitting organiser is recorded so ownership can be checked later.
    AC2: Given all required fields (Event Name, Description, Purpose, Preferred
        Date(s) and Time, Expected Attendance) are filled in, when the Event
        Organiser submits, then the status changes to 'Submitted', the
        submission date is recorded, and it appears in the queue of submitted
        requests visible to Event Coordinators.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
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
def test_legacy_descriptions_are_not_rewritten(value, description, purpose):
    """
    Summary: Descriptions stored before the metadata format are returned unchanged.
    AC1: The form contains: Event Name (required), Description (required),
        Purpose (required), Preferred Date(s) and Time (required), Expected
        Attendance (required), Venue Requirements (optional), Accessibility
        Needs (optional), Equipment Requirements (optional), Registration Needs
        (optional).
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    assert unpack_description(value) == (description, purpose, None)


def test_nullable_legacy_fields_serialize():
    """
    Summary: Older rows with empty optional columns still read back.
    AC1: The form contains: Event Name (required), Description (required),
        Purpose (required), Preferred Date(s) and Time (required), Expected
        Attendance (required), Venue Requirements (optional), Accessibility
        Needs (optional), Equipment Requirements (optional), Registration Needs
        (optional).
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    row = saved_row()
    for column in FIELDS.values():
        row[column] = None
    row["submission_date"] = None
    serialized = serialize(row)
    assert serialized["preferredStartDate"] == ""
    assert serialized["submittedAt"] is None
    assert serialized["purpose"] == ""


def test_timestamptz_values_serialize_as_singapore_local():
    """
    Summary: Stored timestamps are returned as Singapore local time.
    AC1: The form contains: Event Name (required), Description (required),
        Purpose (required), Preferred Date(s) and Time (required), Expected
        Attendance (required), Venue Requirements (optional), Accessibility
        Needs (optional), Equipment Requirements (optional), Registration Needs
        (optional).
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    row = saved_row()
    row["preferred_start_date"] = datetime(2026, 10, 1, 1, tzinfo=UTC)
    row["preferred_end_date"] = datetime(2026, 10, 1, 9, tzinfo=UTC)

    serialized = serialize(row)

    assert serialized["preferredStartDate"] == "2026-10-01T09:00:00"
    assert serialized["preferredEndDate"] == "2026-10-01T17:00:00"


@pytest.mark.parametrize("operation", ["execute", "commit"])
def test_database_failure_never_reports_success(setup, operation):
    """
    Summary: A database failure is never reported as a successful submission.
    AC2: Given all required fields (Event Name, Description, Purpose, Preferred
        Date(s) and Time, Expected Attendance) are filled in, when the Event
        Organiser submits, then the status changes to 'Submitted', the
        submission date is recorded, and it appears in the queue of submitted
        requests visible to Event Coordinators.
    Double: Stub (psycopg2.connect raises)
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


def test_missing_database_configuration():
    """
    Summary: Missing database configuration.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client(), role="Event Organiser")
    assert client.post("/events", json=VALID).status_code == 503
    assert (
        client.get(f"/events/submitted?coordinatorId={COORDINATOR_ID}").status_code
        == 503
    )
