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
  and subject checks, the internal-token path and the fail-closed paths run for
  real in front of a real create_app(); identity checks prove the caller is
  taken from the token, never from the body or headers.
- Assertions are on the HTTP status and the message the caller sees.

Doubled
-------
- Supabase JWKS: Stub (tests/conftest.py) - signing_key returns a throwaway
  ES256 public key so tokens can be minted locally.
- psycopg2.connect: Stub where a route needs the database - a MagicMock
  connection.
- jwt.PyJWKClient: Mock - verifies the JWKS URL built from SUPABASE_URL.

Not proven
----------
- That tokens issued by the real Supabase project verify against its live JWKS
  (-> E2E journeys J5/J6, which sign in for real through the UI).
- That the custom_access_token_hook really puts user_role in the token (-> E2E
  journeys J5/J6).
"""

import time
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.auth import signing_key as real_signing_key
from tests.unit.factories import TEST_SIGNING_KEY, bearer

USER_ID = "e7334aa9-eb3a-4c45-84b5-280501b6c109"


@pytest.fixture(autouse=True)
def internal_service_token(monkeypatch):
    """The token background workers present as X-Internal-Token."""
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "internal-test-token")


EVENT = "22222222-2222-4222-8222-222222222222"
OTHER = "44444444-4444-4444-8444-444444444444"
ROUND = "55555555-5555-4555-8555-555555555555"
INTERNAL = {"X-Internal-Token": "internal-test-token"}


@pytest.fixture
def client(monkeypatch):
    from app import create_app

    monkeypatch.setattr("app.list_unassigned", lambda *args: [])
    return create_app({"TESTING": True, "DATABASE_URL": "unused-test-url"}).test_client()


@pytest.mark.parametrize(
    "method,path,body,headers",
    [
        ("post", "/events/drafts", {}, INTERNAL),
        ("get", "/events/drafts", None, INTERNAL),
        ("patch", f"/events/drafts/{EVENT}", {}, INTERNAL),
        ("post", f"/events/drafts/{EVENT}/submit", {}, INTERNAL),
        ("delete", f"/events/drafts/{EVENT}", None, INTERNAL),
        ("get", "/events/submitted", None, INTERNAL),
        ("get", f"/events?organiserId={OTHER}", None, INTERNAL),
        ("get", "/events", None, INTERNAL),
        ("get", f"/events/{EVENT}?organiserId={OTHER}", None, INTERNAL),
        ("get", f"/events/{EVENT}", None, INTERNAL),
        ("post", f"/events/{EVENT}/change-requests", {}, INTERNAL),
        ("get", "/change-requests", None, INTERNAL),
        ("get", f"/change-requests/{EVENT}", None, INTERNAL),
        ("patch", f"/change-requests/{EVENT}/decision", {}, INTERNAL),
        ("patch", f"/events/{EVENT}", {"assignedCoordinatorId": OTHER}, INTERNAL),
        ("patch", f"/events/{EVENT}/progress", {}, INTERNAL),
        ("patch", f"/events/{EVENT}/details", {}, INTERNAL),
        (
            "patch",
            f"/events/{EVENT}/safety-status",
            {"status": "Pending Safety Check", "safetyCheckId": ROUND, "roundNumber": 1},
            INTERNAL,
        ),
        (
            "patch",
            f"/events/{EVENT}/safety-status",
            {"status": "Confirmed", "safetyCheckId": ROUND, "roundNumber": 1},
            INTERNAL,
        ),
        ("patch", f"/events/{EVENT}/approve", {}, INTERNAL),
        ("patch", f"/events/{EVENT}/clarification-request", {}, INTERNAL),
        ("patch", f"/events/{EVENT}/clarification-response", {}, INTERNAL),
        ("patch", f"/events/{EVENT}/amendment-request", {}, INTERNAL),
        ("patch", f"/events/{EVENT}/amendment-response", {}, INTERNAL),
        ("patch", f"/events/{EVENT}/reject", {}, INTERNAL),
    ],
    ids=["post_events_drafts_internal", "get_events_drafts_none_internal", "patch_f_events_drafts_event_internal", "post_f_events_drafts_event_submit_internal", "delete_f_events_drafts_event_none_internal", "get_events_submitted_none_internal", "get_f_events_organiserid_other_none_internal", "get_events_none_internal", "get_f_events_event_organiserid_other_none_intern", "get_f_events_event_none_internal", "post_f_events_event_change_requests_internal", "get_change_requests_none_internal", "get_f_change_requests_event_none_internal", "patch_f_change_requests_event_decision_internal", "patch_f_events_event_assignedcoordinatorid_other", "patch_f_events_event_progress_internal", "patch_f_events_event_details_internal", "patch_f_events_event_safety_status_status_pendin", "patch_f_events_event_safety_status_status_confir", "patch_f_events_event_approve_internal", "patch_f_events_event_clarification_request_inter", "patch_f_events_event_clarification_response_inte", "patch_f_events_event_amendment_request_internal", "patch_f_events_event_amendment_response_internal", "patch_f_events_event_reject_internal"],
)
def test_ac1_internal_token_alone_is_refused_with_401_on_every_route_that_acts_for_a_user(client, method, path, body, headers):
    """
    Summary: Each route that acts on behalf of a user (drafts, event views, change requests, assignment, progress, details, safety-status, approve, clarification, amendment, reject) answers 401 "Sign in to continue." when only X-Internal-Token is sent.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Stub (the client fixture replaces app.list_unassigned; no database is reached because authentication refuses first, and the JWKS key is unused since no user token is sent)
    """
    # Arrange (Given): client, method, path, body, headers, from fixtures

    # Act (When)
    response = getattr(client, method)(path, json=body, headers=headers)

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_ac2_saved_draft_belongs_to_the_token_user_whatever_organiser_id_the_body_names(client, monkeypatch):
    """
    Summary: POST /events/drafts as the signed-in organiser with a different organiserId in the body saves the draft under the token's user id, not the body's.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event.
    Double: Stub (JWKS test signing key signs the Event Organiser token), Mock (app.save_draft records its arguments; the owner asserted to be the token's user)
    """
    # Arrange (Given)
    calls = []
    monkeypatch.setattr("app.save_draft", lambda *args: calls.append(args) or {})

    # Act (When)
    response = client.post(
        "/events/drafts", json={"organiserId": OTHER, "eventName": "Draft"}, headers=bearer(USER_ID, "Event Organiser")
    )

    # Assert (Then)
    assert response.status_code == 201
    assert calls[0][1] == USER_ID


def test_ac2_viewing_all_events_depends_on_the_token_role_not_a_viewer_role_query_parameter(client):
    """
    Summary: An Event Coordinator token asking for GET /events?viewerRole=Event+Coordinator+Lead is still answered 403 "This role cannot view all internal events.", so a role named in the query is ignored.
    AC2: Given a system user successfully authenticates, when they access
        protected information or functionality, then their access is evaluated
        according to their role and relationship to the relevant event.
    Double: Stub (JWKS test signing key signs an Event Coordinator token; no database is reached because the role check refuses first)
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get("/events?viewerRole=Event+Coordinator+Lead", headers=bearer(USER_ID, "Event Coordinator"))

    # Assert (Then)
    assert response.status_code == 403
    assert response.json == {"message": "This role cannot view all internal events."}



def test_ac1_request_with_no_token_is_refused_with_a_sign_in_prompt(client):
    """
    Summary: GET /events/unassigned with no Authorization header answers 401 "Sign in to continue."
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None beyond the client fixture (it replaces app.list_unassigned, which is never reached); no token is sent, so the JWKS key is unused
    """
    # Arrange (Given): client, from fixtures

    # Act (When)
    response = client.get("/events/unassigned")

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Sign in to continue."}


def test_ac3_credentials_sent_with_a_non_bearer_scheme_are_refused(client):
    """
    Summary: GET /events/unassigned with "Authorization: Basic abc" answers 401.
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality.
    Double: None beyond the client fixture (it replaces app.list_unassigned, which is never reached); the JWKS key is unused because the scheme is rejected first
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert client.get("/events/unassigned", headers={"Authorization": "Basic abc"}).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(bearer(USER_ID, "Event Coordinator", key=ec.generate_private_key(ec.SECP256R1())), id="forged-signature"),
        pytest.param(bearer(USER_ID, "Event Coordinator", exp=int(time.time()) - 60), id="expired"),
        pytest.param(bearer(USER_ID, "Event Coordinator", aud="anon"), id="wrong-audience"),
        pytest.param({"Authorization": "Bearer not-a-jwt"}, id="malformed"),
    ],
)
def test_ac3_forged_expired_wrong_audience_or_malformed_token_is_refused_as_an_invalid_session(client, headers):
    """
    Summary: GET /events/unassigned with a token signed by another key, an expired token, a token for audience "anon", or a non-JWT string answers 401 "Your session is invalid or has expired. Sign in again."
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality.
    Double: Stub (the JWKS test signing key is the only key that would verify; each case is built to fail against it)
    """
    # Arrange (Given): client, headers, from fixtures

    # Act (When)
    response = client.get("/events/unassigned", headers=headers)

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Your session is invalid or has expired. Sign in again."}


def test_ac3_validly_signed_token_with_no_subject_is_refused(client):
    """
    Summary: A token signed with the test key and the right audience, but carrying no sub claim, gets 401 from GET /events/unassigned.
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality.
    Double: Stub (the JWKS test signing key verifies the token; the missing subject is what is refused)
    """
    # Arrange (Given)
    token = jwt.encode({"aud": "authenticated", "exp": int(time.time()) + 60}, TEST_SIGNING_KEY, algorithm="ES256")

    # Act + Assert (When / Then)
    assert client.get("/events/unassigned", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_ac1_old_developer_identity_headers_without_a_token_are_refused(client):
    """
    Summary: GET /events/unassigned carrying only X-Dev-User-Id and X-Dev-Role headers (no Authorization) answers 401, so those headers cannot stand in for a signed-in user.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: None beyond the client fixture (it replaces app.list_unassigned, which is never reached); no Authorization header is sent, so the JWKS key is unused
    """
    # Arrange (Given)
    headers = {"X-Dev-User-Id": USER_ID, "X-Dev-Role": "Event Coordinator"}

    # Act + Assert (When / Then)
    assert client.get("/events/unassigned", headers=headers).status_code == 401


def test_ac3_a_malformed_user_token_is_refused_even_when_the_internal_token_is_also_sent(client):
    """
    Summary: GET /events/unassigned with the right X-Internal-Token and "Authorization: Bearer not-a-jwt" answers 401, so the internal token cannot rescue a bad user token.
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality.
    Double: Stub (the JWKS test signing key is asked to verify the malformed bearer token, which fails)
    """
    # Arrange (Given)
    headers = {"X-Internal-Token": "internal-test-token", "Authorization": "Bearer not-a-jwt"}

    # Act + Assert (When / Then)
    assert client.get("/events/unassigned", headers=headers).status_code == 401


def test_ac3_a_wrong_internal_token_is_refused(client):
    """
    Summary: GET /events/unassigned with X-Internal-Token "guess" and no Authorization header answers 401.
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality.
    Double: None beyond the client fixture (it replaces app.list_unassigned, which is never reached); the JWKS key is unused because no user token is sent
    """
    # Arrange (Given): client, from fixtures

    # Act + Assert (When / Then)
    assert client.get("/events/unassigned", headers={"X-Internal-Token": "guess"}).status_code == 401


def test_ac3_protected_routes_stay_closed_with_503_when_supabase_url_is_not_configured(client, monkeypatch):
    """
    Summary: With SUPABASE_URL removed, GET /events/unassigned with an otherwise valid Event Coordinator token answers 503 instead of granting access.
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality.
    Double: Stub (the client fixture replaces app.list_unassigned, which is never reached; the JWKS key is not reached because SUPABASE_URL is removed first)
    """
    # Arrange (Given)
    monkeypatch.delenv("SUPABASE_URL")

    # Act + Assert (When / Then)
    assert client.get("/events/unassigned", headers=bearer(USER_ID, "Event Coordinator")).status_code == 503


def test_ac3_protected_routes_stay_closed_with_503_when_the_jwks_cannot_be_fetched(client, monkeypatch):
    """
    Summary: When app.auth.signing_key raises PyJWKClientConnectionError, GET /events/unassigned with a validly signed token answers 503 instead of granting access.
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality.
    Double: Stub (app.auth.signing_key replaced by a function that raises PyJWKClientConnectionError)
    """
    # Arrange (Given)
    def unreachable(token):
        raise jwt.PyJWKClientConnectionError("down")

    monkeypatch.setattr("app.auth.signing_key", unreachable)

    # Act + Assert (When / Then)
    assert client.get("/events/unassigned", headers=bearer(USER_ID, "Event Coordinator")).status_code == 503


def test_ac3_token_whose_key_is_not_in_the_jwks_is_refused_as_an_invalid_session_not_a_server_error(client, monkeypatch):
    """
    Summary: GET /events/unassigned with a token whose key id is not in Supabase's published keys (the real auth.signing_key raises PyJWKClientError) answers 401 "Your session is invalid or has expired. Sign in again.", not 500 or 503.
    AC3: Given a system user's authentication attempt is unsuccessful, when the
        authentication attempt is completed, then they remain unable to access
        protected information or functionality. (a token signed by an unknown
        key is a failed sign-in, unlike an unreachable JWKS, which is a 503)
    Double: Stub (the conftest signing-key stub is switched back to the real auth.signing_key; auth._jwks_client is replaced so its get_signing_key_from_jwt raises PyJWKClientError("Unable to find a signing key that matches"); the client fixture replaces app.list_unassigned, which is never reached)
    """
    # Arrange (Given)
    unknown_key = MagicMock()
    unknown_key.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientError("Unable to find a signing key that matches")
    monkeypatch.setattr("app.auth.signing_key", real_signing_key)
    monkeypatch.setattr("app.auth._jwks_client", lambda url: unknown_key)

    # Act (When)
    response = client.get("/events/unassigned", headers=bearer(USER_ID, "Event Coordinator"))

    # Assert (Then)
    assert response.status_code == 401
    assert response.json == {"message": "Your session is invalid or has expired. Sign in again."}


def test_ac1_assigning_a_coordinator_with_no_token_is_refused_before_any_assignment(client, monkeypatch):
    """
    Summary: PATCH /events/<id> naming an assignedCoordinatorId, with no Authorization header, answers 401 and update_event_coordinator is never called.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Mock (app.update_event_coordinator replaced; asserted never called); no token is sent, so the JWKS key is unused
    """
    # Arrange (Given)
    assign = MagicMock()
    monkeypatch.setattr("app.update_event_coordinator", assign)

    # Act (When)
    response = client.patch(f"/events/{EVENT}", json={"assignedCoordinatorId": OTHER})

    # Assert (Then)
    assert response.status_code == 401
    assign.assert_not_called()

def test_ac1_submitted_queue_with_no_token_is_refused_before_any_query(client, monkeypatch):
    """
    Summary: GET /events/submitted with no Authorization header answers 401 and list_submitted is never called.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Mock (app.list_submitted replaced; asserted never called); no token is sent, so the JWKS key is unused
    """
    # Arrange (Given)
    listing = MagicMock()
    monkeypatch.setattr("app.list_submitted", listing)

    # Act (When)
    response = client.get("/events/submitted")

    # Assert (Then)
    assert response.status_code == 401
    listing.assert_not_called()

@pytest.mark.parametrize("path", [
    f"/events/{EVENT}",
    f"/events/{EVENT}?coordinatorId={USER_ID}",
    "/events",
    f"/events?coordinatorId={USER_ID}",
    f"/events?organiserId={OTHER}",
], ids=["details", "details-with-coordinator-id", "list", "list-with-coordinator-id", "list-with-organiser-id"])
def test_ac1_event_reads_naming_a_user_in_the_query_but_sending_no_token_are_refused(client, monkeypatch, path):
    """
    Summary: GET /events and GET /events/<id> with no Authorization header answer 401, even when the query names a coordinatorId or organiserId, and no database connection is opened; a query id alone grants nothing.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Mock (the psycopg2.connect patch is asserted never called); no token is sent, so the JWKS key is unused
    """
    # Arrange (Given)
    connect = MagicMock()
    monkeypatch.setattr("app.models.psycopg2.connect", connect)

    # Act (When)
    response = client.get(path)

    # Assert (Then)
    assert response.status_code == 401
    connect.assert_not_called()


@pytest.mark.parametrize(
    "method, path",
    [
        ("post", "/events/drafts"),
        ("get", "/events/drafts"),
        ("patch", f"/events/drafts/{EVENT}"),
        ("post", f"/events/drafts/{EVENT}/submit"),
        ("delete", f"/events/drafts/{EVENT}"),
    ],
    ids=["save_draft", "list_drafts", "edit_draft", "submit_draft", "delete_draft"],
)
def test_ac1_draft_routes_with_no_token_are_refused_before_any_query(client, monkeypatch, method, path):
    """
    Summary: POST/GET/PATCH/DELETE on the draft routes (save, list, edit, submit, delete) with no Authorization header answer 401, even when the body names an organiserId, and no database connection is opened.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Mock (the psycopg2.connect patch is asserted never called); no token is sent, so the JWKS key is unused
    """
    # Arrange (Given)
    connect = MagicMock()
    monkeypatch.setattr("app.models.psycopg2.connect", connect)

    # Act (When)
    response = getattr(client, method)(path, json={"organiserId": OTHER})

    # Assert (Then)
    assert response.status_code == 401
    connect.assert_not_called()


def test_ac1_event_details_edit_with_no_token_is_refused_even_when_the_body_names_a_coordinator(client, monkeypatch):
    """
    Summary: PATCH /events/<id>/details with no Authorization header answers 401 and no database connection is opened, even though the body names a coordinatorId; the editor is the signed-in user, never an id in the body.
    AC1: Given a system user has not been successfully authenticated, when they
        attempt to access protected information or functionality, then access
        is denied.
    Double: Mock (the psycopg2.connect patch is asserted never called); no token is sent, so the JWKS key is unused
    """
    # Arrange (Given)
    connect = MagicMock()
    monkeypatch.setattr("app.models.psycopg2.connect", connect)

    # Act (When)
    response = client.patch(
        f"/events/{EVENT}/details",
        json={"coordinatorId": USER_ID, "changes": {"eventName": "Renamed"}},
    )

    # Assert (Then)
    assert response.status_code == 401
    connect.assert_not_called()


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_authenticate_with_internal_token_allows_background_worker(client):
    """
    Summary: A background worker presenting the internal token gets past sign-in checking.
    Supporting design check: service-to-service calls authenticate with
        X-Internal-Token
    Double: Stub (app.list_unassigned returns [] via the client fixture; the signing key is unused without a user token)
    """
    response = client.get("/events/unassigned", headers={"X-Internal-Token": "internal-test-token"})

    assert response.status_code not in (401, 503)


def test_health_and_preflight_without_token_are_answered(client):
    """
    Summary: The health check and browser preflights are answered without signing in.
    Supporting design check: /health and OPTIONS answer without a token
    Double: None (these paths skip authentication, so nothing test-specific is stubbed)
    """
    assert client.get("/health").status_code == 200
    assert client.options("/events/unassigned").status_code == 200


def test_internal_token_submission_is_accepted_and_records_no_organiser(client, monkeypatch):
    """
    Summary: POST /events with only the internal token answers 201 and the details handed to submit_event carry no organiserId.
    Supporting design check: a service-to-service submission is accepted on X-Internal-Token and
        is not attributed to any organiser
    Double: Mock (app.submit_event records the details it was given; organiserId asserted absent); no user token is sent, so the JWKS key is unused
    """
    # Arrange (Given)
    submitted = []
    monkeypatch.setattr("app.submit_event", lambda database_url, details: submitted.append(details) or {})

    body = {
        "eventName": "Community Workshop",
        "description": "A workshop",
        "purpose": "Learning",
        "preferredStartDate": "2026-10-01T09:00",
        "preferredEndDate": "2026-10-01T17:00",
        "expectedAttendance": "25",
    }

    # Act (When)
    response = client.post("/events", json=body, headers=INTERNAL)

    # Assert (Then)
    assert response.status_code == 201
    assert "organiserId" not in submitted[0]

def test_signing_key_is_fetched_from_the_supabase_project_jwks_url(monkeypatch):
    """
    Summary: signing_key("token") builds a PyJWKClient for https://project.supabase.test/auth/v1/.well-known/jwks.json (trailing slash handled), asks it for the key of that token once, and returns that key.
    Supporting design check: tokens are verified against the project's published Supabase signing
        keys (the check behind AC1 to AC3)
    Double: Mock (app.auth.jwt.PyJWKClient replaced by a factory that records the JWKS URL and returns a mock client; SUPABASE_URL set by monkeypatch)
    """
    jwks = MagicMock()
    created = []
    monkeypatch.setattr("app.auth.jwt.PyJWKClient", lambda url: created.append(url) or jwks)
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test/")

    key = real_signing_key("token")

    assert created == ["https://project.supabase.test/auth/v1/.well-known/jwks.json"]
    jwks.get_signing_key_from_jwt.assert_called_once_with("token")
    assert key is jwks.get_signing_key_from_jwt.return_value.key
