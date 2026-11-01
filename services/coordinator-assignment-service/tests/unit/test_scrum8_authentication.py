"""
SCRUM-8: User Authentication and Authorization

User Story
----------
As a system user, I want to securely access the system, so that I can use the
information and functionality available to me.

Acceptance Criteria
-------------------
AC1: Given a system user has not been successfully authenticated, when they
     attempt to access protected information or functionality, then access is
     denied.
AC2: Given a system user successfully authenticates, when they access protected
     information or functionality, then their access is evaluated according to
     their role and relationship to the relevant event.
AC3: Given a system user's authentication attempt is unsuccessful, when the
     authentication attempt is completed, then they remain unable to access
     protected information or functionality.

Real
----
- app.auth.authenticate(): bearer parsing, ES256 signature, expiry, audience
  and subject checks, the ignoring of X-Internal-Token and old developer
  headers, and the fail-closed paths run for real in front of a real
  create_app(); the identity check proves the caller is taken from the token,
  never from the body or headers.
- Assertions are on the HTTP status and the message the caller sees.

Doubled
-------
- Supabase JWKS: Stub (tests/conftest.py) - signing_key returns a throwaway
  ES256 public key so tokens can be minted locally.
- get_available_coordinators: Stub (the `client` fixture) - returns [], but is
  never reached because every request in those tests is stopped at sign-in.
- get_assignment_events, get_active_events, assign_event_coordinator, get_user:
  Mock (tests/conftest.py `downstream`) - asserted not called when a request
  has no token, or asserted on which user is looked up.
- jwt.PyJWKClient: Mock - verifies the JWKS URL built from SUPABASE_URL.
- httpx.get / httpx.patch: Stub - record the headers each client function sends
  downstream.

Not proven
----------
- That tokens issued by the real Supabase project verify against its live JWKS
  (-> E2E journeys J5/J6, which sign in for real through the UI).
- That the custom_access_token_hook really puts user_role in the token (-> E2E
  journeys J5/J6).
"""

import time
from unittest.mock import MagicMock

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app import clients, create_app
from app.auth import signing_key as real_signing_key
from tests.unit.factories import TEST_SIGNING_KEY, bearer

USER_ID = "e7334aa9-eb3a-4c45-84b5-280501b6c109"


@pytest.fixture
def client(monkeypatch):
    from app import create_app

    monkeypatch.setattr("app.routes.get_available_coordinators", lambda: [])
    return create_app().test_client()


@pytest.mark.parametrize(
    "method,path",
    [("get", "/queue"), ("get", "/workload"), ("post", "/events/EVT-1/assign-coordinator/user-1")],
    ids=["queue", "workload", "assign"],
)
def test_internal_token_when_lead_action_requested_returns_401(client, method, path):
    """
    Summary: GET /queue, GET /workload and POST assign-coordinator carrying only
        an X-Internal-Token header (no Authorization) are each answered 401, so
        the header is ignored on every Lead route.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Stub (the `client` fixture: get_available_coordinators returns [],
        never reached; Supabase signing key via conftest, never reached)
    """
    # Arrange (Given): client, method, path, from fixtures

    # Act (When)
    response = getattr(client, method)(path, headers={"X-Internal-Token": "internal-test-token"})

    # Assert (Then)
    assert response.status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no-header"),
        pytest.param({"Authorization": "Basic abc"}, id="basic-scheme"),
        pytest.param({"Authorization": "Bearer"}, id="bearer-without-token"),
        pytest.param({"Authorization": "Bearer "}, id="bearer-blank-token"),
        pytest.param({"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Event Coordinator"}, id="dev-identity-headers"),
    ],
)
def test_authenticate_without_bearer_token_returns_401_sign_in_message(client, headers):
    """
    Summary: GET /coordinators with no Authorization header, a "Basic" scheme,
        "Bearer" with no or a blank token, or only X-Dev-User-Id/X-Dev-Role
        headers is answered 401 {"message": "Sign in to continue."}.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Stub (the `client` fixture: get_available_coordinators returns [],
        never reached; Supabase signing key via conftest, never reached)
    """
    # Arrange (Given): client, headers, from fixtures

    # Act (When)
    response = client.get("/coordinators", headers=headers)

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


@pytest.mark.parametrize("path", ["/queue", "/workload"], ids=["queue", "workload"])
def test_authenticate_when_lead_view_requested_without_token_returns_401_without_fetching(downstream, path):
    """
    Summary: GET /queue and GET /workload with no Authorization header are each
        answered 401 and neither get_assignment_events nor get_active_events is
        called.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Mock (get_assignment_events and get_active_events, via the
        downstream fixture, asserted not called)
    """
    # Arrange (Given): downstream, from fixtures

    # Act (When)
    response = create_app().test_client().get(path)

    # Assert (Then)
    assert response.status_code == 401
    downstream.queue.assert_not_called()
    downstream.active.assert_not_called()


def test_authenticate_when_assign_requested_without_token_returns_401_without_saving(downstream):
    """
    Summary: POST assign-coordinator with no Authorization header (and an
        actingUserId in the body) is answered 401 and assign_event_coordinator
        is never called.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Mock (assign_event_coordinator, via the downstream fixture, asserted
        not called)
    """
    # Arrange (Given): downstream, from fixtures

    # Act (When)
    response = create_app().test_client().post(
        "/events/EVT-001/assign-coordinator/user-coordinator", json={"actingUserId": "user-lead"}
    )

    # Assert (Then)
    assert response.status_code == 401
    downstream.assign.assert_not_called()


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(bearer(USER_ID, "Event Coordinator", key=ec.generate_private_key(ec.SECP256R1())), id="forged-signature"),
        pytest.param(bearer(USER_ID, "Event Coordinator", exp=int(time.time()) - 60), id="expired"),
        pytest.param(bearer(USER_ID, "Event Coordinator", aud="anon"), id="wrong-audience"),
        pytest.param({"Authorization": "Bearer not-a-jwt"}, id="malformed"),
        pytest.param(
            {"Authorization": "Bearer " + jwt.encode({"aud": "authenticated", "exp": int(time.time()) + 60}, TEST_SIGNING_KEY, algorithm="ES256")},
            id="missing-subject",
        ),
        pytest.param(
            {"Authorization": "Bearer " + jwt.encode({"sub": USER_ID, "aud": "authenticated"}, TEST_SIGNING_KEY, algorithm="ES256")},
            id="missing-expiry",
        ),
        pytest.param({"X-Internal-Token": "internal-test-token", "Authorization": "Bearer not-a-jwt"}, id="malformed-with-internal-token"),
    ],
)
def test_authenticate_with_invalid_token_returns_401_session_expired(client, headers):
    """
    Summary: GET /coordinators with a Bearer token that is signed by the wrong
        key, expired, issued for audience "anon", not a JWT, validly signed but
        with no "sub" or no "exp" claim, or a malformed token sent alongside an
        X-Internal-Token, is answered 401 {"message": "Your session is invalid or
        has expired. Sign in again."}.
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality.
    Double: Stub (Supabase signing key via conftest trusts only TEST_SIGNING_KEY;
        the `client` fixture's get_available_coordinators returns [], never
        reached)
    """
    # Arrange (Given): client, headers, from fixtures

    # Act (When)
    response = client.get("/coordinators", headers=headers)

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Your session is invalid or has expired. Sign in again."}


def test_authenticate_with_blank_subject_returns_401():
    """
    Summary: Calling authenticate() directly with a validly signed token whose
        "sub" is "" returns a 401, so no handler sees an empty user id.
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality.
    Double: Stub (Supabase signing key via conftest); no create_app(), routes or
        downstream calls involved
    """
    from flask import Flask

    from app.auth import authenticate

    with Flask(__name__).test_request_context("/anything", headers=bearer("", "Attendee")):
        response, status = authenticate()

    assert status == 401


def test_authenticate_when_supabase_url_missing_returns_503(client, monkeypatch):
    """
    Summary: GET /coordinators with a valid Lead token is answered 503 when
        SUPABASE_URL is unset, rather than letting the request through.
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality. (fail closed when sign-in
        cannot be checked)
    Double: Stub (SUPABASE_URL removed with monkeypatch.delenv; the `client`
        fixture's get_available_coordinators returns [], never reached)
    """
    # Arrange (Given)
    monkeypatch.delenv("SUPABASE_URL")

    # Act + Assert (When / Then)
    assert client.get("/coordinators", headers=bearer(USER_ID, "Event Coordinator")).status_code == 503


def test_authenticate_when_jwks_unreachable_returns_503(client, monkeypatch):
    """
    Summary: GET /coordinators with a valid Lead token is answered 503 when
        signing_key raises PyJWKClientConnectionError, rather than letting the
        request through.
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality. (fail closed when the signing
        keys cannot be fetched)
    Double: Stub (app.auth.signing_key raises PyJWKClientConnectionError("down");
        the `client` fixture's get_available_coordinators returns [], never
        reached)
    """
    # Arrange (Given)
    def unreachable(token):
        raise jwt.PyJWKClientConnectionError("down")

    monkeypatch.setattr("app.auth.signing_key", unreachable)

    # Act + Assert (When / Then)
    assert client.get("/coordinators", headers=bearer(USER_ID, "Event Coordinator")).status_code == 503


def test_authenticate_when_token_key_not_in_jwks_returns_401(client, monkeypatch):
    """
    Summary: GET /coordinators with a Bearer token whose key id is not in
        Supabase's published keys (the real auth.signing_key raises
        PyJWKClientError) is answered 401 {"message": "Your session is invalid
        or has expired. Sign in again."}, not 500 or 503.
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality. (a token signed by an unknown
        key is a failed sign-in, unlike an unreachable JWKS, which is a 503)
    Double: Stub (the conftest signing-key stub is switched back to the real
        auth.signing_key; auth._jwks_client is replaced so its
        get_signing_key_from_jwt raises PyJWKClientError("Unable to find a
        signing key that matches"); the `client` fixture's
        get_available_coordinators returns [], never reached)
    """
    # Arrange (Given)
    unknown_key = MagicMock()
    unknown_key.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientError("Unable to find a signing key that matches")
    monkeypatch.setattr("app.auth.signing_key", real_signing_key)
    monkeypatch.setattr("app.auth._jwks_client", lambda url: unknown_key)

    # Act (When)
    response = client.get("/coordinators", headers=bearer(USER_ID, "Event Coordinator"))

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Your session is invalid or has expired. Sign in again."}


def test_signing_key_fetches_key_from_supabase_jwks_url(monkeypatch):
    """
    Summary: auth.signing_key("token") builds a PyJWKClient for
        {SUPABASE_URL}/auth/v1/.well-known/jwks.json (trailing slash trimmed),
        asks it for the key of that token, and returns that key.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied. (a token only counts if it verifies against Supabase's
        published keys)
    Double: Mock (jwt.PyJWKClient is replaced with a factory that records the
        URL and returns a MagicMock whose get_signing_key_from_jwt is asserted)
    """
    jwks = MagicMock()
    created = []
    monkeypatch.setattr("app.auth.jwt.PyJWKClient", lambda url: created.append(url) or jwks)
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test/")

    key = real_signing_key("token")

    assert created == ["https://project.supabase.test/auth/v1/.well-known/jwks.json"]
    jwks.get_signing_key_from_jwt.assert_called_once_with("token")
    assert key is jwks.get_signing_key_from_jwt.return_value.key


DOWNSTREAM_CALLS = [
    pytest.param("get", lambda: clients.get_active_events(), id="get_active_events"),
    pytest.param("get", lambda: clients.get_assignment_events(), id="get_assignment_events"),
    pytest.param("get", lambda: clients.get_available_coordinators(), id="get_available_coordinators"),
    pytest.param("get", lambda: clients.get_user("user-1"), id="get_user"),
    pytest.param("patch", lambda: clients.assign_event_coordinator("EVT-1", "user-1"), id="assign_event_coordinator"),
]


def stub_downstream(monkeypatch, http_method):
    """Replace httpx.<http_method> with a 200 reply that every client function can parse."""
    reply = httpx.Response(200, json={"events": [], "users": []}, request=httpx.Request("GET", "http://downstream.test"))
    stub = MagicMock(return_value=reply)
    monkeypatch.setattr(clients.httpx, http_method, stub)
    return stub


@pytest.mark.parametrize("http_method,call", DOWNSTREAM_CALLS)
def test_downstream_call_inside_request_forwards_callers_token(monkeypatch, http_method, call):
    """
    Summary: Each client function (get_active_events, get_assignment_events,
        get_available_coordinators, get_user, assign_event_coordinator), called
        inside a request that carries an Authorization header, sends exactly
        that header on every httpx call it makes.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event. (the
        downstream service sees the same signed-in user to evaluate)
    Double: Stub (httpx.get or httpx.patch is replaced and answers 200 with
        empty events and users; the headers of every call are inspected)
    """
    stub = stub_downstream(monkeypatch, http_method)

    with create_app().test_request_context(headers={"Authorization": "Bearer lead-token"}):
        call()

    assert stub.call_args_list
    assert all(c.kwargs["headers"] == {"Authorization": "Bearer lead-token"} for c in stub.call_args_list)


@pytest.mark.parametrize("http_method,call", DOWNSTREAM_CALLS)
def test_downstream_call_outside_request_sends_no_token(monkeypatch, http_method, call):
    """
    Summary: Each client function, called outside any request, sends an empty
        headers dict on every httpx call it makes, so no user's token is
        attached.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event. (a call
        with no user behind it carries no identity to be evaluated)
    Double: Stub (httpx.get or httpx.patch is replaced and answers 200 with
        empty events and users; the headers of every call are inspected)
    """
    stub = stub_downstream(monkeypatch, http_method)

    call()

    assert stub.call_args_list
    assert all(c.kwargs["headers"] == {} for c in stub.call_args_list)


def test_assign_with_acting_user_in_body_checks_token_identity_instead(downstream):
    """
    Summary: POST assign-coordinator with an Event Coordinator token and a body
        naming a different actingUserId looks up the token's "sub" with get_user
        exactly once; the body's id is never used.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event. (the
        caller is the token's user, never one named in the request)
    Double: Mock (get_user, via the downstream fixture, returns None and records
        which user id it is asked about; the response is not asserted on)
    """
    # Arrange (Given)
    downstream.get_user.return_value = None

    # Act (When)
    create_app().test_client().post(
        "/events/EVT-1/assign-coordinator/user-1",
        json={"actingUserId": "someone-else"},
        headers=bearer("e7334aa9-eb3a-4c45-84b5-280501b6c109", "Event Coordinator"),
    )

    # Assert (Then)
    downstream.get_user.assert_called_once_with("e7334aa9-eb3a-4c45-84b5-280501b6c109")
