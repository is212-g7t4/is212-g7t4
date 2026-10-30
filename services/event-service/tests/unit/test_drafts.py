"""
SCRUM-12: Save Event Request as Draft

User Story
----------
As an Event Organiser, I want to save an incomplete Event Request as a draft,
so that I can complete or review it later to avoid losing progress

Acceptance Criteria
-------------------
AC1: Given an Event Organiser has entered some (not necessarily all) event
     details, when they choose "Save as Draft," then the request is stored with
     status 'Draft' and is not visible to any Event Coordinator.
AC2: Given an Event Organiser has multiple existing drafts, each draft can be
     opened and edited independently of the others.
AC3: Given an Event Organiser owns a draft, when they delete it, it is
     permanently removed and no longer appears in their draft list.
AC4: Drafts are visible only to the Event Organiser who created them; no other
     role can view or edit someone else's draft.
AC5: Given an Event Organiser has opened one of their drafts, when they choose
     "Submit Request", then the request is checked against the required-field
     and format rules as a new submission. If it passes, its status changes
     from 'Draft' to 'Submitted', its submission time is recorded, and it no
     longer appears in their draft list. If any required details are missing or
     invalid, the submission is refused, the missing or invalid fields are
     listed, and the request stays a 'Draft' with its saved details unchanged.

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
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from app import create_app
from app.models import FIELDS, NOT_DRAFT
from tests.unit.factories import signed_in

ORGANISER_ID = "33333333-3333-4333-8333-333333333333"
OTHER_ORGANISER_ID = "44444444-4444-4444-8444-444444444444"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
DRAFT_ID = "00000000-0000-0000-0000-0000000000d1"
OTHER_DRAFT_ID = "00000000-0000-0000-0000-0000000000d2"

COMPLETE = {
    "eventName": "Community Workshop",
    "description": "A workshop",
    "purpose": "Learning",
    "preferredStartDate": "2026-12-01T09:00",
    "preferredEndDate": "2026-12-01T17:00",
    "expectedAttendance": "25",
}


@pytest.fixture
def setup(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr("app.models.psycopg2.connect", lambda *args, **kwargs: connection)
    app = create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"})
    return signed_in(app.test_client(), role="Event Organiser"), connection, cursor


def draft_row(**overrides):
    row = {column: None for column in FIELDS.values()}
    row.update(
        event_id=DRAFT_ID,
        event_name="Community Workshop",
        description=json.dumps(
            {"_connectsphere": "event-submission-v1", "description": "", "purpose": ""}
        ),
        status="Draft",
        submission_date=None,
        coordinator_id=None,
        organiser_id=ORGANISER_ID,
        assigned_by=None,
        assigned_at=None,
        previous_coordinator_id=None,
    )
    row.update(overrides)
    return row


# AC1 ---------------------------------------------------------------------


def test_save_as_draft_stores_partial_details_with_status_draft(setup):
    """
    Summary: Only a name is entered; the request is stored as 'Draft' with no submission time.
    AC1: Given an Event Organiser has entered some (not necessarily all) event
        details, when they choose "Save as Draft," then the request is stored
        with status 'Draft' and is not visible to any Event Coordinator.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = draft_row()

    # Act (When)
    response = client.post(
        "/events/drafts",
        json={"organiserId": ORGANISER_ID, "eventName": "Community Workshop", "expectedAttendance": ""},
    )

    # Assert (Then)
    assert response.status_code == 201
    assert response.json["status"] == "Draft"
    assert response.json["submittedAt"] is None
    query, params = cursor.execute.call_args.args
    assert 'INSERT INTO public."Event"' in query
    assert "'Draft', NULL" in query
    assert UUID(params[0])
    assert params[1] == "Community Workshop"
    # Unfilled typed columns are NULL rather than failing the insert.
    assert params[3:] == [None] * 8 + [ORGANISER_ID]


@pytest.mark.parametrize(
    "details, problem",
    [
        ({}, "Event Name"),
        ({"eventName": 5}, "Event Name must be text."),
        ({"eventName": "Workshop", "expectedAttendance": "0"}, "Expected Attendance must be a positive whole number"),
        (
            {"eventName": "Workshop", "preferredStartDate": "2026-12-01T10:00", "preferredEndDate": "2026-12-01T09:00"},
            "Preferred End Date & Time must be after the start.",
        ),
        ({"eventName": "Workshop", "preferredStartDate": "tomorrow"}, "Preferred dates must be valid"),
        ({"eventName": "Workshop", "withdrawalDeadline": "tomorrow"}, "Withdrawal Deadline"),
        ({
            "eventName": "Workshop",
            "preferredStartDate": "2026-12-01T10:00",
            "withdrawalDeadline": "2026-12-01T10:01",
        }, "Withdrawal Deadline"),
    ],
    ids=["event_name", "eventname_5_event_name_must_be_text", "eventname_workshop_expectedattendance_0_expected", "eventname_workshop_preferredstartdate_2026_12_01", "eventname_workshop_preferredstartdate_tomorrow_p", "eventname_workshop_withdrawaldeadline_tomorrow_w", "eventname_workshop_preferredstartdate_2026_12_01_2"],
)
def test_save_as_draft_rejects_missing_name_or_malformed_fields(setup, details, problem):
    """
    Summary: A draft needs a name, and any detail it does have must be well formed.
    AC1: Given an Event Organiser has entered some (not necessarily all) event
        details, when they choose "Save as Draft," then the request is stored
        with status 'Draft' and is not visible to any Event Coordinator.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = client.post("/events/drafts", json={"organiserId": ORGANISER_ID, **details})

    # Assert (Then)
    assert response.status_code == 400
    assert any(problem in item for item in response.json["missingFields"] + response.json["errors"])
    cursor.execute.assert_not_called()


def test_save_as_draft_rejects_a_body_that_is_not_an_object(setup):
    """
    Summary: Nothing is stored from a request that isn't a set of event details.
    AC1: Given an Event Organiser has entered some (not necessarily all) event
        details, when they choose "Save as Draft," then the request is stored
        with status 'Draft' and is not visible to any Event Coordinator.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = client.post("/events/drafts", json=["Community Workshop"])

    # Assert (Then)
    assert response.status_code == 400
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    "path",
    [
        f"/events?coordinatorId={COORDINATOR_ID}&viewerRole=Event+Coordinator+Lead",
        "/events/active",
        f"/events/summaries?ids={DRAFT_ID}",
    ],
    ids=["f_events_coordinatorid_coordinator_id_viewerrole", "events_active", "f_events_summaries_ids_draft_id"],
)
def test_coordinator_event_lists_exclude_drafts(setup, path):
    """
    Summary: The coordinator-facing lists that aren't already status-filtered leave drafts out.
    AC1: Given an Event Organiser has entered some (not necessarily all) event
        details, when they choose "Save as Draft," then the request is stored
        with status 'Draft' and is not visible to any Event Coordinator.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    signed_in(client, role="Event Coordinator Lead")
    cursor.fetchall.return_value = []

    # Act (When)
    response = client.get(path)

    # Assert (Then)
    assert response.status_code == 200
    query, _ = cursor.execute.call_args.args
    assert NOT_DRAFT in query


def test_coordinator_cannot_open_a_draft_by_id(setup):
    """
    Summary: Even a view-all role gets 404 for a draft's ID.
    AC1: Given an Event Organiser has entered some (not necessarily all) event
        details, when they choose "Save as Draft," then the request is stored
        with status 'Draft' and is not visible to any Event Coordinator.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = draft_row()

    # Act (When)
    response = client.get(
        f"/events/{DRAFT_ID}?coordinatorId={COORDINATOR_ID}&viewerRole=Event+Coordinator+Lead"
    )

    # Assert (Then)
    assert response.status_code == 404


# AC2 ---------------------------------------------------------------------


def test_draft_list_returns_only_the_organisers_drafts(setup):
    """
    Summary: Every draft the organiser owns is listed separately.
    AC2: Given an Event Organiser has multiple existing drafts, each draft can
        be opened and edited independently of the others.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchall.return_value = [draft_row(), draft_row(event_id=OTHER_DRAFT_ID, event_name="Gala")]

    # Act (When)
    response = client.get(f"/events/drafts?organiserId={ORGANISER_ID}")

    # Assert (Then)
    assert response.status_code == 200
    assert [event["id"] for event in response.json["events"]] == [DRAFT_ID, OTHER_DRAFT_ID]
    query, params = cursor.execute.call_args.args
    assert "organiser_id = %s AND status = 'Draft'" in query
    assert params == [ORGANISER_ID]


def test_editing_a_draft_updates_only_that_draft(setup):
    """
    Summary: Saving one draft writes that draft's row alone and keeps it a 'Draft'.
    AC2: Given an Event Organiser has multiple existing drafts, each draft can
        be opened and edited independently of the others.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [draft_row(), draft_row(event_name="Renamed", expected_attendance=40)]

    # Act (When)
    response = client.patch(
        f"/events/drafts/{DRAFT_ID}",
        json={"organiserId": ORGANISER_ID, "eventName": "Renamed", "expectedAttendance": "40"},
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["eventName"] == "Renamed"
    assert response.json["status"] == "Draft"
    query, params = cursor.execute.call_args.args
    assert 'UPDATE public."Event"' in query
    assert "submission_date = NULL" in query
    assert "WHERE event_id = %s" in query
    assert params[0] == "Renamed"
    assert params[4] == 40
    assert params[-2:] == ["Draft", DRAFT_ID]


def test_cannot_edit_a_request_that_is_no_longer_a_draft(setup):
    """
    Summary: Once submitted, the request is out of the draft flow.
    AC2: Given an Event Organiser has multiple existing drafts, each draft can
        be opened and edited independently of the others.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = draft_row(status="Submitted")

    # Act (When)
    response = client.patch(
        f"/events/drafts/{DRAFT_ID}", json={"organiserId": ORGANISER_ID, "eventName": "Renamed"}
    )

    # Assert (Then)
    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_DRAFT"
    assert cursor.execute.call_count == 1  # the locking read only


# AC3 ---------------------------------------------------------------------


def test_deleting_a_draft_permanently_removes_it(setup):
    """
    Summary: The row is deleted, so it can no longer appear in the draft list.
    AC3: Given an Event Organiser owns a draft, when they delete it, it is
        permanently removed and no longer appears in their draft list.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, connection, cursor = setup
    cursor.fetchone.return_value = draft_row()

    # Act (When)
    response = client.delete(f"/events/drafts/{DRAFT_ID}?organiserId={ORGANISER_ID}")

    # Assert (Then)
    assert response.status_code == 204
    query, params = cursor.execute.call_args.args
    assert 'DELETE FROM public."Event"' in query
    assert "status = 'Draft'" in query
    assert params == [DRAFT_ID]
    connection.__exit__.assert_called_once()


def test_deleting_a_missing_draft_returns_404(setup):
    """
    Summary: A draft that's already gone can't be deleted twice.
    AC3: Given an Event Organiser owns a draft, when they delete it, it is
        permanently removed and no longer appears in their draft list.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    # Act (When)
    response = client.delete(f"/events/drafts/{DRAFT_ID}?organiserId={ORGANISER_ID}")

    # Assert (Then)
    assert response.status_code == 404


def test_draft_delete_cannot_remove_a_submitted_request(setup):
    """
    Summary: Deleting is for drafts only; a submitted request is never removed this way.
    AC3: Given an Event Organiser owns a draft, when they delete it, it is
        permanently removed and no longer appears in their draft list.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.return_value = draft_row(status="Submitted")

    # Act (When)
    response = client.delete(f"/events/drafts/{DRAFT_ID}?organiserId={ORGANISER_ID}")

    # Assert (Then)
    assert response.status_code == 409
    assert cursor.execute.call_count == 1


# AC4 ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("get", f"/events/{DRAFT_ID}?organiserId={OTHER_ORGANISER_ID}", None),
        ("patch", f"/events/drafts/{DRAFT_ID}", {"organiserId": OTHER_ORGANISER_ID, "eventName": "Mine now"}),
        ("delete", f"/events/drafts/{DRAFT_ID}?organiserId={OTHER_ORGANISER_ID}", None),
        ("post", f"/events/drafts/{DRAFT_ID}/submit", {"organiserId": OTHER_ORGANISER_ID, **COMPLETE}),
    ],
    ids=["get_f_events_draft_id_organiserid_other_organise", "patch_f_events_drafts_draft_id_organiserid_other", "delete_f_events_drafts_draft_id_organiserid_othe", "post_f_events_drafts_draft_id_submit_organiserid"],
)
def test_another_organiser_cannot_view_edit_delete_or_submit_a_draft(setup, method, path, body):
    """
    Summary: Someone else's draft is refused before anything is written.
    AC4: Drafts are visible only to the Event Organiser who created them; no
        other role can view or edit someone else's draft.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = draft_row()

    response = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)

    assert response.status_code == 403
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize(
    "method, path",
    [
        ("post", "/events/drafts"),
        ("get", "/events/drafts"),
        ("patch", f"/events/drafts/{DRAFT_ID}"),
        ("post", f"/events/drafts/{DRAFT_ID}/submit"),
        ("delete", f"/events/drafts/{DRAFT_ID}"),
    ],
    ids=["post_events_drafts", "get_events_drafts", "patch_f_events_drafts_draft_id", "post_f_events_drafts_draft_id_submit", "delete_f_events_drafts_draft_id"],
)
def test_draft_requests_without_a_signed_in_organiser_are_refused(setup, method, path):
    """
    Summary: A draft is only ever reached as a signed-in organiser's own (SCRUM-8).
    SCRUM-8 AC1: Given a system user has not been successfully authenticated,
        when they attempt to access protected information or functionality,
        then access is denied.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    _, _, cursor = setup
    client = setup[0].application.test_client()

    # Act (When)
    response = getattr(client, method)(path, json={"organiserId": ORGANISER_ID, **COMPLETE})

    # Assert (Then)
    assert response.status_code == 401
    cursor.execute.assert_not_called()


def test_lead_cannot_assign_a_coordinator_to_a_draft(setup):
    """
    Summary: A Lead can't reach a draft through assignment either.
    AC4: Drafts are visible only to the Event Organiser who created them; no
        other role can view or edit someone else's draft.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    client, _, cursor = setup
    cursor.fetchone.return_value = {"coordinator_id": None, "status": "Draft"}

    response = client.patch(
        f"/events/{DRAFT_ID}",
        json={"assignedCoordinatorId": COORDINATOR_ID, "assignedBy": OTHER_ORGANISER_ID},
    )

    assert response.status_code == 404
    assert cursor.execute.call_count == 1


# AC5 ---------------------------------------------------------------------


def test_submitting_a_complete_draft_moves_it_to_submitted(setup):
    """
    Summary: The draft becomes 'Submitted' with a submission time, which takes it out of the draft list (that list only selects status 'Draft').
    AC5: Given an Event Organiser has opened one of their drafts, when they
        choose "Submit Request", then the request is checked against the
        required-field and format rules as a new submission. If it passes, its
        status changes from 'Draft' to 'Submitted', its submission time is
        recorded, and it no longer appears in their draft list. If any required
        details are missing or invalid, the submission is refused, the missing
        or invalid fields are listed, and the request stays a 'Draft' with its
        saved details unchanged.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        draft_row(),
        draft_row(status="Submitted", submission_date=datetime(2026, 10, 21, 2, tzinfo=UTC),
                  preferred_start_date=datetime(2030, 6, 2, 9, 15, tzinfo=UTC),
                  preferred_end_date=datetime(2030, 6, 2, 12, 45, tzinfo=UTC)),
    ]

    # Act (When)
    response = client.post(
        f"/events/drafts/{DRAFT_ID}/submit", json={"organiserId": ORGANISER_ID, **COMPLETE}
    )

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["status"] == "Submitted"
    assert response.json["submittedAt"] == "2026-10-21T02:00:00+00:00"
    query, params = next(call.args for call in cursor.execute.call_args_list if 'UPDATE public."Event"' in call.args[0])
    assert "submission_date = now()" in query
    assert params[-2:] == ["Submitted", DRAFT_ID]


def test_submitting_an_incomplete_draft_lists_missing_fields_and_keeps_it_a_draft(setup):
    """
    Summary: The same required-field rules as a new submission; nothing is written.
    AC5: Given an Event Organiser has opened one of their drafts, when they
        choose "Submit Request", then the request is checked against the
        required-field and format rules as a new submission. If it passes, its
        status changes from 'Draft' to 'Submitted', its submission time is
        recorded, and it no longer appears in their draft list. If any required
        details are missing or invalid, the submission is refused, the missing
        or invalid fields are listed, and the request stays a 'Draft' with its
        saved details unchanged.
    Double: Stub (cursor returns canned rows), Mock (execute calls asserted)
    """
    # Arrange (Given)
    client, _, cursor = setup

    # Act (When)
    response = client.post(
        f"/events/drafts/{DRAFT_ID}/submit",
        json={"organiserId": ORGANISER_ID, "eventName": "Community Workshop"},
    )

    # Assert (Then)
    assert response.status_code == 400
    assert "Description" in response.json["missingFields"]
    assert "Expected Attendance" in response.json["missingFields"]
    cursor.execute.assert_not_called()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


@pytest.mark.parametrize(
    "method, path",
    [
        ("post", "/events/drafts"),
        ("get", f"/events/drafts?organiserId={ORGANISER_ID}"),
        ("patch", f"/events/drafts/{DRAFT_ID}"),
        ("post", f"/events/drafts/{DRAFT_ID}/submit"),
        ("delete", f"/events/drafts/{DRAFT_ID}?organiserId={ORGANISER_ID}"),
    ],
    ids=["post_events_drafts", "get_f_events_drafts_organiserid_organiser_id", "patch_f_events_drafts_draft_id", "post_f_events_drafts_draft_id_submit", "delete_f_events_drafts_draft_id_organiserid_orga"],
)
def test_draft_requests_fail_loudly_without_a_database(method, path):
    """
    Summary: A draft is never reported as saved when there is nowhere to store it.
    Supporting design check: an Event Service with no database configured
        answers 503
    Double: None
    """
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client(), role="Event Organiser")

    response = getattr(client, method)(path, json={"organiserId": ORGANISER_ID, **COMPLETE})

    assert response.status_code == 503
