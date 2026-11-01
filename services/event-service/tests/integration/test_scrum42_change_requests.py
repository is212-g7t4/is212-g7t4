"""SCRUM-42 Request changes to a submitted event: integration tests.

Story:      As an Event Organiser, I want to request changes to my submitted
            event, so that I can update event details when circumstances change.
Real:       Flask routes, validation, app/models.py SQL, PostgreSQL 17.6 and
            the complete migration chain.
Doubled:    nothing (Event Service is atomic and makes no outbound calls).
Not proven: React rendering. Supporting-document attachments were explicitly
            removed from the agreed story and are not part of this suite.

AC1  The owning organiser can request changes while the event is Submitted,
     Under Review or Approved.
AC2  Draft, Confirmed, Completed, Cancelled and Rejected events are refused.
AC3  Every supported event-detail field can be proposed.
AC4  A non-blank reason/justification is mandatory.
AC5  Removed from scope: no supporting-document attachments.
AC6  Submission creates one linked Pending Review record containing requester,
     timestamp, proposed changes and reason, without changing the Event.
"""

from datetime import datetime, timedelta

import pytest

from tests.integration.factories import (
    COORDINATOR_ID,
    ORGANISER_ID,
    OTHER_ORGANISER_ID,
    SINGAPORE,
    make_event,
    make_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

REASON = "The programme and expected turnout changed."


@pytest.fixture(autouse=True)
def users(db):
    make_user(db, ORGANISER_ID)
    make_user(db, OTHER_ORGANISER_ID)
    make_user(db, COORDINATOR_ID, role="Event Coordinator")


def eligible_event(db, status="Submitted", **overrides):
    values = {
        "status": status,
        "coordinator_id": COORDINATOR_ID,
        "event_name": "Community Workshop",
        "description": "Original description",
        "purpose": "Learning",
        "start": datetime(2030, 3, 1, 9, tzinfo=SINGAPORE),
        "end": datetime(2030, 3, 1, 17, tzinfo=SINGAPORE),
        "expected_attendance": 25,
        "venue_requirements": "Seminar room",
    }
    values.update(overrides)
    return make_event(db, **values)


def request_changes(
    client,
    event_id,
    changes=None,
    reason=REASON,
    organiser_id=ORGANISER_ID,
):
    return client.post(
        f"/events/{event_id}/change-requests",
        json={
            "organiserId": organiser_id,
            "changes": changes or {"expectedAttendance": "40"},
            "reason": reason,
        },
    )


def requests_for_event(db, event_id):
    return db.execute(
        'SELECT * FROM public."EventChangeReq" WHERE event_id = %s ORDER BY request_date',
        [event_id],
    )


@pytest.mark.parametrize("status", ["Submitted", "Under Review", "Approved"])
def test_ac1_owner_can_request_changes_in_each_eligible_status(client, db, status):
    """Normal: every agreed requestable lifecycle state creates a pending row."""
    event_id = eligible_event(db, status=status)

    response = request_changes(client, event_id)

    assert response.status_code == 201
    assert response.get_json()["status"] == "Pending Review"
    assert requests_for_event(db, event_id)[0]["status"] == "Pending Review"


@pytest.mark.parametrize(
    "status",
    ["Draft", "Confirmed", "Completed", "Cancelled", "Rejected"],
)
def test_ac2_non_requestable_statuses_are_refused_without_a_record(client, db, status):
    """Conflict: the prohibited lifecycle states cannot enter this workflow."""
    event_id = eligible_event(db, status=status)
    before = db.event(event_id)

    response = request_changes(client, event_id)

    assert response.status_code == 409
    assert response.get_json()["code"] == "CHANGE_REQUEST_NOT_ALLOWED"
    assert response.get_json()["currentStatus"] == status
    assert requests_for_event(db, event_id) == []
    assert db.event(event_id) == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("eventName", "Community Workshop 2030"),
        ("description", "An updated workshop description"),
        ("purpose", "Learning and networking"),
        ("registrationNeeds", "Online registration required"),
        ("preferredStartDate", "2030-03-01T10:00"),
        ("preferredEndDate", "2030-03-01T18:00"),
        ("expectedAttendance", "40"),
        ("venueRequirements", "Auditorium with movable seating"),
        ("equipmentRequirements", "Projector and two microphones"),
        ("accessibilityNeeds", "Step-free access"),
    ],
)
def test_ac3_each_supported_event_detail_can_be_proposed(client, db, field, value):
    """Normal: every editable detail is persisted in the proposal JSON."""
    event_id = eligible_event(db)

    response = request_changes(client, event_id, changes={field: value})

    assert response.status_code == 201
    assert response.get_json()["proposedChanges"] == {field: value}
    assert requests_for_event(db, event_id)[0]["requested_changes"] == {field: value}


@pytest.mark.parametrize(
    "reason",
    [None, "", "   ", 123],
    ids=["missing", "empty", "whitespace", "not-text"],
)
def test_ac4_reason_is_required_and_invalid_input_writes_nothing(client, db, reason):
    """Failure: no valid justification means no change-request record."""
    event_id = eligible_event(db)
    before = db.event(event_id)

    response = request_changes(client, event_id, reason=reason)

    assert response.status_code == 400
    assert response.get_json()["message"] == "A reason or justification is required."
    assert requests_for_event(db, event_id) == []
    assert db.event(event_id) == before


def test_ac6_pending_record_contains_complete_audit_data_without_updating_event(client, db):
    """Normal: proposal and audit data are written while the Event is untouched."""
    event_id = eligible_event(db)
    before = db.event(event_id)
    changes = {
        "expectedAttendance": "40",
        "description": "Updated description",
        "equipmentRequirements": "Projector",
    }

    response = request_changes(
        client,
        event_id,
        changes=changes,
        reason=f"  {REASON}  ",
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["eventId"] == event_id
    assert body["status"] == "Pending Review"
    assert body["requestedBy"] == ORGANISER_ID
    assert body["proposedChanges"] == changes
    assert body["reason"] == REASON

    row = db.change_request(body["id"])
    assert str(row["event_id"]) == event_id
    assert row["requested_changes"] == changes
    assert row["status"] == "Pending Review"
    assert str(row["requested_by"]) == ORGANISER_ID
    assert row["reason"] == REASON
    assert timedelta(0) <= db.now() - row["request_date"] < timedelta(minutes=1)
    assert row["reviewed_by"] is None
    assert row["review_date"] is None
    assert row["rejection_reason"] is None
    assert db.event(event_id) == before


def test_ac6_only_the_event_owner_can_submit_a_change_request(client, db):
    """Authorization: another organiser cannot create a request for the event."""
    event_id = eligible_event(db)
    before = db.event(event_id)

    response = request_changes(client, event_id, organiser_id=OTHER_ORGANISER_ID)

    assert response.status_code == 403
    assert requests_for_event(db, event_id) == []
    assert db.event(event_id) == before


def test_ac6_only_one_pending_request_can_exist_for_an_event(client, db):
    """Conflict: a second proposal cannot overwrite or duplicate the pending one."""
    event_id = eligible_event(db)
    first = request_changes(client, event_id)
    assert first.status_code == 201

    second = request_changes(
        client,
        event_id,
        changes={"expectedAttendance": "50"},
        reason="A later forecast.",
    )

    assert second.status_code == 409
    assert second.get_json()["code"] == "CHANGE_REQUEST_ALREADY_PENDING"
    rows = requests_for_event(db, event_id)
    assert len(rows) == 1
    assert rows[0]["requested_changes"] == {"expectedAttendance": "40"}
    assert rows[0]["reason"] == REASON


def test_ac6_resending_current_values_is_not_a_change(client, db):
    """Boundary: formatting differences cannot create an empty proposal."""
    event_id = eligible_event(db)
    before = db.event(event_id)

    response = request_changes(
        client,
        event_id,
        changes={"eventName": "  Community Workshop  ", "expectedAttendance": "025"},
    )

    assert response.status_code == 400
    assert requests_for_event(db, event_id) == []
    assert db.event(event_id) == before
