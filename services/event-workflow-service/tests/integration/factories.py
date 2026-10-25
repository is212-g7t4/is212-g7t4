"""Synthetic owner HTTP responses using app/outbox.py and User username contracts."""
from uuid import uuid4

EVENT = "30000000-0000-4000-8000-000000000001"
ORGANISER = "10000000-0000-4000-8000-000000000001"
ALICE = "10000000-0000-4000-8000-000000000002"
BOB = "10000000-0000-4000-8000-000000000003"


def make_job(kind="approval", coordinator=ALICE):
    source = dict(eventId=EVENT, eventName="Community Workshop", recipientId=ORGANISER)
    if kind == "coordinator-assignment":
        source["coordinatorId"] = coordinator
    else:
        source["decision"] = "Approved" if kind == "approval" else "Rejected"
        if kind == "rejection":
            source["reason"] = "Needs accessible transport.\nPlease revise."
    return dict(id=str(uuid4()), type="event." + kind, source=source, envelope=None,
                createdAt="2030-01-01T00:00:00+00:00", leaseToken=str(uuid4()), attempts=1)


def expected_envelope(job, name="Synthetic Alice"):
    source = job["source"]
    if job["type"] == "event.coordinator-assignment":
        details = {**source, "coordinatorName": name}
        message = name + " has been assigned to coordinate Community Workshop."
    elif job["type"] == "event.approval":
        details = source.copy()
        message = "Community Workshop was approved"
    else:
        details = source.copy()
        message = "Community Workshop was rejected: Needs accessible transport.\nPlease revise."
    return dict(version=1, id=job["id"], type=job["type"], recipientId=ORGANISER,
                createdAt=job["createdAt"], message=message,
                destination=dict(kind="event-details",eventId=EVENT), details=details)
