"""Calendar-only time handling; existing write input/output stays unchanged."""

from datetime import datetime, timedelta, timezone

SINGAPORE = timezone(timedelta(hours=8))


def parse_boundary(value):
    try:
        if "T" not in value:
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo:
            parsed = parsed.astimezone(SINGAPORE).replace(tzinfo=None)
        return parsed
    except (TypeError, ValueError, OverflowError):
        return None
