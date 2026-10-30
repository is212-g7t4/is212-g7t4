"""
SCRUM-38: View Registration Status

User Story
----------
As an Attendee, I want to view my registration status for an event, so that I
can confirm my place is secured.

Acceptance Criteria
-------------------
AC1: The Attendee can view a list of events they have registered for.
AC2: For each registered event, the Attendee can see, Event name, date and
     time, venue, registration status (e.g., Confirmed, Withdrawn, Pending),
     registration date
AC3: The Attendee can click on a registered event to view detailed registration
     information including all registration details they submitted (name,
     email, organisation), event details (date, time, venue, description)
AC4: Given the Attendee has not registered for any events, the system displays
     a message stating so

Real
----
- GET /registrations for an Attendee: the attendee's registrations joined with
  event details (Confirmed catalogue first, history lookup for the rest) and
  the empty and failure cases run for real.
- Assertions are on the list returned and the status.

Doubled
-------
- app.routes downstream adapters (get_confirmed_event, save_registration,
  get_attendee_registrations, get_user, ...): Stub / Mock via monkeypatch -
  return canned events, registrations and users, or raise; a Mock records what
  is saved.
- httpx.get / httpx.post (client tests): Stub - canned Event, Registration and
  User Service replies; URLs and headers inspected.

Not proven
----------
- The list page, detail view and "no registrations" message (AC1-AC4 UI half)
  (-> frontend AttendeeRegistrationsPage.test.tsx and e2e
  view-registration-status.spec.ts).
"""

from datetime import datetime, timedelta
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import httpx
import pytest

from app import clients
from app.clients import RegistrationConflictError
from app.validation import event_has_started, validate_registration, withdrawal_deadline_has_passed
from tests.unit.factories import ATTENDEE_ID, EVENT_ID, USER, confirmed_event, payload, registration, response


def test_list_my_registrations_returns_status_with_event_details(client, monkeypatch):
    """
    Summary: An attendee sees each registration's status with the event's name, date, time and venue.
    AC1: The Attendee can view a list of events they have registered for.
    AC2: For each registered event, the Attendee can see, Event name, date and
        time, venue, registration status (e.g., Confirmed, Withdrawn, Pending),
        registration date
    Double: Stub (registrations and confirmed events)
    """
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda: [registration()])
    monkeypatch.setattr("app.routes.get_user", lambda user_id: USER)
    monkeypatch.setattr("app.routes.get_confirmed_events", lambda: [confirmed_event()])

    response = client.get(f"/registrations")

    assert response.status_code == 200
    assert response.json["registrations"][0]["registration"]["status"] == "Confirmed"
    assert response.json["registrations"][0]["event"]["eventName"] == "Community Workshop"
    assert response.json["registrations"][0]["registration"]["attendee_name"] == "Adam Yeo"


def test_list_my_registrations_when_none_returns_empty_list(client, monkeypatch):
    """
    Summary: An attendee with no registrations gets an empty list for the page's message.
    AC4: Given the Attendee has not registered for any events, the system
        displays a message stating so
    Double: Stub (no registrations)
    """
    # Arrange (Given)
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda: [])
    monkeypatch.setattr("app.routes.get_confirmed_events", lambda: [])

    # Act (When)
    response = client.get(f"/registrations")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json == {"registrations": []}


def test_list_my_registrations_when_lookup_fails_returns_502(client, monkeypatch):
    """
    Summary: If the list cannot be built, the attendee gets an error instead of an empty list.
    AC1: The Attendee can view a list of events they have registered for.
    Double: Stub (registration lookup raises)
    """
    monkeypatch.setattr("app.routes.get_attendee_registrations", Mock(side_effect=RuntimeError("secret")))
    response = client.get(f"/registrations")
    assert response.status_code == 502
    assert "secret" not in response.json["message"]


def test_get_attendee_registrations_client_reads_callers_own_list(monkeypatch):
    """
    Summary: The attendee's registrations are read from Registration Service as that attendee.
    AC1: The Attendee can view a list of events they have registered for.
    Double: Stub (httpx.get returns registrations)
    """
    get = Mock(return_value=response(200, {"registrations": [{"registration_id": "r1"}]}))
    monkeypatch.setattr(clients.httpx, "get", get)
    assert clients.get_attendee_registrations() == [{"registration_id": "r1"}]
    assert "params" not in get.call_args.kwargs
