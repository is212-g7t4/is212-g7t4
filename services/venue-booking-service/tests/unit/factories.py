"""Shared unit-test helpers (import as `from tests.unit.factories import ...`)."""

import time
from urllib.parse import parse_qsl, urlencode, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from flask.testing import FlaskClient


# Stands in for Supabase's ES256 signing key; the unit conftest makes the
# verifier trust its public half (SCRUM-8).
TEST_SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())


def bearer(user_id, role, key=TEST_SIGNING_KEY, **claims):
    """Authorization header for a signed-in user, as Supabase would issue it."""
    payload = {"sub": user_id, "aud": "authenticated", "exp": int(time.time()) + 3600, "user_role": role}
    payload.update(claims)
    return {"Authorization": f"Bearer {jwt.encode(payload, key, algorithm='ES256')}"}


# The fields these stories use to name who is acting, and that user's role.
ACTOR_FIELDS = {"reviewedBy": "Venue Staff", "coordinatorId": "Event Coordinator"}


class ActingClient(FlaskClient):
    """Signs in the user a story names as the actor (SCRUM-8).

    Venue Booking Service reads the caller from the token, so an actor field in
    the query or body is taken out of the request and sent as that user's
    bearer token instead (unless the request already carries one).
    """

    def open(self, *args, **kwargs):
        query = kwargs.get("query_string") or []
        query = list(query.items()) if isinstance(query, dict) else list(query)
        if args and isinstance(args[0], str) and "?" in args[0]:
            parts = urlsplit(args[0])
            query = parse_qsl(parts.query, keep_blank_values=True) + query
            args = (parts.path, *args[1:])
        body = kwargs.get("json")
        actor = next(
            (
                (str(value), role)
                for field, role in ACTOR_FIELDS.items()
                for key, value in query + list(body.items() if isinstance(body, dict) else [])
                if key == field and value
            ),
            None,
        )
        if actor and "Authorization" not in (kwargs.get("headers") or {}):
            kwargs["headers"] = {**(kwargs.get("headers") or {}), **bearer(*actor)}
        if query:
            kwargs["query_string"] = urlencode([(k, v) for k, v in query if k not in ACTOR_FIELDS])
        if isinstance(body, dict):
            kwargs["json"] = {k: v for k, v in body.items() if k not in ACTOR_FIELDS}
        return super().open(*args, **kwargs)


def signed_in(client, user_id="00000000-0000-4000-8000-000000000001", role="Event Coordinator"):
    """Sign this test client in, as the user each request names as its actor (or the default)."""
    client.__class__ = ActingClient
    client.environ_base["HTTP_AUTHORIZATION"] = bearer(user_id, role)["Authorization"]
    return client
