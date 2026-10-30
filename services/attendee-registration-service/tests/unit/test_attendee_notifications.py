"""
SCRUM-46: Attendee Registration and Update Notifications

User Story
----------
As an Attendee, I want to receive notifications about my registration status,
so that I can confirm my place and stay updated on event changes.

Acceptance Criteria
-------------------
AC1: Given an Attendee successfully registers for an event, the system sends an
     in-app notification confirming their registration with the event name,
     date, time, venue, and registration reference number.
AC2: Given an Attendee successfully withdraws their registration, the system
     sends an in-app notification confirming the withdrawal with the event
     name.
AC3: Given an event cancellation takes effect, or a change to its date, time or
     venue is approved and applied, all currently registered Attendees receive
     an in-app notification with the event name and cancellation status or
     updated details, as applicable.

Real
----
- GET /registrations history (cancelled events stay listed), the history
  adapter's mapping of event summaries, and the save adapter that captures the
  event's actual venue into the notification snapshot run for real.
- Assertions are on the returned registrations and the exact request sent to
  Registration Service.

Doubled
-------
- Downstream HTTP adapters: Stub (monkeypatch) - canned registrations, events
  and venue bookings; httpx calls inspected where the request is the outcome.

Not proven
----------
- That Registration Service stores the confirmation/withdrawal intent and the
  dispatcher delivers it (-> registration-service
  test_attendee_notifications.py and notification-service consumer tests).
- AC3's change and cancellation notices themselves (-> event-service SCRUM-46
  notification tests; NOT COVERED here).
"""

from app import create_app
from app import routes
from tests.unit.factories import signed_in


def test_list_my_registrations_when_event_cancelled_keeps_it_with_status(
    monkeypatch,
):
    """
    Summary: A cancelled event stays in the attendee's list, with its registration status unchanged.
    AC3: Given an event cancellation takes effect, or a change to its date,
        time or venue is approved and applied, all currently registered
        Attendees receive an in-app notification with the event name and
        cancellation status or updated details, as applicable.
    Double: Stub (Confirmed registration of a Cancelled event)
    """
    # Arrange (Given)
    user = "22222222-2222-4222-8222-222222222222"
    event = "11111111-1111-4111-8111-111111111111"
    ref = "33333333-3333-4333-8333-333333333333"
    monkeypatch.setattr(
        routes,
        "get_attendee_registrations",
        lambda: [
            dict(
                registration_id=ref,
                event_id=event,
                attendee_id=user,
                status="Confirmed",
            )
        ],
    )
    monkeypatch.setattr(
        routes,
        "get_user",
        lambda attendee: dict(username="Synthetic", email="user@example.com"),
    )
    monkeypatch.setattr(routes, "get_confirmed_events", lambda: [])
    monkeypatch.setattr(
        routes,
        "get_historical_events",
        lambda ids: [dict(id=event, eventName="Workshop", status="Cancelled")],
        raising=False,
    )

    # Act (When)
    response = signed_in(create_app().test_client()).get(f"/registrations")

    # Assert (Then)
    assert response.status_code == 200
    assert response.json["registrations"] == [
        dict(
            registration=dict(
                registration_id=ref,
                event_id=event,
                attendee_id=user,
                status="Confirmed",
                attendee_name="Synthetic",
                attendee_email="user@example.com",
                attendee_organization="",
            ),
            event=dict(id=event, eventName="Workshop", status="Cancelled"),
        )
    ]


def test_history_adapter_maps_summaries_only_for_owned_events(
    monkeypatch,
):
    """
    Summary: Past and changed events are looked up only for the attendee's own registrations.
    AC3: Given an event cancellation takes effect, or a change to its date,
        time or venue is approved and applied, all currently registered
        Attendees receive an in-app notification with the event name and
        cancellation status or updated details, as applicable.
    Double: Stub (httpx returns one cancelled event summary)
    """
    from unittest.mock import Mock
    from app import clients

    response = Mock()
    response.json.return_value = {
        "events": [
            dict(
                id="event",
                eventName="Workshop",
                status="Cancelled",
                startTime="2030-03-01T09:00:00",
                endTime="2030-03-01T17:00:00",
                attendeeVenueName=None,
            )
        ]
    }
    get = Mock(return_value=response)
    monkeypatch.setattr(clients.httpx, "get", get)
    assert clients.get_historical_events([]) == []
    events = clients.get_historical_events(["event"])
    assert events == [
        dict(
            id="event",
            eventName="Workshop",
            status="Cancelled",
            startTime="2030-03-01T09:00:00",
            endTime="2030-03-01T17:00:00",
            attendeeVenueName=None,
            preferredStartDate="2030-03-01T09:00:00",
            preferredEndDate="2030-03-01T17:00:00",
            description="",
            purpose="",
        )
    ]
    assert get.call_args.args == (f"{clients.EVENT_SERVICE_URL}/events/attendee-summaries",)
    assert get.call_args.kwargs == dict(params={"ids": "event"}, headers={}, timeout=5)
    response.raise_for_status.assert_called_once()


import pytest
import respx
from app import clients


@pytest.mark.parametrize("state", ["confirmed", "no-approved"], ids=["approved_booking", "no_approved_booking"])
def test_register_captures_booked_venue_for_the_confirmation(
    monkeypatch, state
):
    """
    Summary: The confirmation names the venue actually booked for the event, when there is one.
    AC1: Given an Attendee successfully registers for an event, the system
        sends an in-app notification confirming their registration with the
        event name, date, time, venue, and registration reference number.
    Double: Stub (venue booking lookup), Mock (save request inspected)
    """
    event = "11111111-1111-4111-8111-111111111111"
    monkeypatch.setattr(
        clients, "VENUE_AVAILABILITY_SERVICE_URL", "http://availability.test"
    )
    monkeypatch.setattr(clients, "VENUE_SERVICE_URL", "http://venue.test")
    monkeypatch.setattr(clients, "REGISTRATION_SERVICE_URL", "http://registration.test")
    snapshot = dict(
        eventName="Workshop",
        startDateTime="2030-03-01T09:00:00",
        endDateTime="2030-03-01T17:00:00",
    )
    data = dict(
        eventId=event, capacity=10, notificationContext=snapshot
    )
    with respx.mock(assert_all_mocked=True, assert_all_called=True) as http:
        # Venue Availability app/models.py::serialize and Venue app/__init__.py::venue.
        http.get(f"http://availability.test/events/{event}/venue-bookings").respond(
            200,
            json={
                "bookings": []
                if state == "no-approved"
                else [
                    dict(
                        id="booking",
                        status="Approved",
                        venueId="venue",
                        requestedStartTime="2030-03-01T09:00:00",
                    )
                ]
            },
        )
        if state == "confirmed":
            http.get("http://venue.test/venues/venue").respond(
                200, json={"venue": {"name": "Hall A"}}
            )
            # Registration app/__init__.py::add_registration returns the owner registration wrapper.
            saved = http.post(
                "http://registration.test/registrations",
                json={
                    **data,
                    "notificationContext": {**snapshot, "venueName": "Hall A"},
                },
            ).respond(201, json={"registration": {"registration_id": "ref"}})
            assert clients.save_registration(data) == {"registration_id": "ref"}
            assert saved.call_count == 1
        else:
            with pytest.raises(ValueError):
                clients.save_registration(data)
