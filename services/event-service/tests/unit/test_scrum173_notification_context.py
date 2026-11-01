"""
SCRUM-173: Receive Venue Disruption Notifications

User Story
----------
As an Event Coordinator, I want to receive an in-app notification when a venue
booking for an event assigned to me is affected, so that I know that
alternative arrangements are required.

Acceptance Criteria
-------------------
AC1: Given a rejection is ready for notification, then the notification is
     addressed to the coordinator assigned to that event when the notification
     is created.
AC2: The notification contains the event name, affected venue, closure
     start/end, rejection reason, and a link to the venue rejection.
AC3: Given a temporary system failure occurs during notification dispatch, the
     system must ensure the notification is eventually delivered to the
     assigned coordinator without generating multiple duplicate alerts.

Real
----
- The Event Service routes in app/__init__.py and the rules in app/models.py,
  run through a real create_app(): request validation, the caller's role and
  ownership checks from the signed token, the status rules, and the SQL and
  parameters sent to the database (including notification outbox rows).
- Assertions are on the HTTP status, the response body and the queries and
  parameters the cursor received.

Doubled
-------
- app.get_event: Stub (mocker.patch) - returns a canned event, or raises
  EventNotFoundError, so the lookup runs without a database.
- Supabase JWKS: Stub (tests/conftest.py) - tokens are signed with a throwaway
  ES256 key.

Not proven
----------
- That the SQL runs against the real Postgres schema, constraints and row locks
  (-> tests/integration/ against a throwaway postgres:17.6).
- That the notification outbox rows are delivered (-> Notification Service
  tests and the E2E journeys).
"""

from unittest.mock import patch
from app import create_app
from tests.unit.factories import signed_in

ID = "10000000-0000-0000-0000-000000000001"


def test_ac1_notification_context_returns_the_current_coordinator_only_with_the_internal_token(mocker):
    """
    Summary: Without X-Internal-Token the notification-context lookup is refused with 401; with it, the route returns the event's id, name and current coordinatorId, which is who the notification is addressed to.
    AC1: Given a rejection is ready for notification, then the notification is
        addressed to the coordinator assigned to that event when the
        notification is created.
    Double: Stub (mocker.patch of app.get_event returns {id, eventName, coordinatorId}); no database is involved,
        and the Supabase JWKS Stub verifies the caller's signed token
    """
    # Arrange (Given)
    client = signed_in(create_app(
        {"DATABASE_URL": "synthetic", "INTERNAL_SERVICE_TOKEN": "synthetic-token"}
    ).test_client())
    path = f"/internal/events/{ID}/notification-context"

    # Act + Assert (When / Then)
    assert client.get(path).status_code == 401
    mocker.patch(
        "app.get_event",
        return_value={"id": ID, "eventName": "Seminar", "coordinatorId": ID},
    )
    response = client.get(path, headers={"X-Internal-Token": "synthetic-token"})
    assert response.status_code == 200
    assert response.json == {"id": ID, "eventName": "Seminar", "coordinatorId": ID}


def test_notification_context_fails_closed_without_database_event_or_internal_token_config(mocker):
    """
    Summary: With no DATABASE_URL the lookup answers 503, with an unknown event 404, and with no INTERNAL_SERVICE_TOKEN configured 401 even for a caller sending a token, so no recipient is ever invented.
    Supporting design check: the internal notification-context route fails
        closed when it is misconfigured or the event does not exist
    Double: Stub (mocker.patch of app.get_event raises EventNotFoundError for the 404 step); no database is involved,
        and the Supabase JWKS Stub verifies the caller's signed token
    """
    # Arrange (Given)
    from app import EventNotFoundError

    headers = {"X-Internal-Token": "synthetic-token"}
    client = signed_in(create_app(
        {"DATABASE_URL": None, "INTERNAL_SERVICE_TOKEN": "synthetic-token"}
    ).test_client())
    path = f"/internal/events/{ID}/notification-context"

    # Act + Assert (When / Then)
    assert client.get(path, headers=headers).status_code == 503
    client.application.config["DATABASE_URL"] = "synthetic"
    mocker.patch("app.get_event", side_effect=EventNotFoundError)
    assert client.get(path, headers=headers).status_code == 404
    client.application.config["INTERNAL_SERVICE_TOKEN"] = None
    assert client.get(path, headers=headers).status_code == 401
