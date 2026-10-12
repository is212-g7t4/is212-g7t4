"""SCRUM-149: the SafetyCheck round records behind "submit for safety check".

AC1 ... then its status changes to 'Pending Safety Check' and the submission
    time is recorded — `submitted_at` on round N is that time.
AC3 ... when they enter equipment placement and expected crowd movement notes,
    then the notes are saved with the safety check.
AC4 Given the event is already 'Pending Safety Check', when the Event
    Coordinator submits it again, then no duplicate safety check is created —
    enforced here, since this service owns the records.

Database calls are mocked; no live database writes.
"""
import psycopg2
import pytest
from unittest.mock import MagicMock

from app import create_app
from app.models import RECORD_STATUSES
from tests.unit.factories import COORDINATOR_ID, EVENT_ID, RECORD_ID, record_row


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return app.test_client(), connection, cursor


@pytest.fixture
def no_database():
    app = create_app({"TESTING": True, "DATABASE_URL": None})
    return app.test_client()


def post(client, **overrides):
    body = {"eventId": EVENT_ID, "submittedBy": COORDINATOR_ID, **overrides}
    return client.post("/safety-check-records", json=body)


# --- AC1/AC3: opening a round ------------------------------------------------


def test_first_submission_opens_round_one(setup):
    """AC1: the first submission creates round 1, Pending, with its submitted time."""
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


def test_notes_are_saved_with_the_round(setup):
    """AC3: both note fields reach the INSERT and come back on the record."""
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
)
def test_blank_notes_are_stored_as_null(notes, setup):
    """AC3: the notes are optional, and blank is NULL rather than an empty string."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [None, record_row()]

    response = post(client, **notes)

    assert response.status_code == 201
    assert response.json["equipmentPlacementNotes"] is None
    assert cursor.execute.call_args_list[1].args[1][3:5] == [None, None]


def test_notes_at_the_limit_are_accepted(setup):
    """AC3 boundary: 2000 characters is the limit, not one under it."""
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
)
def test_notes_over_the_limit_are_rejected(field, label, setup):
    """AC3 boundary: 2001 characters is refused, and nothing is written."""
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
)
def test_non_text_notes_are_rejected(field, label, setup):
    """Never trust the caller, even a composite: notes must be text."""
    client, _, cursor = setup

    response = post(client, **{field: {"nested": "object"}})

    assert response.status_code == 400
    assert response.json["message"] == f"{label} must be text."
    cursor.execute.assert_not_called()


def test_round_after_a_decided_round_is_the_next_number(setup):
    """SCRUM-164's resubmission: round N+1 once round N has been decided."""
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


def test_open_round_blocks_a_second_submission(setup):
    """AC4: a round still awaiting a decision means no new round is created."""
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(round_number=1, status="Pending")

    response = post(client)

    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_PENDING"
    assert response.json["safetyCheck"]["roundNumber"] == 1
    assert response.json["safetyCheck"]["submittedAt"] == "2026-11-01T02:30:00+00:00"
    # Only the SELECT ran: nothing was inserted.
    assert cursor.execute.call_count == 1


def test_unique_violation_is_reported_as_the_existing_round(setup):
    """AC4's race: two first submissions, one INSERT loses on the unique key.

    There is no previous round to lock on a first submission, so
    `UNIQUE (event_id, round_number)` is what actually prevents the duplicate.
    The loser re-reads the winner's round and answers with the same 409.
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


def test_round_is_chosen_under_a_row_lock(setup):
    """AC4: the round number and the open-round check are decided under FOR UPDATE."""
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
        {"eventId": "not-a-uuid", "submittedBy": COORDINATOR_ID},
        {"eventId": EVENT_ID, "submittedBy": "nope"},
        {"eventId": EVENT_ID},
        {"submittedBy": COORDINATOR_ID},
        {},
    ],
)
def test_bad_identifiers_are_rejected(body, setup):
    client, _, cursor = setup

    response = client.post("/safety-check-records", json=body)

    assert response.status_code == 400
    assert response.json["message"] == "eventId and submittedBy must be valid UUIDs."
    cursor.execute.assert_not_called()


def test_non_object_body_is_rejected(setup):
    client, _, cursor = setup

    response = client.post("/safety-check-records", json=["not", "an", "object"])

    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    cursor.execute.assert_not_called()


def test_create_without_database_url(no_database):
    response = no_database.post(
        "/safety-check-records",
        json={"eventId": EVENT_ID, "submittedBy": COORDINATOR_ID},
    )

    assert response.status_code == 503
    assert "DATABASE_URL" in response.json["message"]


def test_database_failure_is_503(setup):
    """A connection or schema problem is an outage, not a bad request."""
    client, _, cursor = setup
    cursor.execute.side_effect = psycopg2.OperationalError("connection refused")

    response = post(client)

    assert response.status_code == 503
    assert "Safety Check Record Service" in response.json["message"]
    # The response must not leak credentials, SQL or database internals.
    assert "connection refused" not in response.json["message"]


# --- Listing rounds (AC4's response, and SCRUM-163's history) ----------------


def test_rounds_are_listed_newest_first(setup):
    client, _, cursor = setup
    cursor.fetchall.return_value = [
        record_row(round_number=2, status="Pending"),
        record_row(round_number=1, status="Changes Requested", decided=True),
    ]

    response = client.get(f"/safety-check-records?eventId={EVENT_ID}")

    assert response.status_code == 200
    assert [r["roundNumber"] for r in response.json["safetyChecks"]] == [2, 1]
    assert response.json["safetyChecks"][1]["decidedAt"] == "2026-11-02T03:00:00+00:00"
    assert response.json["safetyChecks"][1]["remarks"] == "Looks safe."
    assert "ORDER BY round_number DESC" in cursor.execute.call_args.args[0]


def test_rounds_can_be_filtered_by_status(setup):
    """AC4 uses this to fetch the open round to report back."""
    client, _, cursor = setup
    cursor.fetchall.return_value = [record_row(status="Pending")]

    response = client.get(
        f"/safety-check-records?eventId={EVENT_ID}&status=Pending"
    )

    assert response.status_code == 200
    sql, params = cursor.execute.call_args.args
    assert "AND status = %s" in sql
    assert params == [EVENT_ID, "Pending"]


@pytest.mark.parametrize("status", list(RECORD_STATUSES))
def test_every_record_status_is_a_valid_filter(status, setup):
    """The full status set, so SCRUM-150/151 need no change here."""
    client, _, cursor = setup
    cursor.fetchall.return_value = []

    response = client.get(f"/safety-check-records?eventId={EVENT_ID}&status={status}")

    assert response.status_code == 200


@pytest.mark.parametrize("status", ["Approved", "pending", "Safety approved"])
def test_unknown_status_filter_is_rejected(status, setup):
    """'Approved' is an *event* status, never a safety check's."""
    client, _, cursor = setup

    response = client.get(f"/safety-check-records?eventId={EVENT_ID}&status={status}")

    assert response.status_code == 400
    assert response.json["message"].startswith("status must be one of: ")
    cursor.execute.assert_not_called()


def test_list_requires_a_valid_event_id(setup):
    client, _, cursor = setup

    response = client.get("/safety-check-records?eventId=nope")

    assert response.status_code == 400
    assert response.json["message"] == "eventId must be a valid UUID."
    cursor.execute.assert_not_called()


def test_list_without_database_url(no_database):
    response = no_database.get(f"/safety-check-records?eventId={EVENT_ID}")

    assert response.status_code == 503


# --- Compensating delete -----------------------------------------------------


def test_open_round_can_be_deleted(setup):
    """Compensation: the composite removes the round it opened when the event
    status update then fails, so the event is not left with an orphan round."""
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
)
def test_decided_round_cannot_be_deleted(status, decided, setup):
    """A decided round is history (SCRUM-163 reads it), so rollback can't take it."""
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(status=status, decided=decided)

    response = client.delete(f"/safety-check-records/{RECORD_ID}")

    assert response.status_code == 409
    assert response.json["message"] == (
        "A safety check that has been decided can't be removed."
    )
    assert cursor.execute.call_count == 1


def test_deleting_a_missing_round_is_404(setup):
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = client.delete(f"/safety-check-records/{RECORD_ID}")

    assert response.status_code == 404
    assert response.json["message"] == "Safety check not found."


def test_delete_requires_a_valid_id(setup):
    client, _, cursor = setup

    response = client.delete("/safety-check-records/not-a-uuid")

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_delete_without_database_url(no_database):
    response = no_database.delete(f"/safety-check-records/{RECORD_ID}")

    assert response.status_code == 503


# --- CORS --------------------------------------------------------------------


def test_cors_allows_the_frontend_origin(setup):
    client, _, _ = setup

    response = client.get("/health", headers={"Origin": "http://localhost:5174"})

    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"
    assert "DELETE" in response.headers["Access-Control-Allow-Methods"]


def test_cors_rejects_another_origin(setup):
    client, _, _ = setup

    response = client.get("/health", headers={"Origin": "http://evil.example"})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_cors_with_no_configured_origin_allows_nothing():
    """A blank FRONTEND_ORIGIN must not become a wildcard."""
    client = create_app({"TESTING": True, "FRONTEND_ORIGIN": ""}).test_client()

    response = client.get("/health", headers={"Origin": "http://localhost:5174"})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_returns_200(setup):
    client, _, _ = setup

    response = client.options(
        "/safety-check-records", headers={"Origin": "http://localhost:5174"}
    )

    assert response.status_code == 200
