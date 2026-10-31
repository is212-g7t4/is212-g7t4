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

Real
----
- The coordinator's registration list for an event they manage: each
  registration with the attendee's name, email and organisation, its date and
  status.
- We check the list returned.

Doubled
-------
- Event Service: says the coordinator may view the event [Stub].
- Registration Service: holds the event's registrations [Stub].
- User Service: holds the attendees' profiles, or fails [Stub]; we check each
  attendee is looked up once [Mock].
- Sign-in: a test key signs the caller's token (tests/unit/conftest.py) [Stub].

Not proven
----------
- That only the assigned coordinator gets the list (AC4) (->
  test_scrum9_event_registrations_access.py).
- The registration counts, capacity and remaining places (AC2, AC3) (->
  registration-service test_scrum40_registration_lists_and_counts.py).
- AC1's list of assigned events is owned by Event Service.
"""

from unittest.mock import Mock

import httpx
import pytest

from app import clients
from tests.unit.factories import EVENT_ID, USER, registration, response


def test_ac3_event_registrations_include_attendee_name_email_and_organisation(client, monkeypatch):
    """
    Summary: The coordinator sees each registered attendee's name, email and organisation with the registration's date and status.
    AC3: The Event Coordinator can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count,
        event capacity (if set), remaining available spots (capacity -
        confirmed registrations)
    Double: The coordinator may view the event, Registration Service holds two
        registrations by the same attendee, and User Service holds that
        attendee's profile [Stub]; we check the profile is looked up once
        [Mock].
    """
    monkeypatch.setattr("app.routes.can_view_event", lambda event_id, role: True)
    get_user = Mock(return_value=USER)
    monkeypatch.setattr(
        "app.routes.get_event_registrations",
        lambda event_id: [registration(), registration(registration_id="registration-2", status="Withdrawn")],
    )
    monkeypatch.setattr("app.routes.get_user", get_user)

    response = client.get(f"/events/{EVENT_ID}/registrations")

    assert response.status_code == 200
    first, second = response.json["registrations"]
    assert first["attendee_name"] == "Adam Yeo"
    assert first["attendee_email"] == "adam@example.com"
    assert first["attendee_organization"] == "External"
    assert first["registration_date"] == "2026-10-08T02:00:00+00:00"
    assert [first["status"], second["status"]] == ["Confirmed", "Withdrawn"]
    assert get_user.call_count == 1


def test_ac3_event_registrations_when_attendee_unknown_still_lists_registration(client, monkeypatch):
    """
    Summary: A registration whose attendee has no profile is still listed, with blank details, so the count stays right.
    AC3: The Event Coordinator can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count,
        event capacity (if set), remaining available spots (capacity -
        confirmed registrations)
    Double: The coordinator may view the event, and User Service has no
        profile for the attendees [Stub].
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


def test_ac3_event_registrations_when_downstream_fails_returns_502(client, monkeypatch):
    """
    Summary: If attendee details cannot be loaded, the coordinator gets an error rather than a partial list.
    AC3: The Event Coordinator can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count,
        event capacity (if set), remaining available spots (capacity -
        confirmed registrations)
    Double: The coordinator may view the event and Registration Service holds
        a registration, but User Service fails [Stub].
    """
    monkeypatch.setattr("app.routes.can_view_event", lambda event_id, role: True)
    monkeypatch.setattr("app.routes.get_event_registrations", lambda event_id: [registration()])
    monkeypatch.setattr("app.routes.get_user", Mock(side_effect=RuntimeError("secret")))

    response = client.get(f"/events/{EVENT_ID}/registrations")

    assert response.status_code == 502
    assert "secret" not in response.json["message"]


def test_ac3_get_event_registrations_client_reads_event_list(monkeypatch):
    """
    Summary: The registrations listed are those Registration Service holds for this event only.
    AC3: The Event Coordinator can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count,
        event capacity (if set), remaining available spots (capacity -
        confirmed registrations)
    Double: Registration Service returns the event's registrations [Stub]; we
        check it was asked for this event [Mock].
    """
    get = Mock(return_value=response(200, {"registrations": [{"registration_id": "r1"}]}))
    monkeypatch.setattr(clients.httpx, "get", get)

    assert clients.get_event_registrations("event-1") == [{"registration_id": "r1"}]
    assert get.call_args.kwargs["params"] == {"eventId": "event-1"}


def test_ac3_get_user_returns_profile_or_none(monkeypatch):
    """
    Summary: An attendee's details come from their User Service profile, or are reported missing if they have none.
    AC3: The Event Coordinator can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count,
        event capacity (if set), remaining available spots (capacity -
        confirmed registrations)
    Double: User Service returns a profile, then has none [Stub].
    """
    monkeypatch.setattr(clients.httpx, "get", Mock(return_value=response(200, {"username": "Adam"})))

    assert clients.get_user("user-1") == {"username": "Adam"}
    monkeypatch.setattr(clients.httpx, "get", Mock(return_value=response(404, {})))
    assert clients.get_user("missing") is None


def test_ac3_get_user_when_user_service_fails_raises(monkeypatch):
    """
    Summary: A User Service failure is passed up rather than shown as blank attendee details.
    AC3: The Event Coordinator can click on an event to view detailed
        registration information including list of registered Attendees with
        name, email, organisation (if provided), registration date,
        registration status (Confirmed, Withdrawn), total registration count,
        event capacity (if set), remaining available spots (capacity -
        confirmed registrations)
    Double: User Service answers with an error [Stub].
    """
    monkeypatch.setattr(clients.httpx, "get", Mock(return_value=response(503, {})))

    with pytest.raises(httpx.HTTPStatusError):
        clients.get_user("user-1")


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_support_event_registrations_with_malformed_event_id_returns_404(client):
    """
    Summary: A malformed event id is answered as not found.
    Supporting design check: malformed ids are rejected before any lookup
    Double: None
    """
    assert client.get("/events/not-a-uuid/registrations").status_code == 404
