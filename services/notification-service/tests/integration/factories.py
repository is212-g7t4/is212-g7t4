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


def make_notification_coordinator(db):
    """Insert a synthetic coordinator parent for recipient-scoped inbox tests."""
    db.execute('INSERT INTO public."User" (user_id,username,email,role) VALUES (%s,%s,%s,%s)',
               [COORDINATOR, "Synthetic Coordinator", "coordinator@example.com", "Event Coordinator"])
    return COORDINATOR


def make_change_envelope(kind="submitted", recipient=ORGANISER):
    """Independent SCRUM-49 wire examples, not imported producer formatters."""
    details = dict(eventName="Workshop", eventId=EVENT, recipientId=recipient,
                   recipientRole="coordinator" if kind == "submitted" else "organiser")
    destination = dict(kind="event-details", eventId=EVENT)
    if kind != "cancelled":
        details["changeRequestId"] = "40000000-0000-4000-8000-000000000001"
    if kind == "submitted":
        details["proposedChanges"] = dict(eventName="New Workshop", expectedAttendance="40")
        destination.update(kind="change-request-review", changeRequestId=details["changeRequestId"])
        message = "Change requested for Workshop. Proposed changes: Event Name: New Workshop; Expected Attendance: 40."
    elif kind == "approved":
        details.update(eventName="New Workshop", previousEventName="Workshop", decision="Approved")
        message = "Change request for New Workshop (formerly Workshop) was approved."
    elif kind == "rejected":
        details.update(decision="Rejected", reason="Keep accessible transport.\n交通安排需完善。")
        message = "Change request for Workshop was rejected: " + details["reason"]
    else:
        message = "Workshop was cancelled."
    return dict(version=1, id=str(uuid4()), type="event.cancelled" if kind == "cancelled" else "event.change-request-" + kind,
                recipientId=recipient, createdAt="2026-10-28T01:00:00+00:00", message=message,
                destination=destination, details=details)


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
