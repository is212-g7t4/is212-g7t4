"""SCRUM-33: Equipment Request Review

User Story
----------
As a Technical Support Staff, I want to review and update the status of an
equipment request so that the Event Coordinator knows the technical
arrangements are approved.

Acceptance Criteria
-------------------
AC1: Technical Support Staff can view the requested equipment, equipment type,
     quantity, and technical requirements for a given event.
AC2: System allows the Technical Support Staff to change the request status
     (eg: to "Approved", "Rejected").
AC3: Ensure the newly updated status is visible to the assigned Event
     Coordinator.

Real
----
- Real review routes, request/response validation and model SQL construction; decision/status visibility is observed.

Doubled
-------
- Stub (database cursor rows), Mock (connection/SQL calls inspected); Fake (trusted composite caller). JWKS key lookup is a Stub.

Not proven
----------
- Actual database persistence/rollback is not proved by cursor doubles.
- AC3 browser visibility, equipment-type rendering, and notification delivery are NOT COVERED ANYWHERE in this module.
- Supporting review validation/transport error regressions retain their original assertions; precise reason/id limits and API status contracts need Jira clarification, not invented ACs.
"""

import psycopg2

import pytest

from tests.unit.factories import EVENT_ID, MIC, REQUEST_ID, TABLE, USER_ID, bearer, db_row, item, approval_context

TS = bearer(USER_ID, "Technical Support")

COORDINATOR = bearer(USER_ID, "Event Coordinator")

SAFETY_OFFICER = bearer(USER_ID, "Safety Officer")


import pytest

from tests.unit.factories import EVENT_ID, MIC, REQUEST_ID, USER_ID, bearer, db_row, approval_context



def test_list_requests_returns_equipment_quantity_and_requirements(setup):
    """
    Summary: Technical Support see each request's equipment, quantity, technical requirements and status.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    Double: Stub (cursor returns a Pending and an Approved row)
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = [db_row(), db_row(technical_requirements=None, status="Approved", reviewed_by=USER_ID)]

    response = client.get("/equipment-requests", headers=TS)

    assert response.status_code == 200
    first, second = response.json["requests"]
    assert first == {
        "id": REQUEST_ID,
        "eventId": EVENT_ID,
        "equipmentId": "2ebcd2d3-636b-48e7-8784-d00000000000",
        "quantityRequested": 15,
        "technicalRequirements": "For vendor booths",
        "status": "Pending",
        "reviewedBy": None,
        "rejectionReason": None,
    }
    assert second["technicalRequirements"] == "" and second["reviewedBy"] == USER_ID
    assert "WHERE" not in cursor.execute.call_args[0][0]



def test_list_requests_with_status_and_event_filters_queries_only_those(setup):
    """
    Summary: Requests can be narrowed to one event and one status.
    AC1: requests are viewed for a given event
    Double: Stub (cursor returns no rows; query inspected)
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = []

    response = client.get(f"/equipment-requests?status=Pending&eventId={EVENT_ID}", headers=TS)

    assert response.json == {"requests": []}
    sql, params = cursor.execute.call_args[0]
    assert "status = %s AND event_id = %s" in sql and params == ["Pending", EVENT_ID]



def test_list_requests_with_several_event_ids_returns_their_requests(setup):
    """
    Summary: The reservation composite can fetch the requests of several events in one call.
    AC1: requests are viewed for a given event
    Double: Stub (cursor returns an Approved row; query inspected)
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = [db_row(status="Approved")]
    other = "5b569df8-b7e4-44a2-af9f-d60000000000"

    response = client.get(f"/equipment-requests?status=Approved&eventIds={EVENT_ID},{other}", headers=TS)

    assert response.status_code == 200
    sql, params = cursor.execute.call_args[0]
    assert "event_id = ANY(%s::uuid[])" in sql and params == ["Approved", [EVENT_ID, other]]



def test_list_requests_with_empty_event_ids_returns_nothing(setup):
    """
    Summary: An empty list of events matches no requests rather than every request.
    AC3: only requests for the coordinator's own events are visible
    Double: Stub (cursor returns no rows)
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = []

    assert client.get("/equipment-requests?eventIds=", headers=TS).json == {"requests": []}
    assert cursor.execute.call_args[0][1] == [[]]



@pytest.mark.parametrize("value", ["not-a-uuid", f"{EVENT_ID},bad"], ids=["not_a_uuid", "one_bad_in_list"])
def test_list_requests_with_malformed_event_ids_returns_400_before_database(setup, value):
    """
    Summary: A malformed event id in the list is refused.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    Double: Mock (connect not called)
    """
    # Review AC1 / Reservation AC2 (validation): require valid event references for scoped reads.
    client, _, connect = setup
    assert client.get(f"/equipment-requests?eventIds={value}", headers=TS).status_code == 400
    connect.assert_not_called()



def test_list_requests_with_more_than_500_event_ids_returns_400(setup):
    """
    Summary: A lookup for too many events at once is refused.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    Double: None
    """
    client, _, _ = setup
    assert client.get("/equipment-requests?eventIds=" + ",".join([EVENT_ID] * 501), headers=TS).status_code == 400



def test_get_request_when_found_returns_it_to_coordinator(setup):
    """
    Summary: A coordinator can open one equipment request.
    AC3: Ensure the newly updated status is visible to the assigned Event
        Coordinator.
    Double: Stub (cursor returns one row)
    """
    client, cursor, _ = setup
    cursor.fetchone.return_value = db_row()

    response = client.get(f"/equipment-requests/{REQUEST_ID}", headers=COORDINATOR)

    assert response.status_code == 200 and response.json["request"]["id"] == REQUEST_ID



def test_review_when_caller_is_coordinator_can_read_decision_but_not_decide(setup):
    """
    Summary: A coordinator sees the decision and reason Technical Support recorded but cannot make one.
    AC3: Ensure the newly updated status is visible to the assigned Event
        Coordinator.
    AC2: only Technical Support Staff change the status
    Double: Stub (cursor returns a Rejected row), Mock (connect)
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = [db_row(status="Rejected", rejection_reason="No technician available.")]

    saved = client.get("/equipment-requests", headers=COORDINATOR).json["requests"][0]
    assert saved["status"] == "Rejected"
    assert saved["rejectionReason"] == "No technician available."
    assert client.patch(f"/equipment-requests/{REQUEST_ID}", headers=COORDINATOR, json={"status": "Approved"}).status_code == 403



def test_review_when_caller_is_safety_officer_can_read_but_not_decide(setup):
    """
    Summary: A Safety Officer can read an event's equipment requests but cannot decide them.
    AC2: only Technical Support Staff change the status
    Double: Stub (cursor returns an Approved row)
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = [db_row(status="Approved")]

    assert client.get("/equipment-requests", headers=SAFETY_OFFICER).json["requests"][0]["status"] == "Approved"
    assert client.patch(f"/equipment-requests/{REQUEST_ID}", headers=SAFETY_OFFICER, json={"status": "Approved"}).status_code == 403



@pytest.mark.parametrize("query", ["?status=Broken", "?eventId=not-a-uuid"], ids=["unknown_status", "bad_event_id"])
def test_list_requests_with_unknown_status_or_bad_event_returns_400_before_database(setup, query):
    """
    Summary: An unknown status or malformed event id filter is refused.
    AC1: Technical Support Staff can view the requested equipment, equipment
        type, quantity, and technical requirements for a given event.
    Double: Mock (connect not called)
    """
    # Review AC1/AC2 (validation): reject invalid event and status filters.
    client, _, connect = setup
    assert client.get(f"/equipment-requests{query}", headers=TS).status_code == 400
    connect.assert_not_called()



@pytest.mark.parametrize("decision", ["Approved", "Rejected"], ids=["approve", "reject"])
def test_review_when_request_pending_sets_approved_or_rejected(setup, decision):
    """
    Summary: Technical Support can approve or reject a pending request, and their identity is recorded.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Stub (cursor returns the decided row; update inspected)
    """
    # Review AC2 / Reservation AC2: save the decision and reviewer on the existing event-linked request.
    client, cursor, _ = setup
    reason = "Equipment needs servicing." if decision == "Rejected" else None
    cursor.fetchone.return_value = db_row(status=decision, reviewed_by=USER_ID, rejection_reason=reason)
    if decision == "Approved":
        cursor.fetchall.side_effect = [[db_row()], [], [cursor.fetchone.return_value]]

    response = client.patch(f"/equipment-requests/{REQUEST_ID}", headers=TS, json={"status": decision, "rejectionReason": reason})

    assert response.status_code == 200
    assert response.json["request"]["status"] == decision
    assert response.json["request"]["reviewedBy"] == USER_ID
    assert response.json["request"]["rejectionReason"] == reason
    sql, params = cursor.execute.call_args[0]
    assert "status = 'Pending'" in sql
    if decision == "Approved":
        assert params == [USER_ID, [REQUEST_ID]]
    else:
        assert "rejection_reason = %s" in sql
        assert params == [decision, USER_ID, reason, REQUEST_ID]



def test_review_when_request_already_decided_returns_409(setup):
    """
    Summary: A request that has already been decided cannot be decided again.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Stub (update matches nothing; the request exists)
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = (1,)

    response = client.patch(f"/equipment-requests/{REQUEST_ID}", headers=TS, json={"status": "Approved"})

    assert response.status_code == 409



def test_review_when_request_unknown_returns_404(setup):
    """
    Summary: Deciding a request that does not exist is refused.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Stub (update matches nothing; the request does not exist)
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = None

    assert client.patch(f"/equipment-requests/{REQUEST_ID}", headers=TS, json={"status": "Approved"}).status_code == 404



@pytest.mark.parametrize("payload", [{"status": "Pending"}, {"status": "Maybe"}, {}, [], None], ids=["back_to_pending", "unknown_status", "no_status", "list_body", "no_body"])
def test_review_with_status_other_than_approved_or_rejected_returns_400(setup, payload):
    """
    Summary: A decision must be Approved or Rejected.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Mock (connect not called)
    """
    # Review AC2 (validation): reject unsupported or missing decision values.
    client, _, connect = setup
    assert client.patch(f"/equipment-requests/{REQUEST_ID}", headers=TS, json=payload).status_code == 400
    connect.assert_not_called()



def test_review_with_malformed_request_id_returns_400_before_database(setup):
    """
    Summary: A decision must name a valid request.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Mock (connect not called)
    """
    client, _, connect = setup
    assert client.patch("/equipment-requests/abc", headers=TS, json={"status": "Approved"}).status_code == 400
    connect.assert_not_called()



@pytest.mark.parametrize("decision", ["Approved", "Rejected"], ids=["approve", "reject"])
def test_bulk_review_when_event_has_pending_requests_decides_all_of_them(setup, decision):
    """
    Summary: Technical Support can approve or reject every pending request of an event at once.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Stub (cursor returns the decided rows; update inspected)
    """
    # Review AC2 / Reservation AC2: update only Pending records belonging to the supplied event ID.
    client, cursor, _ = setup
    reason = "No technician available." if decision == "Rejected" else None
    cursor.fetchall.return_value = [
        db_row(status=decision, reviewed_by=USER_ID, rejection_reason=reason),
        db_row(equipment_request_id="3b1bfb57-a3c0-4450-897e-cc5c73690000", status=decision, reviewed_by=USER_ID, rejection_reason=reason),
    ]

    selected_ids = [REQUEST_ID, "3b1bfb57-a3c0-4450-897e-cc5c73690000"]
    if decision == "Approved":
        cursor.fetchall.side_effect = [[db_row(equipment_request_id=rid) for rid in selected_ids], [], cursor.fetchall.return_value]
    response = client.patch(f"/events/{EVENT_ID}/equipment-requests", headers=TS,
        json={"status": decision, "rejectionReason": reason, "approvalContext": approval_context(request_ids=selected_ids)})

    assert response.status_code == 200
    assert [request["status"] for request in response.json["requests"]] == [decision, decision]
    assert [request["rejectionReason"] for request in response.json["requests"]] == [reason, reason]
    sql, params = cursor.execute.call_args[0]
    assert "status = 'Pending'" in sql
    if decision == "Approved":
        assert params == [USER_ID, selected_ids]
    else:
        assert "event_id = %s" in sql
        assert params == [decision, USER_ID, reason, EVENT_ID]



@pytest.mark.parametrize("reason", [None, "  ", "x" * 501], ids=["missing_reason", "blank_reason", "reason_too_long"])
def test_review_reject_without_valid_reason_returns_400_before_database(setup, reason):
    """
    Summary: Rejecting one request or a whole event needs a reason of at most 500 characters.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Mock (connect not called)
    """
    client, _, connect = setup
    for url in (f"/equipment-requests/{REQUEST_ID}", f"/events/{EVENT_ID}/equipment-requests"):
        response = client.patch(url, headers=TS, json={"status": "Rejected", "rejectionReason": reason})
        assert response.status_code == 400
    connect.assert_not_called()



def test_bulk_review_when_event_has_no_pending_requests_returns_409(setup):
    """
    Summary: An event whose requests were all decided cannot be decided again in bulk.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Stub (no Pending rows; the event has requests)
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = (1,)

    response = client.patch(f"/events/{EVENT_ID}/equipment-requests", headers=TS, json={"status": "Approved"})

    assert response.status_code == 409



def test_bulk_review_when_event_has_no_requests_returns_404(setup):
    """
    Summary: A bulk decision for an event with no requests is refused.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Stub (no rows at all)
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = None

    response = client.patch(f"/events/{EVENT_ID}/equipment-requests", headers=TS, json={"status": "Approved"})

    assert response.status_code == 404



def test_bulk_review_with_wrong_role_event_id_or_status_is_refused(setup):
    """
    Summary: A bulk decision needs Technical Support, a valid event and a real decision.
    AC2: System allows the Technical Support Staff to change the request status
        (eg: to "Approved", "Rejected").
    Double: Mock (connect not called)
    """
    client, _, connect = setup
    url = f"/events/{EVENT_ID}/equipment-requests"

    assert client.patch(url, headers=COORDINATOR, json={"status": "Approved"}).status_code == 403
    assert client.patch("/events/not-a-uuid/equipment-requests", headers=TS, json={"status": "Approved"}).status_code == 400
    assert client.patch(url, headers=TS, json={"status": "Pending"}).status_code == 400
    connect.assert_not_called()



@pytest.mark.parametrize(
    "length, expected_status",
    [(499, 200), (500, 200), (501, 400)],
    ids=["below_limit", "at_limit", "above_limit"],
)
def test_review_reject_when_reason_near_limit_accepts_up_to_500_characters(setup, length, expected_status):
    """
    Summary: A rejection reason can be up to 500 characters.
    AC2: (boundary: reason length = 499, 500, 501)
    Double: Stub (cursor returns the rejected row)
    """
    client, cursor, _ = setup
    cursor.fetchone.return_value = db_row(status="Rejected", reviewed_by=USER_ID, rejection_reason="x" * length)

    response = client.patch(
        f"/equipment-requests/{REQUEST_ID}", headers=TS, json={"status": "Rejected", "rejectionReason": "x" * length}
    )

    assert response.status_code == expected_status



@pytest.mark.parametrize(
    "count, expected_status",
    [(499, 200), (500, 200), (501, 400)],
    ids=["below_limit", "at_limit", "above_limit"],
)
def test_list_requests_when_event_id_count_near_limit_accepts_up_to_500(setup, count, expected_status):
    """
    Summary: Requests can be fetched for up to 500 events at once.
    AC1: (boundary: event ids = 499, 500, 501)
    Double: Stub (cursor returns no rows)
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = []

    response = client.get("/equipment-requests?eventIds=" + ",".join([EVENT_ID] * count), headers=TS)

    assert response.status_code == expected_status



@pytest.mark.parametrize("bulk", [False, True], ids=["single", "bulk"])
@pytest.mark.parametrize("exists,expected", [(False, 404), (True, 409)], ids=["missing", "already_decided"])
def test_rejection_preserves_missing_and_final_decision_responses(setup, bulk, exists, expected):
    """Summary: Rejection remains independent of catalogue/windows and preserves the 404/409 split.
    AC2: Rejection retains its missing-versus-already-decided responses without needing stock context (supporting compatibility check).
    Double: Stub (database lookup rows); Fake (trusted composite caller)
    """
    client, cursor, _ = setup
    cursor.fetchall.return_value = []
    cursor.fetchone.side_effect = [(1,) if exists else None] if bulk else [None, (1,) if exists else None]
    path = f"/events/{EVENT_ID}/equipment-requests" if bulk else f"/equipment-requests/{REQUEST_ID}"
    response = client.patch(path, headers=bearer(USER_ID, "Technical Support"), json={"status": "Rejected", "rejectionReason": "No support available", "approvalContext": None})
    assert response.status_code == expected
