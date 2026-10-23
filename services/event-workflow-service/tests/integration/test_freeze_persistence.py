"""SCRUM-45: As an Event Organiser, I want to receive an in-app notification
when the Lead Coordinator approves or rejects my event request, so that I know
the outcome and who is responsible for coordinating my event.
AC1–AC4/DR4: real PostgreSQL owner API freeze persistence, not mocked readback.
"""
import pytest

from tests.integration.system import ACTOR, HEADERS, ORGANISER, assign_as_lead, wait

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


@pytest.mark.parametrize("kind", ["approval", "rejection", "coordinator-assignment"])
def test_freeze_survives_transaction_and_independent_http_reclaim(system, kind):
    """DR4/AC1–AC4: freeze literal fixture facts through HTTP, release via retry,
    then read a new claim/connection; persisted payload must survive and resist
    a second freeze's replacement, independently of the first response.
    """
    s = system
    if kind == "coordinator-assignment":
        s["sql"]("events", 'UPDATE public."Event" SET coordinator_id=NULL WHERE event_id=%s', (s["event"],))
        result = assign_as_lead(s, ACTOR)
        details = dict(eventId=s["event"], eventName="Community Workshop", recipientId=ORGANISER,
                       coordinatorId=ACTOR, coordinatorName="Synthetic Event Coordinator")
        message = "Synthetic Event Coordinator has been assigned to coordinate Community Workshop."
    else:
        route = "approve" if kind == "approval" else "reject"
        body = dict(coordinatorId=ACTOR)
        if kind == "rejection":
            body["reason"] = "Missing plan"
        result = s["http"]("event-service", "PATCH", f"/events/{s['event']}/{route}", json=body)
        details = dict(eventId=s["event"], eventName="Community Workshop", recipientId=ORGANISER,
                       decision="Approved" if kind == "approval" else "Rejected")
        message = "Community Workshop was approved" if kind == "approval" else "Community Workshop was rejected: Missing plan"
        if kind == "rejection":
            details["reason"] = "Missing plan"
    assert result.status_code == 200, result.text
    def claim():
        response = s["http"]("event-service", "POST", "/internal/notification-outbox/claim", headers=HEADERS, json={})
        assert response.status_code == 200
        return response.json()["jobs"]
    job = claim()[0]
    envelope = dict(version=1, id=job["id"], type="event." + kind, recipientId=ORGANISER,
                    createdAt=job["createdAt"], message=message, details=details,
                    destination=dict(kind="event-details", eventId=s["event"]))
    path = f"/internal/notification-outbox/{job['id']}"
    frozen = s["http"]("event-service", "POST", path + "/freeze", headers=HEADERS,
                       json=dict(leaseToken=job["leaseToken"], envelope=envelope))
    assert frozen.status_code == 200
    assert frozen.json()["envelope"] == envelope
    assert s["http"]("event-service", "POST", path + "/retry", headers=HEADERS,
        json=dict(leaseToken=job["leaseToken"], error="test independent reclaim")).status_code == 200
    reclaimed = wait(claim)[0]
    assert reclaimed["leaseToken"] != job["leaseToken"]
    assert reclaimed["envelope"] == envelope, "New owner transaction must read the saved freeze"
    again = s["http"]("event-service", "POST", path + "/freeze", headers=HEADERS,
        json=dict(leaseToken=reclaimed["leaseToken"], envelope={"replacement": True}))
    assert again.status_code == 200
    assert again.json()["envelope"] == envelope
