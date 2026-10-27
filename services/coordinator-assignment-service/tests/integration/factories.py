"""Synthetic downstream payload builders for coordinator assignment tests."""

LEAD_ID = "33333333-3333-4333-8333-333333333333"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OTHER_COORDINATOR_ID = "22222222-2222-4222-8222-222222222222"
ORGANISER_ID = "44444444-4444-4444-8444-444444444444"
EVENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def user(user_id=COORDINATOR_ID, role="Event Coordinator", username="Coordinator One"):
    return {
        "user_id": user_id,
        "username": username,
        "email": f"{username.lower().replace(' ', '.')}@example.com",
        "role": role,
        "organization": "ConnectSphere",
        "contact_details": "+65 6000 0000",
    }


def lead():
    return user(LEAD_ID, "Event Coordinator Lead", "Lead User")


def event(**overrides):
    result = {
        "id": EVENT_ID,
        "eventName": "Community Workshop",
        "organiserId": ORGANISER_ID,
        "preferredStartDate": "2030-03-01T09:00:00+08:00",
        "preferredEndDate": "2030-03-01T17:00:00+08:00",
        "submittedAt": "2030-02-01T10:00:00+08:00",
        "status": "Submitted",
        "coordinatorId": None,
        "assignedBy": None,
        "assignedAt": None,
        "previousCoordinatorId": None,
    }
    result.update(overrides)
    return result
