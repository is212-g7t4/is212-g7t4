"""Synthetic Event story row builders; never connect to a database."""
from datetime import UTC, datetime
import json
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from flask.testing import FlaskClient

from app.models import FIELDS

EVENT = '10000000-0000-0000-0000-000000000001'
COORDINATOR = '10000000-0000-0000-0000-000000000002'
ROUND = '10000000-0000-0000-0000-000000000003'
OFFICER = '10000000-0000-0000-0000-000000000004'
HEADERS = {'X-Internal-Service-Token': 'synthetic'}
OUTBOX_HEADERS = {'X-Internal-Token': 'synthetic'}
JOB = '10000000-0000-0000-0000-000000000005'
LEASE = '10000000-0000-0000-0000-000000000006'
OTHER_OFFICER = '10000000-0000-0000-0000-000000000007'


def safety_outbox_row(kind, source):
    """A leased persisted row as returned by app/outbox.py's locking SELECT."""
    return dict(source_id=JOB, type=kind, source=source, envelope=None,
                lease_token=LEASE, lease_valid=True, attempts=1,
                created_at=datetime(2030, 1, 1, tzinfo=UTC))


def safety_envelope(row, message) -> dict[str, Any]:
    """Client contract shape from app/outbox.py; expected text supplied by each case."""
    return dict(version=1, id=JOB, type=row['type'],
                recipientId=row['source']['recipientId'],
                createdAt='2030-01-01T00:00:00+00:00',
                message=message, details=dict(row['source']),
                destination=dict(kind='event-details', eventId=EVENT))


def pending_safety_notification_row(coordinator_id: str | None = COORDINATOR):
    """A pending round, including a nullable legacy coordinator, with no assignment changes."""
    row = safety_notification_row()
    metadata = json.loads(row['description'])
    metadata['actionHistory'] = [dict(status='Pending Safety Check', safetyCheckId=ROUND,
                                      details='Submitted for Operational Safety Check (round 1).')]
    row.update(status='Pending Safety Check', coordinator_id=coordinator_id,
               description=json.dumps(metadata))
    return row



def safety_notification_row() -> dict[str, Any]:
    row = dict.fromkeys(FIELDS.values(), '')
    row.update(event_id=EVENT, event_name='Workshop', status='Approved',
               coordinator_id=COORDINATOR, organiser_id=None, expected_attendance=25,
               submission_date=datetime(2026, 10, 1, tzinfo=UTC),
               preferred_start_date=datetime(2030, 3, 1, 1, tzinfo=UTC),
               preferred_end_date=datetime(2030, 3, 1, 9, tzinfo=UTC),
               description=json.dumps({'_connectsphere': 'event-submission-v1',
                                       'description': 'Workshop', 'purpose': 'Learning'}))
    return row


def baseline_entry(status='Pending Safety Check', start='2030-03-01T09:00:00+08:00',
                   end='2030-03-01T17:00:00+08:00', venue='Hall A', **extra):
    """One actionHistory entry carrying the pre-change attendee facts, as update_event_details writes it."""
    baseline = {key: value for key, value in (('startDateTime', start), ('endDateTime', end)) if value is not None}
    baseline['venueName'] = venue
    return dict(status=status, details='Event details updated.', attendeeBaseline=baseline, **extra)


def approval_entry(round_id=ROUND, **extra):
    """The Safety Officer's approval entry; attendee_baseline stops at it."""
    return dict(status='Confirmed', safetyCheckId=round_id, details='Safety approved.', **extra)


def attendee_summary_row(status, history, start=datetime(2030, 3, 2, 1, tzinfo=UTC),
                         end=datetime(2030, 3, 2, 10, tzinfo=UTC), description=None, **extra):
    """A row as list_attendee_event_summaries selects it; the live window defaults to the *new* 2030-03-02 times."""
    if description is None:
        description = json.dumps({'_connectsphere': 'event-submission-v1', 'description': 'Workshop',
                                  'purpose': 'Learning', 'actionHistory': history})
    row = dict(event_id=EVENT, event_name='Workshop', status=status, coordinator_id=COORDINATOR,
               preferred_start_date=start, preferred_end_date=end, description=description)
    return {**row, **extra}


# Stands in for Supabase's ES256 signing key; the unit conftest makes the
# verifier trust its public half (SCRUM-8).
TEST_SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())


def bearer(user_id, role, key=TEST_SIGNING_KEY, **claims):
    """Authorization header for a signed-in user, as Supabase would issue it."""
    payload = {"sub": user_id, "aud": "authenticated", "exp": int(time.time()) + 3600, "user_role": role}
    payload.update(claims)
    return {"Authorization": f"Bearer {jwt.encode(payload, key, algorithm='ES256')}"}


# The fields these stories use to name who is acting, and that user's role.
ACTOR_FIELDS = {
    "decidedBy": "Safety Officer",
    "assignedBy": "Event Coordinator Lead",
    "coordinatorId": "Event Coordinator",
    "organiserId": "Event Organiser",
}


class ActingClient(FlaskClient):
    """Signs in the user a story names as the actor (SCRUM-8).

    Event Service reads the caller from the token, so an actor field in the
    query or body (`coordinatorId`, `organiserId`, ...) is taken out of the
    request and sent as that user's bearer token instead. `viewerRole` and
    `actorRole` stay in the request (they ask for a view) and set the role.
    """

    def open(self, *args, **kwargs):
        if args and isinstance(args[0], str) and "?" in args[0]:
            parts = urlsplit(args[0])
            kwargs["query_string"] = parse_qsl(parts.query) + list(dict(kwargs.get("query_string") or {}).items())
            args = (parts.path, *args[1:])
        query = dict(kwargs.get("query_string") or {})
        body = kwargs.get("json")
        if body is None and kwargs.get("content_type") == "application/json" and isinstance(kwargs.get("data"), (bytes, str)):
            # Raw bodies (size-limit stories) are sent byte-for-byte; only the actor is read.
            try:
                body = json.loads(kwargs["data"])
            except ValueError:
                body = None
        actor = None
        for field, role in ACTOR_FIELDS.items():
            for source in (query, body if isinstance(body, dict) else {}):
                if actor is None and source.get(field):
                    actor = (str(source[field]), role)
        if actor and "Authorization" not in (kwargs.get("headers") or {}):
            body_role = body.get("actorRole") if isinstance(body, dict) else None
            role = query.get("viewerRole") or body_role or actor[1]
            kwargs["headers"] = {**(kwargs.get("headers") or {}), **bearer(actor[0], role)}
        if query:
            kwargs["query_string"] = urlencode([(k, v) for k, v in query.items() if k not in ACTOR_FIELDS or k == "organiserId"])
        if isinstance(kwargs.get("json"), dict):
            kwargs["json"] = {k: v for k, v in body.items() if k not in ACTOR_FIELDS}
        return super().open(*args, **kwargs)


def signed_in(client, user_id="00000000-0000-4000-8000-000000000001", role="Event Coordinator"):
    """Sign this test client in, as the user each request names as its actor (or the default)."""
    client.__class__ = ActingClient
    client.environ_base["HTTP_AUTHORIZATION"] = bearer(user_id, role)["Authorization"]
    return client
