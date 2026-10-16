"""Closure-only validation. Booking time contracts are unchanged."""

from datetime import datetime, timezone, timedelta
from uuid import UUID


def uuid_value(value):
    if not isinstance(value, str):
        raise ValueError("Expected UUID text.")
    return str(UUID(value))


def timestamp(value):
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("Expected ISO timestamp with explicit offset.")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Explicit timezone offset is required.")
    # Reject instants that cannot be represented in UTC or Singapore output.
    parsed.astimezone(timezone.utc)
    parsed.astimezone(timezone(timedelta(hours=8)))
    return parsed


def create_input(data):
    fields = {"venueId", "startDateTime", "endDateTime", "reason"}
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError("Supply only venueId, startDateTime, endDateTime and reason.")
    venue = uuid_value(data["venueId"])
    start, end = timestamp(data["startDateTime"]), timestamp(data["endDateTime"])
    if end <= start or end <= datetime.now(timezone.utc):
        raise ValueError("End must be after start and server now.")
    reason = data["reason"]
    if not isinstance(reason, str) or not reason.strip() or "\x00" in reason:
        raise ValueError("A nonblank reason without NUL is required.")
    reason.encode("utf-8")  # Reject unpaired surrogates before SQL/HTTP encoding.
    return dict(
        venueId=venue,
        startDateTime=start.isoformat(),
        endDateTime=end.isoformat(),
        reason=reason.strip(),
    )


def confirmation_input(body):
    if not isinstance(body, dict) or body.get("confirmed") is not True:
        raise ValueError("Explicit confirmation is required.")
    token = body.get("confirmationToken")
    if not isinstance(token, str) or not token or len(token) > 256:
        raise ValueError("A preview confirmationToken is required.")
    data = create_input(
        {k: v for k, v in body.items() if k not in {"confirmed", "confirmationToken"}}
    )
    return data, token


def list_input(args):
    import base64
    import json

    if set(args) - {"venueId", "limit", "cursor"} or any(
        len(args.getlist(k)) != 1 for k in args
    ):
        raise ValueError("Supply each supported query parameter once.")
    venue = uuid_value(args.get("venueId"))
    limit = int(args.get("limit", "50"))
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100.")
    after = None
    if "cursor" in args:
        token = args["cursor"]
        try:
            if not token or len(token) > 1024:
                raise ValueError()
            parts = json.loads(base64.b64decode(token, altchars=b"-_", validate=True))
            if not isinstance(parts, list) or len(parts) != 3 or parts[0] != venue:
                raise ValueError()
            after = (timestamp(parts[1]), uuid_value(parts[2]))
        except (ValueError, TypeError, UnicodeError) as error:
            raise ValueError("Invalid cursor for this venue.") from error
    return venue, limit, after


def encode_cursor(row):
    import base64
    import json

    return base64.urlsafe_b64encode(
        json.dumps([row["venueId"], row["startDateTime"], row["closureId"]]).encode()
    ).decode()
