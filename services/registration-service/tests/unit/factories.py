"""Synthetic row/envelope builders for SCRUM-46 owner unit boundaries."""
from datetime import UTC, datetime


import time

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from datetime import datetime, UTC

EVENT = "11111111-1111-4111-8111-111111111111"
USER = "22222222-2222-4222-8222-222222222222"
REF = "33333333-3333-4333-8333-333333333333"
JOB = "44444444-4444-4444-8444-444444444444"
LEASE = "55555555-5555-4555-8555-555555555555"


def row(status="Confirmed"):
    """Return a fresh synthetic Registration row with the requested status.
    Stable event, attendee and full reference IDs make owner identity assertions readable.
    """
    return dict(
        registration_id=REF,
        event_id=EVENT,
        attendee_id=USER,
        registration_date=datetime(2030, 1, 1, tzinfo=UTC),
        status=status,
        withdrawn_at=None,
    )


def outbox_row(kind="registration.confirmed"):
    """Return a fresh claimed, unfrozen owner row for the chosen action type.
    The valid lease is a supplied SQL result, not elapsed PostgreSQL time.
    """
    return dict(
        source_id=JOB,
        type=kind,
        source=dict(eventId=EVENT, recipientId=USER, registrationId=REF),
        envelope=None,
        lease_token=LEASE,
        lease_valid=True,
        attempts=1,
        created_at=datetime(2030, 1, 1, tzinfo=UTC),
    )


def envelope(kind="registration.confirmed", naive=False):
    """Build independent expected action content for one registration reference.
    Confirmation includes the full period and Hall A; withdrawal needs the name.
    naive=True expresses the same Singapore-local period without an offset, while
    False uses UTC. Literals do not call production formatters.
    """
    source = {**outbox_row()["source"], "eventName": "Workshop"}
    if kind == "registration.confirmed":
        source.update(
            startDateTime="2030-03-01T09:00:00"
            if naive
            else "2030-03-01T01:00:00+00:00",
            endDateTime="2030-03-01T17:00:00" if naive else "2030-03-01T09:00:00+00:00",
            venueName="Hall A",
        )
    return dict(
        version=1,
        id=JOB,
        type=kind,
        recipientId=USER,
        createdAt="2030-01-01T00:00:00+00:00",
        destination=dict(kind="attendee-registration", registrationId=REF),
        details=source,
        message=(
            f"Registration confirmed for Workshop. Date/time: 01 Mar 2030, 09:00 SGT – 01 Mar 2030, 17:00 SGT. Venue: Hall A. Registration reference: {REF}."
            if kind == "registration.confirmed"
            else "Registration withdrawn for Workshop."
        ),
    )


# Stands in for Supabase's ES256 signing key; the unit conftest makes the
# verifier trust its public half (SCRUM-8).
TEST_SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())


def bearer(user_id, role, key=TEST_SIGNING_KEY, **claims):
    """Authorization header for a signed-in user, as Supabase would issue it."""
    payload = {"sub": user_id, "aud": "authenticated", "exp": int(time.time()) + 3600, "user_role": role}
    payload.update(claims)
    return {"Authorization": f"Bearer {jwt.encode(payload, key, algorithm='ES256')}"}


def signed_in(client, user_id=USER, role="Attendee"):
    """Send every request from this test client with a signed-in user's token."""
    client.environ_base["HTTP_AUTHORIZATION"] = bearer(user_id, role)["Authorization"]
    return client


EVENT_ID = "25c9fe40-c44d-4d79-8d5d-de66d40c1678"


ATTENDEE_ID = "56b34ab1-92cd-4b35-83c7-f04e176e2bd0"


def registration_row(**overrides):
    row = {
        "registration_id": "9f725c7a-ac3d-4d4a-937a-84db7906be71",
        "event_id": EVENT_ID,
        "attendee_id": None,
        "registration_date": datetime(2026, 9, 13, 1, 15, tzinfo=UTC),
        "status": "Confirmed",
        "withdrawn_at": None,
    }
    row.update(overrides)
    return row


def registration_payload(**overrides):
    payload = {
        "eventId": EVENT_ID,
        "capacity": 30,
    }
    payload.update(overrides)
    return payload
