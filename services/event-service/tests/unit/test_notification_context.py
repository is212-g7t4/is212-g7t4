"""# SCRUM-173 — Receive Venue Disruption Notifications

As an Event Coordinator, I want to receive an in-app notification when a venue booking for an event assigned to me is affected, so that I know that alternative arrangements are required.
AC1: Given a rejection is ready for notification, then the notification is addressed to the coordinator assigned to that event when the notification is created.
AC2: The notification contains the event name, affected venue, closure start/end, rejection reason, and a link to the venue rejection.
AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.

## Layer and scope
# SCRUM-173 AC1 — internal preparation lookup seam, hermetic.
Fail closed without token and return the assignment from Event's existing record.


## AC groups
AC1: current coordinator at preparation; recipient is frozen across retries.
AC2: complete frozen content and structured rejection destination.
AC3: eventual delivery without duplicate inbox alerts.
Security, diagnostics, process adapters, fixtures and legacy compatibility are
explicit supporting/cross-ticket checks, not separate direct AC scenarios.
FIRST: unit I/O/clocks are mocked; real integration owns setup/finally teardown.
Historical tests are retrospective evidence, not a new claim of test-first history.
"""

from unittest.mock import patch
from app import create_app
from tests.unit.factories import signed_in

ID = "10000000-0000-0000-0000-000000000001"


def test_preparation_requires_internal_token_and_returns_current_assignment():
    """## AC1 + supporting authorization
    A token-authenticated preparation lookup returns the current assignment; a missing/wrong token is denied.
    """
    client = signed_in(create_app(
        {"DATABASE_URL": "synthetic", "INTERNAL_SERVICE_TOKEN": "synthetic-token"}
    ).test_client())
    path = f"/internal/events/{ID}/notification-context"
    assert client.get(path).status_code == 401
    with patch(
        "app.get_event",
        return_value={"id": ID, "eventName": "Seminar", "coordinatorId": ID},
    ):
        response = client.get(path, headers={"X-Internal-Token": "synthetic-token"})
    assert response.status_code == 200
    assert response.json == {"id": ID, "eventName": "Seminar", "coordinatorId": ID}


def test_context_missing_config_and_event_are_explicit():
    """## AC1 supporting recovery
    Unconfigured lookup and missing event return explicit errors, never a made-up recipient.
    """
    from app import EventNotFoundError

    headers = {"X-Internal-Token": "synthetic-token"}
    client = signed_in(create_app(
        {"DATABASE_URL": None, "INTERNAL_SERVICE_TOKEN": "synthetic-token"}
    ).test_client())
    path = f"/internal/events/{ID}/notification-context"
    assert client.get(path, headers=headers).status_code == 503
    client.application.config["DATABASE_URL"] = "synthetic"
    with patch("app.get_event", side_effect=EventNotFoundError):
        assert client.get(path, headers=headers).status_code == 404
    client.application.config["INTERNAL_SERVICE_TOKEN"] = None
    assert client.get(path, headers=headers).status_code == 401
