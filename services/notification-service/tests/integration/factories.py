"""Synthetic parent rows and SCRUM-45 envelopes; no other service is imported."""
from uuid import uuid4

ORGANISER = "10000000-0000-4000-8000-000000000001"
OTHER = "10000000-0000-4000-8000-000000000002"
EVENT = "30000000-0000-4000-8000-000000000001"
COORDINATOR = "10000000-0000-4000-8000-000000000003"


def make_parents(db):
    for identifier in (ORGANISER, OTHER):
        db.execute('INSERT INTO public."User" (user_id, username, email, role) VALUES (%s,%s,%s,%s)',
                   [identifier, "Synthetic organiser " + identifier[-1], identifier + "@example.com", "Event Organiser"])
    db.execute('INSERT INTO public."Event" (event_id,event_name,organiser_id,status) VALUES (%s,%s,%s,%s)',
               [EVENT, "Accessible Community Workshop", ORGANISER, "Under Review"])


def make_envelope(kind="approval", coordinator="Synthetic Alice", identifier=None):
    details = dict(eventName="Accessible Community Workshop", eventId=EVENT, recipientId=ORGANISER)
    if kind == "coordinator-assignment":
        details.update(coordinatorId=COORDINATOR, coordinatorName=coordinator)
        message = f"{coordinator} has been assigned to coordinate Accessible Community Workshop."
    elif kind == "approval":
        details["decision"] = "Approved"
        message = "Accessible Community Workshop was approved"
    else:
        details.update(decision="Rejected", reason="Needs an accessibility plan.\n交通安排需完善。")
        message = "Accessible Community Workshop was rejected: " + details["reason"]
    return dict(version=1, id=identifier or str(uuid4()), type="event." + kind,
                recipientId=ORGANISER, createdAt="2030-01-01T12:34:56+08:00", message=message,
                destination=dict(kind="event-details", eventId=EVENT), details=details)
