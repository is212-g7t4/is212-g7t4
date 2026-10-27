"""SCRUM-16 Request Amendment on Event Submission: Event Service integration tests.

Story:      As an Event Coordinator, I want to request an amendment on a submitted event
            request assigned to me, so that the Event Organiser can update specific details
            before I decide.
Real:       Flask app and routes, validation, app/models.py SQL, postgres:17.6 with the
            full migration chain.
Doubled:    nothing (Event Service makes no outbound calls).
Not proven: JWT authentication; identity is the coordinatorId / organiserId the caller
            sends. Frontend behaviour, and that Equipment Reservation / Event Workflow keep
            stock held (their own unit tests cover the status list).

AC1  Given an Event Request has status 'Submitted' and is assigned to the current Event
     Coordinator, when they request an amendment, then the status changes to 'Amendment
     Requested', and the Coordinator must specify which field(s) require changes.
AC2  The reason/details for the amendment are stored with the request.
AC3  The Event Organiser can edit only the fields flagged by the Event Coordinator; all
     other submitted fields remain locked.
AC4  Given the Event Organiser resubmits after amending, the status changes back to
     'Submitted', the amendment timestamp is recorded, and the request remains assigned
     to the same Event Coordinator.
AC5  The requesting Event Coordinator's identity and timestamp are recorded for
     auditability.
"""

import json
from datetime import datetime, timedelta

import pytest

from tests.integration.factories import (
    COORDINATOR_ID,
    LEAD_ID,
    ORGANISER_ID,
    OTHER_ORGANISER_ID,
    SINGAPORE,
    make_event,
    make_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

# A second Event Coordinator, for the "not the assigned coordinator" cases.
OTHER_COORDINATOR_ID = "55555555-5555-4555-8555-555555555555"
REASON = "The seminar room is booked that day and 25 is over its limit."
FLAGGED = ["preferredEndDate", "expectedAttendance"]


@pytest.fixture(autouse=True)
def users(db):
    make_user(db, ORGANISER_ID)
    make_user(db, OTHER_ORGANISER_ID)
    make_user(db, COORDINATOR_ID, role="Event Coordinator")
    make_user(db, OTHER_COORDINATOR_ID, role="Event Coordinator")
    make_user(db, LEAD_ID, role="Event Coordinator Lead")


def submitted_event(db, **overrides):
    values = {
        "status": "Under Review",
        "coordinator_id": COORDINATOR_ID,
        "event_name": "Community Workshop",
        "description": "A hands-on workshop",
        "purpose": "Learning",
        "start": datetime(2030, 3, 1, 9, tzinfo=SINGAPORE),
        "end": datetime(2030, 3, 1, 17, tzinfo=SINGAPORE),
        "expected_attendance": 25,
        "venue_requirements": "Seminar room",
    }
    values.update(overrides)
    return make_event(db, **values)


def metadata(row):
    return json.loads(row["description"])


def request_amendment(client, event_id, fields=FLAGGED, reason=REASON, coordinator_id=COORDINATOR_ID):
    return client.patch(
        f"/events/{event_id}/amendment-request",
        json={"coordinatorId": coordinator_id, "fields": fields, "reason": reason},
    )


def resubmit(client, event_id, changes, organiser_id=ORGANISER_ID, note=None):
    body = {"organiserId": organiser_id, "changes": changes}
    if note is not None:
        body["note"] = note
    return client.patch(f"/events/{event_id}/amendment-response", json=body)


def amending_event(client, db, fields=FLAGGED, **overrides):
    event_id = submitted_event(db, **overrides)
    assert request_amendment(client, event_id, fields=fields).status_code == 200
    return event_id


def assert_recent(timestamp, db):
    recorded = datetime.fromisoformat(timestamp)
    assert timedelta(0) <= db.now() - recorded < timedelta(minutes=1)


# AC1 ---------------------------------------------------------------------


def test_ac1_assigned_coordinator_request_moves_event_to_amendment_requested(client, db):
    """Normal: the assigned coordinator's request changes the status, nothing else."""
    event_id = submitted_event(db)
    before = db.event(event_id)

    response = request_amendment(client, event_id)

    assert response.status_code == 200
    assert response.get_json()["status"] == "Amendment Requested"
    row = db.event(event_id)
    assert row["status"] == "Amendment Requested"
    assert str(row["coordinator_id"]) == COORDINATOR_ID
    for column in ("event_name", "preferred_start_date", "preferred_end_date",
                   "expected_attendance", "venue_requirements", "submission_date"):
        assert row[column] == before[column]


def test_ac1_request_without_fields_is_refused_and_event_is_unchanged(client, db):
    """Failure: the coordinator must flag at least one field."""
    event_id = submitted_event(db)
    before = db.event(event_id)

    response = request_amendment(client, event_id, fields=[])

    assert response.status_code == 400
    assert response.get_json()["message"] == "Flag at least one field that needs amending."
    row = db.event(event_id)
    assert row["status"] == before["status"]
    assert row["description"] == before["description"]


def test_ac1_other_coordinator_is_refused_and_event_is_unchanged(client, db):
    """Failure: a coordinator the event isn't assigned to gets 403."""
    event_id = submitted_event(db)
    before = db.event(event_id)

    response = request_amendment(client, event_id, coordinator_id=OTHER_COORDINATOR_ID)

    assert response.status_code == 403
    assert db.event(event_id) == before


def test_ac1_approved_event_cannot_be_sent_for_amendment(client, db):
    """Conflict: once decided, the request can't be sent back."""
    event_id = submitted_event(db, status="Approved")
    before = db.event(event_id)

    response = request_amendment(client, event_id)

    assert response.status_code == 409
    body = response.get_json()
    assert body["code"] == "AMENDMENT_NOT_ALLOWED"
    assert body["currentStatus"] == "Approved"
    assert db.event(event_id) == before


def test_ac1_full_round_trip_then_a_second_amendment(client, db):
    """Normal: request → resubmit → request again leaves one closed and one open round."""
    event_id = amending_event(client, db)
    assert resubmit(client, event_id, {"expectedAttendance": "20"}).status_code == 200

    response = request_amendment(client, event_id, fields=["venueRequirements"])

    assert response.status_code == 200
    row = db.event(event_id)
    assert row["status"] == "Amendment Requested"
    first, second = metadata(row)["amendmentHistory"]
    assert first["resubmittedAt"] is not None
    assert first["changes"] == {"expectedAttendance": {"from": "25", "to": "20"}}
    assert second["fields"] == ["venueRequirements"]
    assert second["resubmittedAt"] is None


# AC2 ---------------------------------------------------------------------


def test_ac2_reason_and_flagged_fields_are_persisted(client, db):
    """Normal: the reason and the (date-paired) flagged fields are stored on the row."""
    event_id = submitted_event(db)

    request_amendment(client, event_id, reason=f"  {REASON}  ")

    amendment = metadata(db.event(event_id))["amendmentHistory"][-1]
    assert amendment["reason"] == REASON
    assert amendment["fields"] == ["preferredStartDate", "preferredEndDate", "expectedAttendance"]


def test_ac2_reason_over_1000_characters_is_refused(client, db):
    """Boundary: 1000 characters is accepted, 1001 is refused and changes nothing."""
    accepted = submitted_event(db)
    refused = submitted_event(db)
    before = db.event(refused)

    assert request_amendment(client, accepted, reason="x" * 1000).status_code == 200
    response = request_amendment(client, refused, reason="x" * 1001)

    assert response.status_code == 400
    assert metadata(db.event(accepted))["amendmentHistory"][-1]["reason"] == "x" * 1000
    assert db.event(refused) == before


# AC3 ---------------------------------------------------------------------


def test_ac3_organiser_can_change_a_flagged_field(client, db):
    """Normal: a flagged column is written with the organiser's value."""
    event_id = amending_event(client, db)

    response = resubmit(client, event_id, {"expectedAttendance": "18"})

    assert response.status_code == 200
    assert response.get_json()["expectedAttendance"] == "18"
    assert db.event(event_id)["expected_attendance"] == 18


def test_ac3_changing_an_unflagged_field_is_refused_and_no_field_changes(client, db):
    """Conflict: one flagged + one unflagged change; neither lands."""
    event_id = amending_event(client, db)
    before = db.event(event_id)

    response = resubmit(
        client, event_id, {"expectedAttendance": "18", "venueRequirements": "Main hall"}
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["code"] == "AMENDMENT_FIELD_LOCKED"
    assert body["lockedFields"] == ["venueRequirements"]
    assert db.event(event_id) == before


def test_ac3_description_amendment_is_saved_in_metadata(client, db):
    """Normal: description lives in the metadata; purpose and the columns are untouched."""
    event_id = amending_event(client, db, fields=["description"])
    before = db.event(event_id)

    response = resubmit(client, event_id, {"description": "A two-part workshop"})

    assert response.status_code == 200
    row = db.event(event_id)
    stored = metadata(row)
    assert stored["description"] == "A two-part workshop"
    assert stored["purpose"] == "Learning"
    for column in ("event_name", "preferred_start_date", "preferred_end_date",
                   "expected_attendance", "venue_requirements"):
        assert row[column] == before[column]


def test_ac3_invalid_amended_dates_are_refused(client, db):
    """Failure: an end before the start is refused and the dates stay as they were."""
    event_id = amending_event(client, db)
    before = db.event(event_id)

    response = resubmit(client, event_id, {"preferredEndDate": "2030-03-01T08:00"})

    assert response.status_code == 400
    assert "Preferred End Date & Time must be after the start." in response.get_json()["errors"]
    row = db.event(event_id)
    assert row["preferred_start_date"] == before["preferred_start_date"]
    assert row["preferred_end_date"] == before["preferred_end_date"]
    assert row["status"] == "Amendment Requested"


def test_ac3_other_organiser_cannot_resubmit(client, db):
    """Failure: only the organiser who submitted the event may amend it."""
    event_id = amending_event(client, db)
    before = db.event(event_id)

    response = resubmit(
        client, event_id, {"expectedAttendance": "18"}, organiser_id=OTHER_ORGANISER_ID
    )

    assert response.status_code == 403
    assert db.event(event_id) == before


# AC4 ---------------------------------------------------------------------


def test_ac4_resubmission_returns_to_submitted_with_the_same_coordinator(client, db):
    """Normal: back to 'Submitted', same coordinator, original submission date."""
    event_id = amending_event(client, db)
    before = db.event(event_id)

    response = resubmit(client, event_id, {"expectedAttendance": "18"})

    assert response.status_code == 200
    assert response.get_json()["coordinatorId"] == COORDINATOR_ID
    row = db.event(event_id)
    assert row["status"] == "Submitted"
    assert str(row["coordinator_id"]) == COORDINATOR_ID
    assert row["submission_date"] == before["submission_date"]


def test_ac4_amendment_timestamp_and_changes_are_recorded(client, db):
    """Normal: who resubmitted, when, the note and a from/to record of each change."""
    event_id = amending_event(client, db)

    resubmit(
        client,
        event_id,
        {"preferredEndDate": "2030-03-01T15:00", "expectedAttendance": "18"},
        note="Shortened the day.",
    )

    amendment = metadata(db.event(event_id))["amendmentHistory"][-1]
    assert amendment["resubmittedBy"] == ORGANISER_ID
    assert_recent(amendment["resubmittedAt"], db)
    assert amendment["note"] == "Shortened the day."
    assert amendment["changes"] == {
        "preferredEndDate": {"from": "2030-03-01T17:00:00", "to": "2030-03-01T15:00:00"},
        "expectedAttendance": {"from": "25", "to": "18"},
    }
    assert db.event(event_id)["preferred_end_date"] == datetime(2030, 3, 1, 15, tzinfo=SINGAPORE)


def test_ac4_event_under_amendment_cannot_be_reassigned(client, db):
    """Conflict: a Lead can't hand the event to another coordinator mid-amendment."""
    event_id = amending_event(client, db)
    before = db.event(event_id)

    response = client.patch(
        f"/events/{event_id}",
        json={"assignedCoordinatorId": OTHER_COORDINATOR_ID, "assignedBy": LEAD_ID},
    )

    assert response.status_code == 409
    row = db.event(event_id)
    assert row["coordinator_id"] == before["coordinator_id"]
    assert row["assigned_by"] == before["assigned_by"]


def test_ac4_resubmitting_twice_is_refused(client, db):
    """Conflict: once resubmitted, the round is closed; a second attempt is 409."""
    event_id = amending_event(client, db)
    assert resubmit(client, event_id, {"expectedAttendance": "18"}).status_code == 200

    response = resubmit(client, event_id, {"expectedAttendance": "12"})

    assert response.status_code == 409
    assert response.get_json()["code"] == "AMENDMENT_NOT_OPEN"
    row = db.event(event_id)
    assert row["expected_attendance"] == 18
    history = metadata(row)["amendmentHistory"]
    assert len(history) == 1
    assert history[0]["resubmittedAt"] is not None


# AC5 ---------------------------------------------------------------------


def test_ac5_requesting_coordinator_identity_and_time_are_recorded(client, db):
    """Normal: requestedBy/requestedAt and an action-history entry are stored."""
    event_id = submitted_event(db)

    request_amendment(client, event_id)

    stored = metadata(db.event(event_id))
    amendment = stored["amendmentHistory"][-1]
    assert amendment["requestedBy"] == COORDINATOR_ID
    assert_recent(amendment["requestedAt"], db)
    action = stored["actionHistory"][-1]
    assert action["status"] == "Amendment Requested"
    assert action["coordinatorId"] == COORDINATOR_ID
    assert action["recordedAt"] == amendment["requestedAt"]


def test_ac5_history_survives_a_later_decision(client, db):
    """Normal: approving after the resubmission keeps the amendment history (real SQL)."""
    event_id = amending_event(client, db)
    assert resubmit(client, event_id, {"expectedAttendance": "18"}).status_code == 200
    history = metadata(db.event(event_id))["amendmentHistory"]

    response = client.patch(
        f"/events/{event_id}/approve", json={"coordinatorId": COORDINATOR_ID}
    )

    assert response.status_code == 200
    row = db.event(event_id)
    assert row["status"] == "Approved"
    assert metadata(row)["amendmentHistory"] == history
    assert response.get_json()["amendmentHistory"] == history
