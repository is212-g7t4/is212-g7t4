"""Registration action display contract, pure and service-local."""

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
    return (
        f"Registration confirmed for {name}. Date/time: {stamp(source['startDateTime'])} – "
        f"{stamp(source['endDateTime'])}. Venue: {source['venueName']}. "
        f"Registration reference: {source['registrationId']}."
    )
