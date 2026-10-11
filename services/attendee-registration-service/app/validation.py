from datetime import datetime
from zoneinfo import ZoneInfo

SGT = ZoneInfo("Asia/Singapore")


def validate_registration(data):
    if not isinstance(data, dict):
        return {}, ["Send a JSON object."], []

    # The attendee's name, email and organisation come from their User record,
    # so only the event and attendee are needed.
    cleaned = {
        "eventId": str(data.get("eventId") or "").strip(),
        "attendeeId": str(data.get("attendeeId") or "").strip(),
    }
    missing = [
        label for key, label in (("eventId", "Event"), ("attendeeId", "Attendee"))
        if not cleaned[key]
    ]
    return cleaned, [], missing


def event_has_started(event, now=None):
    raw_start = event.get("preferredStartDate")
    if not raw_start:
        raise ValueError("Event start time is unavailable.")
    start = datetime.fromisoformat(str(raw_start).replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=SGT)
    current = now or datetime.now(SGT)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SGT)
    return start <= current
