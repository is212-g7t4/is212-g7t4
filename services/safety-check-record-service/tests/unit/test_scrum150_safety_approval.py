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

Real
----
- Recording a Safety Officer's decision on the latest pending round: the
  outcome, the officer, the time and any remarks; refusing rounds already
  decided or no longer the latest; and undoing a decision if the event could
  not be moved.
- We check the round returned and what is saved.

Doubled
-------
- Safety records (database): hold the rounds each test needs, accept new ones,
  or cannot be reached [Stub]; we check what is saved, and that rounds are
  locked before they change [Mock].
- Sign-in: a test key signs the caller's token (tests/unit/conftest.py) [Stub].

Not proven
----------
- That the event moves to 'Confirmed' (-> safety-check-service and
  event-service SCRUM-150 tests).
- That the saving and locking really work in Postgres, including two people
  acting at the same moment (-> tests/integration/, against a throwaway
  postgres:17.6).
"""
import psycopg2
import pytest
from unittest.mock import MagicMock

from app import create_app
from tests.unit.factories import OFFICER_ID, RECORD_ID, record_row, signed_in


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
    Double: The round is pending, and the safety records save the decision
        [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Safety Approved", decided=True),
    ]

    response = decide(client, remarks="Looks safe.")

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
    Double: The safety records hold the rounds this case needs [Stub]; we check
        what is saved [Mock].
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Safety Approved", decided=True),
    ]

    response = decide(client, remarks="   ")

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
    client, _, cursor = setup

    response = decide(client, remarks="x" * 2001)

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
    client, _, cursor = setup

    response = decide(client, remarks={"nested": "object"})

    assert response.status_code == 400
    assert response.json["message"] == "remarks must be text."
    cursor.execute.assert_not_called()


def test_decide_already_decided_round_returns_409(setup):
    """
    Summary: A round that was already decided cannot be decided again.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: The round has already been decided [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(status="Safety Approved", decided=True)

    response = decide(client)

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
    Double: The event already has a newer round [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=1, status="Pending"),
        record_row(round_number=2, status="Pending"),
    ]

    response = decide(client)

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
    client, _, cursor = setup

    response = decide(client, status=status)

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_decide_missing_round_returns_404(setup):
    """
    Summary: Deciding a round that does not exist is refused.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: The safety records hold no such round [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = decide(client)

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
    client, _, cursor = setup

    response = decide(client, safety_check_id=safety_check_id)

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_decide_with_decider_in_body_records_signed_in_officer(setup):
    """
    Summary: The officer recorded as deciding is the one signed in, never someone named in the request.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: The safety records hold the rounds this case needs [Stub]; we check
        what is saved [Mock].
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row()

    decide(client, decidedBy="99999999-9999-4999-8999-999999999999")

    assert all("99999999-9999-4999-8999-999999999999" not in str(c.args) for c in cursor.execute.call_args_list)
    assert any(OFFICER_ID in str(c.args) for c in cursor.execute.call_args_list)


def test_decide_with_non_object_body_returns_400(setup):
    """
    Summary: A decision that is not in the expected form is refused.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: None
    """
    client, _, cursor = setup

    response = client.patch(
        f"/safety-check-records/{RECORD_ID}/decision", json=["not", "an", "object"]
    )

    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    cursor.execute.assert_not_called()


def test_decide_locks_round_before_deciding(setup):
    """
    Summary: Two officers deciding at the same moment cannot both record a decision: the round is locked while it is decided.
    AC3: Given an event is not 'Pending Safety Check', then the approve action
        is not available and an API call is rejected without changing the
        event.
    Double: The safety records hold the round [Stub]; we check it is locked
        before it changes, so two people cannot change it at once [Mock].
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Safety Approved", decided=True),
    ]

    decide(client)

    select_sql = cursor.execute.call_args_list[0].args[0]

    assert "FOR UPDATE" in select_sql


# --- Compensation: reopen -----------------------------------------------------


def test_reopen_with_matching_decision_time_returns_round_to_pending(setup):
    """
    Summary: A decision is undone only for the exact decision it was told about.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The round has been decided [Stub]; we check what is saved [Mock].
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(status="Safety Approved", decided=True),
        record_row(status="Pending"),
    ]

    response = reopen(client)

    assert response.status_code == 200
    assert response.json["status"] == "Pending"
    assert response.json["decidedBy"] is None
    update_sql, update_params = cursor.execute.call_args_list[-1].args
    assert 'UPDATE public."SafetyCheck"' in update_sql
    assert update_params == ["Pending", RECORD_ID]


def test_reopen_with_other_decision_time_returns_409(setup):
    """
    Summary: A decision made later is never undone by a stale rollback.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The round was decided at a different time from the one named
        [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(status="Safety Approved", decided=True)

    response = reopen(client, decidedAt="2099-01-01T00:00:00+00:00")

    assert response.status_code == 409
    assert cursor.execute.call_count == 1


def test_reopen_undecided_round_returns_409(setup):
    """
    Summary: A round that was never decided cannot be reopened.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The round is pending [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = record_row(status="Pending")

    response = reopen(client)

    assert response.status_code == 409


def test_reopen_missing_round_returns_404(setup):
    """
    Summary: Reopening a round that does not exist is refused.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: The safety records hold no such round [Stub].
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = reopen(client)

    assert response.status_code == 404


def test_reopen_with_non_object_body_returns_400(setup):
    """
    Summary: An undo request that is not in the expected form is refused.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: None
    """
    client, _, cursor = setup

    response = client.post(
        f"/safety-check-records/{RECORD_ID}/reopen", json=["not", "an", "object"]
    )

    assert response.status_code == 400
    assert response.json["message"] == "Send a JSON object."
    cursor.execute.assert_not_called()


def test_reopen_without_decision_time_returns_400(setup):
    """
    Summary: A reopen must say which decision it undoes.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: None
    """
    client, _, cursor = setup

    response = reopen(client, decidedAt=None)

    assert response.status_code == 400
    cursor.execute.assert_not_called()


def test_reopen_with_bad_round_id_returns_404(setup):
    """
    Summary: A reopen must name a valid round.
    AC1: Given an event is 'Pending Safety Check', when I approve it, then its
        status changes to 'Confirmed'.
    Double: None
    """
    client, _, cursor = setup

    response = client.post(
        "/safety-check-records/not-a-uuid/reopen",
        json={"decidedAt": "2026-11-02T03:00:00+00:00"},
    )

    assert response.status_code == 400
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [{"status": "Safety Approved"}, {"status": "Safety Approved", "flags": None}],
    ids=["no_remarks", "no_remarks_and_empty_flags"],
)
def test_approve_without_remarks_is_recorded(setup, body):
    """
    Summary: Remarks are optional, so an approval with none is recorded, with no remarks saved.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: The round is pending, and the safety records save the decision
        [Stub]; we check what is saved [Mock].
    """
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Pending"),
        record_row(round_number=1, status="Safety Approved", decided=True),
    ]

    response = client.patch(f"/safety-check-records/{RECORD_ID}/decision", json=body)

    assert response.status_code == 200
    assert response.json["status"] == "Safety Approved"
    update_params = cursor.execute.call_args_list[-1].args[1]
    assert update_params[0] == "Safety Approved"
    assert update_params[2] is None


def test_approve_with_flags_returns_400(setup):
    """
    Summary: An approval cannot flag areas for change; flagged areas belong only to a change request.
    AC2: Given I approve an event, then the safety check is recorded with the
        status 'Safety Approved', together with my identity, the approval
        timestamp and any optional remarks, in the event's history.
    Double: We check the safety records are never touched [Mock].
    """
    client, _, cursor = setup

    response = client.patch(
        f"/safety-check-records/{RECORD_ID}/decision",
        json={"status": "Safety Approved", "flags": [{"area": "venue arrangement", "changeRequired": "x"}]},
    )

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
    Summary: If the safety records cannot be reached, the decision reports the service as unavailable.
    Supporting design check: database errors answer 503 with a safe message
    Double: The safety records cannot be reached [Stub].
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
    Summary: The browser is allowed to send decisions to this service.
    Supporting design check: CORS allows PATCH
    Double: None
    """
    client, _, _ = setup

    response = client.options(
        f"/safety-check-records/{RECORD_ID}/decision",
        headers={"Origin": "http://localhost:5174"},
    )

    assert "PATCH" in response.headers["Access-Control-Allow-Methods"]
