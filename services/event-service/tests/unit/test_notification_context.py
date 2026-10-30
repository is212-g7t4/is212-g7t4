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


def test_preparation_requires_internal_token_and_returns_current_assignment(mocker):
    """
    Summary: A notification lookup with the internal token gets the event's current assignment; others are refused.
    AC1: Given a rejection is ready for notification, then the notification is
        addressed to the coordinator assigned to that event when the
        notification is created.
    Double: Stub (app.get_event returns a canned event or raises)
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


def test_context_missing_config_and_event_are_explicit(mocker):
    """
    Summary: An unconfigured lookup or a missing event gives an explicit error, never a made-up recipient.
    AC1: Given a rejection is ready for notification, then the notification is
        addressed to the coordinator assigned to that event when the
        notification is created.
    Double: Stub (app.get_event returns a canned event or raises)
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
