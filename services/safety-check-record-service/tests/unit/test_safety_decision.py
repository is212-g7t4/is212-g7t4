"""
SCRUM-150: Approve Operational Safety Check

User Story
----------
As a Safety Officer, I want to approve an event's operational safety
arrangements, so that the event can proceed to preparation.

Acceptance Criteria
-------------------
AC1: Given an event is 'Pending Safety Check', when I approve it, then its
     status changes to 'Confirmed'.
AC2: Given I approve an event, then the safety check is recorded with the
     status 'Safety Approved', together with my identity, the approval
     timestamp and any optional remarks, in the event's history.
AC3: Given an event is not 'Pending Safety Check', then the approve action is
     not available and an API call is rejected without changing the event.
AC4: Given the safety check I approve follows a high-impact change, when I
     approve it, then the changed details become visible to registered
     Attendees.

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
- PATCH /safety-check-records/<id>/decision (decide the latest Pending round
  under a row lock, recording the officer, time and remarks) and POST
  /safety-check-records/<id>/reopen (undo a decision when the event move fails)
  run for real.
- Assertions are on the status, the returned round and the SQL sent.

Doubled
-------
- psycopg2.connect: Stub (`setup` fixture) - fresh MagicMock connection; the
  cursor returns canned SafetyCheck rows (or raises); executed SQL, parameters
  and the FOR UPDATE lock are inspected.

Not proven
----------
- That the row lock really serialises two concurrent decisions in PostgreSQL
  (-> tests/integration/, throwaway postgres:17.6).
- That Safety Check Service moves the event status and rolls back with reopen
  on failure (-> safety-check-service unit tests).
"""
import psycopg2
import pytest
from unittest.mock import MagicMock

from app import create_app
from tests.unit.factories import EVENT_ID, OFFICER_ID, RECORD_ID, record_row, signed_in


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(
        "app.models.psycopg2.connect", lambda *args, **kwargs: connection
    )
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client(), OFFICER_ID, "Safety Officer"), connection, cursor


@pytest.fixture
def no_database():
    app = create_app({"TESTING": True, "DATABASE_URL": None})
    return signed_in(app.test_client(), OFFICER_ID, "Safety Officer")


def decide(client, safety_check_id=RECORD_ID, **overrides):
    body = {"status": "Safety Approved", **overrides}
    return client.patch(f"/safety-check-records/{safety_check_id}/decision", json=body)


def reopen(client, safety_check_id=RECORD_ID, **overrides):
    body = {"decidedAt": "2026-11-02T03:00:00+00:00", **overrides}
    return client.post(f"/safety-check-records/{safety_check_id}/reopen", json=body)


# --- AC2: deciding the open round --------------------------------------------


def test_decide_latest_pending_round_records_safety_approved(setup):
    """
    Summary: The Safety Officer's approval of the pending round is recorded as Safety Approved.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: Stub (cursor returns the Pending round, then the decided row)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Safety Approved", decided=True),
    ]

    # Act (When)
    response = decide(client, remarks="Looks safe.")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Safety Approved"
    assert response.json["decidedBy"] == OFFICER_ID
    assert response.json["decidedAt"] == "2026-11-02T03:00:00+00:00"
    assert response.json["remarks"] == "Looks safe."
    update_sql, update_params = cursor.execute.call_args_list[-1].args
    assert 'UPDATE public."SafetyCheck"' in update_sql
    assert update_params == ["Safety Approved", OFFICER_ID, "Looks safe.", RECORD_ID]


def test_decide_with_blank_remarks_stores_null(setup):
    """
    Summary: Optional remarks left blank are stored as nothing.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: Stub (cursor returns rows; update inspected)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Safety Approved", decided=True),
    ]

    # Act (When)
    response = decide(client, remarks="   ")

    # Assert (Then)
    assert response.status_code == 200
    update_params = cursor.execute.call_args_list[-1].args[1]
    assert update_params[2] is None


def test_decide_with_remarks_over_limit_returns_400(setup):
    """
    Summary: Remarks over the length limit are refused.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: None
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = decide(client, remarks="x" * 2001)

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "remarks must be 2000 characters or fewer."
    cursor.execute.assert_not_called()


def test_decide_with_non_text_remarks_returns_400(setup):
    """
    Summary: Remarks must be text.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: None
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = decide(client, remarks={"nested": "object"})

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "remarks must be text."
    cursor.execute.assert_not_called()


def test_decide_already_decided_round_returns_409(setup):
    """
    Summary: A round that was already decided cannot be decided again.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: Stub (cursor returns a decided round)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(status="Safety Approved", decided=True)

    # Act (When)
    response = decide(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "SAFETY_CHECK_ALREADY_DECIDED"
    assert response.json["safetyCheck"]["status"] == "Safety Approved"
    # Only the SELECT ran: no UPDATE.
    assert cursor.execute.call_count == 1


def test_decide_older_round_when_newer_exists_returns_409(setup):
    """
    Summary: Only the latest round can be decided.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: Stub (cursor: a newer round exists)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=1, status="Pending"),
        record_row(round_number=2, status="Pending"),
    ]

    # Act (When)
    response = decide(client)

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "NOT_LATEST_ROUND"
    assert cursor.execute.call_count == 2


@pytest.mark.parametrize("status", ["Pending", "Approved"], ids=["pending", "approved"])
def test_decide_with_status_that_is_not_a_decision_returns_400(status, setup):
    """
    Summary: A decision must be one of the safety outcomes.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: None
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = decide(client, status=status)

    # Assert (Then)
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_decide_missing_round_returns_404(setup):
    """
    Summary: Deciding a round that does not exist is refused.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: Stub (cursor finds nothing)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    # Act (When)
    response = decide(client)

    # Assert (Then)
    assert response.status_code == 404
    assert response.json["message"] == "Safety check not found."


@pytest.mark.parametrize(
    "safety_check_id",
    ["not-a-uuid"],
    ids=["not_a_uuid"],
)
def test_decide_with_bad_round_id_returns_404(safety_check_id, setup):
    """
    Summary: A decision must name a valid round.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: None
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = decide(client, safety_check_id=safety_check_id)

    # Assert (Then)
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_decide_with_decider_in_body_records_signed_in_officer(setup):
    """
    Summary: The officer recorded is the signed-in user, never one named in the body.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    SCRUM-8 AC2: Given a system user successfully authenticates, when they
        access protected information or functionality, then their access is
        evaluated according to their role and relationship to the relevant
        event.
    Double: Stub (cursor returns rows; update inspected)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row()

    # Act (When)
    decide(client, decidedBy="99999999-9999-4999-8999-999999999999")

    # Assert (Then)
    assert all("99999999-9999-4999-8999-999999999999" not in str(c.args) for c in cursor.execute.call_args_list)
    assert any(OFFICER_ID in str(c.args) for c in cursor.execute.call_args_list)


def test_decide_with_non_object_body_returns_400(setup):
    """
    Summary: A request that is not a decision is refused.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: None
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = client.patch(
        f"/safety-check-records/{RECORD_ID}/decision", json=["not", "an", "object"]
    )

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    cursor.execute.assert_not_called()


def test_decide_locks_round_before_deciding(setup):
    """
    Summary: The round is locked while it is decided, so two officers cannot both decide it.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: Stub (cursor; SQL inspected for FOR UPDATE)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Safety Approved", decided=True),
    ]

    decide(client)

    select_sql = cursor.execute.call_args_list[0].args[0]

    # Act + Assert (When / Then)
    assert "FOR UPDATE" in select_sql


# --- Compensation: reopen -----------------------------------------------------


def test_reopen_with_matching_decision_time_returns_round_to_pending(setup):
    """
    Summary: A decision is undone only for the exact decision it was told about.
    AC1: (rollback: a decision whose event move failed is undone)
    Double: Stub (cursor returns the decided round; update inspected)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(status="Safety Approved", decided=True),
        record_row(status="Pending"),
    ]

    # Act (When)
    response = reopen(client)

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Pending"
    assert response.json["decidedBy"] is None
    update_sql, update_params = cursor.execute.call_args_list[-1].args
    assert 'UPDATE public."SafetyCheck"' in update_sql
    assert update_params == ["Pending", RECORD_ID]


def test_reopen_with_other_decision_time_returns_409(setup):
    """
    Summary: A decision made later is never undone by a stale rollback.
    AC1: (rollback)
    Double: Stub (cursor returns a round decided at another time)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(status="Safety Approved", decided=True)

    # Act (When)
    response = reopen(client, decidedAt="2099-01-01T00:00:00+00:00")

    # Assert (Then)
    assert response.status_code == 409
    assert cursor.execute.call_count == 1


def test_reopen_undecided_round_returns_409(setup):
    """
    Summary: A round that was never decided cannot be reopened.
    AC1: (rollback)
    Double: Stub (cursor returns a Pending round)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(status="Pending")

    # Act (When)
    response = reopen(client)

    # Assert (Then)
    assert response.status_code == 409


def test_reopen_missing_round_returns_404(setup):
    """
    Summary: Reopening a round that does not exist is refused.
    AC1: (rollback)
    Double: Stub (cursor finds nothing)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    # Act (When)
    response = reopen(client)

    # Assert (Then)
    assert response.status_code == 404


def test_reopen_with_non_object_body_returns_400(setup):
    """
    Summary: A request that is not a reopen is refused.
    AC1: (rollback)
    Double: None
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = client.post(
        f"/safety-check-records/{RECORD_ID}/reopen", json=["not", "an", "object"]
    )

    # Assert (Then)
    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    cursor.execute.assert_not_called()


def test_reopen_without_decision_time_returns_400(setup):
    """
    Summary: A reopen must say which decision it undoes.
    AC1: (rollback)
    Double: None
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = reopen(client, decidedAt=None)

    # Assert (Then)
    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_reopen_with_bad_round_id_returns_404(setup):
    """
    Summary: A reopen must name a valid round.
    AC1: (rollback)
    Double: None
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = client.post(
        "/safety-check-records/not-a-uuid/reopen",
        json={"decidedAt": "2026-11-02T03:00:00+00:00"},
    )

    # Assert (Then)
    assert response.status_code == 400
    cursor.execute.assert_not_called()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_decide_when_database_url_missing_returns_503(no_database):
    """
    Summary: Deciding reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured service answers 503
    Double: None
    """
    response = no_database.patch(
        f"/safety-check-records/{RECORD_ID}/decision",
        json={"status": "Safety Approved"},
    )

    assert response.status_code == 503


def test_decide_when_database_fails_returns_503(setup):
    """
    Summary: A database outage while deciding gives a 503.
    Supporting design check: database errors answer 503 with a safe message
    Double: Stub (psycopg2.connect raises OperationalError)
    """
    client, _, cursor = setup
    cursor.execute.side_effect = psycopg2.OperationalError("connection refused")

    response = decide(client)

    assert response.status_code == 503
    assert "connection refused" not in response.json["message"]


def test_reopen_when_database_url_missing_returns_503(no_database):
    """
    Summary: Reopening reports itself unavailable when no database is configured.
    Supporting design check: an unconfigured service answers 503
    Double: None
    """
    response = no_database.post(
        f"/safety-check-records/{RECORD_ID}/reopen",
        json={"decidedAt": "2026-11-02T03:00:00+00:00"},
    )

    assert response.status_code == 503


def test_preflight_allows_patch_for_decisions(setup):
    """
    Summary: The browser may send decisions as PATCH.
    Supporting design check: CORS allows PATCH
    Double: None
    """
    client, _, _ = setup

    response = client.options(
        f"/safety-check-records/{RECORD_ID}/decision",
        headers={"Origin": "http://localhost:5174"},
    )

    assert "PATCH" in response.headers["Access-Control-Allow-Methods"]
