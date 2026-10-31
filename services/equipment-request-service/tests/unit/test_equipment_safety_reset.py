"""SCRUM-164: Revise Arrangements and Resubmit for Safety Check

Agreed revision from this conversation; pending confirmation that Jira has been updated

User Story
----------
As an Event Coordinator, I want to see the Safety Officer's feedback and revise
the affected arrangements, so that I can resubmit the event for a safety check
without redoing unaffected planning.

Acceptance Criteria
-------------------
AC1: Given my event is 'Safety Changes Requested', when I open it, then I see
     the decision, reason, requested changes and affected areas.
AC2: Given the venue arrangement is flagged, then the affected venue booking
     must be reviewed again by Venue Staff (revised booking or replacement
     request) before the event can be resubmitted.
AC3: Given the technical arrangement is flagged, then the affected equipment requests that were previously 'Approved' return to 'Pending' and must be approved again by Technical Support Staff before the event can be resubmitted. The safety-change action does not reopen existing 'Rejected' requests or clear their rejection reasons, and requests already 'Pending' remain 'Pending'.
AC4: Given an arrangement was not flagged, then it stays confirmed and does not
     need to be reviewed again.
AC5: Given all flagged arrangements are confirmed again, when I resubmit, then
     the status returns to 'Pending Safety Check' as a new review round, and
     earlier rounds remain in the history.

Real
----
- Real owner safety-reset route, membership validation and SQL construction; existing Approved-to-Pending response and refused invalid selections are asserted.

Doubled
-------
- Stub (database before/after rows), Mock (connection and UPDATE SQL inspected); Stub (JWKS key lookup).

Not proven
----------
- Issue8 Approved-only persistence is NOT PROVED: this checkout lacks PR115’s Approved SQL predicate and its tests/integration/test_equipment_safety_reset.py source. Existing cursor stubs cannot demonstrate preservation of Rejected reasons, Pending reviewers, mixed/ineligible-only selections, replay or lock-waiting rejection. Published regressions remain blocked pending explicit integration; no production code or branch was restored.
- AC1 feedback, AC2 venue review, AC4 unflagged arrangements and AC5 resubmission/history run outside this owner and are NOT COVERED ANYWHERE in this module.
- Related trigger: SCRUM-151 AC2; safety-change orchestration lives in safety-check-service/tests/unit/test_safety_reject_changes.py, which doubles this owner.
- Exact request-id count and error-status limits are supporting reliability checks requiring Jira clarification; they are not new ACs.
"""

import psycopg2

import pytest

from tests.unit.factories import EVENT_ID, MIC, REQUEST_ID, TABLE, USER_ID, bearer, db_row, item

TS = bearer(USER_ID, "Technical Support")

COORDINATOR = bearer(USER_ID, "Event Coordinator")

SAFETY_OFFICER = bearer(USER_ID, "Safety Officer")



def test_safety_reset_with_flagged_requests_returns_them_to_pending_unreviewed(setup):
    """Summary: A flagged technical arrangement sends its equipment requests back to Technical Support as Pending.
    AC3: Approved affected equipment returns to Pending for Technical Support review; validation failures are supporting reliability checks.
    Double: Stub (database rows); Mock (SQL/connection call observations)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    client.application.config["INTERNAL_SERVICE_TOKEN"] = "test-internal-token"
    cursor.fetchall.side_effect = [[db_row(status="Approved", reviewed_by=USER_ID)], [db_row()]]

    # Act (When)
    response = client.post(
        f"/events/{EVENT_ID}/equipment-requests/safety-reset",
        headers={**SAFETY_OFFICER, "X-Internal-Token": "test-internal-token"},
        json={"requestIds": [REQUEST_ID]},
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["requests"][0]["status"] == "Pending"
    assert response.json["requests"][0]["reviewedBy"] is None
    sql, params = cursor.execute.call_args[0]
    assert "SET status = 'Pending', reviewed_by = NULL" in sql
    assert params == [EVENT_ID, [REQUEST_ID]]


def test_safety_reset_with_request_of_other_event_returns_404_without_update(setup):
    """Summary: A request that belongs to another event is not reset.
    AC4: Only the flagged event’s affected arrangements may be reset (supporting membership guard).
    Double: Stub (database rows); Mock (SQL/connection call observations)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    client.application.config["INTERNAL_SERVICE_TOKEN"] = "test-internal-token"
    cursor.fetchall.return_value = []

    # Act (When)
    response = client.post(f"/events/{EVENT_ID}/equipment-requests/safety-reset",
        headers={**SAFETY_OFFICER, "X-Internal-Token": "test-internal-token"}, json={"requestIds": [REQUEST_ID]})

    # Assert (Then)
    assert response.status_code == 404
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("event_id,payload", [
    ("bad", {"requestIds": [REQUEST_ID]}), (EVENT_ID, None), (EVENT_ID, {}),
    (EVENT_ID, {"requestIds": []}), (EVENT_ID, {"requestIds": "bad"}),
    (EVENT_ID, {"requestIds": ["bad"]}), (EVENT_ID, {"requestIds": [REQUEST_ID, REQUEST_ID]}),
    (EVENT_ID, {"requestIds": [REQUEST_ID] * 501}),
], ids=["bad_event_id", "no_body", "empty_object", "empty_ids", "ids_as_text", "bad_request_id", "duplicate_ids", "too_many_ids"])
def test_safety_reset_with_invalid_ids_returns_400_before_database(setup, event_id, payload):
    """Summary: A reset naming a bad event, no requests, bad or duplicate ids, or too many ids is refused.
    AC3: Approved affected equipment returns to Pending for Technical Support review; validation failures are supporting reliability checks.
    Double: Stub (database rows); Mock (SQL/connection call observations)
    """
    # Arrange (Given)
    client, _, connect = setup
    client.application.config["INTERNAL_SERVICE_TOKEN"] = "test-internal-token"

    # Act + Assert (When / Then)
    assert client.post(f"/events/{event_id}/equipment-requests/safety-reset",
        headers={**SAFETY_OFFICER, "X-Internal-Token": "test-internal-token"}, json=payload).status_code == 400
    connect.assert_not_called()


def test_safety_reset_when_database_url_missing_returns_503(setup):
    """Summary: A reset is reported unavailable when no database is configured.
    AC3: Approved affected equipment returns to Pending for Technical Support review; validation failures are supporting reliability checks.
    Double: Stub (database rows); Mock (SQL/connection call observations)
    """
    # Arrange (Given)
    client, _, connect = setup
    client.application.config.update(INTERNAL_SERVICE_TOKEN="test-internal-token", DATABASE_URL=None)

    # Act + Assert (When / Then)
    assert client.post(f"/events/{EVENT_ID}/equipment-requests/safety-reset",
        headers={**SAFETY_OFFICER, "X-Internal-Token": "test-internal-token"}, json={"requestIds": [REQUEST_ID]}).status_code == 503
    connect.assert_not_called()


@pytest.mark.parametrize(
    "count, expected_status",
    [(1, 404), (500, 404), (501, 400)],
    ids=["minimum", "at_limit", "above_limit"],
)
def test_safety_reset_when_request_id_count_near_limits_accepts_1_to_500(setup, count, expected_status):
    """Summary: A safety reset can name from 1 up to 500 equipment requests.
    AC3: Approved affected equipment returns to Pending for Technical Support review; validation failures are supporting reliability checks.
    Double: Stub (database rows); Mock (SQL/connection call observations)
    """
    # Arrange (Given)
    client, cursor, _ = setup
    client.application.config["INTERNAL_SERVICE_TOKEN"] = "test-internal-token"
    cursor.fetchall.return_value = []
    ids = [f"{i:08d}-a3c0-4450-897e-cc5c73690000" for i in range(count)]

    # Act (When)
    response = client.post(
        f"/events/{EVENT_ID}/equipment-requests/safety-reset",
        headers={**SAFETY_OFFICER, "X-Internal-Token": "test-internal-token"},
        json={"requestIds": ids},
    )

    # Assert (Then)
    assert response.status_code == expected_status
