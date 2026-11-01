"""SCRUM-43 Review and process event change requests: integration tests.

Story:      As an Event Coordinator, I want to review and process change
            requests for events I manage, so that I can assess the impact of
            changes and approve or reject them appropriately.
Real:       Flask routes, validation, app/models.py SQL, PostgreSQL 17.6 and
            the complete migration chain.
Doubled:    nothing (Event Service is atomic and makes no outbound calls).
Not proven: Event Workflow Service's cross-service venue/equipment impact
            checks; those are covered in that service's own test suite.

AC1  Only pending requests for events assigned to the coordinator are listed.
AC2  A listed request includes current/original event values, proposed values,
     reason and request timestamp. Attachments are intentionally out of scope.
AC3  Approval updates the Event and records Approved, reviewer and review time
     on the request in the same database transaction.
AC4  Rejection requires and stores a reason, records Rejected, reviewer and
     review time, and leaves the Event unchanged.
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


@pytest.fixture
def client(locked_client):
    """These routes are only for other services, which always send the shared token (SCRUM-10)."""
    locked_client.environ_base["HTTP_X_INTERNAL_TOKEN"] = "synthetic"
    return locked_client

REASON = "More guests accepted the invitation."


@pytest.fixture(autouse=True)
def users(db):
    make_user(db, ORGANISER_ID)
    make_user(db, OTHER_ORGANISER_ID)
    make_user(db, COORDINATOR_ID, role="Event Coordinator")
    make_user(db, LEAD_ID, role="Event Coordinator")


def reviewable_event(db, **overrides):
    values = {
        "status": "Under Review",
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


def internal_headers(client):
    token = client.application.config.get("INTERNAL_SERVICE_TOKEN")
    return {"X-Internal-Token": token} if token else {}


def submit_request(client, event_id, changes=None, reason=REASON):
    return client.post(
        f"/events/{event_id}/change-requests",
        json={
            "organiserId": ORGANISER_ID,
            "changes": changes or {"expectedAttendance": "40"},
            "reason": reason,
        },
    )


def decide(client, change_id, decision, reason=None, coordinator_id=COORDINATOR_ID):
    body = {"coordinatorId": coordinator_id, "decision": decision}
    if reason is not None:
        body["reason"] = reason
    return client.patch(
        f"/change-requests/{change_id}/decision",
        json=body,
        headers=internal_headers(client),
    )


def assert_recent(moment, db):
    assert timedelta(0) <= db.now() - moment < timedelta(minutes=1)


def metadata(row):
    return json.loads(row["description"])


def test_ac1_ac2_list_contains_only_pending_requests_for_managed_events(client, db):
    """Normal: the assigned coordinator sees comparison and request context."""
    event_id = reviewable_event(db)
    submitted = submit_request(client, event_id)
    assert submitted.status_code == 201

    other_event_id = reviewable_event(
        db,
        coordinator_id=LEAD_ID,
        organiser_id=OTHER_ORGANISER_ID,
        event_name="Someone else's event",
    )
    other = client.post(
        f"/events/{other_event_id}/change-requests",
        json={
            "organiserId": OTHER_ORGANISER_ID,
            "changes": {"expectedAttendance": "50"},
            "reason": "Their own reason",
        },
    )
    assert other.status_code == 201

    response = client.get(
        f"/change-requests?coordinatorId={COORDINATOR_ID}",
        headers=internal_headers(client),
    )

    assert response.status_code == 200
    requests = response.get_json()["changeRequests"]
    assert len(requests) == 1
    change = requests[0]
    assert change["id"] == submitted.get_json()["id"]
    assert change["status"] == "Pending Review"
    assert change["requestedBy"] == ORGANISER_ID
    assert change["reason"] == REASON
    assert change["proposedChanges"] == {"expectedAttendance": "40"}
    assert change["event"]["id"] == event_id
    assert change["event"]["eventName"] == "Community Workshop"
    assert change["event"]["expectedAttendance"] == "25"
    assert_recent(datetime.fromisoformat(change["requestedAt"]), db)


def test_ac1_another_coordinator_cannot_read_or_decide_the_request(client, db):
    """Authorization: assignment is enforced on both read and decision paths."""
    event_id = reviewable_event(db)
    change_id = submit_request(client, event_id).get_json()["id"]
    before = db.event(event_id)

    details = client.get(
        f"/change-requests/{change_id}?coordinatorId={LEAD_ID}",
        headers=internal_headers(client),
    )
    decision = decide(client, change_id, "Approved", coordinator_id=LEAD_ID)

    assert details.status_code == 403
    assert decision.status_code == 403
    assert db.event(event_id) == before
    assert db.change_request(change_id)["status"] == "Pending Review"


def test_ac3_approval_updates_event_and_records_auditable_decision(client, db):
    """Normal: event update and Approved audit record commit together."""
    event_id = reviewable_event(db)
    submitted = submit_request(
        client,
        event_id,
        changes={
            "expectedAttendance": "40",
            "description": "Updated description",
        },
    )
    change_id = submitted.get_json()["id"]

    response = decide(client, change_id, "Approved")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "Approved"
    assert body["reviewedBy"] == COORDINATOR_ID
    assert body["rejectionReason"] is None
    assert body["event"]["expectedAttendance"] == "40"
    assert body["event"]["description"] == "Updated description"

    event = db.event(event_id)
    request = db.change_request(change_id)
    assert event["expected_attendance"] == 40
    assert metadata(event)["description"] == "Updated description"
    assert request["status"] == "Approved"
    assert str(request["reviewed_by"]) == COORDINATOR_ID
    assert request["rejection_reason"] is None
    assert_recent(request["review_date"], db)

    pending = client.get(
        f"/change-requests?coordinatorId={COORDINATOR_ID}",
        headers=internal_headers(client),
    )
    assert pending.get_json()["changeRequests"] == []
    assert decide(client, change_id, "Approved").status_code == 409


def test_ac4_rejection_requires_reason_and_preserves_event(client, db):
    """Boundary/normal: blank reason writes nothing; a valid reason is audited."""
    event_id = reviewable_event(db)
    change_id = submit_request(
        client,
        event_id,
        changes={"description": "Proposed description"},
    ).get_json()["id"]
    before = db.event(event_id)

    refused = decide(client, change_id, "Rejected", reason="   ")

    assert refused.status_code == 400
    assert db.event(event_id) == before
    pending = db.change_request(change_id)
    assert pending["status"] == "Pending Review"
    assert pending["reviewed_by"] is None
    assert pending["review_date"] is None

    rejection_reason = "The proposed attendance cannot be supported."
    response = decide(client, change_id, "Rejected", reason=f"  {rejection_reason}  ")

    assert response.status_code == 200
    assert response.get_json()["status"] == "Rejected"
    assert response.get_json()["rejectionReason"] == rejection_reason
    assert db.event(event_id) == before
    rejected = db.change_request(change_id)
    assert rejected["status"] == "Rejected"
    assert rejected["rejection_reason"] == rejection_reason
    assert str(rejected["reviewed_by"]) == COORDINATOR_ID
    assert_recent(rejected["review_date"], db)
