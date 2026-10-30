"""Supabase Auth JWT verification (SCRUM-8).

Every service carries its own copy of this module: there is no shared library
(AGENTS.md). Supabase signs access tokens with ES256; the public keys come from
the project's JWKS endpoint, so no signing secret is needed here.
"""

import os
from functools import lru_cache

import jwt
from flask import g, jsonify, request

# Added to every access token by public.custom_access_token_hook from public."User".role.
ROLE_CLAIM = "user_role"
PUBLIC_PATHS = {"/health"}


@lru_cache(maxsize=1)
def _jwks_client(supabase_url):
    return jwt.PyJWKClient(f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json")


def signing_key(token):
    return _jwks_client(os.environ["SUPABASE_URL"]).get_signing_key_from_jwt(token).key


def authenticate():
    """before_request: require a Supabase access token.

    Sets g.user_id and g.role for the signed-in user.
    """
    g.user_id = g.role = None
    if request.method == "OPTIONS" or request.path in PUBLIC_PATHS or request.path.startswith("/internal/"):
        return None
    authorization = request.headers.get("Authorization")
    # SCRUM-10: only a signed-in user reaches this service. No background worker calls it, so an
    # internal token alone is not a way in.
    if authorization is None:
        return jsonify(message="Sign in to continue."), 401
    scheme, _, token = authorization.partition(" ")
    if scheme != "Bearer" or not token:
        return jsonify(message="Sign in to continue."), 401
    if not os.getenv("SUPABASE_URL"):
        return jsonify(message="Authentication is not configured."), 503
    try:
        claims = jwt.decode(
            token,
            signing_key(token),
            algorithms=["ES256"],
            audience="authenticated",
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWKClientConnectionError:
        return jsonify(message="Unable to verify your session. Please try again."), 503
    except jwt.PyJWTError:
        return jsonify(message="Your session is invalid or has expired. Sign in again."), 401
    if not claims["sub"]:
        return jsonify(message="Your session is invalid or has expired. Sign in again."), 401
    g.user_id, g.role = claims["sub"], claims.get(ROLE_CLAIM)
    return None
