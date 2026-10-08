from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.validation import event_has_started, validate_registration


def test_validation_trims_and_normalizes_input():
    cleaned, errors, missing = validate_registration({
        "eventId": " event ", "attendeeId": " attendee ",
        "fullName": " Adam Yeo ", "email": " ADAM@EXAMPLE.COM ",
        "organization": " External ",
    })
    assert errors == []
    assert missing == []
    assert cleaned["email"] == "adam@example.com"
    assert cleaned["fullName"] == "Adam Yeo"


def test_event_started_handles_singapore_local_time():
    now = datetime(2026, 10, 8, 10, 0, tzinfo=ZoneInfo("Asia/Singapore"))
    assert event_has_started({"preferredStartDate": "2026-10-08T09:00:00"}, now)
    assert not event_has_started({"preferredStartDate": "2026-10-08T11:00:00"}, now)


def test_event_started_requires_a_date():
    with pytest.raises(ValueError):
        event_has_started({})
