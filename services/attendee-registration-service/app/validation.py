import re
from datetime import datetime
from zoneinfo import ZoneInfo

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SGT = ZoneInfo("Asia/Singapore")


def validate_registration(data):
    if not isinstance(data, dict):
        return {}, ["Send a JSON object."], []

    cleaned = {
        "eventId": str(data.get("eventId") or "").strip(),
        "attendeeId": str(data.get("attendeeId") or "").strip(),
        "fullName": str(data.get("fullName") or "").strip(),
        "email": str(data.get("email") or "").strip().lower(),
        "organization": str(data.get("organization") or "").strip(),
    }
    missing = [
        label for key, label in (
            ("eventId", "Event"), ("attendeeId", "Attendee"),
            ("fullName", "Full name"), ("email", "Email address"),
        ) if not cleaned[key]
    ]
    errors = []
    if cleaned["email"] and not EMAIL_PATTERN.fullmatch(cleaned["email"]):
        errors.append("Enter a valid email address.")
    return cleaned, errors, missing


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
