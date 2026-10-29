"""Synthetic SCRUM-49 outbox facts; no database, network or production formatter."""

import time

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from typing import Any

EVENT = "20000000-0000-4000-8000-000000000001"
REQUEST = "30000000-0000-4000-8000-000000000001"
COORDINATOR = "10000000-0000-4000-8000-000000000001"
ORGANISER = "10000000-0000-4000-8000-000000000002"
LEAD = "10000000-0000-4000-8000-000000000003"
OTHER_LEAD = "10000000-0000-4000-8000-000000000004"
OUTBOX = "http://event.test/internal/notification-outbox"
CONTEXT = f"http://event.test/internal/events/{EVENT}/notification-context"


def change_job(kind="event.change-request-submitted", role="coordinator", **facts) -> dict[str, Any]:
    """Return a fresh claimed intent matching Event outbox.serialize's wire shape."""
    return dict(
        id="40000000-0000-4000-8000-000000000001", type=kind,
        leaseToken="50000000-0000-4000-8000-000000000001",
        createdAt="2030-03-01T01:00:00+00:00", attempts=1, envelope=None,
        source=dict(eventId=EVENT, eventName="Workshop", recipientRole=role, **facts),
    )


def change_envelope(item, recipient, message):
    """Describe the expected public envelope, with independently supplied literal text."""
    return dict(
        version=1, id=item["id"], type=item["type"], createdAt=item["createdAt"],
        recipientId=recipient, message=message,
        details={**item["source"], "recipientId": recipient},
        destination=(dict(kind="change-request-review", eventId=EVENT, changeRequestId=REQUEST)
                     if item["type"] == "event.change-request-submitted" else
                     dict(kind="event-details", eventId=EVENT)),
    )


# SCRUM-46 synthetic action facts.
ATTENDEE_EVENT = "11111111-1111-4111-8111-111111111111"
ATTENDEE_USER = "22222222-2222-4222-8222-222222222222"
ATTENDEE_REF = "33333333-3333-4333-8333-333333333333"
ATTENDEE_JOB = "44444444-4444-4444-8444-444444444444"

def attendee_job(kind):
    """Return fresh unfrozen claimed work for the supplied Registration/Event action type.
    Independent event, attendee, registration and action UUIDs expose swapped wire fields;
    the returned dictionary is an API double, not a persisted owner record.
    """
    return dict(id=ATTENDEE_JOB,type=kind,createdAt="2030-01-01T00:00:00+00:00",envelope=None,
                source=dict(eventId=ATTENDEE_EVENT,recipientId=ATTENDEE_USER,registrationId=ATTENDEE_REF))


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
