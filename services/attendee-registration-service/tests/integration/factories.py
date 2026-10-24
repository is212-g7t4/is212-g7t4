"""HTTP response builders for registration-withdrawal integration tests."""

ATTENDEE_ID = "11111111-1111-4111-8111-111111111111"
REGISTRATION_ID = "22222222-2222-4222-8222-222222222222"
EVENT_ID = "33333333-3333-4333-8333-333333333333"


def registration(status="Confirmed"):
    return {
        "registration_id": REGISTRATION_ID,
        "event_id": EVENT_ID,
        "attendee_id": ATTENDEE_ID,
        "registration_date": "2029-12-01T10:00:00+08:00",
        "status": status,
        "withdrawn_at": None,
    }


def event(withdrawal_deadline="2099-03-01T08:00:00+08:00", start="2099-03-01T09:00:00+08:00"):
    return {
        "id": EVENT_ID,
        "eventName": "Community Workshop",
        "preferredStartDate": start,
        "preferredEndDate": "2099-03-01T17:00:00+08:00",
        "withdrawalDeadline": withdrawal_deadline,
        "status": "Confirmed",
    }
