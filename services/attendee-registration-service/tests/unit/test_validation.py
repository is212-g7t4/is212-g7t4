from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.validation import event_has_started, validate_registration, withdrawal_deadline_has_passed


def test_validation_trims_ids_and_drops_profile_fields():
    cleaned, errors, missing = validate_registration({
        "eventId": " event ",
        "fullName": "Adam Yeo", "email": "adam@example.com",
    })
    assert errors == []
    assert missing == []
    assert cleaned == {"eventId": "event"}


def test_event_started_handles_singapore_local_time():
    now = datetime(2026, 10, 8, 10, 0, tzinfo=ZoneInfo("Asia/Singapore"))
    assert event_has_started({"preferredStartDate": "2026-10-08T09:00:00"}, now)
    assert not event_has_started({"preferredStartDate": "2026-10-08T11:00:00"}, now)
    assert event_has_started(
        {"preferredStartDate": "2026-10-08T09:00:00+08:00"},
        datetime(2026, 10, 8, 10, 0),
    )


def test_event_started_requires_a_date():
    with pytest.raises(ValueError):
        event_has_started({})


def test_withdrawal_deadline_prefers_explicit_cutoff_and_falls_back_to_start():
    now = datetime(2026, 10, 24, 10, 0, tzinfo=ZoneInfo("Asia/Singapore"))
    assert withdrawal_deadline_has_passed({
        "withdrawalDeadline": "2026-10-24T09:00:00+08:00",
        "preferredStartDate": "2026-11-10T09:00:00+08:00",
    }, now)
    assert not withdrawal_deadline_has_passed({
        "withdrawalDeadline": "",
        "preferredStartDate": "2026-11-10T09:00:00",
    }, now)
    assert withdrawal_deadline_has_passed(
        {"preferredStartDate": "2026-10-24T09:00:00+08:00"},
        datetime(2026, 10, 24, 10, 0),
    )


def test_withdrawal_deadline_requires_a_date():
    with pytest.raises(ValueError):
        withdrawal_deadline_has_passed({})
