"""
SUPPORTING DESIGN CHECKS: Safety Check Record Service health check

User Story
----------
Supporting/supplementary design checks. No story or acceptance
criterion describes the behaviour these tests check; it is plumbing
that every story of this service relies on.

Real
----
- create_app() and the /health route run for real.
- The assertion is on the status and body.

Doubled
-------
- Nothing.

Not proven
----------
- That the deployed container answers on its port (-> docker-compose and E2E
  journeys).
"""

from app import create_app
from tests.unit.factories import signed_in


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_health_when_called_returns_ok():
    """
    Summary: Anyone can check that Safety Check Record Service is up.
    Supporting design check: /health answers without a token
    Double: None
    """
    client = signed_in(create_app().test_client())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}
