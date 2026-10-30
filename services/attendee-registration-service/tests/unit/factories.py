"""Shared unit-test helpers (import as `from tests.unit.factories import ...`)."""

import httpx
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import ec


# Stands in for Supabase's ES256 signing key; the unit conftest makes the
# verifier trust its public half (SCRUM-8).
TEST_SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())


def bearer(user_id, role, key=TEST_SIGNING_KEY, **claims):
    """Authorization header for a signed-in user, as Supabase would issue it."""
    payload = {"sub": user_id, "aud": "authenticated", "exp": int(time.time()) + 3600, "user_role": role}
    payload.update(claims)
    return {"Authorization": f"Bearer {jwt.encode(payload, key, algorithm='ES256')}"}


def signed_in(client, user_id="00000000-0000-4000-8000-000000000001", role="Event Coordinator"):
    """Send every request from this test client with a signed-in user's token."""
    client.environ_base["HTTP_AUTHORIZATION"] = bearer(user_id, role)["Authorization"]
    return client


EVENT_ID = "25c9fe40-c44d-4d79-8d5d-de66d40c1678"


ATTENDEE_ID = "56b34ab1-92cd-4b35-83c7-f04e176e2bd0"


def payload(**overrides):
    data = {
        "eventId": EVENT_ID,
    }
    data.update(overrides)
    return data


def confirmed_event(**overrides):
    event = {
        "id": EVENT_ID,
        "eventName": "Community Workshop",
        "status": "Confirmed",
        "preferredStartDate": "2099-11-10T09:00:00+08:00",
        "preferredEndDate": "2099-11-10T12:00:00+08:00",
        "expectedAttendance": "30",
        "venueId": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    }
    event.update(overrides)
    return event


def response(status, body):
    request = httpx.Request("GET", "http://service.test")
    return httpx.Response(status, json=body, request=request)


USER = {
    "user_id": ATTENDEE_ID,
    "username": "Adam Yeo",
    "email": "adam@example.com",
    "organization": "External",
}


def registration(**overrides):
    row = {
        "registration_id": "11111111-1111-4111-8111-111111111111",
        "event_id": EVENT_ID,
        "attendee_id": ATTENDEE_ID,
        "registration_date": "2026-10-08T02:00:00+00:00",
        "status": "Confirmed",
    }
    row.update(overrides)
    return row
