"""
SCRUM-153: Re-check Safety After High-Impact Changes

User Story
----------
As an Event Coordinator, I want a safety approval to be withdrawn when a
high-impact detail changes afterwards, so that the event is never prepared on
the basis of an outdated safety review.

Acceptance Criteria
-------------------
AC1: Given an event is 'Confirmed', when its date/time, expected attendance,
     venue requirements, equipment requirements or accessibility needs change,
     then its status returns to 'Pending Safety Check' and the coordinator is
     told why.
AC2: Given only a low-impact field changes (name, description, purpose,
     registration needs), then the event stays 'Confirmed'.
AC3: Given a safety approval is withdrawn, then it stays visible in the event's
     safety history.
AC4: Given a high-impact change to a 'Confirmed' event is waiting for its new
     safety check, when a registered Attendee views the event, then they still
     see the previously approved details, and the changed details are shown to
     them only after the Safety Officer approves the new safety check.
AC5: Given the new safety check ends without approval (changes requested or the
     event is cancelled), then registered Attendees are never shown the
     unapproved change, and they continue to see the last approved details or
     the cancellation.

This file covers the whole story. AC1 to AC3 (the withdrawal itself, through
PATCH /events/<id>/details) come first, then AC4 and AC5 (what registered
Attendees see meanwhile, through GET /events/attendee-summaries).

Real
----
- The Event Service routes in app/__init__.py and the rules in app/models.py,
  run through a real create_app(): request validation, the caller's role and
  ownership checks from the signed token, the status rules, and the SQL and
  parameters sent to the database (including notification outbox rows).
- For AC4 and AC5, GET /events/attendee-summaries and GET /events/summaries:
  the ids validation, reading the event's action history to find the last
  approved schedule and venue, and the JSON returned.
- Assertions are on the HTTP status, the response body and the queries and
  parameters the cursor received.

Doubled
-------
- psycopg2.connect: Stub (fixture) - a MagicMock connection whose cursor
  returns canned rows; Mock - its execute calls are asserted to prove what was
  (or was not) written. The AC4/AC5 tests mostly use it as a Stub only.
- Supabase JWKS: Stub (tests/conftest.py) - tokens are signed with a throwaway
  ES256 key.

Not proven
----------
- That the SQL runs against the real Postgres schema, constraints and row locks
  (-> tests/integration/ against a throwaway postgres:17.6).
- That the notification outbox rows are delivered (-> Notification Service
  tests and the E2E journeys).
- That the history entries the AC4/AC5 tests hand in are the ones the edit
  path writes (-> the AC1 to AC3 tests here and test_scrum46_attendee_notifications.py).
- Which roles may call the attendee endpoint (-> test_scrum9_event_view_access.py).
- That the registration composite passes the result on to Attendees.
"""
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.models import (
    EDITABLE_FIELDS,
    FIELDS,
    HIGH_IMPACT_FIELDS,
    LOW_IMPACT_FIELDS,
    NOT_DRAFT,
    SAFETY_TRANSITIONS,
)
from tests.unit.factories import (
    COORDINATOR,
    EVENT,
    ROUND,
    approval_entry,
    attendee_summary_row,
    baseline_entry,
    signed_in,
)

EVENT_ID = "00000000-0000-0000-0000-000000000001"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OTHER_COORDINATOR_ID = "22222222-2222-4222-8222-222222222222"
OFFICER_ID = "33333333-3333-4333-8333-333333333333"
ROUND_TWO_ID = "55555555-5555-4555-8555-555555555555"
ROUND_THREE_ID = "66666666-6666-4666-8666-666666666666"
OTHER_ROUND_ID = "77777777-7777-4777-8777-777777777777"
INTERNAL_TOKEN = "test-internal-token"
INTERNAL_HEADERS = {"X-Internal-Token": INTERNAL_TOKEN}

RECHECK = {
    "withdrawnSafetyCheckId": ROUND_TWO_ID,
    "safetyCheckId": ROUND_THREE_ID,
    "roundNumber": 3,
    # SCRUM-46: rechecks preserve the last effective actual venue before edits.
    "venueBefore": "Grand Hall",
}

# The coordinator's approve decision, which an edit must never erase.
DECISION = {
    "status": "Approved",
    "coordinatorId": COORDINATOR_ID,
    "decidedAt": "2026-10-02T01:00:00+00:00",
    "reason": None,
}
# The history a 'Confirmed' event carries: submitted for its check, then
# approved. SCRUM-150 writes the second entry, and its `safetyCheckId` is what
# the gate matches the withdrawn round against.
APPROVED_HISTORY = [
    {
        "status": "Pending Safety Check",
        "details": "Submitted for Operational Safety Check (round 2).",
        "coordinatorId": COORDINATOR_ID,
        "safetyCheckId": ROUND_TWO_ID,
        "recordedAt": "2026-10-03T01:00:00+00:00",
    },
    {
        "status": "Confirmed",
        "details": "Operational Safety Check approved (round 2).",
        "decidedBy": OFFICER_ID,
        "safetyCheckId": ROUND_TWO_ID,
        "remarks": "Looks safe.",
        "recordedAt": "2026-10-04T01:00:00+00:00",
    },
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


@pytest.fixture
def no_token(monkeypatch):
    """No INTERNAL_SERVICE_TOKEN configured: the token-locked paths fail closed (SCRUM-10)."""
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": "unused-test-url",
            "INTERNAL_SERVICE_TOKEN": None,
        }
    )
    return signed_in(app.test_client()), connection, cursor


@pytest.fixture
def no_database():
    app = create_app({"TESTING": True, "DATABASE_URL": None})
    return signed_in(app.test_client())


OTHER = "10000000-0000-0000-0000-000000000099"
SECOND_ROUND = "10000000-0000-0000-0000-000000000033"
# The live row holds the coordinator's new, unapproved window (2030-03-02 09:00-18:00 SGT).
LIVE = {"startTime": "2030-03-02T09:00:00", "endTime": "2030-03-02T18:00:00"}
APPROVED = {"startTime": "2030-03-01T09:00:00", "endTime": "2030-03-01T17:00:00"}


@pytest.fixture
def attendee_setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr("app.models.psycopg2.connect", connect)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client()), cursor, connect


def attendee_summary(client, *ids):
    response = client.get(f"/events/attendee-summaries?ids={','.join(ids or (EVENT,))}")
    assert response.status_code == 200, response.json
    return response.json["events"]


def event_row(
    status="Confirmed",
    coordinator_id=COORDINATOR_ID,
    description="A workshop for the community.",
    purpose="Skills sharing.",
    decision=None,
    action_history=None,
    event_name="Community Workshop",
    start=datetime(2026, 11, 10, 9),
    end=datetime(2026, 11, 10, 12),
    expected_attendance=120,
    venue_requirements="Hall A",
    equipment_requirements="Two microphones",
    accessibility_needs="Step-free access",
    registration_needs="Name and email",
):
    row = {column: "" for column in FIELDS.values()}
    row.update(
        event_id=EVENT_ID,
        event_name=event_name,
        status=status,
        coordinator_id=coordinator_id,
        organiser_id=None,
        submission_date=datetime(2026, 10, 1, 8, tzinfo=UTC),
        preferred_start_date=start,
        preferred_end_date=end,
        expected_attendance=expected_attendance,
        venue_requirements=venue_requirements,
        equipment_requirements=equipment_requirements,
        accessibility_needs=accessibility_needs,
        registration_needs=registration_needs,
        description=json.dumps(
            {
                "_connectsphere": "event-submission-v1",
                "description": description,
                "purpose": purpose,
                "decision": decision if decision is not None else DECISION,
                "decisionHistory": [decision if decision is not None else DECISION],
                "actionDetails": "Venue confirmed with Venue Staff.",
                "actionHistory": (
                    APPROVED_HISTORY if action_history is None else action_history
                ),
            }
        ),
    )
    return row


def patch_details(client, changes, headers=None, **overrides):
    body = {"coordinatorId": COORDINATOR_ID, "changes": changes, **overrides}
    return client.patch(f"/events/{EVENT_ID}/details", json=body, headers=headers or {})


def saved_metadata(cursor):
    """The metadata JSON the UPDATE wrote."""
    params = cursor.execute.call_args_list[1].args[1]
    return json.loads(params[-3])


def saved_status(cursor):
    return cursor.execute.call_args_list[1].args[1][-2]


# A changed value per high-impact field, for the parametrised gate tests. The
# start moves earlier and the end later, so each one alone still leaves the
# event's window valid (end after start) and the test exercises the gate
# rather than validation.
HIGH_IMPACT_CHANGES = {
    "preferredStartDate": "2026-11-10T08:00:00",
    "preferredEndDate": "2026-11-10T18:00:00",
    "expectedAttendance": "400",
    "venueRequirements": "Hall B, with a stage",
    "equipmentRequirements": "Four microphones and a projector",
    "accessibilityNeeds": "Step-free access and a hearing loop",
}
LOW_IMPACT_CHANGES = {
    "eventName": "Community Workshop (Autumn)",
    "description": "A rewritten description of the same workshop.",
    "purpose": "Skills sharing and networking.",
    "registrationNeeds": "Name, email and dietary requirements",
}


# --- AC1: the gate ------------------------------------------------------------


@pytest.mark.parametrize("field", list(HIGH_IMPACT_FIELDS))
def test_ac1_a_high_impact_change_to_a_confirmed_event_is_refused_with_a_recheck_required_message_naming_the_field(field, setup):
    """
    Summary: PATCH /events/<id>/details on a 'Confirmed' event changing only one of the start, end, attendance, venue, equipment or accessibility needs, without a recheck block, answers 409 SAFETY_RECHECK_REQUIRED naming that field in highImpactFields and changedFields, with a label and a message that says the safety approval will be withdrawn and the event goes to 'Pending Safety Check'; only the lookup SELECT ran.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (cursor.fetchone returns the 'Confirmed' event with its approval in the history),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()

    # Act (When)
    response = patch_details(client, {field: HIGH_IMPACT_CHANGES[field]})

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_RECHECK_REQUIRED"
    assert response.json["highImpactFields"] == [field]
    assert response.json["changedFields"] == [field]
    assert response.json["labels"]
    assert response.json["labels"][0] in response.json["message"]
    assert "withdraw this event's safety approval" in response.json["message"]
    assert "Pending Safety Check" in response.json["message"]
    # Only the SELECT ran.
    assert cursor.execute.call_count == 1


def test_ac1_a_recheck_saves_the_changed_fields_and_moves_the_event_to_pending_safety_check_in_one_update(setup):
    """
    Summary: PATCH /events/<id>/details on a 'Confirmed' event with attendance and start changes, the internal token and a safetyRecheck block answers 200 with status "Pending Safety Check" and the new attendance "400"; one UPDATE carries both the changed columns and the new status, and three statements ran in all (lookup, update, new-round notification).
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (cursor.fetchone returns the 'Confirmed' event, then the updated 'Pending Safety Check' event),
        Mock (the UPDATE's SQL and parameters and the total call count asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row(),
        event_row(
            status="Pending Safety Check",
            expected_attendance=400,
            start=datetime(2026, 11, 10, 8),
        ),
    ]

    # Act (When)
    response = patch_details(
        client,
        {"expectedAttendance": "400", "preferredStartDate": "2026-11-10T08:00:00"},
        headers=INTERNAL_HEADERS,
        safetyRecheck=RECHECK,
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Pending Safety Check"
    assert response.json["expectedAttendance"] == "400"
    # One UPDATE, carrying both the columns and the new status, so AC1's
    # status change can never land without the change that caused it.
    update_sql, params = cursor.execute.call_args_list[1].args
    assert 'UPDATE public."Event"' in update_sql
    assert "expected_attendance = %s" in update_sql
    assert "status = %s" in update_sql
    assert saved_status(cursor) == "Pending Safety Check"
    assert 400 in params
    # SCRUM-168 also saves the new round notification in this transaction.
    assert cursor.execute.call_count == 3


def test_ac1_the_recheck_history_entry_says_why_naming_the_changed_details_and_both_rounds(setup):
    """
    Summary: After a recheck changing attendance and venue, the stored action history ends with a "Pending Safety Check" entry whose details read "Safety approval withdrawn because Expected attendance and Venue requirements changed after approval ... (round 3)", with the changed and high-impact field lists, the coordinator, the withdrawn round and the new round.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (cursor.fetchone returns the 'Confirmed' event, then the updated event),
        Mock (the UPDATE's metadata parameter asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row(status="Pending Safety Check")]

    patch_details(
        client,
        {"expectedAttendance": "400", "venueRequirements": "Hall B, with a stage"},
        headers=INTERNAL_HEADERS,
        safetyRecheck=RECHECK,
    )

    # Act (When)
    entry = saved_metadata(cursor)["actionHistory"][-1]

    # Assert (Then)
    assert entry["status"] == "Pending Safety Check"
    assert entry["details"] == (
        "Safety approval withdrawn because Expected attendance and Venue "
        "requirements changed after approval. The event needs a new "
        "Operational Safety Check (round 3) before it can proceed to preparation."
    )
    assert entry["changedFields"] == ["expectedAttendance", "venueRequirements"]
    assert entry["highImpactFields"] == ["expectedAttendance", "venueRequirements"]
    assert entry["coordinatorId"] == COORDINATOR_ID
    assert entry["withdrawnSafetyCheckId"] == ROUND_TWO_ID
    assert entry["safetyCheckId"] == ROUND_THREE_ID
    assert entry["recordedAt"]


def test_ac1_changing_both_date_fields_is_reported_as_one_date_time_change_in_the_history(setup):
    """
    Summary: After a recheck changing both the start and the end, the history entry's details start "Safety approval withdrawn because Date/time changed" and mention "Date/time" only once.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (cursor.fetchone returns the 'Confirmed' event, then the updated event),
        Mock (the UPDATE's metadata parameter asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row(status="Pending Safety Check")]

    patch_details(
        client,
        {
            "preferredStartDate": "2026-11-11T09:00:00",
            "preferredEndDate": "2026-11-11T12:00:00",
        },
        headers=INTERNAL_HEADERS,
        safetyRecheck=RECHECK,
    )

    # Act (When)
    details = saved_metadata(cursor)["actionHistory"][-1]["details"]

    # Assert (Then)
    assert details.count("Date/time") == 1
    assert details.startswith("Safety approval withdrawn because Date/time changed")


def test_ac1_the_refusal_message_for_a_change_to_both_date_fields_names_date_time_once(setup):
    """
    Summary: PATCH /events/<id>/details on a 'Confirmed' event changing both the start and the end, without a recheck block, answers 409 with labels ["Date/time"] and a message that mentions "Date/time" once.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (cursor.fetchone returns the 'Confirmed' event); the 409 body's labels and message are the only assertions
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()

    # Act (When)
    response = patch_details(
        client,
        {
            "preferredStartDate": "2026-11-11T09:00:00",
            "preferredEndDate": "2026-11-11T12:00:00",
        },
    )

    # Assert (Then)
    assert response.json["labels"] == ["Date/time"]
    assert response.json["message"].count("Date/time") == 1


def test_ac1_after_a_recheck_the_safety_officer_can_approve_the_new_round_without_any_extra_step(setup):
    """
    Summary: After a recheck edit is saved, feeding its stored metadata back to update_event_safety_status with the new round id and number 3 and the officer's decision moves the event to "Confirmed" (round N+1 is found with no change of its own).
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    Double: Stub (cursor.fetchone returns the 'Confirmed' event, the 'Pending Safety Check' event rebuilt from the saved metadata, then a 'Confirmed' event); the returned status is the only assertion
    """
    # Arrange (Given)
    from app.models import update_event_safety_status

    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row(status="Pending Safety Check")]
    patch_details(
        client,
        {"expectedAttendance": "400"},
        headers=INTERNAL_HEADERS,
        safetyRecheck=RECHECK,
    )
    after_recheck = saved_metadata(cursor)

    cursor.reset_mock()
    row = event_row(status="Pending Safety Check")
    row["description"] = json.dumps(after_recheck)
    cursor.fetchone.side_effect = [row, event_row(status="Confirmed")]

    # Act (When)
    updated = update_event_safety_status(
        "unused-test-url",
        EVENT_ID,
        "Confirmed",
        ROUND_THREE_ID,
        3,
        decided_by=OFFICER_ID,
        remarks="Re-reviewed and safe.",
        # The final direct owner call supplies the corresponding approved venue.
        attendee_venue="Grand Hall",
    )

    # Assert (Then)
    assert updated["status"] == "Confirmed"


# --- AC2: low-impact edits ----------------------------------------------------


@pytest.mark.parametrize("field", list(LOW_IMPACT_FIELDS))
def test_ac2_a_low_impact_change_keeps_a_confirmed_event_confirmed(field, setup):
    """
    Summary: PATCH /events/<id>/details on a 'Confirmed' event changing only the name, description, purpose or registration needs answers 200 with status "Confirmed"; the UPDATE keeps status "Confirmed" and the history entry is a plain "Confirmed" entry listing that field, with no withdrawal and no safety fields.
    AC2: Given only a low-impact field changes (name, description, purpose,
        registration needs), then the event stays 'Confirmed'.
    Double: Stub (cursor.fetchone returns the 'Confirmed' event twice: the lookup and the updated row),
        Mock (the UPDATE's status and metadata asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row()]

    # Act (When)
    response = patch_details(client, {field: LOW_IMPACT_CHANGES[field]})

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Confirmed"
    assert saved_status(cursor) == "Confirmed"
    entry = saved_metadata(cursor)["actionHistory"][-1]
    assert entry["status"] == "Confirmed"
    assert entry["changedFields"] == [field]
    assert "withdrawn" not in entry["details"]
    # No safety fields on a plain edit's entry.
    assert "safetyCheckId" not in entry
    assert "withdrawnSafetyCheckId" not in entry
    assert "highImpactFields" not in entry


def test_ac2_a_low_impact_edit_records_which_details_changed_by_label(setup):
    """
    Summary: After changing the name and the purpose of a 'Confirmed' event, the stored action history ends with the entry "Event details updated: Event name, Purpose."
    AC2: Given only a low-impact field changes (name, description, purpose,
        registration needs), then the event stays 'Confirmed'.
    Double: Stub (cursor.fetchone returns the 'Confirmed' event twice: the lookup and the updated row),
        Mock (the UPDATE's metadata parameter asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row()]

    patch_details(
        client,
        {
            "eventName": LOW_IMPACT_CHANGES["eventName"],
            "purpose": LOW_IMPACT_CHANGES["purpose"],
        },
    )

    # Act (When)
    entry = saved_metadata(cursor)["actionHistory"][-1]

    # Assert (Then)
    assert entry["details"] == "Event details updated: Event name, Purpose."


def test_ac2_a_new_description_and_purpose_are_written_into_the_description_metadata(setup):
    """
    Summary: After changing the description and purpose of a 'Confirmed' event, the metadata JSON in the UPDATE holds the new description and purpose (they are stored in the `description` JSON, not in columns).
    AC2: Given only a low-impact field changes (name, description, purpose,
        registration needs), then the event stays 'Confirmed'.
    Double: Stub (cursor.fetchone returns the 'Confirmed' event twice: the lookup and the updated row),
        Mock (the UPDATE's metadata parameter asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row()]

    patch_details(
        client,
        {
            "description": LOW_IMPACT_CHANGES["description"],
            "purpose": LOW_IMPACT_CHANGES["purpose"],
        },
    )

    # Act (When)
    metadata = saved_metadata(cursor)

    # Assert (Then)
    assert metadata["description"] == LOW_IMPACT_CHANGES["description"]
    assert metadata["purpose"] == LOW_IMPACT_CHANGES["purpose"]


def test_ac1_ac2_an_edit_mixing_low_and_high_impact_fields_on_a_confirmed_event_is_refused_and_saves_nothing(setup):
    """
    Summary: PATCH /events/<id>/details on a 'Confirmed' event changing the name and the attendance together, without a recheck block, answers 409 SAFETY_RECHECK_REQUIRED listing both changed fields and only the attendance as high-impact; only the lookup SELECT ran, so the low-impact name change is not quietly saved.
    AC1: Given an event is 'Confirmed', when its date/time, expected
        attendance, venue requirements, equipment requirements or accessibility
        needs change, then its status returns to 'Pending Safety Check' and the
        coordinator is told why.
    AC2: Given only a low-impact field changes (name, description, purpose,
        registration needs), then the event stays 'Confirmed'.
    Double: Stub (cursor.fetchone returns the 'Confirmed' event),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()

    # Act (When)
    response = patch_details(
        client,
        {
            "eventName": LOW_IMPACT_CHANGES["eventName"],
            "expectedAttendance": "400",
        },
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_RECHECK_REQUIRED"
    assert response.json["changedFields"] == ["eventName", "expectedAttendance"]
    assert response.json["highImpactFields"] == ["expectedAttendance"]
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"expectedAttendance": "120"},
        {"expectedAttendance": " 120 "},
        {"venueRequirements": " Hall A "},
        {"preferredStartDate": "2026-11-10T09:00:00.000"},
        {"preferredStartDate": "2026-11-10T09:00"},
        {"eventName": "Community Workshop"},
        {"description": "A workshop for the community."},
        {
            "preferredStartDate": "2026-11-10T09:00",
            "expectedAttendance": "120",
            "venueRequirements": "Hall A",
        },
    ],
    ids=["expectedattendance_120", "expectedattendance_120_2", "venuerequirements_hall_a", "preferredstartdate_2026_11_10t09_00_00_000", "preferredstartdate_2026_11_10t09_00", "eventname_community_workshop", "description_a_workshop_for_the_community", "preferredstartdate_2026_11_10t09_00_expectedatte"],
)
def test_ac2_re_saving_values_that_are_already_stored_changes_nothing_and_keeps_the_event_confirmed(changes, setup):
    """
    Summary: PATCH /events/<id>/details on a 'Confirmed' event re-sending values equal to the stored ones (including padded or differently formatted attendance, venue and dates) answers 200 with status "Confirmed", no UPDATE is sent (only the lookup ran) and the action history keeps its length.
    AC2: Given only a low-impact field changes (name, description, purpose,
        registration needs), then the event stays 'Confirmed'.
    Double: Stub (cursor.fetchone returns the 'Confirmed' event),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()

    # Act (When)
    response = patch_details(client, changes)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Confirmed"
    # No UPDATE at all: no status change and no history entry.
    assert cursor.execute.call_count == 1
    assert len(response.json["actionHistory"]) == len(APPROVED_HISTORY)


def test_ac3_a_recheck_keeps_the_approval_entry_in_the_history_with_the_withdrawal_after_it(setup):
    """
    Summary: After a recheck edit, the stored decision is unchanged and the second history entry is still the original round-2 approval ("Operational Safety Check approved (round 2)."), with the withdrawal entry added after it.
    AC3: Given a safety approval is withdrawn, then it stays visible in the
        event's safety history.
    Double: Stub (cursor.fetchone returns the 'Confirmed' event, then the updated event),
        Mock (the UPDATE's metadata parameter asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row(status="Pending Safety Check")]

    patch_details(
        client,
        {"expectedAttendance": "400"},
        headers=INTERNAL_HEADERS,
        safetyRecheck=RECHECK,
    )

    # Act (When)
    metadata = saved_metadata(cursor)

    # Assert (Then)
    assert metadata["decision"] == DECISION
    assert metadata["actionHistory"][1] == APPROVED_HISTORY[1]
    assert metadata["actionHistory"][1]["details"] == (
        "Operational Safety Check approved (round 2)."
    )


# --- AC4: while the new safety check is pending ------------------------------


def test_ac4_pending_recheck_shows_attendees_the_approved_schedule_and_venue(attendee_setup):
    """
    Summary: A Confirmed event took a high-impact time edit and now waits for round 2.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor.fetchall returns one 'Pending Safety Check' row: approval, then a baseline for 09:00-17:00 at Hall A; the live columns hold the new 03-02 window)
    """
    # Arrange (Given)
    client, cursor, _ = attendee_setup
    cursor.fetchall.return_value = [
        attendee_summary_row("Pending Safety Check", [approval_entry(), baseline_entry()])
    ]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert event["startTime"] == APPROVED["startTime"]
    assert event["endTime"] == APPROVED["endTime"]
    assert event["attendeeVenueName"] == "Hall A"
    assert event["status"] == "Pending Safety Check"


def test_ac4_utc_baseline_is_returned_in_the_summary_local_format(attendee_setup):
    """
    Summary: A baseline stored in UTC (01:00-09:00) comes back as 09:00-17:00 Singapore time, without an offset.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor.fetchall returns one 'Pending Safety Check' row whose baseline times are 01:00 and 09:00 UTC)
    """
    # Arrange (Given)
    client, cursor, _ = attendee_setup
    cursor.fetchall.return_value = [
        attendee_summary_row("Pending Safety Check", [approval_entry(), baseline_entry(start="2030-03-01T01:00:00+00:00", end="2030-03-01T09:00:00+00:00")])
    ]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert (event["startTime"], event["endTime"]) == ("2030-03-01T09:00:00", "2030-03-01T17:00:00")


def test_ac4_baseline_without_dates_keeps_live_dates_but_approved_venue(attendee_setup):
    """
    Summary: A baseline captured from an event with no dates holds only venueName, so the dates stay live while the venue is still the approved one.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor.fetchall returns one 'Pending Safety Check' row whose baseline holds only venueName 'Hall A')
    """
    # Arrange (Given)
    client, cursor, _ = attendee_setup
    cursor.fetchall.return_value = [
        attendee_summary_row("Pending Safety Check", [approval_entry(), baseline_entry(start=None, end=None)])
    ]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert (event["startTime"], event["endTime"]) == (LIVE["startTime"], LIVE["endTime"])
    assert event["attendeeVenueName"] == "Hall A"


def test_ac4_attendee_response_exposes_no_pending_values_or_history(attendee_setup):
    """
    Summary: The row's metadata carries remarks, the action history, the changed fields and the new times; none of it may reach the attendee, whose payload is exactly the approved details.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor.fetchall returns one 'Pending Safety Check' row whose approval and baseline entries carry remarks, changedFields and pending times)
    """
    # Arrange (Given)
    client, cursor, _ = attendee_setup
    cursor.fetchall.return_value = [attendee_summary_row("Pending Safety Check", [
        approval_entry(remarks="Officer note"),
        baseline_entry(changedFields=["preferredStartDate", "preferredEndDate"],
                       highImpactFields=["preferredStartDate"], remarks="Internal remark",
                       pending={"preferredStartDate": "2030-03-02T09:00:00"}),
    ])]

    # Act + Assert (When / Then)
    assert attendee_summary(client) == [{
        "id": EVENT, "eventName": "Workshop", "status": "Pending Safety Check",
        "coordinatorId": COORDINATOR, **APPROVED, "attendeeVenueName": "Hall A",
    }]


def test_ac4_second_withdrawal_before_any_approval_keeps_the_earliest_baseline(attendee_setup):
    """
    Summary: A venue-change withdrawal (baseline A) is followed, before any new approval, by a time edit that records baseline B; attendees still see baseline A, the last approved details.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor.fetchall returns one 'Pending Safety Check' row with two baselines in its history: Hall A on 03-01, then Hall B on 03-05)
    """
    # Arrange (Given)
    client, cursor, _ = attendee_setup
    cursor.fetchall.return_value = [attendee_summary_row("Pending Safety Check", [
        approval_entry(),
        baseline_entry(status="Approved", withdrawnSafetyCheckId=ROUND),
        dict(status="Pending Safety Check", safetyCheckId=SECOND_ROUND),
        baseline_entry(start="2030-03-05T09:00:00+08:00", end="2030-03-05T17:00:00+08:00", venue="Hall B"),
    ])]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert {key: event[key] for key in ("startTime", "endTime", "attendeeVenueName")} == {
        **APPROVED, "attendeeVenueName": "Hall A"}


def test_ac4_venue_change_withdrawal_shows_the_approved_venue(attendee_setup):
    """
    Summary: The SCRUM-28 path withdraws the approval back to 'Approved' while Venue Staff re-review the booking; attendees still see the approved window and venue.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor.fetchall returns one 'Approved' row: approval, then a baseline marked withdrawnSafetyCheckId)
    """
    # Arrange (Given)
    client, cursor, _ = attendee_setup
    cursor.fetchall.return_value = [attendee_summary_row("Approved", [
        approval_entry(), baseline_entry(status="Approved", withdrawnSafetyCheckId=ROUND),
    ])]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert {key: event[key] for key in ("startTime", "endTime", "attendeeVenueName")} == {
        **APPROVED, "attendeeVenueName": "Hall A"}


def test_ac4_restored_approval_also_ends_the_overlay(attendee_setup):
    """
    Summary: A venue-change withdrawal is undone, restoring the same approval round (by Venue Staff, not a new Safety Officer approval), so the live details are shown again.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor.fetchall returns one 'Confirmed' row: approval, withdrawal baseline, then an approval with restoredSafetyCheckId)
    """
    # Arrange (Given)
    client, cursor, _ = attendee_setup
    cursor.fetchall.return_value = [attendee_summary_row("Confirmed", [
        approval_entry(),
        baseline_entry(status="Approved", withdrawnSafetyCheckId=ROUND),
        approval_entry(restoredSafetyCheckId=ROUND),
    ])]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert (event["startTime"], event["endTime"]) == (LIVE["startTime"], LIVE["endTime"])
    assert event["attendeeVenueName"] is None


@pytest.mark.parametrize("status,history,description", [
    ("Confirmed", [], None),
    ("Pending Safety Check", [dict(status="Pending Safety Check", safetyCheckId=ROUND)], None),
    ("Pending Safety Check", None, "plain legacy description"),
    ("Pending Safety Check", None,
     '{"_connectsphere": "event-submission-v1", "description": "Workshop", "purpose": "Learning"}'),
    ("Confirmed", [approval_entry(), baseline_entry(status="Approved")], None),
], ids=["no-history", "first-submission", "non-json", "no-action-history", "confirmed-row-wins"])
def test_ac4_event_never_withdrawn_or_legacy_metadata_shows_live_values(attendee_setup, status, history, description):
    """
    Summary: With no baseline to fall back to (never withdrawn, first-time submission, or legacy metadata) the live values are shown; so are they when the row is Confirmed, even though an older baseline is on record (confirmed-row-wins).
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor.fetchall returns one row per case: empty history, a first submission only, non-JSON or action-less metadata, or a Confirmed row with an old baseline)
    """
    # Arrange (Given)
    client, cursor, _ = attendee_setup
    cursor.fetchall.return_value = [attendee_summary_row(status, history, description=description)]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert (event["startTime"], event["endTime"]) == (LIVE["startTime"], LIVE["endTime"])
    assert event["attendeeVenueName"] is None


def test_ac4_staff_summaries_still_show_live_values_during_recheck(attendee_setup):
    """
    Summary: The same pending row read through GET /events/summaries (staff screens) shows the live values and no attendeeVenueName: the approved-details overlay is for attendees only.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor.fetchall returns one 'Pending Safety Check' row with an approval and a baseline), read through /events/summaries instead
    """
    # Arrange (Given)
    client, cursor, _ = attendee_setup
    cursor.fetchall.return_value = [
        attendee_summary_row("Pending Safety Check", [approval_entry(), baseline_entry()])
    ]

    # Act (When)
    response = client.get(f"/events/summaries?ids={EVENT}")

    # Assert (Then)
    assert response.status_code == 200
    [event] = response.json["events"]
    assert (event["startTime"], event["endTime"]) == (LIVE["startTime"], LIVE["endTime"])
    assert "attendeeVenueName" not in event


def test_ac4_each_event_in_one_request_gets_its_own_view(attendee_setup):
    """
    Summary: One request names two events: one waiting for its new safety check, one Confirmed with no changes. Only the first falls back to the approved details.
    AC4: Given a high-impact change to a 'Confirmed' event is waiting for its
        new safety check, when a registered Attendee views the event, then they
        still see the previously approved details, and the changed details are
        shown to them only after the Safety Officer approves the new safety
        check.
    Double: Stub (cursor.fetchall returns two rows: a 'Pending Safety Check' one with a baseline, and a 'Confirmed' one with empty history)
    """
    # Arrange (Given)
    client, cursor, _ = attendee_setup
    cursor.fetchall.return_value = [
        attendee_summary_row("Pending Safety Check", [approval_entry(), baseline_entry()]),
        attendee_summary_row("Confirmed", [], event_id=OTHER),
    ]

    # Act (When)
    events = {event["id"]: event for event in attendee_summary(client, EVENT, OTHER)}

    # Assert (Then)
    assert (events[EVENT]["startTime"], events[EVENT]["attendeeVenueName"]) == (APPROVED["startTime"], "Hall A")
    assert (events[OTHER]["startTime"], events[OTHER]["attendeeVenueName"]) == (LIVE["startTime"], None)


# --- AC5: the new safety check ends without approval -------------------------


def test_ac5_changes_requested_keeps_the_first_baseline_across_later_edits(attendee_setup):
    """
    Summary: The Safety Officer requested changes and the coordinator kept editing; the later edit entries carry no baseline of their own, so attendees still see the one recorded before round 2.
    AC5: Given the new safety check ends without approval (changes requested or
        the event is cancelled), then registered Attendees are never shown the
        unapproved change, and they continue to see the last approved details
        or the cancellation.
    Double: Stub (cursor.fetchall returns one 'Safety Changes Requested' row: approval, baseline, the officer's request, then two edit entries with no baseline)
    """
    # Arrange (Given)
    client, cursor, _ = attendee_setup
    cursor.fetchall.return_value = [attendee_summary_row("Safety Changes Requested", [
        approval_entry(),
        baseline_entry(),
        dict(status="Safety Changes Requested", safetyCheckId=SECOND_ROUND, remarks="Fix exits"),
        dict(status="Safety Changes Requested", details="Event details updated: Name.", changedFields=["eventName"]),
        dict(status="Safety Changes Requested", details="Event details updated: Start.",
             changedFields=["preferredStartDate"]),
    ])]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert {key: event[key] for key in ("startTime", "endTime", "attendeeVenueName")} == {
        **APPROVED, "attendeeVenueName": "Hall A"}


def test_ac5_cancelled_after_recheck_shows_approved_details_with_cancellation(attendee_setup):
    """
    Summary: The re-check ends in rejection, so the event is Cancelled; attendees see the cancellation and the approved details, not the unapproved change.
    AC5: Given the new safety check ends without approval (changes requested or
        the event is cancelled), then registered Attendees are never shown the
        unapproved change, and they continue to see the last approved details
        or the cancellation.
    Double: Stub (cursor.fetchall returns one 'Cancelled' row: approval, baseline, then a Cancelled entry for round 2)
    """
    # Arrange (Given)
    client, cursor, _ = attendee_setup
    cursor.fetchall.return_value = [attendee_summary_row("Cancelled", [
        approval_entry(), baseline_entry(), dict(status="Cancelled", safetyCheckId=SECOND_ROUND, remarks="Unsafe"),
    ])]

    # Act (When)
    [event] = attendee_summary(client)

    # Assert (Then)
    assert event["status"] == "Cancelled"
    assert {key: event[key] for key in ("startTime", "endTime", "attendeeVenueName")} == {
        **APPROVED, "attendeeVenueName": "Hall A"}


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


@pytest.mark.parametrize(
    "changes",
    [
        {"eventName": LOW_IMPACT_CHANGES["eventName"]},
        {"description": LOW_IMPACT_CHANGES["description"]},
        {"registrationNeeds": LOW_IMPACT_CHANGES["registrationNeeds"]},
    ],
    ids=["eventname_low_impact_changes_eventname", "description_low_impact_changes_description", "registrationneeds_low_impact_changes_registratio"],
)
def test_a_low_impact_edit_preserves_the_decision_and_earlier_history(changes, setup):
    """
    Summary: PATCH /events/<id>/details on a 'Confirmed' event changing only the name, description or registration needs leaves the stored decision, decision history, action details, `_connectsphere` marker and earlier history entries unchanged and appends exactly one entry.
    Supporting design check: rewriting `description` must not drop the metadata
        stored alongside it
    Double: Stub (cursor.fetchone returns the 'Confirmed' event twice: the lookup and the updated row),
        Mock (the UPDATE's metadata parameter asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(), event_row()]

    patch_details(client, changes)

    # Act (When)
    metadata = saved_metadata(cursor)

    # Assert (Then)
    assert metadata["decision"] == DECISION
    assert metadata["decisionHistory"] == [DECISION]
    assert metadata["actionDetails"] == "Venue confirmed with Venue Staff."
    assert metadata["actionHistory"][: len(APPROVED_HISTORY)] == APPROVED_HISTORY
    assert len(metadata["actionHistory"]) == len(APPROVED_HISTORY) + 1
    assert metadata["_connectsphere"] == "event-submission-v1"


# --- Races and the gate's edges ----------------------------------------------


@pytest.mark.parametrize("withdrawn_id", [OTHER_ROUND_ID, ROUND_THREE_ID], ids=["other_round_id", "round_three_id"])
def test_a_recheck_that_withdraws_the_wrong_round_is_refused(withdrawn_id, setup):
    """
    Summary: PATCH /events/<id>/details with a safetyRecheck block that withdraws a round other than the approval the event holds (a made-up round, or the new round) answers 409 STALE_SAFETY_CHECK and only the lookup read ran.
    Supporting design check: a stale or made-up round cannot move the event
    Double: Stub (cursor.fetchone returns the 'Confirmed' event approved in round 2),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()

    # Act (When)
    response = patch_details(
        client,
        {"expectedAttendance": "400"},
        headers=INTERNAL_HEADERS,
        safetyRecheck={**RECHECK, "withdrawnSafetyCheckId": withdrawn_id},
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "STALE_SAFETY_CHECK"
    assert cursor.execute.call_count == 1


def test_a_recheck_is_refused_when_the_confirmed_event_has_no_approval_entry(setup):
    """
    Summary: PATCH /events/<id>/details with a safetyRecheck block on a 'Confirmed' event whose action history is empty answers 409 STALE_SAFETY_CHECK.
    Supporting design check: with no approval in the history there is nothing
        for the recheck to withdraw
    Double: Stub (cursor.fetchone returns a 'Confirmed' event with an empty history); the 409 status and code are the only assertions
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(action_history=[])

    # Act (When)
    response = patch_details(
        client,
        {"expectedAttendance": "400"},
        headers=INTERNAL_HEADERS,
        safetyRecheck=RECHECK,
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "STALE_SAFETY_CHECK"


@pytest.mark.parametrize(
    "headers",
    [{}, {"X-Internal-Token": "wrong-token"}],
    ids=["missing", "wrong"],
)
def test_a_recheck_block_without_the_right_internal_token_is_still_gated(headers, setup):
    """
    Summary: PATCH /events/<id>/details on a 'Confirmed' event with a safetyRecheck block but a missing or wrong X-Internal-Token answers 409 SAFETY_RECHECK_REQUIRED and only the lookup read ran, so the block is ignored.
    Supporting design check: `safetyRecheck` is only believed from Safety Check
        Service
    Double: Stub (cursor.fetchone returns the 'Confirmed' event),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()

    # Act (When)
    response = patch_details(
        client, {"expectedAttendance": "400"}, headers=headers, safetyRecheck=RECHECK
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_RECHECK_REQUIRED"
    assert cursor.execute.call_count == 1


def test_a_recheck_block_is_refused_with_503_when_no_internal_token_is_configured(no_token):
    """
    Summary: With INTERNAL_SERVICE_TOKEN unset, PATCH /events/<id>/details carrying a safetyRecheck block answers 503 INTERNAL_AUTH_NOT_CONFIGURED and no query is sent.
    Supporting design check: the lock fails closed, so a `safetyRecheck` block
        alone no longer suffices
    Double: Mock (cursor.execute asserted never called)
    """
    # Arrange (Given)
    client, _, cursor = no_token

    # Act (When)
    response = patch_details(
        client, {"expectedAttendance": "400"}, safetyRecheck=RECHECK
    )

    # Assert (Then)
    assert response.status_code == 503
    assert response.json["code"] == "INTERNAL_AUTH_NOT_CONFIGURED"
    cursor.execute.assert_not_called()


def test_a_plain_coordinator_edit_still_works_when_no_internal_token_is_configured(no_token):
    """
    Summary: With INTERNAL_SERVICE_TOKEN unset, PATCH /events/<id>/details by the assigned coordinator changing only the name answers 200.
    Supporting design check: only the recheck and the Lead's edit need the
        lock; an ordinary edit does not
    Double: Stub (cursor.fetchone returns the 'Confirmed' event twice: the lookup and the updated row); the 200 status is the only assertion
    """
    # Arrange (Given)
    client, _, cursor = no_token
    cursor.fetchone.side_effect = [event_row(), event_row()]

    # Act (When)
    response = patch_details(client, {"eventName": LOW_IMPACT_CHANGES["eventName"]})

    # Assert (Then)
    assert response.status_code == 200


def test_a_lead_edit_is_refused_with_503_when_no_internal_token_is_configured(no_token):
    """
    Summary: With INTERNAL_SERVICE_TOKEN unset, PATCH /events/<id>/details with actorRole "Event Coordinator Lead" answers 503 and no query is sent.
    Supporting design check: acting as the Lead needs the lock too, so it is
        refused when the lock is unconfigured
    Double: Mock (cursor.execute asserted never called)
    """
    # Arrange (Given)
    client, _, cursor = no_token

    # Act (When)
    response = patch_details(client, {"eventName": "X"}, actorRole="Event Coordinator Lead")

    # Assert (Then)
    assert response.status_code == 503
    cursor.execute.assert_not_called()


def test_the_safety_status_route_cannot_make_the_recheck_move_on_its_own(setup):
    """
    Summary: PATCH /events/<id>/safety-status to "Pending Safety Check" on a 'Confirmed' event answers 409 INVALID_SAFETY_TRANSITION with currentStatus "Confirmed" and only the lookup read ran.
    Supporting design check: 'Confirmed' to 'Pending Safety Check' is only
        reachable through an edit, never through a bare safety-status call
    Double: Stub (cursor.fetchone returns a 'Confirmed' event),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(status="Confirmed")

    # Act (When)
    response = client.patch(
        f"/events/{EVENT_ID}/safety-status",
        json={
            "status": "Pending Safety Check",
            "safetyCheckId": ROUND_THREE_ID,
            "roundNumber": 3,
            "coordinatorId": COORDINATOR_ID,
        },
        headers=INTERNAL_HEADERS,
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "INVALID_SAFETY_TRANSITION"
    assert response.json["currentStatus"] == "Confirmed"
    # Only the SELECT ran: nothing was written.
    assert cursor.execute.call_count == 1


def test_the_recheck_move_is_the_only_way_out_of_confirmed_in_the_transition_tables():
    """
    Summary: SAFETY_TRANSITIONS lets "Confirmed" go only to "Pending Safety Check", RECHECK_ONLY_MOVES is exactly that one move, and "Cancelled" is not a starting status in SAFETY_TRANSITIONS.
    Supporting design check: 'Confirmed' gains exactly one outgoing safety
        move, and only through /details
    Double: None; the transition tables are read directly, no route or database is used
    """
    # Act (When)
    from app.models import RECHECK_ONLY_MOVES

    # Assert (Then)
    assert SAFETY_TRANSITIONS["Confirmed"] == {"Pending Safety Check"}
    assert RECHECK_ONLY_MOVES == {("Confirmed", "Pending Safety Check")}
    # 'Cancelled' stays terminal (SCRUM-151 AC4).
    assert "Cancelled" not in SAFETY_TRANSITIONS


# --- Statuses other than 'Confirmed' -----------------------------------------


@pytest.mark.parametrize("field", list(HIGH_IMPACT_FIELDS))
def test_a_high_impact_edit_is_blocked_while_the_safety_check_is_pending(field, setup):
    """
    Summary: PATCH /events/<id>/details changing one high-impact field of a 'Pending Safety Check' event answers 409 EVENT_UNDER_SAFETY_REVIEW with currentStatus "Pending Safety Check" and a message saying to wait for the Safety Officer's decision; only the lookup read ran.
    Supporting design check: a high-impact detail does not change under a Safety
        Officer who is mid-review
    Double: Stub (cursor.fetchone returns a 'Pending Safety Check' event),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(status="Pending Safety Check")

    # Act (When)
    response = patch_details(client, {field: HIGH_IMPACT_CHANGES[field]})

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "EVENT_UNDER_SAFETY_REVIEW"
    assert response.json["currentStatus"] == "Pending Safety Check"
    assert "after the Safety Officer's decision" in response.json["message"]
    assert cursor.execute.call_count == 1


def test_a_low_impact_edit_is_allowed_while_the_safety_check_is_pending(setup):
    """
    Summary: PATCH /events/<id>/details renaming a 'Pending Safety Check' event answers 200 with status "Pending Safety Check", and the UPDATE keeps that status.
    Supporting design check: a rename does not affect the review, so it saves as
        usual
    Double: Stub (cursor.fetchone returns the 'Pending Safety Check' event twice: the lookup and the updated row),
        Mock (the UPDATE's status asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        event_row(status="Pending Safety Check"),
        event_row(status="Pending Safety Check"),
    ]

    # Act (When)
    response = patch_details(client, {"eventName": LOW_IMPACT_CHANGES["eventName"]})

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Pending Safety Check"
    assert saved_status(cursor) == "Pending Safety Check"


@pytest.mark.parametrize(
    "status", ["Submitted", "Under Review", "Approved", "Safety Changes Requested"]
)
def test_before_confirmation_a_high_impact_edit_just_saves_without_a_recheck(status, setup):
    """
    Summary: PATCH /events/<id>/details changing the attendance of a 'Submitted', 'Under Review', 'Approved' or 'Safety Changes Requested' event answers 200 with the same status, the UPDATE keeps that status, and the history entry reads "Event details updated: Expected attendance." with no high-impact marker.
    Supporting design check: only a 'Confirmed' event has a safety approval to
        withdraw
    Double: Stub (cursor.fetchone returns the event in the parametrised status twice: the lookup and the updated row),
        Mock (the UPDATE's status and metadata asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [event_row(status=status), event_row(status=status)]

    # Act (When)
    response = patch_details(client, {"expectedAttendance": "400"})

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == status
    assert saved_status(cursor) == status
    entry = saved_metadata(cursor)["actionHistory"][-1]
    assert entry["details"] == "Event details updated: Expected attendance."
    assert "highImpactFields" not in entry


@pytest.mark.parametrize("status", ["Rejected", "Cancelled"])
def test_a_rejected_or_cancelled_event_cannot_be_edited(status, setup):
    """
    Summary: PATCH /events/<id>/details renaming a 'Rejected' or 'Cancelled' event answers 409 EVENT_NOT_EDITABLE with the currentStatus, and only the lookup read ran.
    Supporting design check: a rejected or cancelled event's details are
        history, not a working draft
    Double: Stub (cursor.fetchone returns the event in the parametrised status),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(status=status)

    # Act (When)
    response = patch_details(client, {"eventName": LOW_IMPACT_CHANGES["eventName"]})

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_EDITABLE"
    assert response.json["currentStatus"] == status
    assert cursor.execute.call_count == 1


# --- Access and input ---------------------------------------------------------


def test_a_coordinator_the_event_is_not_assigned_to_is_refused_before_any_status_logic(setup):
    """
    Summary: PATCH /events/<id>/details changing the attendance of an event assigned to a different coordinator answers 403 "not assigned to the current coordinator" with no SAFETY_RECHECK_REQUIRED in the body, and only the lookup read ran.
    Supporting design check: a caller who is not the assigned coordinator
        learns nothing about the event's stage
    Double: Stub (cursor.fetchone returns an event assigned to another coordinator),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=OTHER_COORDINATOR_ID)

    # Act (When)
    response = patch_details(client, {"expectedAttendance": "400"})

    # Assert (Then)
    assert response.status_code == 403
    assert "not assigned to the current coordinator" in response.json["message"]
    assert "SAFETY_RECHECK_REQUIRED" not in response.get_data(as_text=True)
    assert cursor.execute.call_count == 1


def test_an_event_with_no_assigned_coordinator_is_refused(setup):
    """
    Summary: PATCH /events/<id>/details renaming an event that has no coordinator answers 403.
    Supporting design check: an event with no assigned coordinator cannot be
        edited by a coordinator
    Double: Stub (cursor.fetchone returns an event with no coordinator); the 403 status is the only assertion
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(coordinator_id=None)

    # Act (When)
    response = patch_details(client, {"eventName": "Renamed"})

    # Assert (Then)
    assert response.status_code == 403


def test_a_missing_event_is_404(setup):
    """
    Summary: PATCH /events/<id>/details answers 404 "Event request not found." when the database finds no such event.
    Supporting design check: editing an event that does not exist is a 404
    Double: Stub (cursor.fetchone returns None); the 404 status and message are the only assertions
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    # Act (When)
    response = patch_details(client, {"eventName": "Renamed"})

    # Assert (Then)
    assert response.status_code == 404
    assert response.json["message"] == "Event request not found."


@pytest.mark.parametrize("changes", [{}, None, [], "eventName", 7], ids=["empty", "none", "empty_2", "eventname", "7"])
def test_changes_that_are_empty_or_not_an_object_are_refused_before_any_query(changes, setup):
    """
    Summary: PATCH /events/<id>/details with changes {}, null, a list, a string or a number answers 400 "changes must be a non-empty object of fields to update." and no query is sent.
    Supporting design check: the changes field must be a non-empty object
    Double: Mock (cursor.execute asserted never called)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = patch_details(client, changes)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == (
        "changes must be a non-empty object of fields to update."
    )
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("field", ["status", "coordinatorId", "organiserId", "id"])
def test_fields_that_are_not_editable_are_refused_before_any_query(field, setup):
    """
    Summary: PATCH /events/<id>/details trying to change status, coordinatorId, organiserId or id answers 400 naming that field and no query is sent.
    Supporting design check: status and ownership have their own endpoints and
        their own rules
    Double: Mock (cursor.execute asserted never called)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = patch_details(client, {field: "whatever"})

    # Assert (Then)
    assert response.status_code == 400
    assert field in response.json["message"]
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("value", [120, None, {"nested": "object"}, ["a"]], ids=["120", "none", "nested_object", "a"])
def test_a_change_value_that_is_not_text_is_refused_before_any_query(value, setup):
    """
    Summary: PATCH /events/<id>/details with expectedAttendance given as a number, null, an object or a list answers 400 "Every value in changes must be text." and no query is sent.
    Supporting design check: as on submit, the API takes text and converts at
        the boundary
    Double: Mock (cursor.execute asserted never called)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = patch_details(client, {"expectedAttendance": value})

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "Every value in changes must be text."
    cursor.execute.assert_not_called()


def test_a_details_body_that_is_not_a_json_object_is_refused_before_any_query(setup):
    """
    Summary: PATCH /events/<id>/details with a JSON list as the body answers 400 "Send a JSON object." and no query is sent.
    Supporting design check: the request body must be a JSON object
    Double: Mock (cursor.execute asserted never called)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = client.patch(f"/events/{EVENT_ID}/details", json=["not", "an", "object"])

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"expectedAttendance": "0"}, "Expected Attendance"),
        ({"expectedAttendance": "-5"}, "Expected Attendance"),
        ({"expectedAttendance": "not a number"}, "Expected Attendance"),
        ({"preferredEndDate": "2026-11-10T08:00:00"}, "Preferred End Date & Time"),
        ({"preferredStartDate": "not a date"}, "Preferred dates"),
    ],
    ids=["expectedattendance_0_expected_attendance", "expectedattendance_5_expected_attendance", "expectedattendance_not_a_number_expected_attenda", "preferredenddate_2026_11_10t08_00_00_preferred_e", "preferredstartdate_not_a_date_preferred_dates"],
)
def test_the_merged_event_values_are_validated_before_the_gate(changes, expected, setup):
    """
    Summary: PATCH /events/<id>/details on a 'Confirmed' event with attendance 0, -5 or "not a number", an end before the start, or an unparseable start answers 400 "Please correct the event details." with an error naming the field, and only the lookup read ran.
    Supporting design check: an edit is held to the same rules as a submission,
        on the merged event, before the safety gate
    Double: Stub (cursor.fetchone returns the 'Confirmed' event),
        Mock (cursor.execute call count asserted to be 1, the lookup read)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()

    # Act (When)
    response = patch_details(client, changes, headers=INTERNAL_HEADERS)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "Please correct the event details."
    assert any(expected in error for error in response.json["errors"])
    # Validation runs before the gate, so nothing is written.
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("field", ["eventName", "description", "purpose"])
def test_a_required_field_cannot_be_blanked_in_an_edit(field, setup):
    """
    Summary: PATCH /events/<id>/details setting eventName, description or purpose to whitespace answers 400 with a non-empty missingFields list.
    Supporting design check: required details must stay filled in
    Double: Stub (cursor.fetchone returns the 'Confirmed' event); the 400 status and missingFields are the only assertions
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row()

    # Act (When)
    response = patch_details(client, {field: "   "})

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["missingFields"]


def test_setting_a_date_an_event_never_had_counts_as_a_high_impact_change(setup):
    """
    Summary: PATCH /events/<id>/details setting preferredStartDate on a 'Confirmed' event stored with no start answers 409 SAFETY_RECHECK_REQUIRED with highImpactFields ["preferredStartDate"].
    Supporting design check: filling in a date an event never had is a
        high-impact change
    Double: Stub (cursor.fetchone returns a 'Confirmed' event with no start date); the 409 status, code and highImpactFields are the only assertions
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = event_row(start=None)

    # Act (When)
    response = patch_details(client, {"preferredStartDate": "2026-11-10T09:00:00"})

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_RECHECK_REQUIRED"
    assert response.json["highImpactFields"] == ["preferredStartDate"]


@pytest.mark.parametrize(
    ("field", "column", "recheck"),
    [
        ("registrationNeeds", "registration_needs", False),
        ("accessibilityNeeds", "accessibility_needs", True),
    ],
)
def test_an_optional_field_can_be_cleared_with_a_recheck_only_when_it_is_high_impact(field, column, recheck, setup):
    """
    Summary: PATCH /events/<id>/details setting registrationNeeds (low impact) or accessibilityNeeds (high impact, sent with the internal token and a recheck block) to an empty string answers 200 and returns the cleared field.
    Supporting design check: only the required details have to stay filled in
    Double: Stub (cursor.fetchone returns the 'Confirmed' event, then a row with the column cleared); the 200 status and the cleared field are the only assertions
    """
    # Arrange (Given)
    client, _, cursor = setup
    cleared = event_row()
    cleared[column] = ""
    cursor.fetchone.side_effect = [event_row(), cleared]

    # Act (When)
    response = patch_details(
        client,
        {field: ""},
        headers=INTERNAL_HEADERS,
        **({"safetyRecheck": RECHECK} if recheck else {}),
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json[field] == ""


@pytest.mark.parametrize(
    "recheck",
    [
        "not-an-object",
        {"safetyCheckId": ROUND_THREE_ID, "roundNumber": 3},
        {"withdrawnSafetyCheckId": "nope", "safetyCheckId": ROUND_THREE_ID, "roundNumber": 3},
        {"withdrawnSafetyCheckId": ROUND_TWO_ID, "safetyCheckId": "nope", "roundNumber": 3},
        {**RECHECK, "roundNumber": 0},
        {**RECHECK, "roundNumber": "3"},
        {**RECHECK, "roundNumber": True},
        {k: v for k, v in RECHECK.items() if k != "roundNumber"},
    ],
    ids=["not_an_object", "safetycheckid_round_three_id_roundnumber_3", "withdrawnsafetycheckid_nope_safetycheckid_round", "withdrawnsafetycheckid_round_two_id_safetychecki", "recheck_roundnumber_0", "recheck_roundnumber_3", "recheck_roundnumber_true", "k_v_for_k_v_in_recheck_items_if_k_roundnumber"],
)
def test_a_malformed_recheck_block_is_refused_before_any_query(recheck, setup):
    """
    Summary: PATCH /events/<id>/details with a safetyRecheck that is not an object, lacks the withdrawn round, has a non-UUID round id, or has a round number that is 0, a string, true or missing answers 400 with a message naming safetyRecheck and no query is sent.
    Supporting design check: a malformed recheck block is refused before the
        database is read
    Double: Mock (cursor.execute asserted never called)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = patch_details(
        client,
        {"expectedAttendance": "400"},
        headers=INTERNAL_HEADERS,
        safetyRecheck=recheck,
    )

    # Assert (Then)
    assert response.status_code == 400
    assert "safetyRecheck" in response.json["message"]
    cursor.execute.assert_not_called()


def test_every_editable_field_is_classified_as_low_or_high_impact_exactly_once():
    """
    Summary: LOW_IMPACT_FIELDS and HIGH_IMPACT_FIELDS together equal EDITABLE_FIELDS and do not overlap, and every editable field except purpose is a column of the Event table other than withdrawalDeadline.
    Supporting design check: no editable field is both low and high impact, or
        neither
    Double: None; the field sets are read directly, no route or database is used
    """
    # Act + Assert (When / Then)
    assert set(LOW_IMPACT_FIELDS) | set(HIGH_IMPACT_FIELDS) == set(EDITABLE_FIELDS)
    assert not set(LOW_IMPACT_FIELDS) & set(HIGH_IMPACT_FIELDS)
    # Every editable field is a column this service owns, or lives in the
    # `description` JSON (`purpose`).
    # withdrawalDeadline is set by the organiser during event creation and is
    # deliberately not part of coordinator edits or safety re-checks.
    assert set(EDITABLE_FIELDS) - {"purpose"} == set(FIELDS) - {
        "withdrawalDeadline"
    }


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_event_details_edit_answers_503_when_no_database_is_configured(no_database):
    """
    Summary: With no DATABASE_URL set, PATCH /events/<id>/details answers 503 with a message naming DATABASE_URL.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None for the database, since the app has none configured; only the Supabase JWKS Stub, which verifies the signed token
    """
    response = patch_details(no_database, {"eventName": "Renamed"})

    assert response.status_code == 503
    assert "DATABASE_URL" in response.json["message"]


def test_a_database_failure_during_an_edit_answers_503_without_leaking_internals(setup):
    """
    Summary: With cursor.execute raising psycopg2.OperationalError("connection refused"), PATCH /events/<id>/details answers 503 and the message does not contain "connection refused".
    Supporting design check: a database failure answers 503 without internals
    Double: Stub (cursor.execute raises psycopg2.OperationalError)
    """
    client, _, cursor = setup
    cursor.execute.side_effect = __import__("psycopg2").OperationalError(
        "connection refused"
    )

    response = patch_details(client, {"eventName": "Renamed"})

    assert response.status_code == 503
    assert "connection refused" not in response.json["message"]


def test_attendee_request_selects_description_excludes_drafts_and_passes_ids(attendee_setup):
    """
    Summary: A request for two ids runs one query that selects the description column (where the history lives), excludes drafts, and passes the ids as one list parameter; events come back in the order the database returned them.
    Supporting design check: the attendee read has to see the action history
        and must never expose drafts
    Double: Stub (cursor.fetchall returns two 'Confirmed' rows, other id first), Mock (the one cursor.execute call's SQL and parameters asserted)
    """
    # Arrange (Given)
    client, cursor, _ = attendee_setup
    cursor.fetchall.return_value = [
        attendee_summary_row("Confirmed", [], event_id=OTHER),
        attendee_summary_row("Confirmed", []),
    ]

    # Act (When)
    events = attendee_summary(client, EVENT, OTHER)

    # Assert (Then)
    sql, params = cursor.execute.call_args[0]
    assert "description" in sql and NOT_DRAFT in sql
    assert params == [[EVENT, OTHER]]
    assert [event["id"] for event in events] == [OTHER, EVENT]


@pytest.mark.parametrize("query", ["", "?ids=", "?ids=nope", f"?ids={EVENT},nope", "?ids=" + ",".join([EVENT] * 101)],
                         ids=["no_ids_param", "blank_ids", "not_a_uuid", "one_bad_in_list", "101_ids"])
def test_attendee_missing_or_invalid_ids_are_rejected_before_any_query(attendee_setup, query):
    """
    Summary: No ids, a non-UUID, a mixed list or more than 100 ids are all a 400, and the database is never connected to.
    Supporting design check: the id list is validated before any database work
    Double: Mock (the psycopg2.connect patch is asserted never called)
    """
    # Arrange (Given)
    client, _, connect = attendee_setup

    # Act + Assert (When / Then)
    assert client.get(f"/events/attendee-summaries{query}").status_code == 400
    connect.assert_not_called()


def test_attendee_summaries_answer_503_when_no_database_is_configured():
    """
    Summary: Without DATABASE_URL the service reports itself unavailable.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None (the app is created with no DATABASE_URL, so no connection is attempted)
    """
    client = signed_in(create_app({"DATABASE_URL": None}).test_client())
    assert client.get(f"/events/attendee-summaries?ids={EVENT}").status_code == 503
