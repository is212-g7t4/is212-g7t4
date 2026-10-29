"""Shared helpers for Safety Check Service's unit tests."""

import time
from urllib.parse import parse_qsl, urlencode, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from flask.testing import FlaskClient

EVENT_ID = "00000000-0000-0000-0000-000000000001"
COORDINATOR_ID = "11111111-1111-4111-8111-111111111111"
OTHER_COORDINATOR_ID = "22222222-2222-4222-8222-222222222222"
OFFICER_ID = "33333333-3333-4333-8333-333333333333"
BOOKING_ID = "66666666-6666-4666-8666-666666666666"
REQUEST_ID = "77777777-7777-4777-8777-777777777777"
RECORD_ID = "55555555-5555-4555-8555-555555555555"


def booking(status="Approved", booking_id=BOOKING_ID, **overrides):
    """A booking as `venue-availability-service` serialises it."""
    return {
        "id": booking_id,
        "eventId": EVENT_ID,
        "venueId": "88888888-8888-4888-8888-888888888888",
        "requestedStartTime": "2026-11-12T09:00:00",
        "requestedEndTime": "2026-11-12T17:00:00",
        "requiredCapacity": 120,
        "venueRequirements": "Stage and projector",
        "status": status,
        "requestedBy": COORDINATOR_ID,
        "reviewedBy": None,
        **overrides,
    }


def equipment_request(status="Approved", request_id=REQUEST_ID, **overrides):
    """An equipment request as `equipment-request-service` serialises it."""
    return {
        "id": request_id,
        "eventId": EVENT_ID,
        "equipmentId": "99999999-9999-4999-8999-999999999999",
        "quantityRequested": 2,
        "technicalRequirements": "Two wireless mics",
        "status": status,
        "reviewedBy": None,
        **overrides,
    }


def event(status="Approved", **overrides):
    """Only the fields this composite reads from Event Service.

    The editable details are here because SCRUM-153's re-check compares the
    `changes` it is given against the event's current values before
    withdrawing anything.
    """
    return {
        "id": EVENT_ID,
        "eventName": "Community Workshop",
        "status": status,
        "coordinatorId": COORDINATOR_ID,
        "description": "A workshop for the community.",
        "purpose": "Skills sharing.",
        "preferredStartDate": "2026-11-10T09:00:00",
        "preferredEndDate": "2026-11-10T12:00:00",
        "expectedAttendance": "120",
        "venueRequirements": "Hall A",
        "equipmentRequirements": "Two microphones",
        "accessibilityNeeds": "Step-free access",
        "registrationNeeds": "Name and email",
        "actionHistory": [],
        **overrides,
    }


def user(role="Safety Officer", user_id=OFFICER_ID, **overrides):
    """A user as `user-service` serialises it."""
    return {
        "id": user_id,
        "name": "Nurul Huda",
        "role": role,
        **overrides,
    }


def record(round_number=1, status="Pending", **overrides):
    """A round as `safety-check-record-service` serialises it."""
    return {
        "id": RECORD_ID,
        "eventId": EVENT_ID,
        "roundNumber": round_number,
        "submittedBy": COORDINATOR_ID,
        "submittedAt": "2026-11-01T02:30:00+00:00",
        "equipmentPlacementNotes": None,
        "crowdMovementNotes": None,
        "status": status,
        "decidedBy": None,
        "decidedAt": None,
        "remarks": None,
        # SCRUM-153: on every round, null unless its approval was withdrawn.
        "withdrawnAt": None,
        "withdrawnBy": None,
        "withdrawalReason": None,
        "flags": [],
        **overrides,
    }


def venue(venue_id="88888888-8888-4888-8888-888888888888", **overrides):
    """A venue as `venue-service` serialises it (app/models.py::serialize)."""
    return {
        "id": venue_id,
        "name": "Main Hall",
        "location": "Level 1",
        "capacity": 200,
        "facilities": ["projector"],
        "accessibility": "Step-free entry",
        "supportedLayouts": ["Theatre"],
        "status": "Available",
        "setupTimeMinutes": 0,
        "turnaroundTimeMinutes": 0,
        "emergencyAccessDetails": None,
        "knownRestrictions": None,
        "safetyInfoUpdatedBy": None,
        "safetyInfoUpdatedAt": None,
        **overrides,
    }


# Stands in for Supabase's ES256 signing key; the unit conftest makes the
# verifier trust its public half (SCRUM-8).
TEST_SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())


def bearer(user_id, role, key=TEST_SIGNING_KEY, **claims):
    """Authorization header for a signed-in user, as Supabase would issue it."""
    payload = {"sub": user_id, "aud": "authenticated", "exp": int(time.time()) + 3600, "user_role": role}
    payload.update(claims)
    return {"Authorization": f"Bearer {jwt.encode(payload, key, algorithm='ES256')}"}


# The fields these stories use to name who is acting, and that user's role.
ACTOR_FIELDS = {"safetyOfficerId": "Safety Officer", "coordinatorId": "Event Coordinator"}


class ActingClient(FlaskClient):
    """Signs in the user a story names as the actor (SCRUM-8).

    Safety Check Service reads the caller from the token, so an actor field in
    the query or body is taken out of the request and sent as that user's
    bearer token instead.
    """

    def open(self, *args, **kwargs):
        if args and isinstance(args[0], str) and "?" in args[0]:
            parts = urlsplit(args[0])
            kwargs["query_string"] = parse_qsl(parts.query) + list(dict(kwargs.get("query_string") or {}).items())
            args = (parts.path, *args[1:])
        query = dict(kwargs.get("query_string") or {})
        body = kwargs.get("json")
        actor = next(
            (
                (str(source[field]), role)
                for field, role in ACTOR_FIELDS.items()
                for source in (query, body if isinstance(body, dict) else {})
                if source.get(field)
            ),
            None,
        )
        if actor and "Authorization" not in (kwargs.get("headers") or {}):
            kwargs["headers"] = {**(kwargs.get("headers") or {}), **bearer(*actor)}
        if query:
            kwargs["query_string"] = urlencode([(k, v) for k, v in query.items() if k not in ACTOR_FIELDS])
        if isinstance(body, dict):
            kwargs["json"] = {k: v for k, v in body.items() if k not in ACTOR_FIELDS}
        return super().open(*args, **kwargs)


def signed_in(client, user_id="00000000-0000-4000-8000-000000000001", role="Event Coordinator"):
    """Sign this test client in, as the user each request names as its actor (or the default)."""
    client.__class__ = ActingClient
    client.environ_base["HTTP_AUTHORIZATION"] = bearer(user_id, role)["Authorization"]
    return client
