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
- An attendee's list of their registrations: each registration's status and
  date, joined with the event's details (confirmed events first, other events
  such as cancelled ones looked up separately) and the attendee's own details.
- We check what the attendee sees, including an empty list.

Doubled
-------
- Registration Service: holds the attendee's registrations, or fails [Stub].
- Event Service: lists confirmed events and looks up the others [Stub].
- User Service: holds the attendee's profile [Stub].
- Sign-in: a test key signs the caller's token (tests/unit/conftest.py) [Stub].

Not proven
----------
- The list page, detail view and "no registrations" message (-> frontend
  AttendeeRegistrationsPage.test.tsx and attendeeRegistrations.test.ts).
"""

from unittest.mock import Mock


from app import clients
from tests.unit.factories import EVENT_ID, USER, confirmed_event, registration, response


def test_ac1_ac2_ac3_list_my_registrations_returns_status_with_event_details(client, monkeypatch):
    """
    Summary: An attendee sees each registration's status and date, with the event's name, schedule and venue, and their own details.
    AC1: The Attendee can view a list of events they have registered for.
    AC2: For each registered event, the Attendee can see, Event name, date and
        time, venue, registration status (e.g., Confirmed, Withdrawn, Pending),
        registration date
    AC3: The Attendee can click on a registered event to view detailed
        registration information including all registration details they
        submitted (name, email, organisation), event details (date, time,
        venue, description)
    Double: Registration Service holds one confirmed registration, User Service
        holds the attendee's profile, and Event Service lists the event as
        confirmed [Stub].
    """
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda: [registration()])
    monkeypatch.setattr("app.routes.get_user", lambda user_id: USER)
    monkeypatch.setattr("app.routes.get_confirmed_events", lambda: [confirmed_event(venueName="Hall A", description="Hands-on session")])

    response = client.get("/registrations")

    assert response.status_code == 200
    [item] = response.json["registrations"]
    assert item["registration"]["status"] == "Confirmed"
    assert item["registration"]["registration_date"] == "2026-10-08T02:00:00+00:00"
    assert item["registration"]["attendee_name"] == "Adam Yeo"
    assert item["registration"]["attendee_email"] == "adam@example.com"
    assert item["registration"]["attendee_organization"] == "External"
    assert item["event"]["eventName"] == "Community Workshop"
    assert item["event"]["preferredStartDate"] == "2099-11-10T09:00:00+08:00"
    assert item["event"]["preferredEndDate"] == "2099-11-10T12:00:00+08:00"
    assert item["event"]["venueName"] == "Hall A"
    assert item["event"]["description"] == "Hands-on session"


def test_ac4_list_my_registrations_when_none_returns_empty_list(client, monkeypatch):
    """
    Summary: An attendee with no registrations gets an empty list, which the page shows as "no registrations".
    AC4: Given the Attendee has not registered for any events, the system
        displays a message stating so
    Double: Registration Service holds no registrations for the attendee [Stub].
    """
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda: [])
    monkeypatch.setattr("app.routes.get_confirmed_events", lambda: [])

    response = client.get("/registrations")

    assert response.status_code == 200
    assert response.json == {"registrations": []}


def test_ac1_list_my_registrations_when_lookup_fails_returns_502(client, monkeypatch):
    """
    Summary: If the list cannot be loaded, the attendee gets an error rather than a misleading "no registrations".
    AC1: The Attendee can view a list of events they have registered for.
    Double: Registration Service fails [Stub].
    """
    monkeypatch.setattr("app.routes.get_attendee_registrations", Mock(side_effect=RuntimeError("secret")))

    response = client.get("/registrations")

    assert response.status_code == 502
    assert "secret" not in response.json["message"]


def test_ac1_get_attendee_registrations_client_reads_callers_own_list(monkeypatch):
    """
    Summary: Only the signed-in attendee's own registrations are asked for; no other attendee can be named.
    AC1: The Attendee can view a list of events they have registered for.
    Double: Registration Service returns the attendee's registrations, and we
        check the request names no attendee [Mock].
    """
    get = Mock(return_value=response(200, {"registrations": [{"registration_id": "r1"}]}))
    monkeypatch.setattr(clients.httpx, "get", get)

    assert clients.get_attendee_registrations() == [{"registration_id": "r1"}]
    assert "params" not in get.call_args.kwargs


def test_ac1_ac2_list_my_registrations_when_event_cancelled_keeps_it_with_status(client, monkeypatch):
    """
    Summary: A registration for an event that is no longer open, such as a cancelled one, still appears in the list with the event's status.
    AC1: The Attendee can view a list of events they have registered for.
    AC2: For each registered event, the Attendee can see, Event name, date and
        time, venue, registration status (e.g., Confirmed, Withdrawn, Pending),
        registration date
    Double: Registration Service holds a registration for an event that is no
        longer among the confirmed events, and Event Service's past-event
        lookup reports it as Cancelled [Stub].
    """
    monkeypatch.setattr("app.routes.get_attendee_registrations", lambda: [registration()])
    monkeypatch.setattr("app.routes.get_user", lambda attendee_id: USER)
    monkeypatch.setattr("app.routes.get_confirmed_events", lambda: [])
    monkeypatch.setattr(
        "app.routes.get_historical_events",
        lambda ids: [dict(id=EVENT_ID, eventName="Community Workshop", status="Cancelled")],
    )

    response = client.get("/registrations")

    assert response.status_code == 200
    [item] = response.json["registrations"]
    assert item["registration"]["status"] == "Confirmed"
    assert item["event"] == dict(id=EVENT_ID, eventName="Community Workshop", status="Cancelled")
