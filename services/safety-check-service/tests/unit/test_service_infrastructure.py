"""
SUPPORTING DESIGN CHECKS: Safety Check Service health check, browser access and set-up

User Story
----------
Supporting/supplementary design checks. No story or acceptance
criterion describes the behaviour these tests check; it is plumbing
that every story of this service relies on.

Real
----
- The health check, the browser access (CORS) rules, the warning logged when
  this service starts without its credentials, and the default addresses of
  the other services.
- We check the answers, the browser access headers and the log.

Doubled
-------
- None: settings are set or removed for each test.

Not proven
----------
- That a real browser accepts the CORS headers (-> E2E journeys, which run the
  real frontend against the real services).
- That the warning is visible in the deployed container's logs (NOT COVERED
  ANYWHERE).
"""

import pytest

from app import clients, create_app
from tests.unit.factories import signed_in


@pytest.fixture
def client():
    return signed_in(create_app().test_client())


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_create_app_without_internal_token_logs_warning(monkeypatch, caplog):
    """
    Summary: Starting without this service's credentials logs a warning, since Event Service will refuse its moves.
    Supporting design check: a misconfigured service warns at startup
    Double: None
    """
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", "")

    with caplog.at_level("WARNING"):
        create_app()

    assert "INTERNAL_SERVICE_TOKEN is not set" in caplog.text


def test_create_app_with_internal_token_logs_nothing(monkeypatch, caplog):
    """
    Summary: Starting with this service's credentials logs no warning.
    Supporting design check: a misconfigured service warns at startup
    Double: None
    """
    monkeypatch.setattr(clients, "INTERNAL_SERVICE_TOKEN", "shared-secret")

    with caplog.at_level("WARNING"):
        create_app()

    assert "INTERNAL_SERVICE_TOKEN is not set" not in caplog.text


def test_clients_default_to_local_host_ports():
    """
    Summary: Without configuration, this service calls the other services at their local development addresses.
    Supporting design check: downstream URLs default for local runs
    Double: The other service answers as this case needs [Stub]; we check the
        request sent to it [Mock].
    """
    assert clients.EVENT_SERVICE_URL.endswith((":5003", ":5000"))
    assert clients.VENUE_AVAILABILITY_SERVICE_URL.endswith((":5008", ":5000"))
    assert clients.EQUIPMENT_REQUEST_SERVICE_URL.endswith((":5011", ":5000"))
    assert clients.SAFETY_CHECK_RECORD_SERVICE_URL.endswith((":5013", ":5000"))
    assert clients.USER_SERVICE_URL.endswith((":5001", ":5000"))
    assert clients.VENUE_SERVICE_URL.endswith((":5006", ":5000"))


def test_health_without_token_returns_ok(client):
    """
    Summary: Anyone can check the service is up without signing in.
    Supporting design check: /health answers without a token
    Double: None
    """
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_cors_for_frontend_origin_returns_allow_origin(client):
    """
    Summary: The configured frontend may call the service from a browser.
    Supporting design check: the configured frontend origin gets a CORS grant
    Double: None
    """
    response = client.get("/health", headers={"Origin": "http://localhost:5174"})

    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5174"


def test_cors_for_other_origin_sends_no_grant(client):
    """
    Summary: Other websites are not granted browser access.
    Supporting design check: other origins get no CORS grant
    Double: None
    """
    response = client.get("/health", headers={"Origin": "http://evil.example"})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_cors_with_blank_origin_allows_nothing(monkeypatch):
    """
    Summary: Blanking FRONTEND_ORIGIN switches browser access off.
    Supporting design check: an empty FRONTEND_ORIGIN grants no origin
    Double: None
    """
    monkeypatch.setenv("FRONTEND_ORIGIN", "")
    blank = signed_in(create_app().test_client())

    response = blank.get("/health", headers={"Origin": "http://localhost:5174"})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_without_token_returns_200(client):
    """
    Summary: The browser's preflight check is answered without signing in.
    Supporting design check: preflight requests answer without a token
    Double: None
    """
    response = client.options(
        "/safety-checks", headers={"Origin": "http://localhost:5174"}
    )

    assert response.status_code == 200
