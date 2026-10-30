"""Save an Event Request as a draft, AC1–AC5. Database calls are mocked; no live database writes.

AC1  Saving some (not necessarily all) details stores the request as 'Draft',
     not visible to any Event Coordinator.
AC2  Each of an organiser's drafts can be opened and edited independently.
AC3  Deleting a draft removes it permanently from the organiser's draft list.
AC4  Only the organiser who created a draft can view or edit it.
AC5  Submitting a completed draft applies the full submission rules and moves
     it to 'Submitted'; an incomplete one is refused and stays a 'Draft'.
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
    return signed_in(app.test_client()), connection, cursor


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


def test_ac1_save_as_draft_stores_partial_details_with_status_draft(setup):
    """AC1: only a name is entered; the request is stored as 'Draft' with no submission time."""
    client, _, cursor = setup
    cursor.fetchone.return_value = draft_row()

    response = client.post(
        "/events/drafts",
        json={"organiserId": ORGANISER_ID, "eventName": "Community Workshop", "expectedAttendance": ""},
    )

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
)
def test_ac1_save_as_draft_rejects_missing_name_or_malformed_fields(setup, details, problem):
    """AC1: a draft needs a name, and any detail it does have must be well formed."""
    client, _, cursor = setup

    response = client.post("/events/drafts", json={"organiserId": ORGANISER_ID, **details})

    assert response.status_code == 400
    assert any(problem in item for item in response.json["missingFields"] + response.json["errors"])
    cursor.execute.assert_not_called()


def test_ac1_save_as_draft_rejects_a_body_that_is_not_an_object(setup):
    """AC1: nothing is stored from a request that isn't a set of event details."""
    client, _, cursor = setup

    response = client.post("/events/drafts", json=["Community Workshop"])

    assert response.status_code == 400
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    "method, path",
    [
        ("post", "/events/drafts"),
        ("get", f"/events/drafts?organiserId={ORGANISER_ID}"),
        ("patch", f"/events/drafts/{DRAFT_ID}"),
        ("post", f"/events/drafts/{DRAFT_ID}/submit"),
        ("delete", f"/events/drafts/{DRAFT_ID}?organiserId={ORGANISER_ID}"),
    ],
)
def test_ac1_draft_requests_fail_loudly_without_a_database(method, path):
    """AC1: a draft is never reported as saved when there is nowhere to store it."""
    client = signed_in(create_app({"TESTING": True, "DATABASE_URL": None}).test_client())

    response = getattr(client, method)(path, json={"organiserId": ORGANISER_ID, **COMPLETE})

    assert response.status_code == 503


@pytest.mark.parametrize(
    "path",
    [
        f"/events?coordinatorId={COORDINATOR_ID}&viewerRole=Event+Coordinator+Lead",
        "/events/active",
        f"/events/summaries?ids={DRAFT_ID}",
    ],
)
def test_ac1_coordinator_event_lists_exclude_drafts(setup, path):
    """AC1: the coordinator-facing lists that aren't already status-filtered leave drafts out."""
    client, _, cursor = setup
    signed_in(client, role="Event Coordinator Lead")
    cursor.fetchall.return_value = []

    response = client.get(path)

    assert response.status_code == 200
    query, _ = cursor.execute.call_args.args
    assert NOT_DRAFT in query


def test_ac1_coordinator_cannot_open_a_draft_by_id(setup):
    """AC1: even a view-all role gets 404 for a draft's ID."""
    client, _, cursor = setup
    cursor.fetchone.return_value = draft_row()

    response = client.get(
        f"/events/{DRAFT_ID}?coordinatorId={COORDINATOR_ID}&viewerRole=Event+Coordinator+Lead"
    )

    assert response.status_code == 404


# AC2 ---------------------------------------------------------------------


def test_ac2_draft_list_returns_only_the_organisers_drafts(setup):
    """AC2: every draft the organiser owns is listed separately."""
    client, _, cursor = setup
    cursor.fetchall.return_value = [draft_row(), draft_row(event_id=OTHER_DRAFT_ID, event_name="Gala")]

    response = client.get(f"/events/drafts?organiserId={ORGANISER_ID}")

    assert response.status_code == 200
    assert [event["id"] for event in response.json["events"]] == [DRAFT_ID, OTHER_DRAFT_ID]
    query, params = cursor.execute.call_args.args
    assert "organiser_id = %s AND status = 'Draft'" in query
    assert params == [ORGANISER_ID]


def test_ac2_editing_a_draft_updates_only_that_draft(setup):
    """AC2: saving one draft writes that draft's row alone and keeps it a 'Draft'."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [draft_row(), draft_row(event_name="Renamed", expected_attendance=40)]

    response = client.patch(
        f"/events/drafts/{DRAFT_ID}",
        json={"organiserId": ORGANISER_ID, "eventName": "Renamed", "expectedAttendance": "40"},
    )

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


def test_ac2_cannot_edit_a_request_that_is_no_longer_a_draft(setup):
    """AC2: once submitted, the request is out of the draft flow."""
    client, _, cursor = setup
    cursor.fetchone.return_value = draft_row(status="Submitted")

    response = client.patch(
        f"/events/drafts/{DRAFT_ID}", json={"organiserId": ORGANISER_ID, "eventName": "Renamed"}
    )

    assert response.status_code == 409
    assert response.json["code"] == "EVENT_NOT_DRAFT"
    assert cursor.execute.call_count == 1  # the locking read only


# AC3 ---------------------------------------------------------------------


def test_ac3_deleting_a_draft_permanently_removes_it(setup):
    """AC3: the row is deleted, so it can no longer appear in the draft list."""
    client, connection, cursor = setup
    cursor.fetchone.return_value = draft_row()

    response = client.delete(f"/events/drafts/{DRAFT_ID}?organiserId={ORGANISER_ID}")

    assert response.status_code == 204
    query, params = cursor.execute.call_args.args
    assert 'DELETE FROM public."Event"' in query
    assert "status = 'Draft'" in query
    assert params == [DRAFT_ID]
    connection.__exit__.assert_called_once()


def test_ac3_deleting_a_missing_draft_returns_404(setup):
    """AC3: a draft that's already gone can't be deleted twice."""
    client, _, cursor = setup
    cursor.fetchone.return_value = None

    response = client.delete(f"/events/drafts/{DRAFT_ID}?organiserId={ORGANISER_ID}")

    assert response.status_code == 404


def test_ac3_draft_delete_cannot_remove_a_submitted_request(setup):
    """AC3: deleting is for drafts only; a submitted request is never removed this way."""
    client, _, cursor = setup
    cursor.fetchone.return_value = draft_row(status="Submitted")

    response = client.delete(f"/events/drafts/{DRAFT_ID}?organiserId={ORGANISER_ID}")

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
)
def test_ac4_another_organiser_cannot_view_edit_delete_or_submit_a_draft(setup, method, path, body):
    """AC4: someone else's draft is refused before anything is written."""
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
)
def test_ac4_draft_requests_without_a_signed_in_organiser_are_refused(setup, method, path):
    """AC4: a draft is only ever reached as a signed-in organiser's own (SCRUM-8)."""
    _, _, cursor = setup
    client = setup[0].application.test_client()

    response = getattr(client, method)(path, json={"organiserId": ORGANISER_ID, **COMPLETE})

    assert response.status_code == 401
    cursor.execute.assert_not_called()


def test_ac4_lead_cannot_assign_a_coordinator_to_a_draft(setup):
    """AC4: a Lead can't reach a draft through assignment either."""
    client, _, cursor = setup
    cursor.fetchone.return_value = {"coordinator_id": None, "status": "Draft"}

    response = client.patch(
        f"/events/{DRAFT_ID}",
        json={"assignedCoordinatorId": COORDINATOR_ID, "assignedBy": OTHER_ORGANISER_ID},
    )

    assert response.status_code == 404
    assert cursor.execute.call_count == 1


# AC5 ---------------------------------------------------------------------


def test_ac5_submitting_a_complete_draft_moves_it_to_submitted(setup):
    """AC5: the draft becomes 'Submitted' with a submission time, which takes it out
    of the draft list (that list only selects status 'Draft')."""
    client, _, cursor = setup
    cursor.fetchone.side_effect = [
        draft_row(),
        draft_row(status="Submitted", submission_date=datetime(2026, 10, 21, 2, tzinfo=UTC),
                  preferred_start_date=datetime(2030, 6, 2, 9, 15, tzinfo=UTC),
                  preferred_end_date=datetime(2030, 6, 2, 12, 45, tzinfo=UTC)),
    ]

    response = client.post(
        f"/events/drafts/{DRAFT_ID}/submit", json={"organiserId": ORGANISER_ID, **COMPLETE}
    )

    assert response.status_code == 200
    assert response.json["status"] == "Submitted"
    assert response.json["submittedAt"] == "2026-10-21T02:00:00+00:00"
    query, params = next(call.args for call in cursor.execute.call_args_list if 'UPDATE public."Event"' in call.args[0])
    assert "submission_date = now()" in query
    assert params[-2:] == ["Submitted", DRAFT_ID]


def test_ac5_submitting_an_incomplete_draft_lists_missing_fields_and_keeps_it_a_draft(setup):
    """AC5: the same required-field rules as a new submission; nothing is written."""
    client, _, cursor = setup

    response = client.post(
        f"/events/drafts/{DRAFT_ID}/submit",
        json={"organiserId": ORGANISER_ID, "eventName": "Community Workshop"},
    )

    assert response.status_code == 400
    assert "Description" in response.json["missingFields"]
    assert "Expected Attendance" in response.json["missingFields"]
    cursor.execute.assert_not_called()
