"""Event change display contract; service-local, with no outbound I/O."""
from datetime import datetime
from zoneinfo import ZoneInfo

LABELS = {
    "eventName": "Event Name", "description": "Description", "purpose": "Purpose",
    "registrationNeeds": "Registration Needs", "preferredStartDate": "Start Date/Time",
    "preferredEndDate": "End Date/Time", "expectedAttendance": "Expected Attendance",
    "venueRequirements": "Venue Requirements", "equipmentRequirements": "Equipment Requirements",
    "accessibilityNeeds": "Accessibility Needs",
}


def change_message(kind, source):
    if kind == "event.cancelled":
        return f"{source['eventName']} was cancelled."
    if kind in ("event.change-request-approved", "event.change-request-rejected"):
        name = source["eventName"]
        if source.get("previousEventName"):
            name += f" (formerly {source['previousEventName']})"
        if kind == "event.change-request-approved":
            return f"Change request for {name} was approved."
        return f"Change request for {name} was rejected: {source['reason']}"
    changes = []
    for field, label in LABELS.items():
        if field not in source["proposedChanges"]:
            continue
        value = source["proposedChanges"][field]
        if field in ("preferredStartDate", "preferredEndDate"):
            stamp = datetime.fromisoformat(value)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=ZoneInfo("Asia/Singapore"))
            value = stamp.astimezone(ZoneInfo("Asia/Singapore")).strftime("%d %b %Y, %H:%M SGT")
        changes.append(f"{label}: {value}")
    return f"Change requested for {source['eventName']}. Proposed changes: {'; '.join(changes)}."
