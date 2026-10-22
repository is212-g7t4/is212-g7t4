"""SCRUM-12 Save Event Request as Draft: integration tests, route to real Postgres.

Real: the Flask app and routes, validation, app/models.py SQL, postgres:17.6 with the full
migration chain. Doubled: nothing (Event Service makes no outbound calls). Identity is the
organiserId / coordinatorId the caller sends, as in production today, so these tests prove
the ownership rules given an asserted ID, not authentication.

AC1  Saving some (not necessarily all) details stores the request as 'Draft', not visible
     to any Event Coordinator.
AC2  Each of an organiser's drafts can be opened and edited independently.
AC3  Deleting a draft removes it permanently from the organiser's draft list.
AC4  Only the organiser who created a draft can view or edit it.
AC5  Submitting a draft applies the full submission rules; if it passes it becomes
     'Submitted' with a submission time, otherwise it stays a 'Draft', unchanged.
"""

from datetime import datetime, timedelta

import pytest

from tests.integration.factories import (
    COMPLETE,
    COORDINATOR_ID,
    LEAD_ID,
    ORGANISER_ID,
    OTHER_ORGANISER_ID,
    SINGAPORE,
    UNKNOWN_ID,
    make_event,
    make_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

LEAD = "Event Coordinator Lead"


@pytest.fixture(autouse=True)
def organisers(db):
    make_user(db, ORGANISER_ID)
    make_user(db, OTHER_ORGANISER_ID)


def draft_names(client, organiser_id=ORGANISER_ID):
    response = client.get(f"/events/drafts?organiserId={organiser_id}")
    assert response.status_code == 200
    return [event["eventName"] for event in response.get_json()["events"]]


# AC1 ---------------------------------------------------------------------


def test_saving_only_a_name_stores_a_draft_with_no_submission_time(client, db):
    """SCRUM-12 AC1 (normal): partial details are stored as 'Draft', blanks as NULL."""
    response = client.post("/events/drafts", json={"eventName": "Spring Fair", "organiserId": ORGANISER_ID})

    assert response.status_code == 201
    row = db.event(response.get_json()["id"])
    assert row["status"] == "Draft"
    assert row["submission_date"] is None
    assert str(row["organiser_id"]) == ORGANISER_ID
    assert row["event_name"] == "Spring Fair"
    assert row["preferred_start_date"] is None
    assert row["expected_attendance"] is None
    assert row["venue_requirements"] is None
    assert row["coordinator_id"] is None


@pytest.mark.parametrize(
    ("details", "stored"),
    [
        ({"expectedAttendance": "1"}, {"expected_attendance": 1}),
        (
            {"preferredStartDate": "2030-03-01T09:00", "preferredEndDate": "2030-03-01T09:01"},
            {"preferred_end_date": datetime(2030, 3, 1, 9, 1, tzinfo=SINGAPORE)},
        ),
    ],
    ids=["attendance-of-one", "end-one-minute-after-start"],
)
def test_draft_values_at_the_lower_limit_are_saved(client, db, details, stored):
    """SCRUM-12 AC1 (boundary): the smallest valid attendance and period are accepted."""
    response = client.post("/events/drafts", json={"eventName": "Spring Fair", "organiserId": ORGANISER_ID, **details})

    assert response.status_code == 201
    row = db.event(response.get_json()["id"])
    for column, value in stored.items():
        assert row[column] == value


@pytest.mark.parametrize(
    ("details", "error"),
    [
        ({"expectedAttendance": "0"}, "Expected Attendance must be a positive whole number (maximum 2147483647)."),
        (
            {"preferredStartDate": "2030-03-01T09:00", "preferredEndDate": "2030-03-01T09:00"},
            "Preferred End Date & Time must be after the start.",
        ),
    ],
    ids=["attendance-of-zero", "end-equals-start"],
)
def test_draft_values_just_past_the_limit_are_refused_and_nothing_is_stored(client, db, details, error):
    """SCRUM-12 AC1 (boundary): whatever is filled in must already be valid."""
    response = client.post("/events/drafts", json={"eventName": "Spring Fair", "organiserId": ORGANISER_ID, **details})

    assert response.status_code == 400
    assert response.get_json()["errors"] == [error]
    assert db.event_count() == 0


def test_a_draft_without_a_name_is_refused_and_nothing_is_stored(client, db):
    """SCRUM-12 AC1 (failure): Event Name is the one field a draft needs."""
    response = client.post("/events/drafts", json={"description": "No name yet", "organiserId": ORGANISER_ID})

    assert response.status_code == 400
    assert response.get_json()["missingFields"] == ["Event Name"]
    assert db.event_count() == 0


def test_a_draft_for_an_organiser_who_is_not_a_user_is_refused_and_nothing_is_stored(client, db):
    """SCRUM-12 AC1 (failure): Event.organiser_id has a real foreign key to User.

    Only asserts that it is refused; today it surfaces as a 503 "database connection"
    message, which is reported separately rather than locked in here.
    """
    response = client.post("/events/drafts", json={"eventName": "Spring Fair", "organiserId": UNKNOWN_ID})

    assert response.status_code >= 400
    assert db.event_count() == 0


@pytest.mark.parametrize(
    "path",
    [
        f"/events/submitted?coordinatorId={LEAD_ID}&viewerRole={LEAD}",
        "/events/unassigned",
        "/events/active",
        f"/events?coordinatorId={LEAD_ID}&viewerRole={LEAD}",
    ],
)
def test_coordinator_lists_leave_out_drafts(client, db, path):
    """SCRUM-12 AC1 (visibility): coordinator views list the submitted request, never the draft."""
    make_event(db, status="Draft", event_name="Secret Draft")
    make_event(db, status="Submitted", event_name="Submitted Fair")

    response = client.get(path)

    assert response.status_code == 200
    names = [event["eventName"] for event in response.get_json()["events"]]
    assert names == ["Submitted Fair"]


def test_event_summaries_leave_out_drafts(client, db):
    """SCRUM-12 AC1 (visibility): the cross-service name lookup doesn't reveal drafts either."""
    draft_id = make_event(db, status="Draft", event_name="Secret Draft")
    submitted_id = make_event(db, status="Submitted", event_name="Submitted Fair")

    response = client.get(f"/events/summaries?ids={draft_id},{submitted_id}")

    assert response.status_code == 200
    assert [event["id"] for event in response.get_json()["events"]] == [submitted_id]


def test_a_coordinator_cannot_open_a_draft_by_id(client, db):
    """SCRUM-12 AC1 (visibility): even the Lead, who sees every event, gets 404 for a draft."""
    draft_id = make_event(db, status="Draft")

    response = client.get(f"/events/{draft_id}?coordinatorId={LEAD_ID}&viewerRole={LEAD}")

    assert response.status_code == 404


def test_the_lead_cannot_assign_a_coordinator_to_a_draft(client, db):
    """SCRUM-12 AC1 (conflict): a draft never reaches the coordinator workflow."""
    make_user(db, COORDINATOR_ID, role="Event Coordinator")
    make_user(db, LEAD_ID, role=LEAD)
    draft_id = make_event(db, status="Draft")

    response = client.patch(f"/events/{draft_id}", json={"assignedCoordinatorId": COORDINATOR_ID, "assignedBy": LEAD_ID})

    assert response.status_code == 404
    row = db.event(draft_id)
    assert row["coordinator_id"] is None
    assert row["status"] == "Draft"


# AC2 ---------------------------------------------------------------------


def test_the_draft_list_holds_each_of_the_organisers_drafts_and_nothing_else(client, db):
    """SCRUM-12 AC2 (normal): separate drafts, not submitted requests or other people's."""
    make_event(db, status="Draft", event_name="Winter Gala")
    make_event(db, status="Draft", event_name="Autumn Fair")
    make_event(db, status="Submitted", event_name="Submitted Fair")
    make_event(db, status="Draft", event_name="Someone Else's Draft", organiser_id=OTHER_ORGANISER_ID)

    assert draft_names(client) == ["Autumn Fair", "Winter Gala"]


def test_opening_a_draft_returns_its_saved_details(client, db):
    """SCRUM-12 AC2 (normal): the organiser can open their draft to continue it."""
    draft_id = make_event(db, status="Draft", event_name="Winter Gala", description="Year-end party", expected_attendance=80)

    response = client.get(f"/events/{draft_id}?organiserId={ORGANISER_ID}")

    assert response.status_code == 200
    body = response.get_json()
    assert (body["eventName"], body["description"], body["expectedAttendance"], body["status"]) == (
        "Winter Gala", "Year-end party", "80", "Draft",
    )


def test_editing_one_draft_leaves_the_other_draft_untouched(client, db):
    """SCRUM-12 AC2 (normal): drafts are edited independently."""
    edited_id = make_event(db, status="Draft", event_name="Spring Fair")
    other_id = make_event(db, status="Draft", event_name="Winter Gala", expected_attendance=80)
    other_before = db.event(other_id)

    response = client.patch(
        f"/events/drafts/{edited_id}",
        json={"eventName": "Spring Fair v2", "expectedAttendance": "40", "organiserId": ORGANISER_ID},
    )

    assert response.status_code == 200
    edited = db.event(edited_id)
    assert (edited["event_name"], edited["expected_attendance"]) == ("Spring Fair v2", 40)
    assert (edited["status"], edited["submission_date"]) == ("Draft", None)
    assert db.event(other_id) == other_before


def test_clearing_a_field_when_editing_a_draft_stores_it_as_empty(client, db):
    """SCRUM-12 AC2 (boundary): an edit replaces the draft's details, including blanks."""
    draft_id = make_event(db, status="Draft", venue_requirements="Main hall")

    response = client.patch(
        f"/events/drafts/{draft_id}",
        json={"eventName": "Spring Fair", "venueRequirements": "", "organiserId": ORGANISER_ID},
    )

    assert response.status_code == 200
    assert db.event(draft_id)["venue_requirements"] is None


def test_a_submitted_request_cannot_be_edited_as_a_draft(client, db):
    """SCRUM-12 AC2 (conflict): once submitted, the draft endpoints no longer apply."""
    event_id = make_event(db, status="Submitted")
    before = db.event(event_id)

    response = client.patch(f"/events/drafts/{event_id}", json={"eventName": "Changed", "organiserId": ORGANISER_ID})

    assert response.status_code == 409
    assert response.get_json()["code"] == "EVENT_NOT_DRAFT"
    assert db.event(event_id) == before


# AC3 ---------------------------------------------------------------------


def test_deleting_a_draft_removes_it_permanently(client, db):
    """SCRUM-12 AC3 (normal): the row is gone and the draft list no longer shows it."""
    deleted_id = make_event(db, status="Draft", event_name="Spring Fair")
    make_event(db, status="Draft", event_name="Winter Gala")

    response = client.delete(f"/events/drafts/{deleted_id}?organiserId={ORGANISER_ID}")

    assert response.status_code == 204
    assert db.event(deleted_id) is None
    assert draft_names(client) == ["Winter Gala"]


def test_deleting_a_draft_that_does_not_exist_returns_404(client, db):
    """SCRUM-12 AC3 (failure): an unknown ID, and a second delete of the same draft."""
    draft_id = make_event(db, status="Draft")

    assert client.delete(f"/events/drafts/{UNKNOWN_ID}?organiserId={ORGANISER_ID}").status_code == 404
    assert client.delete(f"/events/drafts/{draft_id}?organiserId={ORGANISER_ID}").status_code == 204
    assert client.delete(f"/events/drafts/{draft_id}?organiserId={ORGANISER_ID}").status_code == 404


def test_a_submitted_request_cannot_be_deleted_through_the_draft_route(client, db):
    """SCRUM-12 AC3 (conflict): only drafts can be deleted here."""
    event_id = make_event(db, status="Submitted")

    response = client.delete(f"/events/drafts/{event_id}?organiserId={ORGANISER_ID}")

    assert response.status_code == 409
    assert db.event(event_id) is not None


# AC4 ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/events/{id}?organiserId=" + OTHER_ORGANISER_ID, None),
        ("patch", "/events/drafts/{id}", {"eventName": "Hijacked", "organiserId": OTHER_ORGANISER_ID}),
        ("delete", "/events/drafts/{id}?organiserId=" + OTHER_ORGANISER_ID, None),
        ("post", "/events/drafts/{id}/submit", {**COMPLETE, "organiserId": OTHER_ORGANISER_ID}),
    ],
    ids=["view", "edit", "delete", "submit"],
)
def test_another_organiser_cannot_touch_someone_elses_draft(client, db, method, path, body):
    """SCRUM-12 AC4 (failure): 403, and the owner's draft is exactly as it was."""
    draft_id = make_event(db, status="Draft")
    before = db.event(draft_id)

    response = getattr(client, method)(path.format(id=draft_id), json=body)

    assert response.status_code == 403
    assert db.event(draft_id) == before


@pytest.mark.parametrize("organiser_id", [None, "not-a-uuid"], ids=["missing", "invalid"])
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/events/drafts", {"eventName": "Spring Fair"}),
        ("get", "/events/drafts", None),
        ("patch", "/events/drafts/{id}", {"eventName": "Changed"}),
        ("delete", "/events/drafts/{id}", None),
        ("post", "/events/drafts/{id}/submit", dict(COMPLETE)),
    ],
    ids=["create", "list", "edit", "delete", "submit"],
)
def test_draft_routes_refuse_a_missing_or_invalid_organiser_id(client, db, method, path, body, organiser_id):
    """SCRUM-12 AC4 (failure): no organiser, no access; nothing is written."""
    draft_id = make_event(db, status="Draft")
    before = db.event(draft_id)
    url = path.format(id=draft_id)
    if body is None:
        url += f"?organiserId={organiser_id}" if organiser_id else ""
    elif organiser_id:
        body = {**body, "organiserId": organiser_id}

    response = getattr(client, method)(url, json=body)

    assert response.status_code == 400
    assert db.event_count() == 1
    assert db.event(draft_id) == before


# AC5 ---------------------------------------------------------------------


def test_submitting_a_complete_draft_moves_it_to_submitted(client, db):
    """SCRUM-12 AC5 (normal): 'Submitted', time recorded, out of the drafts, into the Lead's queue."""
    draft_id = make_event(db, status="Draft", event_name="Community Workshop")

    response = client.post(f"/events/drafts/{draft_id}/submit", json={**COMPLETE, "organiserId": ORGANISER_ID})

    assert response.status_code == 200
    row = db.event(draft_id)
    assert row["status"] == "Submitted"
    assert timedelta(0) <= db.now() - row["submission_date"] < timedelta(minutes=1)
    assert row["expected_attendance"] == 25
    assert row["preferred_start_date"] == datetime(2030, 3, 1, 9, tzinfo=SINGAPORE)
    assert draft_names(client) == []
    unassigned = client.get("/events/unassigned").get_json()["events"]
    assert [event["id"] for event in unassigned] == [draft_id]


def test_submitting_an_incomplete_draft_lists_what_is_missing_and_keeps_it_a_draft(client, db):
    """SCRUM-12 AC5 (failure): refused, fields listed, saved details unchanged."""
    draft_id = make_event(db, status="Draft", event_name="Spring Fair", venue_requirements="Main hall")
    before = db.event(draft_id)

    response = client.post(f"/events/drafts/{draft_id}/submit", json={"eventName": "Spring Fair", "organiserId": ORGANISER_ID})

    assert response.status_code == 400
    assert response.get_json()["missingFields"] == [
        "Description", "Purpose", "Preferred Start Date & Time", "Preferred End Date & Time", "Expected Attendance",
    ]
    assert db.event(draft_id) == before


def test_submitting_a_draft_whose_end_equals_its_start_is_refused(client, db):
    """SCRUM-12 AC5 (boundary): the full format rules apply on submit."""
    draft_id = make_event(db, status="Draft")
    before = db.event(draft_id)

    response = client.post(
        f"/events/drafts/{draft_id}/submit",
        json={**COMPLETE, "preferredEndDate": COMPLETE["preferredStartDate"], "organiserId": ORGANISER_ID},
    )

    assert response.status_code == 400
    assert response.get_json()["errors"] == ["Preferred End Date & Time must be after the start."]
    assert db.event(draft_id) == before


def test_a_request_that_is_already_submitted_cannot_be_submitted_again(client, db):
    """SCRUM-12 AC5 (conflict): 409, and the original submission time stands."""
    event_id = make_event(db, status="Submitted")
    before = db.event(event_id)

    response = client.post(f"/events/drafts/{event_id}/submit", json={**COMPLETE, "organiserId": ORGANISER_ID})

    assert response.status_code == 409
    assert response.get_json()["code"] == "EVENT_NOT_DRAFT"
    assert db.event(event_id) == before
