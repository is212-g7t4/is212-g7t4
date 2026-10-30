"""
SCRUM-40: View Event Info as Event Coord

User Story
----------
As an Event Coordinator, I want to view registration information for events I
manage, so that I can track attendance numbers and plan logistics.

Acceptance Criteria
-------------------
AC1: The Event Coordinator can view a list of events they are assigned to
     manage.
AC2: For each managed event, the Event Coordinator can see the total number of
     registrations.
AC3: The Event Coordinator can click on an event to view detailed registration
     information including list of registered Attendees with name, email,
     organisation (if provided), registration date, registration status
     (Confirmed, Withdrawn), total registration count, event capacity (if set),
     remaining available spots (capacity - confirmed registrations)
AC4: Given the Event Coordinator is not assigned to an event, they cannot view
     registration information for that event.

SCRUM-41: View Event Info as Event Organizer

User Story
----------
As an Event Organiser, I want to view registration information for my events,
so that I can see who is attending.

Acceptance Criteria
-------------------
AC1: The Event Organiser can view a list of events that they have created.
AC2: For each approved event, the Event Organiser can see the total number of
     registrations.
AC3: The Event Organiser can click on an event to view detailed registration
     information including list of registered Attendees with name, email,
     organisation (if provided), registration date, registration status
     (Confirmed, Withdrawn), total registration count
AC4: Given the Event Organiser did not create the event, they cannot view
     registration information for that event.

Real
----
- GET /events/<id>/registrations: the registrations joined with each attendee's
  name, email and organisation from User Service, tolerance of unknown
  attendees, and the failure mapping run for real, as do the Registration and
  User client functions.
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
- The relationship check (only the assigned coordinator / creating organiser)
  is tested in test_event_registrations_access.py (SCRUM-9).
- Capacity and remaining places (SCRUM-40 AC3): shown by the UI from event data
  (-> frontend RegistrationTable tests).
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


def test_event_registrations_include_attendee_name_email_and_organisation(client, monkeypatch):
    """
    Summary: The event team sees each attendee's name, email and organisation alongside the registration.
    AC3: The Event Coordinator can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count,
        event capacity (if set), remaining available spots (capacity -
        confirmed registrations)
    SCRUM-41 AC3: The Event Organiser can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count
    Double: Stub (registrations and users)
    """
    monkeypatch.setattr("app.routes.can_view_event", lambda event_id, role: True)
    """Coordinator registration list: details come from User, looked up once each."""
    get_user = Mock(return_value=USER)
    monkeypatch.setattr(
        "app.routes.get_event_registrations",
        lambda event_id: [registration(), registration(registration_id="registration-2")],
    )
    monkeypatch.setattr("app.routes.get_user", get_user)

    response = client.get(f"/events/{EVENT_ID}/registrations")

    assert response.status_code == 200
    first = response.json["registrations"][0]
    assert first["attendee_name"] == "Adam Yeo"
    assert first["attendee_email"] == "adam@example.com"
    assert first["attendee_organization"] == "External"
    assert get_user.call_count == 1


def test_event_registrations_when_attendee_unknown_still_lists_registration(client, monkeypatch):
    """
    Summary: A registration whose attendee cannot be found is still listed, with empty details.
    AC3: The Event Coordinator can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count,
        event capacity (if set), remaining available spots (capacity -
        confirmed registrations)
    Double: Stub (User Service returns nothing for one attendee)
    """
    monkeypatch.setattr("app.routes.can_view_event", lambda event_id, role: True)
    monkeypatch.setattr(
        "app.routes.get_event_registrations",
        lambda event_id: [registration(), registration(attendee_id=None)],
    )
    monkeypatch.setattr("app.routes.get_user", lambda user_id: None)

    response = client.get(f"/events/{EVENT_ID}/registrations")

    assert response.status_code == 200
    assert [r["attendee_name"] for r in response.json["registrations"]] == ["", ""]


def test_event_registrations_when_downstream_fails_returns_502(client, monkeypatch):
    """
    Summary: If the list cannot be built, the event team gets an error rather than a partial list.
    AC3: The Event Coordinator can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count,
        event capacity (if set), remaining available spots (capacity -
        confirmed registrations)
    Double: Stub (registration lookup raises)
    """
    monkeypatch.setattr("app.routes.can_view_event", lambda event_id, role: True)
    monkeypatch.setattr("app.routes.get_event_registrations", lambda event_id: [registration()])
    monkeypatch.setattr("app.routes.get_user", Mock(side_effect=RuntimeError("secret")))

    response = client.get(f"/events/{EVENT_ID}/registrations")

    assert response.status_code == 502
    assert "secret" not in response.json["message"]


def test_event_registrations_with_malformed_event_id_returns_404(client):
    """
    Summary: A malformed event id is not found.
    AC3: The Event Coordinator can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count,
        event capacity (if set), remaining available spots (capacity -
        confirmed registrations)
    Double: None
    """
    assert client.get("/events/not-a-uuid/registrations").status_code == 404


def test_get_event_registrations_client_reads_event_list(monkeypatch):
    """
    Summary: An event's registrations are read from Registration Service.
    AC3: The Event Coordinator can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count,
        event capacity (if set), remaining available spots (capacity -
        confirmed registrations)
    Double: Stub (httpx.get returns rows)
    """
    get = Mock(return_value=response(200, {"registrations": [{"registration_id": "r1"}]}))
    monkeypatch.setattr(clients.httpx, "get", get)
    assert clients.get_event_registrations("event-1") == [{"registration_id": "r1"}]
    assert get.call_args.kwargs["params"] == {"eventId": "event-1"}


def test_get_user_returns_profile_or_none(monkeypatch):
    """
    Summary: An attendee's profile is read from User Service, or reported missing.
    AC3: The Event Coordinator can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count,
        event capacity (if set), remaining available spots (capacity -
        confirmed registrations)
    Double: Stub (httpx.get returns a user or 404)
    """
    monkeypatch.setattr(clients.httpx, "get", Mock(return_value=response(200, {"username": "Adam"})))
    assert clients.get_user("user-1") == {"username": "Adam"}
    monkeypatch.setattr(clients.httpx, "get", Mock(return_value=response(404, {})))
    assert clients.get_user("missing") is None


def test_get_user_when_user_service_fails_raises(monkeypatch):
    """
    Summary: A User Service failure is raised.
    AC3: The Event Coordinator can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count,
        event capacity (if set), remaining available spots (capacity -
        confirmed registrations)
    Double: Stub (httpx.get answers 503)
    """
    monkeypatch.setattr(clients.httpx, "get", Mock(return_value=response(503, {})))
    with pytest.raises(httpx.HTTPStatusError):
        clients.get_user("user-1")
