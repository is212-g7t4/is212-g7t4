"""SCRUM-46 attendee display contract; local pure functions, no external I/O."""

from datetime import datetime
from zoneinfo import ZoneInfo


def stamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Singapore"))
    return parsed.astimezone(ZoneInfo("Asia/Singapore")).strftime("%d %b %Y, %H:%M SGT")


def attendee_message(kind, source):
    name = source["eventName"]
    if kind == "registration.withdrawn":
        return f"Registration withdrawn for {name}."
    if kind == "attendee.event-cancelled":
        return f"{name} was cancelled."
    if kind == "attendee.event-updated":
        labels = {
            "startDateTime": "Start date/time",
            "endDateTime": "End date/time",
            "venueName": "Venue",
        }
        changes = []
        for field, label in labels.items():
            if field in source["changes"]:
                old, new = source["changes"][field]
                if field != "venueName":
                    old, new = stamp(old), stamp(new)
                changes.append(f"{label}: {old} → {new}")
        return f"{name} was updated. {'; '.join(changes)}."
    return (
        f"Registration confirmed for {name}. Date/time: {stamp(source['startDateTime'])} – "
        f"{stamp(source['endDateTime'])}. Venue: {source['venueName']}. "
        f"Registration reference: {source['registrationId']}."
    )
