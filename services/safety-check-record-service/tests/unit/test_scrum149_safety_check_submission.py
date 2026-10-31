"""
SCRUM-149: Submit Event for Operational Safety Check

User Story
----------
As an Event Coordinator, I want to submit my event for an Operational Safety
Check once its venue and technical arrangements are confirmed, so that the
Safety Officer can review it before preparation begins.

Acceptance Criteria
-------------------
AC1: Given an event assigned to the Event Coordinator has at least one approved
     venue booking, and none of its venue bookings or equipment requests is
     still pending, when the Event Coordinator submits it for a safety check,
     then its status changes to 'Pending Safety Check' and the submission time
     is recorded. Rejected, cancelled or expired venue bookings and rejected
     equipment requests are no longer part of the event's arrangements and do
     not block submission.
AC2: Given any venue booking or equipment request for the event is still
     pending, or the event has no approved venue booking, when the Event
     Coordinator tries to submit, then submission is blocked and the
     outstanding arrangements are listed.
AC3: Given the Event Coordinator is submitting, when they enter equipment
     placement and expected crowd movement notes, then the notes are saved with
     the safety check.
AC4: Given the event is already 'Pending Safety Check', when the Event
     Coordinator submits it again, then no duplicate safety check is created.
AC5: Given the Event Coordinator is not the assigned coordinator, then the
     submit action is not available and an API call is rejected.

Real
----
- Recording a safety submission: a new round numbered after the last, with the
  coordinator, the time and the optional notes; only one pending round per
  event; finding an event's rounds by status; and removing a round again if the
  rest of the submission fails.
- We check the round returned and what is saved.

Doubled
-------
- Safety records (database): hold the rounds each test needs, accept new ones,
  or cannot be reached [Stub]; we check what is saved, and that rounds are
  locked before they change [Mock].
- Sign-in: a test key signs the caller's token (tests/unit/conftest.py) [Stub].

Not proven
----------
- That Safety Check Service only submits ready events and moves the event to
  'Pending Safety Check' (-> safety-check-service SCRUM-149 tests).
- That the saving and locking really work in Postgres, including two people
  acting at the same moment (-> tests/integration/, against a throwaway
  postgres:17.6).
"""
import psycopg2
import pytest
from unittest.mock import MagicMock

from app import create_app
from app.models import RECORD_STATUSES
from tests.unit.factories import COORDINATOR_ID, EVENT_ID, RECORD_ID, record_row, signed_in


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client(), COORDINATOR_ID), connection, cursor


@pytest.fixture
def no_database():
    app = create_app({"TESTING": True, "DATABASE_URL": None})
    return signed_in(app.test_client(), COORDINATOR_ID)


def post(client, **overrides):
    body = {"eventId": EVENT_ID, **overrides}
    return client.post("/safety-check-records", json=body)


# --- AC1/AC3: opening a round ------------------------------------------------


def test_open_round_for_first_submission_creates_round_one(setup):
    """
    Summary: An event's first safety submission opens round 1 as Pending.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: The event has no earlier round, and the safety records accept the
        new one [Stub]; we check the round saved [Mock].
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [None, record_row(round_number=1)]

    response = post(client)

    assert response.status_code == 201
    assert response.json["roundNumber"] == 1
    assert response.json["status"] == "Pending"
    assert response.json["submittedAt"] == "2026-11-01T02:30:00+00:00"
    assert response.json["submittedBy"] == COORDINATOR_ID
    assert response.json["eventId"] == EVENT_ID
    insert_sql, insert_params = cursor.execute.call_args_list[1].args
    assert 'INSERT INTO public."SafetyCheck"' in insert_sql
    assert insert_params[1] == 1
    assert insert_params[-1] == "Pending"


def test_open_round_with_notes_saves_them_with_the_round(setup):
    """
    Summary: Equipment placement and crowd movement notes are saved with the round.
    AC3: Given the Event Coordinator is submitting, when they enter equipment
        placement and expected crowd movement notes, then the notes are saved
        with the safety check.
    Double: The safety records accept the new round [Stub]; we check what is
        saved with it [Mock].
    """
    client, _, cursor = setup
    placement = "Speakers either side of the stage, cables taped along the left wall."
    crowd = "Entry through Door A, exit through Doors B and C."
    cursor.fetchone.side_effect = [
        None,
        record_row(equipment_placement_notes=placement, crowd_movement_notes=crowd),
    ]

    response = post(
        client, equipmentPlacementNotes=placement, crowdMovementNotes=crowd
    )

    assert response.status_code == 201
    assert response.json["equipmentPlacementNotes"] == placement
    assert response.json["crowdMovementNotes"] == crowd
    assert cursor.execute.call_args_list[1].args[1][3:5] == [placement, crowd]


@pytest.mark.parametrize(
    "notes",
    [
        {},
        {"equipmentPlacementNotes": "", "crowdMovementNotes": ""},
        {"equipmentPlacementNotes": "   ", "crowdMovementNotes": "\n\t"},
        {"equipmentPlacementNotes": None, "crowdMovementNotes": None},
    ],
    ids=["omitted", "empty", "whitespace", "null"],
)
def test_open_round_with_blank_notes_stores_null(notes, setup):
    """
    Summary: Notes left blank are stored as nothing rather than empty text.
    AC3: Given the Event Coordinator is submitting, when they enter equipment
        placement and expected crowd movement notes, then the notes are saved
        with the safety check.
    Double: The safety records accept the new round [Stub]; we check what is
        saved with it [Mock].
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [None, record_row()]

    response = post(client, **notes)

    assert response.status_code == 201
    assert response.json["equipmentPlacementNotes"] is None
    assert cursor.execute.call_args_list[1].args[1][3:5] == [None, None]


def test_open_round_with_notes_at_limit_is_accepted(setup):
    """
    Summary: Notes up to the length limit are accepted.
    AC3: Given the Event Coordinator is submitting, when they enter equipment
        placement and expected crowd movement notes, then the notes are saved
        with the safety check.
    Double: The safety records accept the new round [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [None, record_row()]

    response = post(client, equipmentPlacementNotes="x" * 2000)

    assert response.status_code == 201


@pytest.mark.parametrize(
    ("field", "label"),
    [
        ("equipmentPlacementNotes", "Equipment placement notes"),
        ("crowdMovementNotes", "Expected crowd movement notes"),
    ],
    ids=["equipment_placement", "crowd_movement"],
)
def test_open_round_with_notes_over_limit_returns_400_naming_field(field, label, setup):
    """
    Summary: Notes over the limit are refused, naming the field.
    AC3: Given the Event Coordinator is submitting, when they enter equipment
        placement and expected crowd movement notes, then the notes are saved
        with the safety check.
    Double: We check the safety records are never touched [Mock].
    """
    client, _, cursor = setup

    response = post(client, **{field: "x" * 2001})

    assert response.status_code == 400
    assert response.json["message"] == f"{label} must be 2000 characters or fewer."
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    ("field", "label"),
    [
        ("equipmentPlacementNotes", "Equipment placement notes"),
        ("crowdMovementNotes", "Expected crowd movement notes"),
    ],
    ids=["equipment_placement", "crowd_movement"],
)
def test_open_round_with_non_text_notes_returns_400_naming_field(field, label, setup):
    """
    Summary: Notes must be text.
    AC3: Given the Event Coordinator is submitting, when they enter equipment
        placement and expected crowd movement notes, then the notes are saved
        with the safety check.
    Double: We check the safety records are never touched [Mock].
    """
    client, _, cursor = setup

    response = post(client, **{field: {"nested": "object"}})

    assert response.status_code == 400
    assert response.json["message"] == f"{label} must be text."
    cursor.execute.assert_not_called()


def test_open_round_after_decided_round_uses_next_number(setup):
    """
    Summary: A resubmission after a decision opens the next round number.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: The event's latest round is decided, and the safety records accept
        the new one [Stub]; we check its number [Mock].
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=2, status="Changes Requested", decided=True),
        record_row(round_number=3),
    ]

    response = post(client)

    assert response.status_code == 201
    assert response.json["roundNumber"] == 3
    assert cursor.execute.call_args_list[1].args[1][1] == 3


# --- AC4: no duplicate safety check -----------------------------------------


def test_open_round_while_one_pending_returns_409(setup):
    """
    Summary: A second submission while a round is still pending creates no duplicate.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: The event already has a pending round [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(round_number=1, status="Pending")

    response = post(client)

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_PENDING"
    assert response.json["safetyCheck"]["roundNumber"] == 1
    assert response.json["safetyCheck"]["submittedAt"] == "2026-11-01T02:30:00+00:00"
    # Only the SELECT ran: nothing was inserted.
    assert cursor.execute.call_count == 1


def test_open_round_when_database_reports_duplicate_returns_409(setup):
    """
    Summary: If the database's uniqueness rule fires, it is reported as the existing round.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: Another submission saved the same round first [Stub].
    """
    client, connection, cursor = setup
    cursor.execute.side_effect = [None, psycopg2.errors.UniqueViolation, None]
    cursor.fetchone.side_effect = [None, record_row(round_number=1)]

    response = post(client)

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_PENDING"
    assert response.json["safetyCheck"]["roundNumber"] == 1
    # The aborted transaction has to be rolled back before the re-read.
    connection.rollback.assert_called_once()


def test_open_round_locks_event_rounds_before_choosing_number(setup):
    """
    Summary: Two submissions made at the same moment cannot both open a round: the round number is chosen while the event's rounds are locked.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: The safety records hold the round [Stub]; we check it is locked
        before it changes, so two people cannot change it at once [Mock].
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [None, record_row()]

    post(client)

    select_sql = cursor.execute.call_args_list[0].args[0]

    assert "FOR UPDATE" in select_sql
    assert "ORDER BY round_number DESC" in select_sql


# --- Input and configuration -------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"eventId": "not-a-uuid"},
        {},
    ],
    ids=["bad_event_id", "missing_event_id"],
)
def test_open_round_with_bad_event_id_returns_400(body, setup):
    """
    Summary: A round must name a valid event.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: None
    """
    client, _, cursor = setup

    response = client.post("/safety-check-records", json=body)

    assert response.status_code == 400
    assert response.json["message"] == "eventId must be a valid UUID."
    cursor.execute.assert_not_called()


def test_open_round_with_non_object_body_returns_400(setup):
    """
    Summary: A submission that is not in the expected form is refused.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: None
    """
    client, _, cursor = setup

    response = client.post("/safety-check-records", json=["not", "an", "object"])

    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    cursor.execute.assert_not_called()


# --- Listing rounds (AC4's response, and SCRUM-163's history) ----------------


def test_list_rounds_with_status_filter_queries_only_that_status(setup):
    """
    Summary: Rounds can be filtered by status.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: We check how the safety records are searched [Mock].
    """
    client, _, cursor = setup
    cursor.fetchall.side_effect = [[record_row(status="Pending")], []]

    response = client.get(
        f"/safety-check-records?eventId={EVENT_ID}&status=Pending"
    )

    assert response.status_code == 200
    sql, params = cursor.execute.call_args_list[0].args
    assert "AND status = %s" in sql
    assert params == [EVENT_ID, "Pending"]


@pytest.mark.parametrize("status", list(RECORD_STATUSES))
def test_list_rounds_accepts_every_record_status_as_filter(status, setup):
    """
    Summary: Every round status can be used as a filter.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: The safety records hold no such round [Stub].
    """
    client, _, cursor = setup
    cursor.fetchall.return_value = []

    response = client.get(f"/safety-check-records?eventId={EVENT_ID}&status={status}")

    assert response.status_code == 200


@pytest.mark.parametrize("status", ["Approved", "pending", "Safety approved"], ids=["approved", "lowercase_pending", "wrong_case_approved"])
def test_list_rounds_with_unknown_status_returns_400(status, setup):
    """
    Summary: A status that rounds never have is refused.
    AC4: Given the event is already 'Pending Safety Check', when the Event
        Coordinator submits it again, then no duplicate safety check is
        created.
    Double: None
    """
    client, _, cursor = setup

    response = client.get(f"/safety-check-records?eventId={EVENT_ID}&status={status}")

    assert response.status_code == 400
    assert response.json["message"].startswith("status must be one of: ")
    cursor.execute.assert_not_called()


# --- Compensating delete -----------------------------------------------------


def test_delete_open_round_removes_it(setup):
    """
    Summary: An open round can be undone when the submission fails later.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: The round is pending [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(status="Pending")

    response = client.delete(f"/safety-check-records/{RECORD_ID}")

    assert response.status_code == 204
    assert "FOR UPDATE" in cursor.execute.call_args_list[0].args[0]
    assert 'DELETE FROM public."SafetyCheck"' in cursor.execute.call_args_list[1].args[0]


@pytest.mark.parametrize(
    ("status", "decided"),
    [
        ("Safety Approved", True),
        ("Changes Requested", True),
        ("Safety Rejected", True),
        ("Pending", True),
    ],
    ids=["safety_approved", "changes_requested", "safety_rejected", "pending_with_decision"],
)
def test_delete_decided_round_returns_409(status, decided, setup):
    """
    Summary: A decided round can never be undone.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: The round has already been decided [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(status=status, decided=decided)

    response = client.delete(f"/safety-check-records/{RECORD_ID}")

    assert response.status_code == 409
    assert response.json["message"] == (
        "A safety check that has been decided can't be removed."
    )
    assert cursor.execute.call_count == 1


def test_delete_missing_round_returns_404(setup):
    """
    Summary: Undoing a round that does not exist is refused.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: The safety records hold no such round [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = client.delete(f"/safety-check-records/{RECORD_ID}")

    assert response.status_code == 404
    assert response.json["message"] == "Safety check not found."


def test_delete_round_with_bad_id_returns_404(setup):
    """
    Summary: Undoing needs a valid round id.
    AC1: Given an event assigned to the Event Coordinator has at least one
        approved venue booking, and none of its venue bookings or equipment
        requests is still pending, when the Event Coordinator submits it for a
        safety check, then its status changes to 'Pending Safety Check' and the
        submission time is recorded. Rejected, cancelled or expired venue
        bookings and rejected equipment requests are no longer part of the
        event's arrangements and do not block submission.
    Double: None
    """
    client, _, cursor = setup

    response = client.delete("/safety-check-records/not-a-uuid")

    assert response.status_code == 400
    cursor.execute.assert_not_called()


# --- CORS --------------------------------------------------------------------


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_open_round_when_database_url_missing_returns_503(no_database):
    """
    Summary: Opening a round reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured service answers 503
    Double: None
    """
    response = no_database.post(
        "/safety-check-records",
        json={"eventId": EVENT_ID},
    )

    assert response.status_code == 503
    assert "DATABASE_URL" in response.json["message"]


def test_open_round_when_database_fails_returns_503(setup):
    """
    Summary: If the safety records cannot be reached, the submission reports the service as unavailable.
    Supporting design check: database errors answer 503 with a safe message
    Double: The safety records cannot be reached [Stub].
    """
    client, _, cursor = setup
    cursor.execute.side_effect = psycopg2.OperationalError("connection refused")

    response = post(client)

    assert response.status_code == 503
    assert "Safety Check Record Service" in response.json["message"]
    # The response must not leak credentials, SQL or database internals.
    assert "connection refused" not in response.json["message"]


def test_delete_round_when_database_url_missing_returns_503(no_database):
    """
    Summary: Undoing reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured service answers 503
    Double: None
    """
    response = no_database.delete(f"/safety-check-records/{RECORD_ID}")

    assert response.status_code == 503


def test_preflight_from_frontend_origin_is_allowed(setup):
    """
    Summary: The frontend may call this service from a browser.
    Supporting design check: CORS for the configured frontend origin
    Double: None
    """
    client, _, _ = setup

    response = client.get("/health", headers={"Origin": "http://localhost:5174"})

    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert "DELETE" in response.headers["Access-Control-Allow-Methods"]


def test_preflight_from_other_origin_gets_no_grant(setup):
    """
    Summary: Other websites get no browser access.
    Supporting design check: CORS for the configured frontend origin
    Double: None
    """
    client, _, _ = setup

    response = client.get("/health", headers={"Origin": "http://evil.example"})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_with_blank_frontend_origin_allows_nothing():
    """
    Summary: Blanking the frontend origin turns browser access off.
    Supporting design check: CORS for the configured frontend origin
    Double: None
    """
    client = signed_in(create_app({"TESTING": True, "FRONTEND_ORIGIN": ""}).test_client(), COORDINATOR_ID)

    response = client.get("/health", headers={"Origin": "http://localhost:5174"})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_returns_200(setup):
    """
    Summary: The browser's preflight check is answered.
    Supporting design check: CORS for the configured frontend origin
    Double: None
    """
    client, _, _ = setup

    response = client.options(
        "/safety-check-records", headers={"Origin": "http://localhost:5174"}
    )

    assert response.status_code == 200
